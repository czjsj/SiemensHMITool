"""
MiMo visual analysis bridge.

This module lets a text-first DeepSeek agent call Xiaomi MiMo-V2.5 for image
understanding. It accepts local image paths, public image URLs, or base64/data
URLs, sends them to MiMo's OpenAI-compatible chat completion endpoint, and
returns a structured JSON object suitable for feeding back into DeepSeek.
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator


ImageType = Literal["path", "url", "base64"]
OutputSchema = Literal[
    "brief",
    "detailed",
    "ocr",
    "chart",
    "table",
    "ui",
    "drawing",
    "compare",
    "custom",
]


class ImageInput(BaseModel):
    """One image item for MiMo visual analysis."""

    type: ImageType
    value: str
    mime_type: Optional[str] = None

    @field_validator("value")
    @classmethod
    def non_empty_value(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("image value cannot be empty")
        return value.strip()


class MiMoVisionRequest(BaseModel):
    """The JSON contract exposed to DeepSeek as a tool input."""

    images: List[ImageInput] = Field(min_length=1)
    task: str = Field(default="Describe the image content accurately.")
    output_schema: OutputSchema = "detailed"
    language: str = "zh-CN"
    max_completion_tokens: int = Field(default=2048, ge=128, le=8192)


@dataclass
class MiMoConfig:
    api_key: str
    base_url: str = "https://api.xiaomimimo.com/v1"
    model: str = "mimo-v2.5"
    timeout_seconds: float = 90.0

    @classmethod
    def from_env(cls) -> "MiMoConfig":
        api_key = os.getenv("MIMO_API_KEY")
        if not api_key:
            raise RuntimeError("Missing MIMO_API_KEY environment variable")
        return cls(
            api_key=api_key,
            base_url=os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1").rstrip("/"),
            model=os.getenv("MIMO_MODEL", "mimo-v2.5"),
            timeout_seconds=float(os.getenv("MIMO_TIMEOUT_SECONDS", "90")),
        )


SUPPORTED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp",
}


SYSTEM_PROMPT = (
    "You are a precise multimodal visual perception engine. "
    "Your job is to inspect images and return faithful visual observations for another reasoning model. "
    "Do not hallucinate. Separate visible facts from inferences. "
    "If something is unclear, say it is unclear. "
    "Return concise structured JSON in the requested language."
)


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
    if provided:
        mime_type = provided
    else:
        mime_type, _ = mimetypes.guess_type(path)
        mime_type = mime_type or "image/png"

    if mime_type == "image/jpg":
        mime_type = "image/jpeg"

    if mime_type not in SUPPORTED_MIME_TYPES:
        raise ValueError(f"Unsupported image MIME type: {mime_type}")
    return mime_type


def _path_to_data_url(path: str, mime_type: Optional[str]) -> str:
    file_path = Path(path).expanduser().resolve()
    if not file_path.exists():
        raise FileNotFoundError(f"Image file not found: {file_path}")
    if not file_path.is_file():
        raise ValueError(f"Image path is not a file: {file_path}")

    actual_mime = _guess_mime_type(str(file_path), mime_type)
    data = file_path.read_bytes()
    encoded = base64.b64encode(data).decode("utf-8")
    return f"data:{actual_mime};base64,{encoded}"


def _base64_to_data_url(value: str, mime_type: Optional[str]) -> str:
    if value.startswith("data:"):
        return value
    actual_mime = _guess_mime_type("image.png", mime_type or "image/png")
    return f"data:{actual_mime};base64,{value}"


def _image_to_content_part(image: ImageInput) -> Dict[str, Any]:
    if image.type == "url":
        url = image.value
    elif image.type == "path":
        url = _path_to_data_url(image.value, image.mime_type)
    elif image.type == "base64":
        url = _base64_to_data_url(image.value, image.mime_type)
    else:  # pragma: no cover - pydantic already validates this
        raise ValueError(f"Unknown image type: {image.type}")

    return {"type": "image_url", "image_url": {"url": url}}


def _build_user_text(req: MiMoVisionRequest) -> str:
    schema_hint = SCHEMA_HINTS.get(req.output_schema, SCHEMA_HINTS["detailed"])
    return f"""
请完成下面的视觉分析任务。语言：{req.language}

任务：{req.task}

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


