# -*- coding: utf-8 -*-
"""
HMI 设备发现 — 查找 HMI 设备并识别类型（Basic/Comfort/Unified）。
"""

from __future__ import annotations

from typing import Any


class DeviceDiscovery:
    """HMI 设备发现与类型识别。

    负责：
      - 遍历项目设备找到 HMI 软件对象
      - 识别 HMI 家族（Basic/Comfort/Unified）
      - 列出已有画面
    """

    def __init__(self, config: dict):
        self._cfg = config.get("openness", config)
        self._hmi_defaults = config.get("hmi_defaults", {})

    def find_hmi_software(self, project, tia_module) -> tuple:
        """遍历设备，找到目标 HMI 设备的 HmiTarget/Software。

        参数:
            project: TIA Project 对象。
            tia_module: Siemens.Engineering 模块。

        返回:
            (software_object, device_object, device_item_object) 或 (None, None, None)
        """
        target_name = str(self._cfg.get("hmi_device", "") or "").strip()

        # 尝试加载 HMI 程序集
        for asm in ("Siemens.Engineering.HmiUnified", "Siemens.Engineering.Hmi"):
            try:
                __import__(asm)  # noqa: F401
            except Exception:
                pass

        def _target_match(device, item, sw) -> bool:
            if not target_name:
                return True
            candidates = []
            for obj in (device, item, sw):
                for attr in ("Name", "DeviceName", "TypeIdentifier", "OrderNumber"):
                    try:
                        v = getattr(obj, attr)
                        if v:
                            candidates.append(str(v))
                    except Exception:
                        pass
            return any(c == target_name for c in candidates)

        for device in project.Devices:
            for item in device.DeviceItems:
                try:
                    sw_container = item.GetService[
                        __import__("Siemens.Engineering.HW.Features",
                                   fromlist=["SoftwareContainer"]).SoftwareContainer]()
                    if sw_container and sw_container.Software:
                        sw = sw_container.Software
                        sw_type = f"{type(sw).__module__}.{type(sw).__name__}"
                        if "Hmi" in sw_type and _target_match(device, item, sw):
                            return sw, device, item
                except Exception:
                    continue
        return None, None, None

    def detect_family(
        self, sw, device=None, item=None
    ) -> str:
        """区分 Basic / Comfort / Unified。

        返回 "Basic" | "Comfort" | "Unified" | "Classic" | "Unknown"
        """
        sw_type_name = type(sw).__name__
        sw_full_name = (
            type(sw).FullName if hasattr(type(sw), "FullName") else sw_type_name
        )
        sw_module = type(sw).__module__ or ""

        is_unified = (
            "HmiUnified" in sw_full_name
            or "HmiUnified" in sw_module
            or "Unified" in sw_type_name
        )
        if is_unified:
            return "Unified"

        is_classic = (
            "Hmi" in sw_type_name
            or "Hmi" in sw_full_name
            or "Hmi" in sw_module
        )
        if not is_classic:
            return "Unknown"

        # 进一步区分 Basic/Comfort
        cfg_type = (
            (self._hmi_defaults or {}).get("hmi_type")
            or self._cfg.get("hmi_type")
            or ""
        )
        cfg_low = str(cfg_type).lower()
        if "basic" in cfg_low or "ktp" in cfg_low:
            return "Basic"
        if "comfort" in cfg_low:
            return "Comfort"

        # 从设备名/型号检测
        parts = []
        for obj in (device, item, sw):
            if obj is None:
                continue
            for attr in ("Name", "DeviceName", "TypeIdentifier", "OrderNumber", "ProductName"):
                try:
                    v = getattr(obj, attr)
                    if v:
                        parts.append(str(v))
                except Exception:
                    pass
        joined = " ".join(p for p in parts if p).lower()
        if "basic" in joined or "ktp" in joined:
            return "Basic"
        if "comfort" in joined:
            return "Comfort"

        return "Classic"

    def list_screens(self, hmi_software) -> list[str]:
        """列出 HMI 设备中已有画面名称。"""
        names: list[str] = []
        try:
            screen_folder = hmi_software.ScreenFolder
            screens = self._collect_screens(screen_folder)
            for s in screens:
                try:
                    names.append(str(s.Name))
                except Exception:
                    pass
        except Exception:
            pass
        return names

    def _collect_screens(self, folder) -> list:
        """递归收集 ScreenFolder 中所有画面。"""
        screens: list = []
        try:
            for s in folder.Screens:
                screens.append(s)
        except Exception:
            pass
        try:
            for sub_folder in folder.Folders:
                try:
                    screens.extend(self._collect_screens(sub_folder))
                except Exception:
                    pass
        except Exception:
            pass
        return screens
