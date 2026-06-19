# -*- coding: utf-8 -*-
"""
多阶段流水线编排器
==================
将「生成 → 预览渲染 → MiMo 视觉审查 → 修正 → 再审查」串联为一个
SSE 事件生成器，供 Flask 路由直接使用。

流水线状态机:
  pipeline_start → [image_analysis] → generate_start →
  review_start → review_result →
    ├─ review_pass → pipeline_done
    ├─ 达到最大迭代 → pipeline_done
    └─ regenerate_start → (回到 generate_start 的下一轮)

所有阶段均通过 yield (event_name, data) 返回，与现有 SSE 模式完全兼容。
"""
from __future__ import annotations

import base64
import json
from typing import Any, Dict, Generator, List, Optional, Tuple

from .llm_client import LLMClient, extract_json
from .hmi_ir import validate_ir, IRValidationError, scale_ir_to_resolution
from .prompts import build_messages
from .preview_renderer import render_ir_to_png
from .mimo_client import analyze_with_mimo
from .review_prompts import HMI_REVIEW_TASK, IMAGE_ANALYSIS_TASK, build_review_feedback_text
from .tia_text_sanitizer import sanitize_ir_text_fields
from .variable_engine import VariableEngine




def _target_resolution_from_config(config: Dict[str, Any]) -> str:
    """前端预览/视觉审查使用的目标分辨率。显式 openness.target_resolution 优先。"""
    openness = config.get("openness", {}) or {}
    defaults = config.get("hmi_defaults", {}) or {}
    return (openness.get("target_resolution") or openness.get("screen_resolution")
            or defaults.get("resolution") or "").strip()


def _adapt_ir_to_target_resolution(ir: dict, config: Dict[str, Any]) -> dict:
    """让生成后的 IR 立即使用目标 HMI 坐标系，保证预览和导入一致。"""
    target = _target_resolution_from_config(config)
    if target:
        return scale_ir_to_resolution(ir, target)
    return ir


def _analyze_uploaded_images(
    images: List[Dict[str, Any]],
    requirement: str,
    mimo_cfg: Dict[str, Any],
) -> str:
    """用 MiMo 分析上传的参考图片，提取 HMI 相关信息。返回附加文本。"""
    if not images or not mimo_cfg.get("api_key"):
        return ""

    # 只分析前 3 张（避免 token 爆炸）
    to_analyze = images[:3]
    try:
        result = analyze_with_mimo(
            images=to_analyze,
            task=IMAGE_ANALYSIS_TASK,
            output_schema="detailed",
            config=mimo_cfg,
            language="zh-CN",
        )
    except Exception:
        return ""

    if not result.get("ok"):
        return ""

    parsed = result.get("visual_result", {})
    summary = parsed.get("summary", "")
    if not summary:
        return ""

    parts = [f"【上传图片分析结果】\n{summary}"]
    params = parsed.get("parameters") or []
    if params:
        parts.append("识别到的参数/变量: " + ", ".join(params))
    controls = parsed.get("controls") or []
    if controls:
        parts.append("识别到的控制元素: " + ", ".join(controls))
    indicators = parsed.get("status_indicators") or []
    if indicators:
        parts.append("识别到的状态指示: " + ", ".join(indicators))
    suggestions = parsed.get("hmi_suggestions", "")
    if suggestions:
        parts.append(f"HMI 设计建议: {suggestions}")

    return "\n".join(parts)


def _safe_review(ir: dict, mimo_cfg: dict) -> dict:
    """安全地执行一次 MiMo 视觉审查。返回审查结果 dict。"""
    try:
        png_bytes = render_ir_to_png(ir)
    except Exception as exc:
        return {
            "ok": False,
            "error_type": "render",
            "message": f"预览图渲染失败: {exc}",
        }

    png_b64 = base64.b64encode(png_bytes).decode("utf-8")
    return analyze_with_mimo(
        images=[{"type": "base64", "value": png_b64, "mime_type": "image/png"}],
        task=HMI_REVIEW_TASK,
        output_schema="ui",
        config=mimo_cfg,
        language="zh-CN",
    )


