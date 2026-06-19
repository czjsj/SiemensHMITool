# -*- coding: utf-8 -*-
"""
Flask 主程序
=============
路由一览：
  GET  /                      主界面
  GET  /api/config            读取配置（结构化 + 原始 YAML）
  POST /api/config            保存配置（结构化）
  POST /api/config/raw        保存原始 YAML
  POST /api/generate          流式生成 HMI 画面 IR（SSE）
  POST /api/build             校验 IR -> 生成 SimaticML XML 并落盘，返回预览数据
  GET  /api/openness/diagnose 诊断 Openness 环境
  POST /api/openness/connect  一键连接博途
  POST /api/openness/import   导入已生成的 XML 到博途
  POST /api/openness/disconnect 断开
"""
import os
import io
import json
import base64
import datetime

from flask import (Flask, request, jsonify, Response,
                   render_template, stream_with_context)

from backend import config_manager as cfgm
from backend import prompts
from backend.llm_client import LLMClient, extract_json
from backend.hmi_ir import validate_ir, IRValidationError
from backend.simaticml_generator import generate_simaticml
from backend.openness_manager import OpennessManager
from backend.openness.classic_executor import ClassicOpennessExecutor
from backend.openness.diagnostics_utils import (
    describe_dotnet_object,
    inspect_xml_document,
)
from backend.template_xml_generator import generate_from_template_xml
from backend.pipeline_orchestrator import run_pipeline
from backend.variable_engine import VariableEngine

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__,
            template_folder=os.path.join(BASE_DIR, "templates"),
            static_folder=os.path.join(BASE_DIR, "static"))

# 开发期禁用静态文件缓存，防止浏览器缓存旧版 app.js / style.css，
# 否则会出现「前端调用已废弃接口（如 /api/tia/status）→ 404 → 诊断弹窗卡死」这类问题。
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0


@app.after_request
def _no_cache_static(resp):
    if request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-store, max-age=0"
    return resp


# 全局唯一的 Openness 连接（附加态需要在多次请求间保持）
_openness = None


def get_openness():
    global _openness
    cfg = cfgm.load_config()
    if _openness is None:
        _openness = OpennessManager(cfg)
    else:
        _openness.cfg = cfg["openness"]
        _openness.output_cfg = cfg.get("output", {})
    return _openness


# --------------------------------------------------------------------------
# 页面
# --------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------
@app.route("/api/config", methods=["GET"])
def get_config():
    cfg = cfgm.load_config()
    # 出于安全，前端展示时对 api_key 做掩码（编辑时仍可整体覆盖）
    return jsonify({"config": cfg, "raw": cfgm.get_raw_yaml()})


@app.route("/api/config", methods=["POST"])
def post_config():
    try:
        data = request.get_json(force=True)
        saved = cfgm.save_config(data.get("config", {}))
        return jsonify({"ok": True, "config": saved})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/api/config/raw", methods=["POST"])
def post_config_raw():
    try:
        text = request.get_json(force=True).get("raw", "")
        saved = cfgm.save_raw_yaml(text)
        return jsonify({"ok": True, "config": saved})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


# --------------------------------------------------------------------------
# 文件解析（PDF 提取文本 / 图片转 base64 备用于视觉模型）
# --------------------------------------------------------------------------
def parse_uploaded_files(files):
    """返回 (extra_text, images_for_preview, images_for_analysis)。

    images_for_preview:  前端展示用（含 name, data_url）。
    images_for_analysis: MiMo 分析用（含 name, type:"base64", value:纯b64, mime_type）。
    """
    extra_text_parts = []
    images_preview = []
    images_analysis = []
    for f in files:
        filename = (f.filename or "").lower()
        raw = f.read()
        if filename.endswith(".pdf"):
            extra_text_parts.append(_extract_pdf_text(raw, f.filename))
        elif filename.endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")):
            b64 = base64.b64encode(raw).decode("ascii")
            mime = "image/png" if filename.endswith(".png") else "image/jpeg"
            images_preview.append({"name": f.filename, "data_url": f"data:{mime};base64,{b64}"})
            images_analysis.append({
                "name": f.filename,
                "type": "base64",
                "value": b64,
                "mime_type": mime,
            })
            extra_text_parts.append(f"[随附图片：{f.filename}]")
        elif filename.endswith((".txt", ".md", ".csv")):
            extra_text_parts.append(
                f"[文本文件 {f.filename}]\n" + raw.decode("utf-8", errors="ignore"))
    return (
        "\n\n".join(p for p in extra_text_parts if p),
        images_preview,
        images_analysis,
    )


