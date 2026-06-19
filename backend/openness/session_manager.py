# -*- coding: utf-8 -*-
"""
TIA Portal 会话管理器 — 连接、附加、断开与项目操作。
"""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Any


class SessionManager:
    """TIA Portal 会话管理。

    负责：
      - 诊断环境
      - 连接到运行中的 TIA Portal 实例
      - 打开项目
      - 断开连接
    """

    def __init__(self, config: dict):
        self._cfg = config.get("openness", config)
        self._portal = None
        self._project = None
        self._tia = None

        self._clr_available = False
        try:
            import clr  # noqa: F401
            self._clr_available = True
        except Exception:
            pass

    @property
    def is_connected(self) -> bool:
        return self._portal is not None and self._project is not None

    @property
    def portal(self):
        return self._portal

    @property
    def project(self):
        return self._project

    @property
    def tia(self):
        return self._tia

    def diagnose(self) -> dict[str, Any]:
        """环境诊断。"""
        dll = self._cfg.get("dll_path", "")
        result = {
            "os": platform.system(),
            "is_windows": platform.system() == "Windows",
            "pythonnet_installed": self._clr_available,
            "dll_path": dll,
            "dll_exists": os.path.exists(dll) if dll else False,
            "running_tia_processes": [],
            "openness_group_hint": "请确认当前用户在 'Siemens TIA Openness' 组中",
            "ready": False,
            "messages": [],
        }

        if not result["is_windows"]:
            result["messages"].append("当前非 Windows，Openness 仅支持 Windows。")
        if not self._clr_available:
            result["messages"].append("未检测到 pythonnet，请 pip install pythonnet。")
        if dll and not result["dll_exists"]:
            result["messages"].append("Siemens.Engineering.dll 路径不存在。")

        if result["is_windows"]:
            try:
                out = subprocess.check_output(
                    ["tasklist", "/FI", "IMAGENAME eq Siemens.Automation.Portal.exe"],
                    stderr=subprocess.DEVNULL, text=True)
                if "Siemens.Automation.Portal" in out:
                    result["running_tia_processes"].append("Siemens.Automation.Portal.exe")
            except Exception:
                pass

        result["ready"] = (
            result["is_windows"] and self._clr_available and result["dll_exists"]
        )
        if result["ready"] and not result["messages"]:
            result["messages"].append("环境检查通过，可尝试连接。")
        return result

    def connect(self) -> dict[str, Any]:
        """附加到正在运行的博途实例并打开项目。"""
        if not (self._clr_available and platform.system() == "Windows"):
            return {
                "connected": False,
                "error": "当前环境不支持 Openness（需 Windows + pythonnet）。",
                "diagnose": self.diagnose(),
            }

        dll = self._cfg.get("dll_path", "")
        if not os.path.exists(dll):
            return {"connected": False, "error": f"DLL 不存在：{dll}"}

        try:
            import clr
            sys = __import__("sys")
            sys.path.append(os.path.dirname(dll))
            clr.AddReference(dll)
            import Siemens.Engineering as tia  # type: ignore
            self._tia = tia

            attach_running = self._cfg.get("attach_running", True)
            if attach_running:
                processes = list(tia.TiaPortal.GetProcesses())
                if not processes:
                    return {
                        "connected": False,
                        "error": "未发现正在运行的博途实例，请先打开 TIA Portal 并加载项目。",
                    }
                self._portal = processes[0].Attach()
            else:
                self._portal = tia.TiaPortal(tia.TiaPortalMode.WithUserInterface)

            projects = list(self._portal.Projects)
            project_path = self._cfg.get("project_path", "")
            if project_path:
                from System.IO import FileInfo  # type: ignore
                self._project = self._portal.Projects.Open(FileInfo(project_path))
            elif projects:
                self._project = projects[0]
            else:
                return {"connected": False, "error": "博途中没有已打开的项目。"}

            return {
                "connected": True,
                "project_name": str(self._project.Name),
                "message": f"已连接到项目：{self._project.Name}",
            }
        except Exception as e:
            return {"connected": False, "error": f"连接失败：{e}"}

    def disconnect(self) -> dict[str, Any]:
        """与博途解除附加（不关闭博途本体）。"""
        try:
            if self._portal:
                self._portal.Dispose()
        except Exception:
            pass
        self._portal = None
        self._project = None
        self._tia = None
        return {"disconnected": True}
