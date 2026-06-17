# -*- coding: utf-8 -*-
"""config.yaml 读写与校验。前端的"配置"页通过 /api/config 读写本文件。"""
import os
import copy
import threading
import yaml

_LOCK = threading.Lock()
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config.yaml")

# 默认配置，首次运行若无 config.yaml 则据此生成
DEFAULT_CONFIG = {
    "llm": {
        "active_provider": "deepseek",
        "thinking_depth": "中",                # 关闭 / 低 / 中 / 高
        "stream": True,
        "show_thinking": True,
        "providers": {
            "deepseek": {
                "base_url": "https://api.deepseek.com",
                "api_key": "",
                "chat_model": "deepseek-chat",
                "reasoner_model": "deepseek-reasoner",
                "supports_vision": False,
            },
            "openai_compatible": {
                "base_url": "https://api.openai.com/v1",
                "api_key": "",
                "chat_model": "gpt-4o-mini",
                "reasoner_model": "o1-mini",
                "supports_vision": True,
            },
        },
    },
    "openness": {
        "tia_version": "V18",
        "dll_path": r"C:\Program Files\Siemens\Automation\Portal V18\PublicAPI\V18\Siemens.Engineering.dll",
        "attach_running": True,                # True=附加到已打开的博途实例
        "project_path": "",                    # 留空则使用当前已打开项目
        "hmi_device": "HMI_1",                 # 目标 HMI 设备名
        "screen_folder": "",                   # 留空导入到根画面文件夹
        "compile_after_import": True,
        "save_after_import": False,
    },
    "hmi_defaults": {
        "resolution": "1280x800",
        "hmi_type": "Comfort",
        "background_color": "#1F2630",
        "font_family": "Arial",
    },
    "output": {
        "export_dir": "exports",
        "encoding": "utf-8-sig",               # UTF-8 含 BOM
    },
    "server": {
        "host": "127.0.0.1",
        "port": 5000,
        "debug": True,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """把 override 合并进 base（深合并），用于补全缺省键。"""
    result = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config() -> dict:
    """加载配置；不存在则写入默认配置后返回。"""
    with _LOCK:
        if not os.path.exists(_CONFIG_PATH):
            with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
                yaml.safe_dump(DEFAULT_CONFIG, f, allow_unicode=True, sort_keys=False)
            return copy.deepcopy(DEFAULT_CONFIG)
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        # 与默认配置合并，保证新增字段不会缺失
        return _deep_merge(DEFAULT_CONFIG, data)


def save_config(new_config: dict) -> dict:
    """整体保存配置（前端结构化表单提交后调用）。"""
    with _LOCK:
        merged = _deep_merge(DEFAULT_CONFIG, new_config)
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.safe_dump(merged, f, allow_unicode=True, sort_keys=False)
        return merged


def save_raw_yaml(text: str) -> dict:
    """直接保存原始 YAML 文本（前端"原始编辑"模式）。会校验可解析性。"""
    parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise ValueError("YAML 根节点必须是一个映射(对象)。")
    return save_config(parsed)


def get_raw_yaml() -> str:
    """返回当前 config.yaml 的原始文本。"""
    cfg = load_config()
    return yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False)
