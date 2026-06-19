# -*- coding: utf-8 -*-
"""
HMI 编译器 — Openness Compile 触发与结果收集。

真实调用 TIA Portal Openness ICompilable.Compile() 接口。
递归遍历 CompilerResult.Messages 主列表，
每条消息读取自身的 Severity/Description/Path/ObjectName，
然后递归子 Messages[]。

Error > 0 时编译不得成功。
"""

from __future__ import annotations

from typing import Any


class HmiCompiler:
    """HMI 编译触发与递归结果收集。

    CompilerResult.Messages 递归结构:
      CompilerResult
        .ErrorCount   : int
        .WarningCount : int
        .Messages[]   → CompilerMessage
          ├── .Severity    : int (0=Info, 1=Warning, 2=Error)
          ├── .Description : string
          ├── .Path        : string
          ├── .ObjectName  : string
          └── .Messages[]  → CompilerMessage (recursive)
    """

    def __init__(self):
        self._clr_available = False
        try:
            import clr  # noqa: F401
            self._clr_available = True
        except Exception:
            pass
        # Last compiled result for query services to reuse
        self._last_compile_result: dict[str, Any] | None = None

    @property
    def last_compile_result(self) -> dict[str, Any] | None:
        return self._last_compile_result

    def compile(self, hmi_software) -> dict[str, Any]:
        """对 HMI 软件对象触发编译。

        hmi_software=None  → dry mode (ok=True, no error).
        """
        result: dict[str, Any] = {
            "ok": False,
            "errors": 0,
            "warnings": 0,
            "infos": 0,
            "messages": [],
        }

        if hmi_software is None:
            result["messages"].append({
                "severity": "Info",
                "description": "No HMI software object — compile skipped (dry mode).",
                "path": "", "object_name": "",
            })
            result["ok"] = True
            return result

        if not self._clr_available:
            result["messages"].append({
                "severity": "Error",
                "description": "pythonnet not available — cannot compile.",
                "path": "", "object_name": "",
            })
            result["errors"] = 1
            self._last_compile_result = result
            return result

        try:
            from Siemens.Engineering.Compiler import ICompilable  # type: ignore

            compiler_instance = hmi_software.GetService[ICompilable]()
            compile_output = compiler_instance.Compile()

            try:
                result["errors"] = int(getattr(compile_output, "ErrorCount", 0))
                result["warnings"] = int(getattr(compile_output, "WarningCount", 0))
            except Exception:
                pass

            # 递归遍历 CompilerResult.Messages
            result["messages"] = self._collect_all_messages(compile_output)
            result["infos"] = sum(
                1 for m in result["messages"] if m.get("severity") == "Info")

            result["ok"] = result["errors"] == 0

        except Exception as e:
            result["errors"] = 1
            result["messages"].append({
                "severity": "Error",
                "description": f"Compile exception: {e}",
                "path": "", "object_name": "",
            })
            result["ok"] = False

        self._last_compile_result = result
        return result

    def syntax_check(self, script_body: str, language: str = "javascript") -> dict[str, Any]:
        """脚本语法检查（需真实 TIA 设备）。"""
        return {
            "ok": True, "errors": [],
            "messages": [{
                "severity": "Info",
                "description": f"{language} syntax check skipped without target device.",
                "path": "", "object_name": "",
            }],
        }

    # ------------------------------------------------------------------
    # 递归 CompilerResult.Messages 遍历
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_all_messages(compile_result) -> list[dict[str, Any]]:
        """递归遍历 CompilerResult.Messages。

        官方结构:
          Messages[] → CompilerMessage
            .Severity    : int (0=Info, 1=Warning, 2=Error)
            .Description : string
            .Path        : string
            .ObjectName  : string
            .Messages[]  (recursive)

        同时兼容旧版 ErrorMessages/WarningMessages 分离列表。
        """
        messages: list[dict[str, Any]] = []

        def _severity_name(sev) -> str:
            try:
                v = int(sev)
            except (TypeError, ValueError):
                try:
                    v = int(sev.value) if hasattr(sev, "value") else -1
                except Exception:
                    v = -1
            if v <= 0:   return "Info"
            if v == 1:   return "Warning"
            return "Error"

        def _collect_from_list(msg_list, depth: int = 0):
            if depth > 30 or msg_list is None:
                return
            try:
                iterator = iter(msg_list)
            except TypeError:
                return

            for msg in iterator:
                entry: dict[str, Any] = {
                    "severity": "Info",
                    "description": "", "path": "", "object_name": "",
                }

                # Severity — 每条消息自带的 severity 字段
                try:
                    entry["severity"] = _severity_name(
                        getattr(msg, "Severity", 0))
                except Exception:
                    pass

                # Description
                for f in ("Description", "Message", "Text", "MessageText"):
                    try:
                        v = getattr(msg, f, None)
                        if v and str(v).strip():
                            entry["description"] = str(v)
                            break
                    except Exception:
                        pass

                # Path
                for f in ("Path", "FilePath", "Location", "SourcePath"):
                    try:
                        v = getattr(msg, f, None)
                        if v and str(v).strip():
                            entry["path"] = str(v)
                            break
                    except Exception:
                        pass

                # ObjectName
                for f in ("ObjectName", "Name", "TargetName", "ScreenName"):
                    try:
                        v = getattr(msg, f, None)
                        if v and str(v).strip():
                            entry["object_name"] = str(v)
                            break
                    except Exception:
                        pass

                messages.append(entry)

                # 递归子 Messages
                for sub_attr in ("Messages", "Children", "SubMessages",
                                  "NestedMessages", "InnerResults"):
                    try:
                        sub = getattr(msg, sub_attr, None)
                        if sub is not None:
                            _collect_from_list(sub, depth + 1)
                    except Exception:
                        pass

        # 主入口: CompilerResult.Messages
        _collect_from_list(getattr(compile_result, "Messages", None))

        # 兼容: 如果没有 .Messages，尝试分离列表
        if not messages:
            for attr in ("ErrorMessages", "WarningMessages", "InfoMessages"):
                _collect_from_list(getattr(compile_result, attr, None))

        return messages
