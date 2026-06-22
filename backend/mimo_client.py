# -*- coding: utf-8 -*-
"""
MiMo 视觉 API 客户端
====================
从 deepseek_mimo_vision_skill 适配，为 HMI 画面助手提供图像理解能力。
使用 requests（项目已有），不依赖 pydantic。
"""
from __future__ import annotations

import base64
import io
import json
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

# ---- MiMo 支持的图片 MIME 类型 ----
SUPPORTED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp",
}

# ---- MiMo 系统提示词（从 skill 的 SKILL.md 策略适配） ----
MIMO_SYSTEM_PROMPT = (
    "You are a precise multimodal visual perception engine. "
    "Your job is to inspect images and return faithful visual observations "
    "for another reasoning model. Do not hallucinate. "
    "Separate visible facts from inferences. "
    "If something is unclear, say it is unclear. "
    "Return concise structured JSON in the requested language."
)

# ---- output_schema 提示词映射 ----
SCHEMA_HINTS: Dict[str, str] = {
    "brief": "Return only summary, answer, and uncertainties.",
    "detailed": "Return summary, visible_text, objects, layout, details, uncertainties, and answer.",
    "ocr": "Focus on OCR. Preserve line breaks and reading order. Return visible_text and answer.",
    "chart": "Focus on chart title, axes, units, legend, trends, approximate values, and uncertainty.",
    "table": "Focus on table structure, headers, rows, merged cells, values, and uncertainty.",
    "ui": "Focus on UI state, buttons, labels, errors, selected options, and likely next action if visible.",
    "drawing": "Focus on technical drawing symbols, dimensions, callouts, title block, annotations, and ambiguity.",
    "compare": "Compare all images. Label them Image 1, Image 2, etc. Extract similarities and differences.",
    "custom": "Follow the user's task exactly and return structured JSON.",
}


def _guess_mime_type(path: str, provided: Optional[str]) -> str:
    """根据文件路径推断 MIME 类型，或使用提供的值。"""
    if provided:
        mime_type = provided
    else:
        mime_type, _ = mimetypes.guess_type(path)
        mime_type = mime_type or "image/png"

    if mime_type == "image/jpg":
        mime_type = "image/jpeg"

    if mime_type not in SUPPORTED_MIME_TYPES:
        raise ValueError(f"不支持的图片 MIME 类型: {mime_type}")
    return mime_type


def _path_to_data_url(path: str, mime_type: Optional[str]) -> str:
    """将本地文件路径转为 base64 data URL。"""
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"图片文件不存在: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"路径不是文件: {file_path}")

    actual_mime = _guess_mime_type(str(file_path), mime_type)
    data = file_path.read_bytes()
    encoded = base64.b64encode(data).decode("utf-8")
    return f"data:{actual_mime};base64,{encoded}"


def _base64_to_data_url(value: str, mime_type: Optional[str]) -> str:
    """将纯 base64 或已有 data URL 标准化为 data URL。"""
    if value.startswith("data:"):
        return value
    actual_mime = _guess_mime_type("image.png", mime_type or "image/png")
    return f"data:{actual_mime};base64,{value}"


def _resize_image_if_needed(data_url: str, max_dimension: int) -> str:
    """若图片尺寸超过 max_dimension，用 Pillow 等比缩放后重新编码。"""
    if max_dimension <= 0:
        return data_url

    try:
        from PIL import Image as PILImage
    except ImportError:
        return data_url  # Pillow 未安装时不缩放

    # 解析 data URL
    header, b64_data = data_url.split(",", 1)
    raw = base64.b64decode(b64_data)
    img = PILImage.open(io.BytesIO(raw))
    w, h = img.size
    if w <= max_dimension and h <= max_dimension:
        return data_url

    ratio = min(max_dimension / w, max_dimension / h)
    new_w, new_h = int(w * ratio), int(h * ratio)
    img = img.resize((new_w, new_h), PILImage.LANCZOS)

    buf = io.BytesIO()
    img_format = "PNG" if "png" in header else "JPEG"
    img.save(buf, format=img_format)
    resized_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    mime = "image/png" if img_format == "PNG" else "image/jpeg"
    return f"data:{mime};base64,{resized_b64}"


def _image_to_content_part(image: Dict[str, Any], max_dimension: int) -> Dict[str, Any]:
    """将一帧图片输入转为 MiMo API 的 content part。"""
    img_type = image.get("type", "url")
    mime_type = image.get("mime_type")

    if img_type == "url":
        url = image["value"]
    elif img_type == "path":
        url = _path_to_data_url(image["value"], mime_type)
    elif img_type == "base64":
        url = _base64_to_data_url(image["value"], mime_type)
    else:
        raise ValueError(f"未知图片类型: {img_type}")

    if max_dimension > 0 and not img_type == "url":
        url = _resize_image_if_needed(url, max_dimension)

    return {"type": "image_url", "image_url": {"url": url}}


def _build_user_text(task: str, output_schema: str, language: str) -> str:
    """为 MiMo 构建结构化的用户提示文本。"""
    schema_hint = SCHEMA_HINTS.get(output_schema, SCHEMA_HINTS["detailed"])
    return f"""
请完成下面的视觉分析任务。语言：{language}

任务：{task}

输出要求：
- {schema_hint}
- 只描述图中可见内容；推断必须明确标注为推断。
- 看不清、被遮挡、分辨率不足的地方要写入 uncertainties。
- 尽量返回 JSON，不要添加 Markdown 代码块。

建议 JSON 结构：
{{
  "summary": "...",
  "visible_text": ["..."],
  "objects": ["..."],
  "layout": "...",
  "details": ["..."],
  "uncertainties": ["..."],
  "answer": "..."
}}
""".strip()


