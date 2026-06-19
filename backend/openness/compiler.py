# -*- coding: utf-8 -*-
"""
HMI 编译器 — Openness Compile 触发与结果收集。
"""

from __future__ import annotations

from typing import Any


class HmiCompiler:
    """HMI 编译触发与结果收集。

    使用方式:
        compiler = HmiCompiler()
        compiler.compile(hmi_software)  # 触发编译
    """

    def __init__(self):
        pass

    def compile(self, hmi_software) -> dict[str, Any]:
        """对 HMI 软件对象触发编译。

        参数:
            hmi_software: HMI 软件对象（来自 DeviceDiscovery.find_hmi_software()）。

        返回:
            {"ok": True/False, "errors": int, "warnings": int, "messages": [...]}
        """
        result: dict[str, Any] = {
            "ok": False,
            "errors": 0,
            "warnings": 0,
            "messages": [],
        }

        if hmi_software is None:
            result["messages"].append("无 HMI 软件对象，跳过编译。")
            return result

        try:
            from Siemens.Engineering.Compiler import ICompilable  # type: ignore
            compiler = hmi_software.GetService[ICompilable]()
            result_compile = compiler.Compile()

            # 尝试解析编译结果
            try:
                result["errors"] = int(getattr(result_compile, "ErrorCount", 0))
                result["warnings"] = int(getattr(result_compile, "WarningCount", 0))
            except Exception:
                pass

            result["ok"] = result["errors"] == 0
            if result["errors"]:
                result["messages"].append(
                    f"编译完成：{result['errors']} 个错误，{result['warnings']} 个警告"
                )
            else:
                result["messages"].append("编译通过，无错误。")

        except Exception as e:
            result["messages"].append(f"编译异常：{e}")

        return result

    def syntax_check(self, script_body: str, language: str = "javascript") -> dict[str, Any]:
        """对脚本进行语法检查（预留接口，需要目标设备支持）。

        参数:
            script_body: 脚本体。
            language: 脚本语言 ("javascript" | "vbs")。

        返回:
            {"ok": True/False, "errors": [...]}
        """
        # 语法检查依赖目标设备 API，当前版本返回占位结果
        return {
            "ok": True,
            "errors": [],
            "messages": [f"{language} 语法检查（未连接到目标设备时跳过）"],
        }
