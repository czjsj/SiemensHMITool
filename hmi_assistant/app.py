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
    """返回 (extra_text, images_b64_list)。"""
    extra_text_parts = []
    images = []
    for f in files:
        filename = (f.filename or "").lower()
        raw = f.read()
        if filename.endswith(".pdf"):
            extra_text_parts.append(_extract_pdf_text(raw, f.filename))
        elif filename.endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp")):
            b64 = base64.b64encode(raw).decode("ascii")
            mime = "image/png" if filename.endswith(".png") else "image/jpeg"
            images.append({"name": f.filename, "data_url": f"data:{mime};base64,{b64}"})
            extra_text_parts.append(f"[随附图片：{f.filename}]")
        elif filename.endswith((".txt", ".md", ".csv")):
            extra_text_parts.append(
                f"[文本文件 {f.filename}]\n" + raw.decode("utf-8", errors="ignore"))
    return "\n\n".join(p for p in extra_text_parts if p), images


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
        extra_text, _images = parse_uploaded_files(files)
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
# 由 IR 文本生成 SimaticML 并落盘 + 返回预览数据
# --------------------------------------------------------------------------
@app.route("/api/build", methods=["POST"])
def build():
    body = request.get_json(force=True)
    raw = body.get("raw_output", "")
    try:
        ir = extract_json(raw)
        ir = validate_ir(ir)
    except (IRValidationError, ValueError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    cfg = cfgm.load_config()
    tia_version = cfg["openness"].get("tia_version", "V18")
    xml = generate_simaticml(ir, tia_version)

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


@app.route("/api/openness/import", methods=["POST"])
def openness_import():
    body = request.get_json(force=True)
    xml_path = body.get("xml_path", "")
    if not xml_path or not os.path.exists(xml_path):
        return jsonify({"imported": False, "error": "XML 路径无效，请先生成画面。"}), 400
    return jsonify(get_openness().import_screen(xml_path))


@app.route("/api/openness/disconnect", methods=["POST"])
def openness_disconnect():
    return jsonify(get_openness().disconnect())


if __name__ == "__main__":
    cfg = cfgm.load_config()
    server = cfg.get("server", {})
    app.run(host=server.get("host", "127.0.0.1"),
            port=server.get("port", 5000),
            debug=server.get("debug", True),
            threaded=True)