def _safe_parse_json(text: str, output_schema: str = "detailed") -> Dict[str, Any]:
    """尝试从 MiMo 输出中解析 JSON；失败则返回与 output_schema 匹配的兜底结构。

    对于 output_schema="ui"（HMI 画面审查），兜底结构包含审查专用字段
    (pass/score/categories/summary/critical_issues/suggestions)，
    避免解析失败时审查结果静默退化为全空导致"显示无"。
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            # 对 ui 审查结果做最小 schema 校验，补全缺失字段
            if output_schema == "ui":
                parsed = _ensure_review_schema(parsed)
            return parsed
    except json.JSONDecodeError:
        pass

    # 兜底结构：根据 output_schema 返回不同字段集
    if output_schema == "ui":
        return {
            "pass": False,
            "score": 0,
            "categories": {},
            "summary": "审查结果解析失败：视觉模型未返回有效 JSON 结构。",
            "critical_issues": ["视觉模型未按 JSON 格式返回审查结果，无法提取关键问题。"],
            "suggestions": [],
            "_parse_failed": True,
        }
    return {
        "summary": "MiMo 返回非 JSON 文本，raw_text 中保留原始结果。",
        "visible_text": [],
        "objects": [],
        "layout": "",
        "details": [],
        "uncertainties": ["视觉模型未按 JSON 格式返回，raw_text 中保留了原始结果。"],
        "answer": text.strip(),
    }


def _ensure_review_schema(parsed: dict) -> dict:
    """对 ui 审查结果做最小 schema 校验，补全缺失的必需字段。"""
    defaults = {
        "score": 0,
        "categories": {},
        "summary": "",
        "critical_issues": [],
        "suggestions": [],
    }
    for key, default in defaults.items():
        if key not in parsed:
            parsed[key] = default
    # score 必须是数字
    if not isinstance(parsed.get("score"), (int, float)):
        parsed["score"] = 0
    # critical_issues / suggestions 必须是列表
    for list_key in ("critical_issues", "suggestions"):
        if not isinstance(parsed.get(list_key), list):
            parsed[list_key] = []
    return parsed


def _extract_usage(raw: Dict[str, Any]) -> Dict[str, int]:
    """从 MiMo API 原始响应中提取 token 用量。"""
    usage = raw.get("usage") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "image_tokens": int(prompt_details.get("image_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def analyze_with_mimo(
    images: List[Dict[str, Any]],
    task: str,
    output_schema: str = "detailed",
    config: Optional[Dict[str, Any]] = None,
    language: str = "zh-CN",
) -> Dict[str, Any]:
    """
    调用 MiMo-V2.5 进行视觉分析。

    参数:
        images: 图片列表，每项含 type(path|url|base64), value, mime_type(可选)。
        task: 视觉分析任务描述。
        output_schema: 输出类型(brief|detailed|ocr|chart|table|ui|drawing|compare|custom)。
        config: MiMo 配置节（即 config["mimo"]），为 None 时报错。
        language: 输出语言，默认 zh-CN。

    返回:
        {ok, model, task, visual_result, raw_text, usage}  成功时
        {ok: false, error_type, message, retryable}         失败时
    """
    if not config:
        return {
            "ok": False,
            "error_type": "auth",
            "message": "未配置 MiMo，请在设置中填写 MiMo API Key 并开启视觉审查。",
            "retryable": False,
        }

    api_key = config.get("api_key", "")
    if not api_key:
        return {
            "ok": False,
            "error_type": "auth",
            "message": "MiMo API Key 为空，请在设置中填写。",
            "retryable": False,
        }

    base_url = config.get("base_url", "https://api.xiaomimimo.com/v1").rstrip("/")
    model = config.get("model", "mimo-v2.5")
    timeout = config.get("review_timeout_seconds", 90)
    max_dimension = config.get("image_analysis_max_size", 2048)

    # 验证 images 参数
    if not images or not isinstance(images, list):
        return {
            "ok": False,
            "error_type": "bad_input",
            "message": "images 必须是非空列表。",
            "retryable": False,
        }

    try:
        content_parts = [_image_to_content_part(img, max_dimension) for img in images]
        content_parts.append({"type": "text", "text": _build_user_text(task, output_schema, language)})

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": MIMO_SYSTEM_PROMPT},
                {"role": "user", "content": content_parts},
            ],
            "max_completion_tokens": 4096,
        }

        headers = {
            "api-key": api_key,
            "Content-Type": "application/json",
        }

        resp = requests.post(
            f"{base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=timeout,
        )

        if resp.status_code >= 400:
            retryable = resp.status_code in {408, 429, 500, 502, 503, 504}
            return {
                "ok": False,
                "error_type": "api",
                "message": f"MiMo API 错误 {resp.status_code}: {resp.text[:1000]}",
                "retryable": retryable,
            }

        raw = resp.json()
        message = raw.get("choices", [{}])[0].get("message", {})
        raw_text = message.get("content") or ""
        parsed = _safe_parse_json(raw_text, output_schema=output_schema)

        return {
            "ok": True,
            "model": raw.get("model", model),
            "task": task,
            "visual_result": parsed,
            "raw_text": raw_text,
            "usage": _extract_usage(raw),
        }

    except requests.exceptions.Timeout:
        return {
            "ok": False,
            "error_type": "network",
            "message": f"MiMo API 请求超时（{timeout}s）。",
            "retryable": True,
        }
    except requests.exceptions.ConnectionError as exc:
        return {
            "ok": False,
            "error_type": "network",
            "message": f"无法连接到 MiMo API: {exc}",
            "retryable": True,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error_type": "api",
            "message": str(exc),
            "retryable": False,
        }
