"""
Minimal DeepSeek agent loop with MiMo vision tool calling.

This file demonstrates the complete bridge:
1. Send the user request to DeepSeek with a tool definition.
2. If DeepSeek calls `mimo_visual_analyze`, execute the MiMo bridge.
3. Feed the tool result back to DeepSeek.
4. Return DeepSeek's final answer.

Set environment variables from `.env.example` before running.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from openai import OpenAI

from mimo_vision import TOOL_SCHEMA, analyze_with_mimo


load_dotenv()


DEEPSEEK_SYSTEM_PROMPT = """
你是一个以 DeepSeek 为主推理模型的智能体。你可以调用外部视觉工具 mimo_visual_analyze。

重要规则：
1. 只要用户的问题依赖图片、截图、图表、表格、图纸、UI、OCR 或多图对比，就必须先调用 mimo_visual_analyze。
2. 不要凭空猜测图片内容。
3. 工具返回后，把视觉结果作为证据，再用你的推理能力给出最终答案。
4. 如果视觉结果里有 uncertainties，不要把不确定内容说成确定事实。
5. 默认使用中文回答。
""".strip()


def _deepseek_client() -> OpenAI:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY environment variable")
    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )


def _message_to_dict(message: Any) -> Dict[str, Any]:
    """Convert OpenAI SDK message object to a JSON-serializable dict."""
    if hasattr(message, "model_dump"):
        return message.model_dump(exclude_none=True)
    if isinstance(message, dict):
        return message
    raise TypeError(f"Unsupported message type: {type(message)}")


def ask_deepseek_with_mimo_vision(
    user_text: str,
    image_paths_or_urls: Optional[List[str]] = None,
    model: Optional[str] = None,
    max_rounds: int = 4,
) -> str:
    """
    Ask DeepSeek a question. If image paths/URLs are provided, they are embedded
    into the user text as explicit references so DeepSeek can call the MiMo tool.
    """
    client = _deepseek_client()
    deepseek_model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")

    visual_hint = ""
    if image_paths_or_urls:
        image_items = []
        for item in image_paths_or_urls:
            image_type = "url" if item.startswith(("http://", "https://")) else "path"
            image_items.append({"type": image_type, "value": item})
        visual_hint = (
            "\n\n可用图片输入如下。需要视觉理解时，请调用 mimo_visual_analyze，并把这些图片作为 images 参数：\n"
            + json.dumps(image_items, ensure_ascii=False, indent=2)
        )

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": DEEPSEEK_SYSTEM_PROMPT},
        {"role": "user", "content": user_text + visual_hint},
    ]

    for _ in range(max_rounds):
        response = client.chat.completions.create(
            model=deepseek_model,
            messages=messages,
            tools=[TOOL_SCHEMA],
        )
        assistant_message = response.choices[0].message
        assistant_dict = _message_to_dict(assistant_message)
        messages.append(assistant_dict)

        tool_calls = getattr(assistant_message, "tool_calls", None) or []
        if not tool_calls:
            return assistant_message.content or ""

        for tool_call in tool_calls:
            function_name = tool_call.function.name
            raw_args = tool_call.function.arguments or "{}"
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {
                    "images": [],
                    "task": "Invalid JSON arguments from DeepSeek; cannot analyze image.",
                    "output_schema": "brief",
                }

            if function_name == "mimo_visual_analyze":
                tool_result = analyze_with_mimo(args)
            else:
                tool_result = {
                    "ok": False,
                    "error_type": "bad_input",
                    "message": f"Unknown tool: {function_name}",
                    "retryable": False,
                }

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                }
            )

    return "已达到最大工具调用轮数，未能生成最终答案。请检查 DeepSeek 是否持续重复调用工具。"


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="DeepSeek + MiMo vision bridge demo.")
    parser.add_argument("--question", required=True, help="User question")
    parser.add_argument("--image", action="append", help="Local image path or public image URL. Repeat for multiple images.")
    args = parser.parse_args()

    answer = ask_deepseek_with_mimo_vision(args.question, args.image or [])
    print(answer)
