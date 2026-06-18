# -*- coding: utf-8 -*-
"""
大模型客户端
================
- 使用 OpenAI 兼容的 /chat/completions 接口（DeepSeek、OpenAI、各类兼容网关均可）。
- 流式输出：逐块产出 (kind, text)：
      kind = "thinking" 思考过程增量
      kind = "content"  正文增量
- 思考深度(thinking_depth)：
      关闭 -> 使用普通 chat 模型，不产出思考
      低/中/高 -> 优先使用 reasoner 模型（如 deepseek-reasoner）并映射 reasoning_effort；
                 若 provider 无原生推理，则退化为"提示词诱导思考"，把 <thinking>..</thinking>
                 解析为思考过程。
"""
import json
import requests


# 思考深度 -> reasoning_effort（部分模型支持）/ 思考预算提示
DEPTH_MAP = {
    "关闭": {"use_reasoner": False, "effort": None,     "hint_tokens": 0},
    "低":   {"use_reasoner": True,  "effort": "low",    "hint_tokens": 512},
    "中":   {"use_reasoner": True,  "effort": "medium", "hint_tokens": 1500},
    "高":   {"use_reasoner": True,  "effort": "high",   "hint_tokens": 4000},
}

# 当 provider 无原生推理字段时，注入这段提示让模型先思考再回答
_THINKING_INDUCE = (
    "在给出最终 JSON 之前，请先在 <thinking> 与 </thinking> 标签之间，"
    "用中文简要推演：涉及哪些状态量/操作量/显示量、各对象类型与布局、变量与文本列表如何组织。"
    "思考不超过 {budget} 字。随后在标签之外只输出最终 JSON。"
)


class LLMClient:
    def __init__(self, config: dict):
        self.cfg = config
        llm = config["llm"]
        self.provider_name = llm["active_provider"]
        self.provider = llm["providers"][self.provider_name]
        self.depth = llm.get("thinking_depth", "中")
        self.show_thinking = llm.get("show_thinking", True)

    # ---- 内部：选择模型与请求体 ----
    def _build_payload(self, messages):
        depth_cfg = DEPTH_MAP.get(self.depth, DEPTH_MAP["中"])
        use_reasoner = depth_cfg["use_reasoner"]
        model = (
            self.provider.get("reasoner_model")
            if use_reasoner and self.provider.get("reasoner_model")
            else self.provider.get("chat_model")
        )

        payload = {
            "model": model,
            "messages": list(messages),
            "stream": True,
            "temperature": 0.3,
            "max_tokens": 8192,
        }

        native_reasoner = use_reasoner and self.provider.get("reasoner_model")
        if native_reasoner:
            # 对支持 reasoning_effort 的模型透传；DeepSeek-reasoner 会忽略未知字段
            if depth_cfg["effort"]:
                payload["reasoning_effort"] = depth_cfg["effort"]
        elif use_reasoner:
            # 无原生推理：用提示词诱导，并在请求里加一条 system 提醒
            budget = depth_cfg["hint_tokens"]
            payload["messages"] = [
                {"role": "system",
                 "content": _THINKING_INDUCE.format(budget=budget)}
            ] + payload["messages"]

        return payload, native_reasoner

    # ---- 对外：流式生成 ----
    def stream(self, messages):
        """生成器：yield (kind, text)。kind ∈ {'thinking','content','error'}"""
        base_url = self.provider["base_url"].rstrip("/")
        api_key = self.provider.get("api_key", "")
        if not api_key:
            yield ("error", f"未配置 {self.provider_name} 的 API Key，请到"
                            f"右上角设置或配置页填写。")
            return

        url = base_url + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload, native_reasoner = self._build_payload(messages)

        # 诱导式思考的解析状态机
        in_thinking_block = False
        buffer = ""

        try:
            with requests.post(url, headers=headers, json=payload,
                               stream=True, timeout=300) as resp:
                if resp.status_code != 200:
                    detail = resp.text[:500]
                    yield ("error", f"模型接口返回 {resp.status_code}：{detail}")
                    return

                for raw in resp.iter_lines(decode_unicode=True):
                    if not raw:
                        continue
                    if raw.startswith("data:"):
                        raw = raw[5:].strip()
                    if raw == "[DONE]":
                        break
                    try:
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {}) or {}

                    # ① 原生推理字段（DeepSeek: reasoning_content）
                    rc = delta.get("reasoning_content")
                    if rc and self.show_thinking:
                        yield ("thinking", rc)

                    # ② 正文
                    content = delta.get("content")
                    if content is None:
                        continue

                    if native_reasoner or not self.show_thinking:
                        # 原生推理模型：content 即正文
                        yield ("content", content)
                        continue

                    # ③ 诱导式：解析 <thinking>..</thinking>
                    buffer += content
                    while buffer:
                        if not in_thinking_block:
                            idx = buffer.find("<thinking>")
                            if idx == -1:
                                # 没有思考标签起点，可能还在凑标签，保守输出
                                if "<think" in buffer[-9:]:
                                    break  # 等待更多字符判断是否是标签
                                yield ("content", buffer)
                                buffer = ""
                            else:
                                if idx > 0:
                                    yield ("content", buffer[:idx])
                                buffer = buffer[idx + len("<thinking>"):]
                                in_thinking_block = True
                        else:
                            idx = buffer.find("</thinking>")
                            if idx == -1:
                                if "</think" in buffer[-10:]:
                                    break
                                yield ("thinking", buffer)
                                buffer = ""
                            else:
                                if idx > 0:
                                    yield ("thinking", buffer[:idx])
                                buffer = buffer[idx + len("</thinking>"):]
                                in_thinking_block = False
        except requests.exceptions.Timeout:
            yield ("error", "模型请求超时（>300s）。")
        except requests.exceptions.RequestException as e:
            yield ("error", f"网络/请求异常：{e}")


    # ---- 对外：非流式生成（用于辅助调用，如图片分析） ----
    def generate_sync(self, messages: list) -> str:
        """非流式单次生成，返回完整响应文本。"""
        base_url = self.provider["base_url"].rstrip("/")
        api_key = self.provider.get("api_key", "")
        if not api_key:
            raise RuntimeError(f"未配置 {self.provider_name} 的 API Key。")

        url = base_url + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload, _native = self._build_payload(messages)
        payload["stream"] = False
        payload.pop("reasoning_effort", None)  # 非流式时不需要思考深度字段
        # 去掉诱导思考的额外 system 消息（非流式时不需要解析 <thinking>）
        if payload["messages"] and payload["messages"][0].get("role") == "system":
            first_content = payload["messages"][0].get("content", "")
            if "<thinking>" in first_content and "</thinking>" in first_content:
                payload["messages"] = payload["messages"][1:]
        payload["max_tokens"] = payload.get("max_tokens", 8192)

        resp = requests.post(url, headers=headers, json=payload, timeout=300)
        if resp.status_code != 200:
            raise RuntimeError(f"模型接口返回 {resp.status_code}: {resp.text[:500]}")

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("模型返回空响应。")
        return choices[0].get("message", {}).get("content", "") or ""


def extract_json(text: str):
    """从模型完整输出中抽取第一个 JSON 对象。返回 dict 或抛 ValueError。"""
    s = text.strip()
    # 去掉 ```json ``` 围栏
    if "```" in s:
        import re
        m = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL)
        if m:
            s = m.group(1).strip()
    # 容错：截取首个 { 到匹配的 }
    start = s.find("{")
    if start == -1:
        raise ValueError("输出中未找到 JSON 对象。")
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = s[start:i + 1]
                return json.loads(candidate)
    raise ValueError("JSON 对象大括号不匹配。")