def _extract_usage(raw: Dict[str, Any]) -> Dict[str, int]:
    usage = raw.get("usage") or {}
    prompt_details = usage.get("prompt_tokens_details") or {}
    return {
        "prompt_tokens": int(usage.get("prompt_tokens") or 0),
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "image_tokens": int(prompt_details.get("image_tokens") or 0),
        "total_tokens": int(usage.get("total_tokens") or 0),
    }


def _safe_parse_json(text: str) -> Dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    return {
        "summary": "MiMo returned non-JSON text.",
        "visible_text": [],
        "objects": [],
        "layout": "",
        "details": [],
        "uncertainties": ["视觉模型没有按 JSON 格式返回，raw_text 中保留了原始结果。"],
        "answer": text.strip(),
    }


def analyze_with_mimo(request_data: Dict[str, Any], config: Optional[MiMoConfig] = None) -> Dict[str, Any]:
    """
    Execute one MiMo visual analysis request.

    Parameters
    ----------
    request_data:
        Dict matching MiMoVisionRequest.
    config:
        Optional MiMoConfig. If omitted, loaded from environment variables.
    """
    try:
        req = MiMoVisionRequest.model_validate(request_data)
        cfg = config or MiMoConfig.from_env()
    except (ValidationError, RuntimeError, ValueError) as exc:
        return {
            "ok": False,
            "error_type": "bad_input" if not isinstance(exc, RuntimeError) else "auth",
            "message": str(exc),
            "retryable": False,
        }

    try:
        content_parts = [_image_to_content_part(img) for img in req.images]
        content_parts.append({"type": "text", "text": _build_user_text(req)})

        payload = {
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content_parts},
            ],
            "max_completion_tokens": req.max_completion_tokens,
        }

        headers = {
            "api-key": cfg.api_key,
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=cfg.timeout_seconds) as client:
            response = client.post(f"{cfg.base_url}/chat/completions", headers=headers, json=payload)

        if response.status_code >= 400:
            retryable = response.status_code in {408, 429, 500, 502, 503, 504}
            return {
                "ok": False,
                "error_type": "api",
                "message": f"MiMo API error {response.status_code}: {response.text[:1000]}",
                "retryable": retryable,
            }

        raw = response.json()
        message = raw.get("choices", [{}])[0].get("message", {})
        raw_text = message.get("content") or ""
        parsed = _safe_parse_json(raw_text)

        return {
            "ok": True,
            "model": raw.get("model", cfg.model),
            "task": req.task,
            "visual_result": parsed,
            "raw_text": raw_text,
            "usage": _extract_usage(raw),
        }

    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        return {
            "ok": False,
            "error_type": "network",
            "message": str(exc),
            "retryable": True,
        }
    except Exception as exc:  # Keep tool result JSON-safe for the agent loop.
        return {
            "ok": False,
            "error_type": "api",
            "message": str(exc),
            "retryable": False,
        }


TOOL_SCHEMA: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "mimo_visual_analyze",
        "description": (
            "Use Xiaomi MiMo-V2.5 vision to analyze images, screenshots, UI, charts, tables, "
            "technical drawings, OCR, or multiple-image comparisons. Call this whenever visual content "
            "is required before answering."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "images": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["path", "url", "base64"]},
                            "value": {"type": "string"},
                            "mime_type": {"type": "string"},
                        },
                        "required": ["type", "value"],
                    },
                },
                "task": {"type": "string"},
                "output_schema": {
                    "type": "string",
                    "enum": ["brief", "detailed", "ocr", "chart", "table", "ui", "drawing", "compare", "custom"],
                },
                "language": {"type": "string", "default": "zh-CN"},
            },
            "required": ["images", "task"],
        },
    },
}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Analyze images with Xiaomi MiMo-V2.5.")
    parser.add_argument("--image", action="append", required=True, help="Local image path or public image URL. Repeat for multiple images.")
    parser.add_argument("--task", required=True, help="Visual analysis task.")
    parser.add_argument("--schema", default="detailed", choices=list(SCHEMA_HINTS.keys()))
    parser.add_argument("--language", default="zh-CN")
    args = parser.parse_args()

    images = []
    for item in args.image:
        if item.startswith("http://") or item.startswith("https://"):
            images.append({"type": "url", "value": item})
        else:
            images.append({"type": "path", "value": item})

    result = analyze_with_mimo(
        {
            "images": images,
            "task": args.task,
            "output_schema": args.schema,
            "language": args.language,
        }
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
