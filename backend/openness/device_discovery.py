# -*- coding: utf-8 -*-
"""
HMI 设备发现 — 查找 HMI 设备并识别类型（Basic/Comfort/Unified）。
"""

from __future__ import annotations

from typing import Any

import logging

logger = logging.getLogger(__name__)


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
                except Exception as exc:
                    logger.debug(
                        "DeviceDiscovery: 跳过设备项 %s: %s",
                        getattr(item, "Name", "unknown"), exc,
                    )
                    continue
        return None, None, None

    def detect_family(
        self, sw, device=None, item=None
    ) -> str:
        """区分 Basic / Comfort / Unified。

        V5.0: 增强设备型号模式匹配，添加 KTP/TP 系列检测。

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

        # V5.0: 扩展设备型号检测 — 从设备名/型号/订单号识别
        # Basic 面板型号: KTP400, KTP700, KTP900, KTP1200, TP700, TP900
        # Comfort 面板型号: TP1200, TP1500, TP1900, TP2200
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

        # V5.0: 精确型号匹配
        basic_models = {"ktp400", "ktp700", "ktp900", "ktp1200",
                        "tp700", "tp900",
                        "basic panel", "ktp basic"}
        comfort_models = {"tp1200", "tp1500", "tp1900", "tp2200",
                          "comfort panel", "tp comfort"}

        if any(m in joined for m in basic_models) or "basic" in joined or "ktp" in joined:
            return "Basic"
        if any(m in joined for m in comfort_models) or "comfort" in joined:
            return "Comfort"

        logger.warning(
            "detect_family: 无法区分 Basic/Comfort，返回 'Classic'。"
            " 设备名: %s, 型号: %s",
            getattr(device, "Name", "?"),
            joined[:200] if joined else "N/A",
        )
        return "Classic"

    def resolve_family_with_fallback(
        self, sw, device=None, item=None, config_type_hint: str | None = None,
    ) -> str:
        """增强的家族检测 — 带配置回退。

        策略:
          1. 调用 detect_family()
          2. 如果结果是 "Unknown" 或 "Classic"，且提供了 config_type_hint，使用配置提示
          3. 如果仍无法确定，记录详细诊断信息用于调试

        参数:
            sw: HMI 软件对象。
            device: 设备对象（可选）。
            item: 设备项对象（可选）。
            config_type_hint: 配置中的 hmi_type 提示 ('basic', 'comfort', 'unified')。

        返回:
            "Basic" | "Comfort" | "Unified" | "Unknown"
        """
        family = self.detect_family(sw, device, item)

        if family in ("Unknown", "Classic") and config_type_hint:
            hint_lower = config_type_hint.lower()
            if "basic" in hint_lower:
                logger.info(
                    "resolve_family_with_fallback: detect_family=%s，使用配置回退为 'Basic'",
                    family,
                )
                return "Basic"
            elif "comfort" in hint_lower:
                logger.info(
                    "resolve_family_with_fallback: detect_family=%s，使用配置回退为 'Comfort'",
                    family,
                )
                return "Comfort"
            elif "unified" in hint_lower:
                logger.info(
                    "resolve_family_with_fallback: detect_family=%s，使用配置回退为 'Unified'",
                    family,
                )
                return "Unified"

        if family == "Unknown":
            # 记录设备信息用于调试
            sw_info = {}
            for obj, label in [(sw, "sw"), (device, "device"), (item, "item")]:
                if obj is None:
                    continue
                for attr in dir(obj):
                    if not attr.startswith("_"):
                        try:
                            val = getattr(obj, attr)
                            if val is not None and not callable(val):
                                sw_info[f"{label}.{attr}"] = str(val)[:100]
                        except Exception:
                            pass
            logger.warning(
                "resolve_family_with_fallback: HMI 家族检测失败。设备信息: %s",
                sw_info,
            )

        return family

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
