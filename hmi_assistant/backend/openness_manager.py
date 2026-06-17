# -*- coding: utf-8 -*-
"""
TIA Portal Openness 连接管理器
================================
通过 pythonnet 加载 Siemens.Engineering.dll，附加到正在运行的博途实例，
定位 HMI 设备并导入生成的画面 XML。

运行前提（缺一不可）：
  - 操作系统：Windows；
  - 已安装对应版本的 TIA Portal 与 Openness（PublicAPI）；
  - 当前 Windows 用户已加入 "Siemens TIA Openness" 用户组；
  - Siemens.Engineering.dll 路径正确（见 config.yaml -> openness.dll_path）。

在非 Windows / 无 pythonnet 环境下，本模块自动进入"诊断模式"，不会让程序崩溃，
便于先在任意机器上调试前端与大模型。
"""
import os
import sys
import platform
import subprocess

# 延迟导入，避免非 Windows 环境直接报错
_clr_available = False
try:
    import clr  # noqa: F401  (pythonnet)
    _clr_available = True
except Exception:
    _clr_available = False


class OpennessManager:
    def __init__(self, config: dict):
        self.cfg = config["openness"]
        self.output_cfg = config.get("output", {})
        self._portal = None
        self._project = None
        self._tia = None          # Siemens.Engineering 命名空间引用

    # ---------------- 诊断 ----------------
    def diagnose(self) -> dict:
        """返回环境检查结果，供前端"诊断"按钮展示。"""
        dll = self.cfg.get("dll_path", "")
        result = {
            "os": platform.system(),
            "is_windows": platform.system() == "Windows",
            "pythonnet_installed": _clr_available,
            "dll_path": dll,
            "dll_exists": os.path.exists(dll) if dll else False,
            "running_tia_processes": [],
            "openness_group_hint": "请确认当前用户在 'Siemens TIA Openness' 组中",
            "ready": False,
            "messages": [],
        }
        if not result["is_windows"]:
            result["messages"].append("当前非 Windows，Openness 仅支持 Windows。")
        if not _clr_available:
            result["messages"].append("未检测到 pythonnet，请 pip install pythonnet。")
        if dll and not result["dll_exists"]:
            result["messages"].append("Siemens.Engineering.dll 路径不存在，请在配置页修正。")

        # 列举 TIA 进程（best-effort）
        if result["is_windows"]:
            try:
                out = subprocess.check_output(
                    ["tasklist", "/FI", "IMAGENAME eq Siemens.Automation.Portal.exe"],
                    stderr=subprocess.DEVNULL, text=True)
                if "Siemens.Automation.Portal" in out:
                    result["running_tia_processes"].append("Siemens.Automation.Portal.exe")
            except Exception:
                pass

        result["ready"] = (result["is_windows"] and _clr_available
                           and result["dll_exists"])
        if result["ready"] and not result["messages"]:
            result["messages"].append("环境检查通过，可尝试连接。")
        return result

    # ---------------- 连接 ----------------
    def connect(self) -> dict:
        """附加到正在运行的博途实例并打开项目。返回状态字典。"""
        if not (_clr_available and platform.system() == "Windows"):
            return {"connected": False,
                    "error": "当前环境不支持 Openness（需 Windows + pythonnet）。",
                    "diagnose": self.diagnose()}

        dll = self.cfg["dll_path"]
        if not os.path.exists(dll):
            return {"connected": False, "error": f"DLL 不存在：{dll}"}

        try:
            import clr
            sys.path.append(os.path.dirname(dll))
            clr.AddReference(dll)
            import Siemens.Engineering as tia            # type: ignore
            self._tia = tia

            if self.cfg.get("attach_running", True):
                processes = list(tia.TiaPortal.GetProcesses())
                if not processes:
                    return {"connected": False,
                            "error": "未发现正在运行的博途实例，请先打开 TIA Portal 并加载项目。"}
                self._portal = processes[0].Attach()
            else:
                self._portal = tia.TiaPortal(tia.TiaPortalMode.WithUserInterface)

            # 取已打开项目
            projects = list(self._portal.Projects)
            if self.cfg.get("project_path"):
                self._project = self._portal.Projects.Open(
                    self._make_fileinfo(self.cfg["project_path"]))
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

    def _make_fileinfo(self, path):
        from System.IO import FileInfo   # type: ignore
        return FileInfo(path)

    # ---------------- 查找 HMI 软件 ----------------
    def _find_hmi_software(self):
        """遍历设备，找到目标 HMI 设备的 HmiTarget/Software。"""
        import Siemens.Engineering.HmiUnified as hmiU      # noqa
        target_name = self.cfg.get("hmi_device", "")
        for device in self._project.Devices:
            for item in device.DeviceItems:
                try:
                    sw_container = item.GetService[
                        __import__("Siemens.Engineering.HW.Features",
                                   fromlist=["SoftwareContainer"]).SoftwareContainer]()
                    if sw_container and sw_container.Software:
                        sw = sw_container.Software
                        # HMI 软件类型名包含 HmiTarget
                        if "Hmi" in type(sw).__name__:
                            if (not target_name) or (str(device.Name) == target_name):
                                return sw
                except Exception:
                    continue
        return None

    # ---------------- 导入画面 ----------------
    def import_screen(self, xml_path: str) -> dict:
        """把 SimaticML XML 导入到 HMI 画面文件夹。"""
        if not self._project:
            return {"imported": False, "error": "尚未连接到博途项目，请先点击连接。"}
        try:
            from Siemens.Engineering import ImportOptions   # type: ignore
            sw = self._find_hmi_software()
            if sw is None:
                return {"imported": False,
                        "error": f"未找到 HMI 设备 '{self.cfg.get('hmi_device')}' 的软件。"}

            screen_folder = sw.ScreenFolder
            # 如配置了子文件夹，可在此定位/创建
            file_info = self._make_fileinfo(xml_path)
            screen_folder.Screens.Import(file_info, ImportOptions.Override)

            msg = ["画面已导入。"]
            if self.cfg.get("compile_after_import", True):
                try:
                    self._compile()
                    msg.append("已触发编译。")
                except Exception as ce:
                    msg.append(f"编译时告警：{ce}")
            if self.cfg.get("save_after_import", False):
                self._project.Save()
                msg.append("项目已保存。")

            return {"imported": True, "message": " ".join(msg)}
        except Exception as e:
            return {"imported": False, "error": f"导入失败：{e}"}

    def _compile(self):
        from Siemens.Engineering.Compiler import ICompilable  # type: ignore  # noqa
        # 对 HMI 软件触发编译
        sw = self._find_hmi_software()
        compiler = sw.GetService[ICompilable]()
        compiler.Compile()

    def disconnect(self):
        """与博途解除附加（不关闭博途本体）。"""
        try:
            if self._portal:
                self._portal.Dispose()
        except Exception:
            pass
        self._portal = None
        self._project = None
        return {"disconnected": True}