def _extract_pdf_text(raw_bytes, name):
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(io.BytesIO(raw_bytes)) as pdf:
            for i, page in enumerate(pdf.pages):
                t = page.extract_text() or ""
                if t.strip():
                    text_parts.append(f"--- {name} 第{i+1}页 ---\n{t}")
        return "\n".join(text_parts) if text_parts else f"[PDF {name} 无可提取文本]"
    except Exception as e:
        return f"[PDF {name} 解析失败：{e}]"


# --------------------------------------------------------------------------
# 流式生成（SSE）
# --------------------------------------------------------------------------
@app.route("/api/generate", methods=["POST"])
def generate():
    # 兼容 multipart（带文件）与 json（纯文本）两种提交
    if request.content_type and "multipart/form-data" in request.content_type:
        requirement = request.form.get("requirement", "")
        depth = request.form.get("thinking_depth", "")
        files = request.files.getlist("files")
        extra_text, _images, _images_analysis = parse_uploaded_files(files)
    else:
        body = request.get_json(force=True)
        requirement = body.get("requirement", "")
        depth = body.get("thinking_depth", "")
        extra_text = ""

    if not requirement.strip():
        return jsonify({"error": "画面需求不能为空"}), 400

    cfg = cfgm.load_config()
    if depth:
        cfg["llm"]["thinking_depth"] = depth   # 本次请求临时覆盖思考深度
    client = LLMClient(cfg)
    messages = prompts.build_messages(requirement, extra_text)

    def sse(event, data):
        return f"data: {json.dumps({'event': event, 'data': data}, ensure_ascii=False)}\n\n"

    @stream_with_context
    def event_stream():
        yield sse("start", {"depth": cfg["llm"]["thinking_depth"]})
        full_content = []
        try:
            for kind, text in client.stream(messages):
                if kind == "thinking":
                    yield sse("thinking", text)
                elif kind == "content":
                    full_content.append(text)
                    yield sse("content", text)
                elif kind == "error":
                    yield sse("error", text)
                    return
            # 流结束后尝试解析 JSON，附带提示
            raw = "".join(full_content)
            try:
                ir = extract_json(raw)
                yield sse("parsed_ok", {"hint": "已解析出画面 IR，可点击「生成 XML / 预览」。"})
            except Exception as pe:
                yield sse("parse_warn", f"输出解析为 JSON 时有问题：{pe}")
            yield sse("done", {})
        except Exception as e:
            yield sse("error", f"生成异常：{e}")

    return Response(event_stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------
# 流式生成 + 视觉审查（SSE）—— 带 MiMo 审查的多阶段流水线
# --------------------------------------------------------------------------
@app.route("/api/generate/with_review", methods=["POST"])
def generate_with_review():
    # 兼容 multipart（带文件）与 json（纯文本）两种提交
    if request.content_type and "multipart/form-data" in request.content_type:
        requirement = request.form.get("requirement", "")
        depth = request.form.get("thinking_depth", "")
        files = request.files.getlist("files")
        extra_text, _images_preview, images_analysis = parse_uploaded_files(files)
    else:
        body = request.get_json(force=True)
        requirement = body.get("requirement", "")
        depth = body.get("thinking_depth", "")
        extra_text = ""
        images_analysis = []

    if not requirement.strip():
        return jsonify({"error": "画面需求不能为空"}), 400

    cfg = cfgm.load_config()
    if depth:
        cfg["llm"]["thinking_depth"] = depth

    def sse(event, data):
        return f"data: {json.dumps({'event': event, 'data': data}, ensure_ascii=False)}\n\n"

    @stream_with_context
    def event_stream():
        yield sse("start", {"depth": cfg["llm"]["thinking_depth"], "pipeline": True})
        try:
            for event, data in run_pipeline(
                requirement=requirement,
                extra_text=extra_text,
                uploaded_images=images_analysis,
                config=cfg,
            ):
                yield sse(event, data)
        except Exception as exc:
            yield sse("error", f"流水线异常: {exc}")

    return Response(event_stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------
# 由 IR 文本生成 SimaticML 并落盘 + 返回预览数据
# --------------------------------------------------------------------------
@app.route("/api/build", methods=["POST"])
def build():
    body = request.get_json(force=True)
    raw = body.get("raw_output", "")
    try:
        ir = extract_json(raw)
        ir = validate_ir(ir)
        # ---- 变量引擎：自动绑定 process_tag + 生成 HMI Tags + VBS 脚本 ----
        ir = VariableEngine().generate(ir)
    except (IRValidationError, ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    cfg = cfgm.load_config()
    tia_version = cfg["openness"].get("tia_version", "V18")
    ref_xml = cfg.get("output", {}).get("reference_xml", "")
    xml = generate_simaticml(ir, tia_version, ref_xml)

    # 落盘
    export_dir = os.path.join(BASE_DIR, cfg["output"].get("export_dir", "exports"))
    os.makedirs(export_dir, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{ir['meta']['screen_name']}_{ts}"
    encoding = cfg["output"].get("encoding", "utf-8-sig")

    xml_path = os.path.join(export_dir, base_name + ".xml")
    with open(xml_path, "w", encoding=encoding) as f:
        f.write(xml)
    json_path = os.path.join(export_dir, base_name + ".json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(ir, f, ensure_ascii=False, indent=2)

    return jsonify({
        "ok": True,
        "ir": ir,                       # 供前端渲染预览
        "xml": xml,                     # 供前端展示/复制
        "xml_path": xml_path,
        "json_path": json_path,
        "warnings": ir.get("_warnings", []),
    })


# --------------------------------------------------------------------------
# Openness
# --------------------------------------------------------------------------
@app.route("/api/openness/diagnose", methods=["GET"])
def openness_diagnose():
    return jsonify(get_openness().diagnose())


# 兼容别名：某些（旧缓存）前端会在页面加载时轮询 /api/openness/status 与
# /api/tia/status。统一返回诊断结果 + 连接状态，避免出现 404 卡住诊断弹窗。
@app.route("/api/openness/status", methods=["GET"])
@app.route("/api/tia/status", methods=["GET"])
def openness_status():
    mgr = get_openness()
    diag = mgr.diagnose()
    connected = getattr(mgr, "_portal", None) is not None
    return jsonify({
        "connected": connected,
        "ready": diag.get("ready", False),
        "diagnose": diag,
    })


@app.route("/api/openness/connect", methods=["POST"])
def openness_connect():
    return jsonify(get_openness().connect())


@app.route("/api/openness/export-reference", methods=["POST"])
def openness_export_reference():
    """从已连接的博途项目导出 HMI 画面作为 SimaticML 格式参考。
    支持可选请求体：{"screen_name": "画面名"}，为空则导出第一个画面。
    """
    body = {}
    if request.content_type and "application/json" in request.content_type:
        try:
            body = request.get_json(force=True) or {}
        except Exception:
            pass
    screen_name = body.get("screen_name", "")

    result = get_openness().export_reference_screen(screen_name)
    if result.get("ok"):
        cfg = cfgm.load_config()
        cfg.setdefault("output", {})["reference_xml"] = result["xml"]
        cfgm.save_config(cfg)
        return jsonify({
            "ok": True,
            "screen_name": result["screen_name"],
            "message": f"已从画面 '{result['screen_name']}' 提取格式模板。",
            "warnings": result.get("warnings", []),
        })
    return jsonify({
        "ok": False,
        "message": result.get("message", "导出参考画面失败"),
        "warnings": result.get("warnings", []),
        "details": result.get("details"),
    }), 400


@app.route("/api/openness/capabilities", methods=["GET"])
def openness_capabilities():
    """获取当前 HMI 设备的能力信息（类型、推荐模式、画面列表等）。"""
    return jsonify(get_openness().get_hmi_capabilities())


@app.route("/api/openness/export-template", methods=["POST"])
def openness_export_template():
    """导出指定画面作为模板 XML（经典 HMI 模板路线用）。"""
    body = request.get_json(force=True)
    screen_name = body.get("screen_name", "")
    export_dir = body.get("export_dir", "")
    overwrite = body.get("overwrite", True)

    try:
        result = get_openness().export_screen_xml_template(screen_name, export_dir, overwrite)
    except Exception as e:
        return jsonify({
            "ok": False,
            "message": f"导出模板 XML 异常：{e}",
            "warnings": [],
        }), 500

    if result.get("ok"):
        # 自动更新配置中的模板 XML 路径
        cfg = cfgm.load_config()
        cfg.setdefault("openness", {}).setdefault("classic_template", {})["template_xml_path"] = result["xml_path"]
        cfg.setdefault("openness", {}).setdefault("classic_template", {})["template_screen_name"] = result["screen_name"]
        cfgm.save_config(cfg)
        return jsonify(result)
    return jsonify({
        "ok": False,
        "message": result.get("message", "导出模板 XML 失败"),
        "warnings": result.get("warnings", []),
        "details": result.get("details"),
    }), 400


@app.route("/api/build/template-xml", methods=["POST"])
def build_template_xml():
    """只生成模板 XML（改写后），不导入到博途。"""
    body = request.get_json(force=True)
    ir_data = body.get("ir")
    template_xml_path = body.get("template_xml_path", "")

    if not ir_data:
        return jsonify({"ok": False, "error": "缺少 ir 数据"}), 400

    try:
        ir = validate_ir(ir_data)
        # ---- 变量引擎：自动绑定 process_tag + 生成 HMI Tags + VBS 脚本 ----
        ir = VariableEngine().generate(ir)
    except (IRValidationError, ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    # 确定模板 XML 路径
    if not template_xml_path:
        cfg = cfgm.load_config()
        template_xml_path = cfg.get("openness", {}).get("classic_template", {}).get("template_xml_path", "")

    if not template_xml_path or not os.path.exists(template_xml_path):
        return jsonify({"ok": False, "error": f"模板 XML 路径无效：{template_xml_path}"}), 400

    with open(template_xml_path, "r", encoding="utf-8") as f:
        template_xml = f.read()

    new_xml, warnings = generate_from_template_xml(ir, template_xml)

    # 落盘
    cfg = cfgm.load_config()
    gen_dir = cfg.get("openness", {}).get("classic_template", {}).get("generated_xml_dir", "exports/generated_from_template")
    if not os.path.isabs(gen_dir):
        gen_dir = os.path.join(BASE_DIR, gen_dir)
    os.makedirs(gen_dir, exist_ok=True)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    xml_path = os.path.join(gen_dir, f"{ir['meta']['screen_name']}_{ts}.xml")
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(new_xml)

    return jsonify({
        "ok": True,
        "xml": new_xml,
        "xml_path": xml_path,
        "warnings": warnings,
    })


@app.route("/api/openness/import", methods=["POST"])
def openness_import():
    """导入画面到博途。支持旧 XML 路径模式和新 IR + mode 模式。"""
    body = request.get_json(force=True)
    xml_path = body.get("xml_path", "")
    ir_data = body.get("ir")
    mode = body.get("mode", "auto")

    # 新模式：IR + mode（自动路由）
    if ir_data:
        # ---- 变量引擎预处理（统一在导入前绑定变量） ----
        try:
            ir_data = validate_ir(ir_data)
            ir_data = VariableEngine().generate(ir_data)
        except (IRValidationError, ValueError) as e:
            return jsonify({"ok": False, "error": f"IR 校验失败：{e}"}), 400
        if mode in ("unified_direct", "classic_template_xml", "simaticml", "auto"):
            result = get_openness().import_or_generate_from_ir(ir_data, mode)
            return jsonify(result)
        # 旧 IR 模式（无 mode 或 simaticml）：先生成 XML 再导入
        cfg = cfgm.load_config()
        tia_version = cfg["openness"].get("tia_version", "V18")
        ref_template = cfg.get("output", {}).get("reference_xml", "")
        ir = ir_data  # 已通过 validate + VariableEngine 处理
        xml = generate_simaticml(ir, tia_version, ref_template)
        export_dir = os.path.join(BASE_DIR, cfg["output"].get("export_dir", "exports"))
        os.makedirs(export_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        xml_path = os.path.join(export_dir, f"{ir['meta']['screen_name']}_{ts}.xml")
        with open(xml_path, "w", encoding=cfg["output"].get("encoding", "utf-8-sig")) as f:
            f.write(xml)

    if not xml_path or not os.path.exists(xml_path):
        return jsonify({"imported": False, "error": "XML 路径无效，请先生成画面。"}), 400
    return jsonify(get_openness().import_screen(xml_path))


@app.route("/api/openness/sync-tags", methods=["POST"])
def openness_sync_tags():
    """手动同步变量到 TIA HMI 变量表。"""
    body = request.get_json(force=True)
    tags = body.get("tags") or []
    if not tags:
        return jsonify({"ok": False, "error": "tags 数组为空"}), 400
    return jsonify(get_openness().sync_tags(tags))


@app.route("/api/openness/disconnect", methods=["POST"])
def openness_disconnect():
    return jsonify(get_openness().disconnect())


# --------------------------------------------------------------------------
# V3.0 新 API — 部署计划与能力查询
# --------------------------------------------------------------------------

@app.route("/api/hmi/plan", methods=["POST"])
def hmi_plan():
    """构建部署计划（dry-run 预览）。

    请求格式:
        {
            "project": { "schema_version": "2.0", ... },   // HmiProjectSpec
            "options": {
                "dry_run": true,
                "conflict_policy": "rename",
                "compile_after_deploy": true
            }
        }

    返回 DeploymentPlan JSON。
    """
    try:
        body = request.get_json(force=True)
    except Exception:
        return jsonify({"ok": False, "error": "请求体必须为 JSON"}), 400

    from backend.domain.ir_v2 import HmiProjectSpec
    from backend.domain.deployment_plan import DeploymentPlan
    from backend.planners.deployment_planner import DeploymentPlanner
    from backend.capabilities.capability_service import CapabilityService

    project_data = body.get("project")
    options = body.get("options", {})

    if not project_data:
        return jsonify({"ok": False, "error": "缺少 project 字段"}), 400

    try:
        project = HmiProjectSpec.model_validate(project_data)
    except Exception as e:
        return jsonify({"ok": False, "error": f"project 校验失败: {e}"}), 400

    # 覆盖 dry_run
    dry_run = options.get("dry_run", True)

    # 使用能力服务
    cap_svc = CapabilityService()
    planner = DeploymentPlanner(cap_svc)

    plan = planner.build_plan(project, dry_run=dry_run)

    return jsonify({
        "ok": True,
        "plan": plan.model_dump(),
    })


@app.route("/api/hmi/capabilities", methods=["GET"])
def hmi_capabilities():
    """查询目标设备能力矩阵（静态 + 已连接设备的运行时信息）。

    可选 query 参数:
        family: basic | comfort | unified
        tia_version: V16 | V18 | V20
    """
    from backend.capabilities.capability_service import CapabilityService
    from backend.domain.ir_v2 import TargetSpec
    from backend.domain.enums import HmiFamily

    family = request.args.get("family", "auto")
    tia_version = request.args.get("tia_version", None)

    try:
        family_enum = HmiFamily(family)
    except ValueError:
        family_enum = HmiFamily.AUTO

    target = TargetSpec(family=family_enum, tia_version=tia_version)
    cap_svc = CapabilityService()
    caps = cap_svc.resolve(target)

    # 如果已连接 TIA，附加运行时信息
    runtime_info = {}
    try:
        mgr = get_openness()
        if getattr(mgr, "_portal", None) is not None:
            hmi_caps = mgr.get_hmi_capabilities()
            runtime_info = {
                "connected": True,
                "hmi_software_type": hmi_caps.get("hmi_software_type"),
                "recommended_mode": hmi_caps.get("recommended_mode"),
            }
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "family": family_enum.value,
        "tia_version": tia_version,
        "capabilities": caps.to_dict(),
        "runtime": runtime_info,
    })


@app.route("/api/hmi/runtime-metadata", methods=["GET"])
def hmi_runtime_metadata():
    """获取已连接 TIA 的运行时元数据（版本、DLL 等）。"""
    try:
        mgr = get_openness()
        diagnose = mgr.diagnose()
        caps = mgr.get_hmi_capabilities()
        return jsonify({
            "ok": True,
            "diagnose": diagnose,
            "capabilities": caps,
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# --------------------------------------------------------------------------
# V3.0 真实部署入口 — validate / plan / deploy / verify / compile
# --------------------------------------------------------------------------

@app.route("/api/hmi/validate", methods=["POST"])
def hmi_validate():
    """校验 HmiProjectSpec（交叉引用 + 能力检查）。"""
    try:
        body = request.get_json(force=True)
    except Exception:
        return jsonify({"ok": False, "error": "请求体必须为 JSON"}), 400

    from backend.domain.ir_v2 import HmiProjectSpec
    from backend.services.deployment_service import DeploymentService

    project_data = body.get("project")
    mode = body.get("mode", "v2")

    # 支持 legacy IR dict 自动转换
    if not project_data:
        return jsonify({"ok": False, "error": "缺少 project 字段"}), 400

    if mode == "legacy" and isinstance(project_data, dict) and "schema_version" not in project_data:
        from backend.variable_engine import enrich_to_v2
        from backend.domain.ir_v2 import HmiProjectSpec as PS
        try:
            project = enrich_to_v2(project_data)
        except Exception as e:
            return jsonify({"ok": False, "error": f"Legacy IR 转换失败: {e}"}), 400
    else:
        try:
            project = HmiProjectSpec.model_validate(project_data)
        except Exception as e:
            return jsonify({"ok": False, "error": f"project 校验失败: {e}"}), 400

    svc = DeploymentService()
    result = svc.validate(project)
    return jsonify(result)


@app.route("/api/hmi/deploy", methods=["POST"])
def hmi_deploy():
    """执行 V3 统一部署流水线。

    请求格式:
        {
            "project": { "schema_version": "2.0", ... },
            "mode": "v2",
            "options": { "dry_run": true, "compile_after_deploy": true },
            "legacy_ir": null
        }

    部署顺序（不可跳过）:
      validate → BackendFactory → build_plan → execute steps → verify → compile
    """
    try:
        body = request.get_json(force=True)
    except Exception:
        return jsonify({"ok": False, "error": "请求体必须为 JSON"}), 400

    from backend.domain.ir_v2 import HmiProjectSpec
    from backend.services.deployment_service import DeploymentService, RuntimeContext

    project_data = body.get("project")
    mode = body.get("mode", "v2")
    options = body.get("options", {})
    legacy_ir = body.get("legacy_ir")

    if not project_data and not legacy_ir:
        return jsonify({"ok": False, "error": "缺少 project 或 legacy_ir 字段"}), 400

    # ---- IR 解析 ----
    if legacy_ir and mode != "v2":
        # 旧 IR 模式：先转换为 V2
        from backend.variable_engine import enrich_to_v2
        try:
            project = enrich_to_v2(legacy_ir)
        except Exception as e:
            return jsonify({"ok": False, "error": f"Legacy IR 转换失败: {e}"}), 400
    else:
        if isinstance(project_data, dict) and "schema_version" not in project_data:
            from backend.variable_engine import enrich_to_v2
            try:
                project = enrich_to_v2(project_data)
            except Exception as e:
                return jsonify({"ok": False, "error": f"Legacy IR 转换失败: {e}"}), 400
        else:
            try:
                project = HmiProjectSpec.model_validate(project_data)
            except Exception as e:
                return jsonify({"ok": False, "error": f"project 校验失败: {e}"}), 400

    # ---- Runtime 上下文 ----
    connected = False
    openness_mgr = None
    hmi_sw = None
    project_obj = None
    dll_path = ""
    try:
        mgr = get_openness()
        dll_path = mgr._cfg.get("dll_path", "") if hasattr(mgr, "_cfg") else ""
        if getattr(mgr, "_portal", None) is not None:
            connected = True
            openness_mgr = mgr
            project_obj = getattr(mgr, "_project", None)
            # 尝试定位 HMI software
            try:
                from backend.openness.device_discovery import DeviceDiscovery
                discovery = DeviceDiscovery(mgr._cfg if hasattr(mgr, "_cfg") else {})
                sw, _, _ = discovery.find_hmi_software(project_obj, getattr(mgr, "_tia", None))
                hmi_sw = sw
            except Exception:
                pass
    except Exception:
        pass

    dry_run = options.get("dry_run", not connected)
    ctx = RuntimeContext(
        connected=connected and not dry_run,
        openness_manager=openness_mgr,
        tia_version=project.target.tia_version or "",
        hmi_software=hmi_sw,
        project_obj=project_obj,
        dll_path=dll_path,
    )

    svc = DeploymentService(ctx)
    result = svc.deploy(project)
    return jsonify(result)


@app.route("/api/hmi/verify", methods=["POST"])
def hmi_verify():
    """部署后验证: 查询 TIA 对象 + 编译结果验证。"""
    try:
        body = request.get_json(force=True)
    except Exception:
        return jsonify({"ok": False, "error": "请求体必须为 JSON"}), 400

    from backend.domain.ir_v2 import HmiProjectSpec
    from backend.services.deployment_service import DeploymentService, RuntimeContext, BackendFactory

    project_data = body.get("project")
    if not project_data:
        return jsonify({"ok": False, "error": "缺少 project 字段"}), 400

    try:
        if isinstance(project_data, dict) and "schema_version" not in project_data:
            from backend.variable_engine import enrich_to_v2
            project = enrich_to_v2(project_data)
        else:
            project = HmiProjectSpec.model_validate(project_data)
    except Exception as e:
        return jsonify({"ok": False, "error": f"project 解析失败: {e}"}), 400

    connected = False
    hmi_sw = None
    try:
        mgr = get_openness()
        if getattr(mgr, "_portal", None) is not None:
            connected = True
            project_obj = getattr(mgr, "_project", None)
            try:
                from backend.openness.device_discovery import DeviceDiscovery
                discovery = DeviceDiscovery(mgr._cfg if hasattr(mgr, "_cfg") else {})
                sw, _, _ = discovery.find_hmi_software(project_obj, getattr(mgr, "_tia", None))
                hmi_sw = sw
            except Exception:
                pass
    except Exception:
        pass

    ctx = RuntimeContext(connected=connected, openness_manager=get_openness() if connected else None,
                         hmi_software=hmi_sw)
    backend, _ = BackendFactory.create(project.target)

    verify_result = backend.verify(project, context={"connected": connected, "hmi_software": hmi_sw})
    return jsonify({
        "ok": verify_result.success,
        "verification": verify_result.model_dump(),
        "connected": connected,
    })


@app.route("/api/hmi/compile", methods=["POST"])
def hmi_compile():
    """触发 HMI 编译（需已连接 TIA）。"""
    try:
        body = request.get_json(force=True) if request.content_type and "application/json" in request.content_type else {}
    except Exception:
        body = {}

    connected = False
    try:
        mgr = get_openness()
        if getattr(mgr, "_portal", None) is not None:
            connected = True
    except Exception:
        pass

    if not connected:
        return jsonify({
            "ok": False,
            "error": "未连接到 TIA Portal，无法编译。",
            "compile": {"errors": 0, "warnings": 0, "messages": ["NOT_CONNECTED"]},
        })

    try:
        from backend.openness.compiler import HmiCompiler
        compiler = HmiCompiler()
        sw = mgr._find_hmi_software()
        result = compiler.compile(sw)
        return jsonify({"ok": result["ok"], "compile": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e), "compile": {"errors": 1, "messages": [str(e)]}}), 500


# --------------------------------------------------------------------------
# 调试 API — 最小变量导入闭环探针
# --------------------------------------------------------------------------
@app.route("/api/hmi/debug/import-tag", methods=["POST"])
def debug_import_tag():
    """独立变量导入探针 — 用于定位 Import 失败根因。

    只执行变量导入，禁止同时导入 Connection/Screen/Script/Compile。

    请求 JSON:
        {
            "device_name": "HMI_1",          (可选，用于定位 HMI 设备)
            "xml_path": "D:\\probe\\ImportProbe.xml",  (必填，真实 TIA 导出 XML)
            "expected_tag_name": "ImportProbe",        (必填，导入后期望的变量名)
            "xml_mode": "exact_export"                 (可选，默认 exact_export)
        }

    响应 JSON:
        {
            "success": bool,
            "target": {...},
            "default_table": {...},
            "tag_composition": {...},
            "xml_info": {...},
            "before_tags": [],
            "after_tags": [],
            "new_tags": [],
            "imported_tag": {...},
            "exception_chain": [],
            "error": "..." (失败时)
        }
    """
    data = request.get_json(force=True, silent=True) or {}

    xml_path = data.get("xml_path", "").strip()
    expected_tag_name = data.get("expected_tag_name", "").strip()
    device_name = data.get("device_name", "").strip() or None

    # 参数校验
    if not xml_path:
        return jsonify({"success": False, "error": "xml_path 为必填参数"}), 400
    if not expected_tag_name:
        return jsonify({"success": False, "error": "expected_tag_name 为必填参数"}), 400

    if not os.path.isfile(xml_path):
        return jsonify({
            "success": False,
            "error": f"XML 文件不存在: {xml_path}",
            "xml_info": inspect_xml_document(xml_path),
        }), 400

    # 获取 Openness 连接
    mgr = get_openness()
    if getattr(mgr, "_portal", None) is None:
        return jsonify({
            "success": False,
            "error": "TIA Portal 未连接，请先调用 /api/openness/connect",
        }), 503

    # 创建 executor 并定位 HMI Target
    executor = ClassicOpennessExecutor()
    if not executor.is_available:
        return jsonify({
            "success": False,
            "error": "pythonnet/CLR 不可用",
        }), 503

    hmi_software, device, device_item = executor.locate_hmi_target(
        mgr._project, expected_device_name=device_name
    )

    if hmi_software is None:
        return jsonify({
            "success": False,
            "error": "未找到 Classic HMI Target",
            "device_name_filter": device_name,
            "xml_info": inspect_xml_document(xml_path),
        }), 404

    # 外部引用前置检查
    ref_check = executor.validate_external_tag_references(hmi_software, xml_path)
    if ref_check.get("status") == "BLOCKED":
        return jsonify({
            "success": False,
            "error": "EXTERNAL_TAG_REFERENCE_UNRESOLVED: 外部引用未解析",
            "status": "BLOCKED",
            "references": ref_check.get("references", []),
            "blocked_reasons": ref_check.get("blocked_reasons", []),
            "target": describe_dotnet_object(hmi_software),
            "xml_info": inspect_xml_document(xml_path),
        }), 422

    # 执行探针导入
    try:
        probe_result = executor.import_exact_exported_tag_probe(
            hmi_software, xml_path, expected_tag_name
        )
        return jsonify(probe_result)

    except Exception as exc:
        from backend.openness.diagnostics_utils import collect_exception_chain
        return jsonify({
            "success": False,
            "error": str(exc),
            "exception_chain": collect_exception_chain(exc),
            "target": describe_dotnet_object(hmi_software),
            "xml_info": inspect_xml_document(xml_path),
        }), 500


if __name__ == "__main__":
    cfg = cfgm.load_config()
    server = cfg.get("server", {})
    app.run(host=server.get("host", "127.0.0.1"),
            port=server.get("port", 5000),
            debug=server.get("debug", True),
            threaded=True)