def _summarize_review_for_sse(review_result: dict) -> dict:
    """将完整审查结果精简为前端友好的 SSE 数据。"""
    return {
        "pass": review_result.get("pass", False),
        "score": review_result.get("score", 0),
        "categories": review_result.get("categories", {}),
        "summary": review_result.get("summary", ""),
        "critical_issues": review_result.get("critical_issues", []),
        "suggestions": review_result.get("suggestions", []),
    }


def run_pipeline(
    requirement: str,
    extra_text: str,
    uploaded_images: List[Dict[str, Any]],
    config: dict,
) -> Generator[Tuple[str, Any], None, None]:
    """
    多阶段生成流水线。

    参数:
        requirement:      用户输入的中文画面需求。
        extra_text:       从上传文件(PDF/文本等)提取的补充文字。
        uploaded_images:  上传的图片列表（每项含 name, data_url）。
        config:           完整应用配置。

    Yields:
        (event_name, data) 元组，event_name 如 SSE 契约定义。
    """
    mimo_cfg = config.get("mimo", {})
    review_enabled = mimo_cfg.get("enabled", False) and bool(mimo_cfg.get("api_key"))
    max_iterations = mimo_cfg.get("max_iterations", 3) if review_enabled else 1
    pass_threshold = mimo_cfg.get("review_pass_threshold", 70)

    # ---- 流水线开始 ----
    yield ("pipeline_start", {"max_iterations": max_iterations})

    # ---- 可选：分析上传的参考图片 ----
    if uploaded_images and review_enabled and mimo_cfg.get("image_analysis_enabled", True):
        yield ("image_analysis_start", {})
        analysis_text = _analyze_uploaded_images(uploaded_images, requirement, mimo_cfg)
        if analysis_text:
            if extra_text:
                extra_text = extra_text + "\n\n" + analysis_text
            else:
                extra_text = analysis_text
            yield ("image_analysis_result", {"summary": analysis_text[:300]})
        else:
            yield ("image_analysis_result", {"summary": ""})

    # ---- Stage 1: 初始生成 ----
    client = LLMClient(config)
    target_res = _target_resolution_from_config(config)
    if target_res:
        requirement_for_llm = (
            f"目标 HMI 分辨率为 {target_res}。请务必在 meta.resolution 中使用 {target_res}，"
            f"所有对象坐标和尺寸都必须基于 {target_res} 坐标系。\n\n"
            f"{requirement}"
        )
    else:
        requirement_for_llm = requirement
    messages = build_messages(requirement_for_llm, extra_text)

    yield ("generate_start", {"stage": 1})
    full_content: List[str] = []

    try:
        for kind, text in client.stream(messages):
            if kind == "thinking":
                yield ("thinking", text)
            elif kind == "content":
                full_content.append(text)
                yield ("content", text)
            elif kind == "error":
                yield ("error", text)
                yield ("pipeline_done", {"error": text, "ir": None})
                return
    except Exception as exc:
        yield ("error", f"生成异常: {exc}")
        yield ("pipeline_done", {"error": str(exc), "ir": None})
        return

    raw = "".join(full_content)
    try:
        ir = extract_json(raw)
        yield ("parsed_ok", {"hint": "已解析出画面 IR，准备视觉审查。"})
    except Exception as pe:
        yield ("parse_warn", f"输出解析为 JSON 时有问题: {pe}")
        yield ("pipeline_done", {"error": str(pe), "ir": None})
        return

    try:
        ir = validate_ir(ir)
        ir = _adapt_ir_to_target_resolution(ir, config)
    except IRValidationError as ve:
        yield ("error", f"IR 校验失败: {ve}")
        yield ("pipeline_done", {"error": str(ve), "ir": None})
        return

    # ---- 清洗 IR 文本字段（去除 HTML/富文本，确保 TIA 兼容） ----
    ir = sanitize_ir_text_fields(ir)

    # ---- 变量引擎：自动绑定 process_tag + 生成 HMI Tags + VBS 脚本 ----
    var_engine = VariableEngine()
    ir = var_engine.generate(ir)
    yield ("variable_bind", {
        "summary": VariableEngine.get_binding_summary(ir),
    })

    # ---- 如果审查未启用，直接返回 ----
    if not review_enabled:
        yield ("pipeline_done", {
            "ir": ir, "iterations": 1,
            "final_score": None, "passed": None,
            "note": "视觉审查未启用（请在设置中开启并填写 MiMo API Key）。",
        })
        return

    # ---- 审查-修正循环 ----
    current_ir = ir
    final_score = 0
    final_passed = False

    for iteration in range(1, max_iterations + 1):
        yield ("review_start", {"iteration": iteration})

        # 渲染 + 审查
        yield ("review_progress", {"status": "rendering"})
        review_result = _safe_review(current_ir, mimo_cfg)

        if not review_result.get("ok"):
            reason = review_result.get("message", "MiMo API 错误")
            yield ("review_progress", {"status": "review_skipped", "reason": reason})
            yield ("pipeline_done", {
                "ir": current_ir, "iterations": iteration,
                "final_score": None, "passed": None,
                "note": f"审查跳过: {reason}",
            })
            return

        yield ("review_progress", {"status": "analyzing"})

        # 解析审查结果
        visual = review_result.get("visual_result", {})
        score = int(visual.get("score", 0))
        passed = bool(visual.get("pass", score >= pass_threshold))
        final_score = score
        final_passed = passed

        review_sse = _summarize_review_for_sse(visual)
        yield ("review_result", review_sse)

        # 审查通过 → 结束
        if passed:
            yield ("review_pass", {"ir": current_ir, "score": score})
            yield ("pipeline_done", {
                "ir": current_ir, "iterations": iteration,
                "final_score": score, "passed": True,
            })
            return

        # 达到最大迭代次数 → 结束
        if iteration >= max_iterations:
            yield ("pipeline_done", {
                "ir": current_ir, "iterations": iteration,
                "final_score": score, "passed": False,
                "note": f"已达到最大迭代次数 ({max_iterations})，返回当前最佳结果。",
            })
            return

        # ---- 修正阶段 ----
        critical = visual.get("critical_issues") or []
        yield ("regenerate_start", {
            "iteration": iteration + 1,
            "issues": critical[:5],
        })

        regen_messages = build_messages(
            requirement,
            extra_context=extra_text,
            review_context={
                "previous_ir": current_ir,
                "review_result": visual,
            },
        )

        full_content = []
        try:
            for kind, text in client.stream(regen_messages):
                if kind == "thinking":
                    yield ("thinking", text)
                elif kind == "content":
                    full_content.append(text)
                    yield ("content", text)
                elif kind == "error":
                    yield ("error", text)
                    yield ("pipeline_done", {
                        "ir": current_ir, "iterations": iteration,
                        "final_score": final_score, "passed": False,
                        "note": f"修正阶段出错: {text}",
                    })
                    return
        except Exception as exc:
            yield ("error", f"修正生成异常: {exc}")
            yield ("pipeline_done", {
                "ir": current_ir, "iterations": iteration,
                "final_score": final_score, "passed": False,
            })
            return

        raw = "".join(full_content)
        try:
            current_ir = extract_json(raw)
            current_ir = validate_ir(current_ir)
            current_ir = _adapt_ir_to_target_resolution(current_ir, config)
            # ---- 清洗修正后的 IR 文本字段 ----
            current_ir = sanitize_ir_text_fields(current_ir)
            # ---- 变量引擎：重新绑定（修正后可能有新对象） ----
            current_ir = var_engine.generate(current_ir)
            yield ("parsed_ok", {"hint": f"第 {iteration + 1} 轮修正完成，准备再次审查。"})
        except Exception as pe:
            yield ("parse_warn", f"修正后 IR 解析失败: {pe}")
            yield ("pipeline_done", {
                "ir": current_ir, "iterations": iteration,
                "final_score": final_score, "passed": False,
                "note": f"第 {iteration + 1} 轮修正后 IR 解析失败，返回上一版结果。",
            })
            return

    # 不应到达这里
    yield ("pipeline_done", {
        "ir": current_ir, "iterations": max_iterations,
        "final_score": final_score, "passed": final_passed,
    })
