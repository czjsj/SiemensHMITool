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
    """TIA Portal Openness Façade — 向后兼容的入口。

    V3.0 内部委托给 modular 子模块:
      - SessionManager    → 连接/断开/诊断
      - DeviceDiscovery   → HMI 设备查找与类型识别
      - HmiCompiler       → 编译触发
      - ExceptionMapper   → .NET 异常 → Diagnostic
      - AssemblyLoader    → DLL 加载与版本元数据

    旧 API 完全保留，不作破坏性变更。
    """

    def __init__(self, config: dict):
        self.cfg = config["openness"]
        self.output_cfg = config.get("output", {})
        self.hmi_defaults = config.get("hmi_defaults", {})
        self._portal = None
        self._project = None
        self._tia = None          # Siemens.Engineering 命名空间引用

        # ---- V3.0 委托实例 (lazy-init 以保持向后兼容) ----
        self._session_mgr = None
        self._device_discovery = None
        self._compiler = None
        self._exception_mapper = None
        self._assembly_loader = None

    # ---- V3.0 委托属性 ----

    @property
    def session(self):
        if self._session_mgr is None:
            from backend.openness.session_manager import SessionManager
            self._session_mgr = SessionManager({
                "openness": self.cfg,
                "hmi_defaults": self.hmi_defaults,
            })
        return self._session_mgr

    @property
    def device_discovery(self):
        if self._device_discovery is None:
            from backend.openness.device_discovery import DeviceDiscovery
            self._device_discovery = DeviceDiscovery({
                "openness": self.cfg,
                "hmi_defaults": self.hmi_defaults,
            })
        return self._device_discovery

    @property
    def compiler(self):
        if self._compiler is None:
            from backend.openness.compiler import HmiCompiler
            self._compiler = HmiCompiler()
        return self._compiler

    @property
    def exception_mapper(self):
        if self._exception_mapper is None:
            from backend.openness.exception_mapper import ExceptionMapper
            self._exception_mapper = ExceptionMapper()
        return self._exception_mapper

    @property
    def assembly_loader(self):
        if self._assembly_loader is None:
            from backend.openness.assembly_loader import AssemblyLoader
            self._assembly_loader = AssemblyLoader()
        return self._assembly_loader

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

    # ------------------------------------------------------------------
    # XML 预处理 + Lint（委托给管线各层）
    # ------------------------------------------------------------------
    def _preprocess_xml_for_import(self, xml_content: str, hmi_software=None) -> tuple:
        """在导入前预处理 XML，解决所有已知导入冲突。

        处理流水线（委托给管线各层）：
          1. TextNormalizer — 文本级 HTML 清洗 + 控制字符移除
          2. MultilingualTextBuilder — DOM 级重建为标准结构
          3. ScreenNumberAllocator — 删除 <Number> 节点
          4. screen name 冲突检测
          5. XmlValidator — 最终校验

        参数:
            xml_content: 原始 XML 字符串。
            hmi_software: HMI 软件对象（可选），用于检测已有画面。

        返回:
            (processed_xml, warnings_list)
        """
        import re
        from .text_normalizer import TextNormalizer
        from .multilingual_text_builder import MultilingualTextBuilder
        from .screen_number_allocator import ScreenNumberAllocator
        from .xml_validator import XmlValidator
        import xml.etree.ElementTree as ET

        warnings: list = []

        # ---- Step 1: 文本级清洗（管线第一层：TextNormalizer） ----
        xml_content, clean_report = TextNormalizer.normalize_xml_content(xml_content)
        if clean_report.get("html_removed", 0) > 0:
            tags = clean_report.get("html_tags_found", [])
            warnings.append(
                f"已清洗 {clean_report['html_removed']} 处 HTML/富文本标签"
                f"（{', '.join(tags[:10])}），"
                f"TIA Portal 不支持 MultilingualText 含 HTML 结构。"
            )
        if clean_report.get("controls_removed", 0) > 0:
            warnings.append(f"已移除 {clean_report['controls_removed']} 处非法控制字符")

        # ---- Step 2: DOM 级 MultilingualText 重建（管线第二层） ----
        decl_match = re.match(r'(<\?xml[^?]*\?>\s*)', xml_content)
        declaration = decl_match.group(1) if decl_match else ""
        for m in re.finditer(r'xmlns(?::(\w+))?="([^"]+)"', xml_content[:4096]):
            prefix = m.group(1) or ""
            ET.register_namespace(prefix, m.group(2)) if prefix else ET.register_namespace("", m.group(2))
        try:
            root = ET.fromstring(xml_content)
            builder = MultilingualTextBuilder()
            mt_count = 0
            for mt_elem in [e for e in root.iter() if MultilingualTextBuilder._local_tag(e) in ("MultilingualText",)]:
                try:
                    builder.rebuild_element(mt_elem)
                    mt_count += 1
                except Exception:
                    pass
            if mt_count:
                xml_content = ET.tostring(root, encoding="unicode")
                if declaration and not xml_content.startswith("<?"):
                    xml_content = declaration.rstrip() + "\n" + xml_content
                warnings.append(
                    f"DOM 级重建了 {mt_count} 个 MultilingualText 节点为 TIA 标准结构"
                )
        except ET.ParseError:
            warnings.append("XML DOM 解析失败，跳过 MultilingualText 重建")

        # ---- Step 3: 删除 <Number> 节点（管线第三层） ----
        allocator = ScreenNumberAllocator()
        xml_content = allocator.remove_number_nodes(xml_content)
        warnings.append("已删除 XML 中的 <Number> 节点，TIA 将自动分配 screen number。")

        # ---- Step 3.5: 画面尺寸保护 ----
        # TIA/WinCC Advanced 要求导入 XML 的 Screen Width/Height 与目标设备完全一致。
        # 如果不先修正，Screens.Import 可能报错，部分环境下甚至导致 TIA Portal 闪退。
        xml_content = self._align_xml_screen_size_to_hmi(xml_content, hmi_software, warnings)

        # ---- Step 4: screen name 冲突检测 ----
        # 兼容两种格式：
        #   1) <SW.Screen Name="...">
        #   2) TIA V16/Comfort: <Hmi.Screen.Screen><AttributeList><Name>...</Name>
        def _extract_screen_name_from_xml(xml_text: str) -> str:
            m = re.search(r'<(?:SW\.)?Screen[^>]*Name="([^"]*)"', xml_text)
            if m:
                return m.group(1)
            try:
                r = ET.fromstring(xml_text)
                def local(elem):
                    tag = elem.tag
                    if "}" in tag:
                        return tag.rsplit("}", 1)[-1]
                    if "." in tag:
                        return tag.rsplit(".", 1)[-1]
                    return tag
                for elem in r.iter():
                    if local(elem) != "Screen":
                        continue
                    for child in elem:
                        if local(child) != "AttributeList":
                            continue
                        for attr in child:
                            if local(attr) == "Name" and (attr.text or "").strip():
                                return attr.text.strip()
            except Exception:
                pass
            return ""

        def _replace_screen_name_in_xml(xml_text: str, old_name: str, new_name: str) -> str:
            if f'Name="{old_name}"' in xml_text:
                return xml_text.replace(f'Name="{old_name}"', f'Name="{new_name}"', 1)
            try:
                r = ET.fromstring(xml_text)
                replaced = False
                def local(elem):
                    tag = elem.tag
                    if "}" in tag:
                        return tag.rsplit("}", 1)[-1]
                    if "." in tag:
                        return tag.rsplit(".", 1)[-1]
                    return tag
                for elem in r.iter():
                    if local(elem) != "Screen":
                        continue
                    for child in elem:
                        if local(child) != "AttributeList":
                            continue
                        for attr in child:
                            if local(attr) == "Name" and (attr.text or "").strip() == old_name:
                                attr.text = new_name
                                replaced = True
                                break
                        if replaced:
                            break
                    if replaced:
                        break
                if replaced:
                    result = ET.tostring(r, encoding="unicode")
                    if declaration and not result.startswith("<?"):
                        result = declaration.rstrip() + "\n" + result
                    return result
            except Exception:
                pass
            return xml_text

        screen_name = _extract_screen_name_from_xml(xml_content)
        if screen_name and hmi_software is not None:
            existing_names = self._list_available_screens(hmi_software)
            if screen_name in existing_names:
                import datetime
                suffix = datetime.datetime.now().strftime("%H%M%S")
                new_name = f"{screen_name}_{suffix}"
                xml_content = _replace_screen_name_in_xml(xml_content, screen_name, new_name)
                warnings.append(
                    f"画面名称 '{screen_name}' 已存在，已自动重命名为 '{new_name}'。"
                )

        # ---- Step 5: XML Lint 最终扫描（管线第四层：XmlValidator 闸门） ----
        validation = XmlValidator.validate(xml_content)
        if validation.errors:
            for err in validation.errors:
                warnings.append(f"[Lint 错误] {err}")
        if validation.warnings:
            for w in validation.warnings:
                if w not in warnings:
                    warnings.append(f"[Lint 警告] {w}")
        if validation.stats.get("html_tags", 0) > 0:
            warnings.append(
                f"[Lint 严重] 预处理后仍检测到 {validation.stats['html_tags']} 处 HTML 标签，"
                f"导入可能失败。请检查原始 IR 中的文本字段是否包含 HTML。"
            )

        return xml_content, warnings

    # ------------------------------------------------------------------
    # screen size 检测与自动对齐
    # ------------------------------------------------------------------
    def _local_xml_tag(self, elem) -> str:
        """提取 ElementTree 元素本地名，兼容命名空间和 Hmi.Screen.* 点分名。"""
        tag = elem.tag
        if "}" in tag:
            tag = tag.rsplit("}", 1)[-1]
        if "." in tag:
            tag = tag.rsplit(".", 1)[-1]
        return tag

    def _parse_resolution_text(self, value: str):
        """解析 '800x480' / '800*480' / '800,480' 为 (800, 480)。"""
        import re
        if not value:
            return None
        m = re.search(r'(\d{3,5})\s*[xX*×,，]\s*(\d{3,5})', str(value))
        if not m:
            return None
        return int(m.group(1)), int(m.group(2))

    def _extract_screen_size_from_xml(self, xml_content: str):
        """从画面 XML 的 Screen 直接 AttributeList 读取 Width/Height。"""
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(xml_content)
        except Exception:
            return None

        for elem in root.iter():
            if self._local_xml_tag(elem) != "Screen":
                continue
            width = height = None
            for child in list(elem):
                if self._local_xml_tag(child) != "AttributeList":
                    continue
                for attr in list(child):
                    name = self._local_xml_tag(attr)
                    text = (attr.text or "").strip()
                    if name == "Width" and text.isdigit():
                        width = int(text)
                    elif name == "Height" and text.isdigit():
                        height = int(text)
            if width and height:
                return width, height
        return None

    def _set_screen_size_in_xml(self, xml_content: str, width: int, height: int,
                                scale_items: bool = True):
        """只修改 Screen 直接 Width/Height；可选按比例缩放画面控件坐标。"""
        import re
        import xml.etree.ElementTree as ET

        decl_match = re.match(r'(<\?xml[^?]*\?>\s*)', xml_content)
        declaration = decl_match.group(1) if decl_match else ""
        try:
            root = ET.fromstring(xml_content)
        except Exception:
            return xml_content, None, 0

        old_size = None
        screen_elem = None
        for elem in root.iter():
            if self._local_xml_tag(elem) != "Screen":
                continue
            screen_elem = elem
            old_size = self._read_screen_size_from_element(elem)
            for child in list(elem):
                if self._local_xml_tag(child) != "AttributeList":
                    continue
                has_w = has_h = False
                for attr in list(child):
                    name = self._local_xml_tag(attr)
                    if name == "Width":
                        attr.text = str(width)
                        has_w = True
                    elif name == "Height":
                        attr.text = str(height)
                        has_h = True
                if not has_w:
                    w_elem = ET.SubElement(child, "Width")
                    w_elem.text = str(width)
                if not has_h:
                    h_elem = ET.SubElement(child, "Height")
                    h_elem.text = str(height)
            break

        scaled_count = 0
        if scale_items and screen_elem is not None and old_size:
            old_w, old_h = old_size
            if old_w > 0 and old_h > 0 and (old_w, old_h) != (width, height):
                sx = width / old_w
                sy = height / old_h
                scaled_count = self._scale_screen_items(screen_elem, sx, sy)

        result = ET.tostring(root, encoding="unicode")
        if declaration and not result.startswith("<?"):
            result = declaration.rstrip() + "\n" + result
        return result, old_size, scaled_count

    def _read_screen_size_from_element(self, screen_elem):
        width = height = None
        for child in list(screen_elem):
            if self._local_xml_tag(child) != "AttributeList":
                continue
            for attr in list(child):
                name = self._local_xml_tag(attr)
                text = (attr.text or "").strip()
                if name == "Width" and text.isdigit():
                    width = int(text)
                elif name == "Height" and text.isdigit():
                    height = int(text)
        if width and height:
            return width, height
        return None

    def _scale_screen_items(self, screen_elem, sx: float, sy: float) -> int:
        """缩放 ScreenItems 的 Left/Top/Width/Height/Radius，避免尺寸变小后控件大量越界。"""
        item_tags = {
            "ScreenItem", "IOField", "Button", "SymbolicIOField", "Circle",
            "Ellipse", "Rectangle", "TextField", "GraphicView", "TrendView",
            "Gauge", "Slider", "Switch", "Line", "AlarmView", "UserView",
        }
        scaled = 0
        for item in screen_elem.iter():
            if item is screen_elem or self._local_xml_tag(item) not in item_tags:
                continue
            for attr_list in list(item):
                if self._local_xml_tag(attr_list) != "AttributeList":
                    continue
                touched = False
                for prop in list(attr_list):
                    name = self._local_xml_tag(prop)
                    text = (prop.text or "").strip()
                    if not text.lstrip("-").isdigit():
                        continue
                    value = int(text)
                    if name in ("Left", "X"):
                        prop.text = str(int(round(value * sx)))
                        touched = True
                    elif name in ("Top", "Y"):
                        prop.text = str(int(round(value * sy)))
                        touched = True
                    elif name == "Width":
                        prop.text = str(max(1, int(round(value * sx))))
                        touched = True
                    elif name == "Height":
                        prop.text = str(max(1, int(round(value * sy))))
                        touched = True
                    elif name == "Radius":
                        prop.text = str(max(1, int(round(value * min(sx, sy)))))
                        touched = True
                if touched:
                    scaled += 1
        return scaled

    def _resolve_hmi_screen_size(self, hmi_software, warnings: list = None):
        """优先从目标 HMI 已有画面/导出 XML 获取真实尺寸，避免依赖默认配置。"""
        warnings = warnings if warnings is not None else []

        # 1) 显式配置优先：openness.target_resolution = "800x480"。
        explicit = self.cfg.get("target_resolution") or self.cfg.get("screen_resolution")
        parsed = self._parse_resolution_text(explicit)
        if parsed:
            return parsed

        # 2) 直接读取已有画面对象属性。
        screens = []
        try:
            screens = self._collect_screens(hmi_software.ScreenFolder)
        except Exception:
            screens = []
        for s in screens:
            try:
                w = getattr(s, "Width", None)
                h = getattr(s, "Height", None)
                if w and h:
                    return int(w), int(h)
            except Exception:
                pass

        # 3) 导出第一个已有画面，解析其 XML 中的 Width/Height。
        for s in screens[:3]:
            try:
                import tempfile
                name = str(getattr(s, "Name", "_screen_size_probe"))
                export_path = os.path.join(tempfile.gettempdir(), f"_tia_size_probe_{name}.xml")
                export_result = self._export_screen_to_file(s, export_path)
                if export_result.get("ok") and os.path.exists(export_path):
                    with open(export_path, "r", encoding="utf-8-sig", errors="ignore") as f:
                        size = self._extract_screen_size_from_xml(f.read())
                    try:
                        os.remove(export_path)
                    except Exception:
                        pass
                    if size:
                        return size
            except Exception as e:
                warnings.append(f"导出已有画面读取尺寸失败：{e}")

        warnings.append(
            "无法自动读取目标 HMI 画面尺寸。请在 config.yaml 的 openness 下增加 "
            "target_resolution，例如 target_resolution: \"800x480\"。"
        )
        return None

    def _align_xml_screen_size_to_hmi(self, xml_content: str, hmi_software, warnings: list):
        """导入前把 XML Screen 尺寸对齐到目标 HMI，避免 Screens.Import 内部崩溃。"""
        if hmi_software is None:
            return xml_content
        xml_size = self._extract_screen_size_from_xml(xml_content)
        target_size = self._resolve_hmi_screen_size(hmi_software, warnings)
        if not xml_size or not target_size:
            return xml_content
        if xml_size == target_size:
            return xml_content

        auto_scale = self.cfg.get("auto_scale_screen_items", True)
        xml_content, old_size, scaled = self._set_screen_size_in_xml(
            xml_content, target_size[0], target_size[1], scale_items=auto_scale
        )
        warnings.append(
            f"已将 XML 画面尺寸从 {xml_size[0]}x{xml_size[1]} "
            f"自动对齐为目标 HMI 尺寸 {target_size[0]}x{target_size[1]}。"
        )
        if auto_scale and scaled:
            warnings.append(f"已按比例缩放 {scaled} 个画面控件，减少导入后越界。")
        return xml_content

    # ------------------------------------------------------------------
    # screen number 冲突检测与自动分配
    # ------------------------------------------------------------------
    def _detect_screen_number_conflicts(
        self, hmi_software, xml_content: str
    ) -> dict:
        """检测 XML 中的 screen number 是否与已有画面冲突。

        返回:
            {
                "has_conflict": True/False,
                "xml_number": int or None,
                "used_numbers": [...],
                "suggested_number": int,
                "warnings": [...],
            }
        """
        import re
        result = {
            "has_conflict": False,
            "xml_number": None,
            "used_numbers": [],
            "suggested_number": 1,
            "warnings": [],
        }

        # 收集已有 screen numbers
        try:
            for s in hmi_software.ScreenFolder.Screens:
                try:
                    num = s.Number
                    result["used_numbers"].append(int(num))
                except Exception:
                    pass
        except Exception:
            pass

        # 从 XML 提取 Number
        number_match = re.search(r'<(\w+:)?Number>(\d+)</(\w+:)?Number>', xml_content)
        if number_match:
            result["xml_number"] = int(number_match.group(2))

        # 自动分配：已有画面中最大 number + 1
        if result["used_numbers"]:
            result["suggested_number"] = max(result["used_numbers"]) + 1
        else:
            result["suggested_number"] = 1

        # 检测冲突
        if result["xml_number"] is not None and result["xml_number"] in result["used_numbers"]:
            result["has_conflict"] = True
            result["warnings"].append(
                f"screen number '{result['xml_number']}' 已被占用，"
                f"建议使用 '{result['suggested_number']}'。"
                f"当前已用 numbers: {result['used_numbers']}"
            )

        return result

    # ------------------------------------------------------------------
    # 统一导入封装（稳定版：仅 Screens.Import，无 hacks）
    # ------------------------------------------------------------------
    def _import_to_screens(
        self, screens_collection, file_info, import_options, preprocessed_xml_path=None
    ) -> dict:
        """统一导入封装 — 严格按照 Openness 规范。

        规范要求（必须遵守）：
          1. 唯一方式：Screens.Import(FileInfo, ImportOptions.Override)
          2. 禁止: ScreenComposition.Import / InvokeMember 反射 / temp ASCII hack
          3. 每次操作重新获取对象链，避免 disposed object

        参数:
            screens_collection: HMI ScreenFolder.Screens 集合。
            file_info: System.IO.FileInfo 对象。
            import_options: ImportOptions.Override 等。
            preprocessed_xml_path: 预处理后的 XML 路径（仅用于错误诊断）。

        返回:
            {"ok": True/False, "method": "...", "attempts": [...]}
        """
        attempts = []

        # ---- 唯一策略：Screens.Import(FileInfo, ImportOptions) ----
        # 不允许：ASCII temp path、反射、其他 hack
        try:
            screens_collection.Import(file_info, import_options)
            return {
                "ok": True,
                "method": "Screens.Import(FileInfo, ImportOptions.Override)",
                "attempts": attempts,
            }
        except Exception as e:
            attempts.append({
                "method": "Screens.Import(FileInfo, ImportOptions.Override)",
                "error": str(e),
                "xml_path": preprocessed_xml_path,
            })

        # ---- Fail Fast：不尝试任何补救方案 ----
        return {
            "ok": False,
            "message": (
                f"导入失败：Screens.Import 调用失败。"
                f"请确认：1) XML 格式兼容当前 TIA 版本；"
                f"2) screen number/name 无冲突；"
                f"3) TIA Portal 中已加载项目。"
                f"详情：{attempts}"
            ),
            "attempts": attempts,
        }

    # ---------------- 查找 HMI 软件 ----------------
    def _find_hmi_software(self):
        """遍历设备，找到目标 HMI 设备的 HmiTarget/Software。
        兼容 Basic/Comfort 等经典面板（Siemens.Engineering.Hmi）和 Unified 面板
        （Siemens.Engineering.HmiUnified），自动探测当前 TIA 版本可用的程序集。
        """
        # 按实际安装情况尝试加载 HMI 程序集（Basic/Comfort 归属 Hmi，Unified 归属 HmiUnified）
        for asm in ("Siemens.Engineering.HmiUnified", "Siemens.Engineering.Hmi"):
            try:
                __import__(asm)  # noqa: F401
            except Exception:
                pass

        target_name = str(self.cfg.get("hmi_device", "") or "").strip()
        self._last_hmi_device = None
        self._last_hmi_item = None

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

        for device in self._project.Devices:
            for item in device.DeviceItems:
                try:
                    sw_container = item.GetService[
                        __import__("Siemens.Engineering.HW.Features",
                                   fromlist=["SoftwareContainer"]).SoftwareContainer]()
                    if sw_container and sw_container.Software:
                        sw = sw_container.Software
                        sw_type = f"{type(sw).__module__}.{type(sw).__name__}"
                        # Basic/Comfort/Unified 的软件对象类型名/模块名均会包含 Hmi。
                        if "Hmi" in sw_type and _target_match(device, item, sw):
                            self._last_hmi_device = device
                            self._last_hmi_item = item
                            return sw
                except Exception:
                    continue
        return None

    def _safe_str_attr(self, obj, attr: str) -> str:
        try:
            value = getattr(obj, attr)
            return str(value) if value is not None else ""
        except Exception:
            return ""

    def _detect_classic_hmi_family(self, sw, device=None, item=None) -> str:
        """把经典 HMI 进一步区分为 Basic / Comfort / Classic。

        Openness 中 Basic 和 Comfort 通常同属 Siemens.Engineering.Hmi，
        仅靠 sw 的 Python/.NET 类型名往往只能识别为 HmiTarget。这里综合：
        1) 用户配置 hmi_defaults.hmi_type / openness.hmi_type；
        2) 设备名、DeviceItem 名、TypeIdentifier/OrderNumber 等字符串。
        """
        cfg_type = (
            (self.hmi_defaults or {}).get("hmi_type")
            or self.cfg.get("hmi_type")
            or ""
        )
        cfg_low = str(cfg_type).lower()
        if "basic" in cfg_low or "ktp" in cfg_low:
            return "Basic"
        if "comfort" in cfg_low:
            return "Comfort"

        parts = []
        for obj in (device, item, sw):
            if obj is None:
                continue
            parts.append(type(obj).__name__)
            parts.append(getattr(type(obj), "FullName", "") or "")
            for attr in ("Name", "DeviceName", "TypeIdentifier", "OrderNumber", "ProductName"):
                parts.append(self._safe_str_attr(obj, attr))
        joined = " ".join(p for p in parts if p).lower()

        if "basic" in joined or "ktp" in joined:
            return "Basic"
        if "comfort" in joined:
            return "Comfort"
        return "Classic"

    # ---------------- 导出参考画面（校准用） -----------------
    def export_reference_screen(self, screen_name: str = "") -> dict:
        """导出 HMI 画面的 XML 作为格式参考。
        如果 screen_name 为空则导出第一个画面。
        用于 SimaticML 校准：不同 TIA 版本/HMI 类型的 XML schema 不同，
        用实际导出的格式做模板才能保证导入兼容。

        参数: screen_name — 可选，指定要导出的画面名称。
        """
        warnings: list = []
        if not self._project:
            return {"ok": False, "message": "尚未连接到博途项目。", "warnings": warnings}
        try:
            sw = self._find_hmi_software()
            if sw is None:
                return {"ok": False, "message": "未找到 HMI 设备。", "warnings": warnings}

            # 使用统一的画面查找
            target_screen, find_warnings = self._find_screen_by_name(sw, screen_name)
            warnings.extend(find_warnings)

            if target_screen is None:
                available = self._list_available_screens(sw)
                return {
                    "ok": False,
                    "message": f"未找到画面 '{screen_name}'。" if screen_name
                               else "HMI 画面文件夹中没有画面。请先在博途中手动创建一个画面。",
                    "available_screens": available,
                    "warnings": warnings,
                }

            actual_name = str(target_screen.Name)

            # 使用统一的导出封装（不再直接传 str 给 Screen.Export）
            import tempfile
            export_path = os.path.join(tempfile.gettempdir(), f"_tia_ref_{actual_name}.xml")
            export_result = self._export_screen_to_file(target_screen, export_path)

            if not export_result.get("ok"):
                return {
                    "ok": False,
                    "message": f"导出参考画面失败：{export_result.get('message', '')}",
                    "warnings": warnings + export_result.get("warnings", []),
                    "details": {"attempts": export_result.get("attempts", [])},
                }

            with open(export_path, "r", encoding="utf-8") as f:
                xml_content = f.read()

            # 清理临时文件
            try:
                os.remove(export_path)
            except Exception:
                pass

            return {
                "ok": True,
                "screen_name": actual_name,
                "xml": xml_content,
                "message": f"参考画面 XML 已导出：{actual_name}",
                "warnings": warnings + export_result.get("warnings", []),
                "details": {
                    "export_method": export_result.get("method"),
                    "attempts": export_result.get("attempts", []),
                },
            }
        except Exception as e:
            return {
                "ok": False,
                "message": f"导出参考画面异常：{e}",
                "warnings": warnings,
            }

    # ---------------- 导入画面（IR → 画面）---------------
    def import_screen(self, xml_path: str) -> dict:
        """把 SimaticML XML 导入到 HMI 画面文件夹。

        严格按照 TIA Portal Openness 导入规范：
          - 使用 Screens.Import(FileInfo, ImportOptions.Override)
          - 导入前预处理 XML（删除 Number 节点、检测 name 冲突）
          - 每次重新获取对象链，避免 disposed object
        """
        if not self._project:
            return {"imported": False, "error": "尚未连接到博途项目，请先点击连接。"}
        try:
            from Siemens.Engineering import ImportOptions   # type: ignore

            # ⚠️ 每次重新获取对象链（禁止复用旧引用，避免 disposed object）
            sw = self._find_hmi_software()
            if sw is None:
                return {"imported": False,
                        "error": f"未找到 HMI 设备 '{self.cfg.get('hmi_device')}' 的软件。"}

            # ---- 读取并预处理 XML ----
            with open(xml_path, "r", encoding="utf-8-sig") as f:
                xml_content = f.read()

            processed_xml, prep_warnings = self._preprocess_xml_for_import(
                xml_content, sw
            )

            # ---- screen number 冲突检测 ----
            conflict_info = self._detect_screen_number_conflicts(sw, processed_xml)
            prep_warnings.extend(conflict_info.get("warnings", []))

            # ---- 将预处理后的 XML 写入临时文件用于导入 ----
            import tempfile
            import shutil

            temp_dir = tempfile.mkdtemp(prefix="tia_import_")
            preprocessed_path = os.path.join(temp_dir, "preprocessed_screen.xml")
            try:
                with open(preprocessed_path, "w", encoding="utf-8-sig") as f:
                    f.write(processed_xml)

                # ⚠️ 重新获取对象链：Project → Device → HmiTarget → ScreenFolder → Screens
                sw2 = self._find_hmi_software()
                if sw2 is None:
                    return {"imported": False,
                            "error": "无法重新获取 HMI 设备引用。"}

                file_info = self._make_fileinfo(preprocessed_path)
                screen_folder = sw2.ScreenFolder

                # 如配置了子文件夹，定位或创建
                sub_folder_name = self.cfg.get("screen_folder", "")
                if sub_folder_name:
                    folder = screen_folder.Folders.Find(sub_folder_name)
                    if folder is None:
                        folder = screen_folder.Folders.Create(sub_folder_name)
                    target_screens = folder.Screens
                else:
                    target_screens = screen_folder.Screens

                # ---- 统一导入：Screens.Import(FileInfo, ImportOptions.Override) ----
                import_result = self._import_to_screens(
                    target_screens, file_info, ImportOptions.Override,
                    preprocessed_xml_path=preprocessed_path,
                )
            finally:
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass

            if not import_result["ok"]:
                return {"imported": False, "error": import_result["message"],
                        "warnings": prep_warnings}

            msg = ["画面已导入。"]
            if prep_warnings:
                msg.append(f"预处理警告：{'; '.join(prep_warnings)}")

            if self.cfg.get("compile_after_import", True):
                try:
                    self._compile()
                    msg.append("已触发编译。")
                except Exception as ce:
                    msg.append(f"编译时告警：{ce}")
            if self.cfg.get("save_after_import", False):
                self._project.Save()
                msg.append("项目已保存。")

            return {"imported": True, "message": " ".join(msg),
                    "warnings": prep_warnings}
        except Exception as e:
            return {"imported": False, "error": f"导入失败：{e}",
                    "message": f"导入失败：{e}"}

    def _compile(self):
        from Siemens.Engineering.Compiler import ICompilable  # type: ignore  # noqa
        # 对 HMI 软件触发编译
        sw = self._find_hmi_software()
        compiler = sw.GetService[ICompilable]()
        compiler.Compile()

    # ------------------------------------------------------------------
    # 变量表同步（VariableEngine 集成）— V4.2 家族感知路由
    # ------------------------------------------------------------------
    def sync_tags(self, tags: list) -> dict:
        """将 HMI Tags 自动写入 TIA Portal 项目的 HMI 变量表。

        V4.2: 重构为家族感知路由。不再硬编码 sw.TagTables，改为：
          - Classic (Basic/Comfort) → TagXmlBuilder + ClassicOpennessExecutor.import_tags_to_default_table
          - Unified → UnifiedOpennessExecutor.create_tags
          - Unknown → 反射探测 + 结构化诊断

        参数:
            tags: IR 中的 tags 数组，每项含 name/data_type/address/comment。

        返回:
            {"ok": True/False, "created": [...], "skipped": [...], "errors": [...]}
        """
        result: dict = {"ok": False, "created": [], "skipped": [], "errors": []}

        if not self._project:
            result["errors"].append("尚未连接到博途项目。")
            return result

        try:
            sw = self._find_hmi_software()
            if sw is None:
                result["errors"].append("未找到 HMI 设备。")
                return result

            # V4.2: 探测对象 .NET 类型用于诊断
            sw_type = _net_type_name(sw)

            # V4.2: 识别 HMI 家族（Basic/Comfort/Unified/Unknown）
            caps = self.get_hmi_capabilities()
            hmi_family = caps.get("hmi_family", "Unknown")

            # V4.2: Unknown family 立即阻断，不探测容器
            if hmi_family not in ("Basic", "Comfort", "Classic", "Unified"):
                from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
                from backend.domain.enums import DiagnosticSeverity

                sw_info = _describe_dotnet_object_safe(sw)
                diag = Diagnostic(
                    code=DiagnosticCodes.HMI_FAMILY_UNKNOWN,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P30_TAG_TABLES_AND_TAGS",
                    message=(
                        f"HMI family is '{hmi_family}'. "
                        f"Cannot import tags for unknown HMI type. "
                        f"Object type: {sw_info.get('dotnet_full_name', sw_type)}. "
                        f"Available properties: {sw_info.get('properties', {})}."
                    ),
                    details={
                        "sw_type": sw_type,
                        "hmi_family": hmi_family,
                        "detected_family_info": sw_info,
                    },
                    remediation=(
                        "Specify hmi_defaults.hmi_type as 'basic', 'comfort', or 'unified', "
                        "or connect to a supported HMI device."
                    ),
                )
                result["errors"].append(f"[{diag.code}] {diag.message}")
                return result

            # V4.2: 反射探测变量容器，获取已有变量名
            container = _resolve_hmi_tag_container(sw, hmi_family)
            if not container["ok"]:
                for d in container["diagnostics"]:
                    result["errors"].append(d)
                return result

            existing_names = container["existing_names"]
            access_path = container["access_path"]

            # 过滤已存在的变量
            skipped: list[str] = []
            new_tags: list[dict] = []
            for t in tags:
                name = str(t.get("name", "")).strip()
                if not name:
                    continue
                if name in existing_names:
                    skipped.append(name)
                else:
                    new_tags.append(t)

            result["skipped"] = skipped

            if not new_tags:
                result["ok"] = len(skipped) > 0
                if not result["ok"] and not result["errors"]:
                    result["errors"].append("没有可创建的变量。")
                return result

            # V4.2: 根据家族路由到正确的 executor
            if hmi_family in ("Basic", "Comfort", "Classic"):
                # 经典路径：TagXmlBuilder 生成 XML + import_hmi_tags_safe（XML Import 主路径）
                from backend.openness.classic_executor import ClassicOpennessExecutor
                from backend.backends.classic.tag_xml_builder import TagXmlBuilder
                from backend.domain.ir_v2 import TagSpec
                from backend.domain.enums import TagScope

                tag_specs = []
                tag_items: list[dict] = []
                for t in new_tags:
                    name = str(t.get("name", "")).strip()
                    data_type = str(t.get("data_type", "Bool")).strip()
                    addr = str(t.get("address", "")).strip()
                    scope = TagScope.EXTERNAL if addr else TagScope.INTERNAL

                    spec = TagSpec(
                        name=name,
                        data_type=data_type,
                        scope=scope,
                        table="DefaultTagTable",
                    )
                    if addr:
                        spec.address = addr
                    tag_specs.append(spec)

                    # 构建 tag_items 用于预期变量名列表
                    item: dict = {
                        "name": name,
                        "data_type": data_type,
                        "scope": "external" if addr else "internal",
                    }
                    if addr:
                        item["address"] = addr
                    conn = str(t.get("connection", "")).strip()
                    if conn:
                        item["connection"] = conn
                    tag_items.append(item)

                xml_builder = TagXmlBuilder()
                tags_xml = xml_builder.build_tags_batch_export_xml(
                    tag_specs, table_name="DefaultTagTable",
                )
                executor = ClassicOpennessExecutor()
                # V4.2: XML Import 主路径（无 UPSERT Create 回退）
                step_result = executor.import_hmi_tags_safe(sw, tags_xml, tag_items)

                if step_result.success:
                    result["created"] = [t["name"] for t in new_tags]
                    result["ok"] = True
                else:
                    # 检查 payload 中的部分成功信息
                    payload = getattr(step_result, "payload", None) or {}
                    missing_tags = payload.get("missing_tags", [])
                    imported_count = payload.get("imported_count", 0)
                    if imported_count > 0:
                        result["created"] = [
                            n for n in [t["name"] for t in new_tags]
                            if n not in missing_tags
                        ]
                        result["ok"] = True if result["created"] else False
                    for d in step_result.diagnostics:
                        result["errors"].append(
                            f"[{d.code}] {d.message}"
                        )

            elif hmi_family == "Unified":
                # Unified 路径：UnifiedOpennessExecutor.create_tags
                from backend.openness.unified_executor import UnifiedOpennessExecutor

                specs = [
                    {
                        "name": str(t.get("name", "")).strip(),
                        "data_type": str(t.get("data_type", "Bool")).strip(),
                    }
                    for t in new_tags
                ]
                executor = UnifiedOpennessExecutor()
                step_result = executor.create_tags(sw, specs)

                if step_result.success:
                    result["created"] = [t["name"] for t in new_tags]
                    result["ok"] = True
                else:
                    for d in step_result.diagnostics:
                        result["errors"].append(
                            f"[{d.code}] {d.message}"
                        )

            else:
                # Unknown HMI family — BLOCK, do not guess API
                from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
                from backend.domain.enums import DiagnosticSeverity

                sw_info = _describe_dotnet_object_safe(sw)
                diag = Diagnostic(
                    code=DiagnosticCodes.HMI_FAMILY_UNKNOWN,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P30_TAG_TABLES_AND_TAGS",
                    message=(
                        f"HMI family is '{hmi_family}'. "
                        f"Cannot import tags for unknown HMI type. "
                        f"Object type: {sw_info.get('dotnet_full_name', sw_type)}. "
                        f"Available properties: {sw_info.get('properties', {})}."
                    ),
                    details={
                        "sw_type": sw_type,
                        "hmi_family": hmi_family,
                        "detected_family_info": sw_info,
                    },
                    remediation=(
                        "Specify hmi_defaults.hmi_type as 'basic', 'comfort', or 'unified', "
                        "or connect to a supported HMI device."
                    ),
                )
                result["errors"].append(f"[{diag.code}] {diag.message}")

        except Exception as e:
            result["errors"].append(f"同步变量表异常：{e}")

        return result

    def _verify_hmi_tags_exist(self, tag_names: list[str]) -> None:
        """验证所有 tag names 在 HMI Tag Table 中存在。

        V4.2: 重构为家族感知验证。不再硬编码 sw.TagTables，改为：
          - Classic → ClassicOpennessExecutor.read_default_tag_table
          - Unified → sw.Tags 直接枚举
          - Unknown → 反射探测 + 结构化 ValueError

        如果缺失，抛出 ValueError，后续画面导入被阻断。
        """
        if not tag_names or not self._project:
            return

        sw = self._find_hmi_software()
        if sw is None:
            raise ValueError("无法定位 HMI 设备以验证变量。")

        caps = self.get_hmi_capabilities()
        hmi_family = caps.get("hmi_family", "Unknown")
        sw_type = _net_type_name(sw)

        existing_names: set[str] = set()

        if hmi_family in ("Basic", "Comfort", "Classic"):
            # 经典路径：ClassicOpennessExecutor 读取 DefaultTagTable
            try:
                from backend.openness.classic_executor import ClassicOpennessExecutor
                executor = ClassicOpennessExecutor()
                dt = executor.read_default_tag_table(sw)
                if dt.get("success"):
                    existing_names = set(dt.get("tag_names", []))
                else:
                    # Fallback: 直接反射读取
                    container = _resolve_hmi_tag_container(sw, hmi_family)
                    if container["ok"]:
                        existing_names = container["existing_names"]
                    else:
                        raise ValueError(
                            f"无法验证 Classic HMI 变量: {dt.get('error', '未知错误')}。"
                            f"对象类型: {sw_type}，"
                            f"诊断: {container.get('diagnostics', [])}"
                        )
            except ValueError:
                raise
            except Exception as e:
                # Fallback: 直接反射
                container = _resolve_hmi_tag_container(sw, hmi_family)
                if container["ok"]:
                    existing_names = container["existing_names"]
                else:
                    raise ValueError(
                        f"无法验证 Classic HMI 变量: {e}。"
                        f"对象类型: {sw_type}，"
                        f"已尝试路径: TagFolder.DefaultTagTable.Tags"
                    )

        elif hmi_family == "Unified":
            # Unified 路径：sw.Tags 直接集合
            tags_coll = _try_get_attr(sw, "Tags")
            if tags_coll is not None:
                from backend.openness.diagnostics_utils import enumerate_tag_names
                existing_names = set(enumerate_tag_names(tags_coll))
            else:
                probed = {}
                for attr in ("Tags", "TagFolder", "Screens"):
                    probed[attr] = _try_get_attr(sw, attr) is not None
                raise ValueError(
                    f"无法验证 Unified HMI 变量：hmiSoftware.Tags 不可用。"
                    f"对象类型: {sw_type}，"
                    f"可用属性探测: {probed}。"
                    f"请确认当前传入的是 Unified hmi_software 对象。"
                )

        else:
            # 未知家族：反射探测所有可能路径
            container = _resolve_hmi_tag_container(sw, hmi_family)
            if container["ok"]:
                existing_names = container["existing_names"]
            else:
                probed = {}
                for attr in ("TagFolder", "TagTables", "Tags"):
                    probed[attr] = _try_get_attr(sw, attr) is not None
                raise ValueError(
                    f"无法验证 HMI 变量：未知的 HMI 家族 '{hmi_family}'。"
                    f"当前对象类型为 {sw_type}，"
                    f"已尝试路径: hmiSoftware.Tags / TagFolder.DefaultTagTable.Tags，"
                    f"可用属性探测: {probed}。"
                    f"请确认当前传入的是 hmi_software 对象，而不是 target/capability wrapper。"
                )

        missing = sorted(set(tag_names) - existing_names)
        if missing:
            raise ValueError(
                f"HMI Tag Table 中缺失以下变量: {missing}。"
                f"变量导入未完全成功，禁止继续导入画面。"
            )

    # ------------------------------------------------------------------
    # 6.1.1 HMI 类型识别
    # ------------------------------------------------------------------
    def get_hmi_capabilities(self) -> dict:
        """返回当前 HMI 设备的能力信息，供前端展示和路由决策。"""
        base = {
            "connected": self._project is not None,
            "project_name": str(self._project.Name) if self._project else "",
            "hmi_device": self.cfg.get("hmi_device", ""),
            "hmi_software_type": "Unknown",
            "is_unified": False,
            "is_classic": False,
            "is_basic": False,
            "is_comfort": False,
            "hmi_family": "Unknown",
            "supports_direct_screen_items": False,
            "supports_screen_xml_export_import": False,
            "available_screens": [],
            "recommended_mode": "simaticml",
            "warnings": [],
        }

        if not self._project:
            base["warnings"].append("尚未连接到博途项目。")
            return base

        try:
            sw = self._find_hmi_software()
            if sw is None:
                base["warnings"].append(
                    f"未找到 HMI 设备 '{self.cfg.get('hmi_device', '')}'，"
                    f"请检查设备名或确认项目中存在 HMI 设备。"
                )
                return base

            sw_type_name = type(sw).__name__
            sw_full_name = type(sw).FullName if hasattr(type(sw), "FullName") else sw_type_name
            sw_module = type(sw).__module__ or ""

            # 识别 HMI 类型。Basic/Comfort 同属经典 HMI，需要额外区分。
            is_unified = ("HmiUnified" in sw_full_name or
                          "HmiUnified" in sw_module or
                          "Unified" in sw_type_name)
            is_classic = not is_unified and ("Hmi" in sw_type_name or
                                             "Hmi" in sw_full_name or
                                             "Hmi" in sw_module)
            classic_family = "Unknown"
            if is_classic:
                classic_family = self._detect_classic_hmi_family(
                    sw,
                    getattr(self, "_last_hmi_device", None),
                    getattr(self, "_last_hmi_item", None),
                )

            is_basic = is_classic and classic_family == "Basic"
            is_comfort = is_classic and classic_family == "Comfort"

            base["hmi_family"] = "Unified" if is_unified else classic_family
            base["hmi_software_type"] = "Unified" if is_unified else (classic_family if is_classic else "Unknown")
            base["is_unified"] = is_unified
            base["is_classic"] = is_classic
            base["is_basic"] = is_basic
            base["is_comfort"] = is_comfort
            base["supports_screen_xml_export_import"] = bool(is_unified or is_classic)

            if is_unified:
                base["supports_direct_screen_items"] = True
                base["recommended_mode"] = "unified_direct"
            elif is_classic:
                base["supports_direct_screen_items"] = False
                base["recommended_mode"] = "classic_template_xml"

                tmpl_cfg = self.cfg.get("classic_template", {})
                has_template = bool(tmpl_cfg.get("enabled") and tmpl_cfg.get("template_xml_path"))

                if is_basic:
                    base["warnings"].append(
                        "已按 Basic/KTP Basic 经典面板处理：不使用 Unified 直接绘制，"
                        "建议只使用 Basic 面板自身导出的模板 XML 进行改写后导入。"
                    )
                    if not has_template:
                        base["warnings"].append(
                            "Basic 面板尚未配置模板 XML。请先在同一 Basic 触摸屏设备下手工创建模板画面，"
                            "导出 XML 后填入 classic_template.template_xml_path。"
                        )
                elif not has_template:
                    base["warnings"].append(
                        "经典 HMI 推荐使用模板 XML 模式，但尚未配置模板。"
                        "请先在博途中手工创建模板画面并导出模板 XML。"
                    )

            # 列出已有画面
            try:
                screens = list(sw.ScreenFolder.Screens)
                base["available_screens"] = [str(s.Name) for s in screens]
            except Exception:
                base["available_screens"] = []
                base["warnings"].append("无法列出画面列表。")

        except Exception as e:
            base["warnings"].append(f"获取 HMI 能力时出错：{e}")

        return base

    # ------------------------------------------------------------------
    # 6.1.2 支持指定画面导出模板 XML
    # ------------------------------------------------------------------
    def export_screen_xml_template(
        self,
        screen_name: str = "",
        export_dir: str = "",
        overwrite: bool = True,
    ) -> dict:
        """导出指定 HMI 画面为模板 XML 文件。

        参数:
            screen_name: 要导出的画面名称。为空则导出第一个画面。
            export_dir: 导出目录。为空则使用配置中的 template_export_dir。
            overwrite: 是否覆盖已有文件。

        返回:
            {"ok": True, "screen_name": "...", "xml_path": "...", "xml": "...", ...}
        """
        warnings: list = []
        if not self._project:
            return {"ok": False, "message": "尚未连接 TIA Portal 项目。", "warnings": warnings}

        try:
            sw = self._find_hmi_software()
            if sw is None:
                return {"ok": False, "message": "未找到 HMI 设备。", "warnings": warnings}

            # 使用统一的画面查找
            target_screen, find_warnings = self._find_screen_by_name(sw, screen_name)
            warnings.extend(find_warnings)

            if target_screen is None:
                available = self._list_available_screens(sw)
                return {
                    "ok": False,
                    "message": f"未找到画面 '{screen_name}'。" if screen_name
                               else "HMI 画面文件夹中没有画面。",
                    "available_screens": available,
                    "warnings": warnings,
                }

            actual_name = str(target_screen.Name)

            # 确定导出路径
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if not export_dir:
                tmpl_cfg = self.cfg.get("classic_template", {})
                export_dir = tmpl_cfg.get("template_export_dir", "exports/templates")
            if not os.path.isabs(export_dir):
                export_dir = os.path.join(base_dir, export_dir)
            os.makedirs(export_dir, exist_ok=True)

            xml_path = os.path.join(export_dir, f"{actual_name}_template.xml")

            if os.path.exists(xml_path) and not overwrite:
                return {
                    "ok": False,
                    "message": f"模板 XML 已存在：{xml_path}（设置 overwrite=true 覆盖）",
                    "xml_path": xml_path,
                    "warnings": warnings,
                }

            # 使用统一的导出封装（不再传 str 给 Screen.Export）
            export_result = self._export_screen_to_file(target_screen, xml_path)

            if not export_result.get("ok"):
                return {
                    "ok": False,
                    "message": f"导出模板 XML 失败：{export_result.get('message', '')}",
                    "xml_path": xml_path,
                    "warnings": warnings + export_result.get("warnings", []),
                    "details": {"attempts": export_result.get("attempts", [])},
                }

            with open(xml_path, "r", encoding="utf-8-sig", errors="ignore") as f:
                xml_content = f.read()

            return {
                "ok": True,
                "screen_name": actual_name,
                "xml_path": xml_path,
                "xml": xml_content,
                "message": f"模板 XML 已导出：{xml_path}",
                "warnings": warnings + export_result.get("warnings", []),
                "details": {
                    "export_method": export_result.get("method"),
                    "attempts": export_result.get("attempts", []),
                },
            }
        except Exception as e:
            return {
                "ok": False,
                "message": f"导出模板 XML 异常：{e}",
                "warnings": warnings,
            }

    # ------------------------------------------------------------------
    # 6.1.3 支持经典 HMI 模板 XML 导入
    # ------------------------------------------------------------------
    def import_screen_xml(
        self,
        xml_path: str,
        screen_folder: str = "",
        import_option: str = "Override",
    ) -> dict:
        """将 XML 画面文件导入到经典 HMI 的画面文件夹。

        严格按照 TIA Portal Openness 导入规范：
          - 统一使用 Screens.Import(FileInfo, ImportOptions)
          - 导入前预处理 XML（删除 Number 节点、检测 name 冲突）
          - 每次重新获取对象链，避免 disposed object

        参数:
            xml_path: XML 文件路径。
            screen_folder: 目标子文件夹名，留空导入到根画面文件夹。
            import_option: ImportOptions（Override / Rename / ...）。

        返回:
            {"imported": True, "message": "...", ...}
        """
        if not self._project:
            return {"imported": False, "error": "尚未连接到博途项目。",
                    "message": "尚未连接到博途项目。"}

        if not os.path.exists(xml_path):
            return {"imported": False,
                    "error": f"XML 文件不存在: {xml_path}",
                    "message": f"XML 文件不存在: {xml_path}"}

        try:
            from Siemens.Engineering import ImportOptions  # type: ignore

            # ⚠️ 每次重新获取对象链（禁止复用旧引用，避免 disposed object）
            sw = self._find_hmi_software()
            if sw is None:
                return {"imported": False,
                        "error": f"未找到 HMI 设备 '{self.cfg.get('hmi_device')}'。",
                        "message": f"未找到 HMI 设备 '{self.cfg.get('hmi_device')}'。"}

            # ---- 读取并预处理 XML ----
            with open(xml_path, "r", encoding="utf-8-sig") as f:
                xml_content = f.read()

            processed_xml, prep_warnings = self._preprocess_xml_for_import(
                xml_content, sw
            )

            # ---- screen number 冲突检测 ----
            conflict_info = self._detect_screen_number_conflicts(sw, processed_xml)
            prep_warnings.extend(conflict_info.get("warnings", []))

            # ---- 将预处理后的 XML 写入临时文件用于导入 ----
            import tempfile
            import shutil

            temp_dir = tempfile.mkdtemp(prefix="tia_import_xml_")
            preprocessed_path = os.path.join(temp_dir, "preprocessed_screen.xml")
            try:
                with open(preprocessed_path, "w", encoding="utf-8-sig") as f:
                    f.write(processed_xml)

                # ⚠️ 重新获取对象链（避免 disposed object）
                # Project → Device → HmiTarget → ScreenFolder → Folders → Screens
                sw2 = self._find_hmi_software()
                if sw2 is None:
                    return {"imported": False,
                            "error": "无法重新获取 HMI 设备引用。"}

                target_folder = sw2.ScreenFolder

                # 如果指定了子文件夹，尝试定位或创建
                if screen_folder:
                    try:
                        found = target_folder.Folders.Find(screen_folder)
                        if found is not None:
                            target_folder = found
                        else:
                            # 尝试创建子文件夹（TIA V17+ 支持）
                            try:
                                target_folder = target_folder.Folders.Create(screen_folder)
                            except Exception:
                                pass  # 旧版本可能不支持创建，继续使用根文件夹
                    except Exception:
                        pass

                # 解析导入选项
                import_opt = ImportOptions.Override
                opt_lower = import_option.lower()
                if "rename" in opt_lower:
                    try:
                        import_opt = ImportOptions.Rename
                    except AttributeError:
                        pass
                elif "preserve" in opt_lower:
                    try:
                        import_opt = ImportOptions.PreserveExisting
                    except AttributeError:
                        pass

                # ---- 统一导入：Screens.Import(FileInfo, ImportOptions) ----
                file_info = self._make_fileinfo(preprocessed_path)
                import_result = self._import_to_screens(
                    target_folder.Screens, file_info, import_opt,
                    preprocessed_xml_path=preprocessed_path,
                )
            finally:
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception:
                    pass

            if not import_result["ok"]:
                return {"imported": False, "error": import_result["message"],
                        "message": import_result["message"],
                        "warnings": prep_warnings}

            msg = ["画面已导入。"]
            if prep_warnings:
                msg.append(f"预处理警告：{'; '.join(prep_warnings)}")

            if self.cfg.get("compile_after_import", True):
                try:
                    self._compile()
                    msg.append("已触发编译。")
                except Exception as ce:
                    msg.append(f"编译时告警：{ce}")
            if self.cfg.get("save_after_import", False):
                self._project.Save()
                msg.append("项目已保存。")

            return {"imported": True, "message": " ".join(msg),
                    "warnings": prep_warnings}
        except Exception as e:
            err = f"导入失败：{e}"
            return {"imported": False, "error": err, "message": err}

    # ------------------------------------------------------------------
    # 6.1.4 Unified 直接画面生成
    # ------------------------------------------------------------------
    def create_unified_screen_from_ir(self, ir: dict) -> dict:
        """通过 Openness 对象模型直接创建 Unified 画面对象。

        仅用于 Unified HMI。遍历 IR 的 objects，按类型创建 Unified 控件。

        返回:
            {
                "ok": True/False,
                "screen_name": "...",
                "mode": "unified_direct",
                "hmi_type": "Unified",
                "objects_created": [...],
                "warnings": [...],
                "message": "...",
            }
        """
        if not self._project:
            return {"ok": False, "error": "尚未连接到博途项目。",
                    "mode": "unified_direct", "hmi_type": "Unknown", "warnings": []}

        # 检查是否为 Unified HMI
        caps = self.get_hmi_capabilities()
        if not caps["is_unified"]:
            return {
                "ok": False,
                "error": f"当前 HMI 类型为 {caps['hmi_software_type']}，"
                         f"Unified 直接绘制仅支持 Unified HMI。",
                "mode": "unified_direct",
                "hmi_type": caps["hmi_software_type"],
                "screen_name": ir.get("meta", {}).get("screen_name", ""),
                "objects_created": [],
                "warnings": caps["warnings"],
            }

        ud_cfg = self.cfg.get("unified_direct", {})
        policy = ud_cfg.get("unsupported_object_policy", "warn")
        update_existing = ud_cfg.get("update_existing_screen", True)
        clear_existing = ud_cfg.get("clear_existing_items", True)

        meta = ir.get("meta", {})
        screen_name = meta.get("screen_name", "Screen_1")
        objects = ir.get("objects", [])
        warnings: list[str] = []
        created_items: list[dict] = []

        try:
            sw = self._find_hmi_software()
            if sw is None:
                return {"ok": False, "error": "未找到 HMI 设备。",
                        "mode": "unified_direct", "hmi_type": "Unified",
                        "screen_name": screen_name, "objects_created": [], "warnings": warnings}

            # 查找或创建 Screen
            screen = None
            try:
                for s in sw.ScreenFolder.Screens:
                    if str(s.Name) == screen_name:
                        screen = s
                        break
            except Exception:
                pass

            if screen is not None:
                if not update_existing:
                    return {
                        "ok": False,
                        "error": f"画面 '{screen_name}' 已存在，且 update_existing_screen=false。",
                        "mode": "unified_direct", "hmi_type": "Unified",
                        "screen_name": screen_name, "objects_created": [], "warnings": warnings,
                    }
                if clear_existing:
                    try:
                        items = list(screen.ScreenItems)
                        for item in items:
                            try:
                                item.Delete()
                            except Exception:
                                pass
                        warnings.append(f"已清空画面 '{screen_name}' 的已有对象。")
                    except Exception as e:
                        warnings.append(f"清空已有对象时出错：{e}")
            else:
                try:
                    screen = sw.ScreenFolder.Screens.CreateScreen(screen_name)
                    warnings.append(f"已创建新画面 '{screen_name}'。")
                except Exception as e:
                    return {
                        "ok": False,
                        "error": f"创建画面 '{screen_name}' 失败：{e}",
                        "mode": "unified_direct", "hmi_type": "Unified",
                        "screen_name": screen_name, "objects_created": [], "warnings": warnings,
                    }

            # 遍历 IR 对象并创建 Unified 控件
            type_map = {
                "Text": ["Text", "TextBox", "Label", "TextBlock"],
                "Button": ["Button"],
                "IOField": ["IOField", "InputOutputField"],
                "SymbolicIOField": ["SymbolicIOField"],
                "Indicator": ["Circle", "Ellipse", "Shape", "Rectangle"],
            }

            for obj in objects:
                oid = obj.get("id", f"Item_{len(created_items)}")
                otype = obj.get("type", "")
                candidate_types = type_map.get(otype, [otype])

                item = _create_screen_item(screen, candidate_types, oid)
                if item is None:
                    msg = f"无法创建控件 '{oid}' (type={otype})，候选类型 {candidate_types} 均不可用。"
                    if policy == "error":
                        return {
                            "ok": False, "error": msg,
                            "mode": "unified_direct", "hmi_type": "Unified",
                            "screen_name": screen_name,
                            "objects_created": created_items, "warnings": warnings,
                        }
                    else:
                        warnings.append(msg)
                        created_items.append({
                            "object_id": oid, "object_type": otype,
                            "status": "skipped", "message": msg,
                        })
                        continue

                # 设置属性
                try:
                    _try_set_attr(item, "Name", oid)
                    x, y = obj.get("x", 0), obj.get("y", 0)
                    _try_set_attr(item, "Left", x)
                    _try_set_attr(item, "Top", y)

                    w = obj.get("width")
                    h = obj.get("height")
                    if w is not None:
                        _try_set_attr(item, "Width", w)
                    if h is not None:
                        _try_set_attr(item, "Height", h)

                    text = obj.get("text")
                    if text:
                        _try_set_attr(item, "Text", text)

                    tag = obj.get("process_tag")
                    if tag:
                        _try_set_attr(item, "ProcessValue", tag)

                    # 颜色
                    bg = obj.get("background_color")
                    if bg:
                        _try_set_attr(item, "BackColor", _hex_to_argb_int(bg))

                    created_items.append({
                        "object_id": oid, "object_type": otype,
                        "status": "created",
                        "message": f"已创建 {otype} 控件 '{oid}'。",
                    })
                except Exception as ex:
                    msg = f"设置控件 '{oid}' 属性时出错：{ex}"
                    warnings.append(msg)
                    created_items.append({
                        "object_id": oid, "object_type": otype,
                        "status": "failed", "message": msg,
                    })

            # 编译和保存
            if self.cfg.get("compile_after_import", True):
                try:
                    self._compile()
                    warnings.append("已触发编译。")
                except Exception as ce:
                    warnings.append(f"编译时告警：{ce}")
            if self.cfg.get("save_after_import", False):
                self._project.Save()
                warnings.append("项目已保存。")

            return {
                "ok": True,
                "mode": "unified_direct",
                "hmi_type": "Unified",
                "screen_name": screen_name,
                "objects_created": created_items,
                "warnings": warnings,
                "message": f"已创建 {screen_name}，共处理 {len(created_items)} 个对象。",
            }

        except Exception as e:
            return {
                "ok": False,
                "error": f"Unified 直接生成失败：{e}",
                "mode": "unified_direct", "hmi_type": "Unified",
                "screen_name": screen_name,
                "objects_created": created_items, "warnings": warnings,
            }

    # ------------------------------------------------------------------
    # 6.1.5 统一入口：根据模式自动路由
    # ------------------------------------------------------------------
    def import_or_generate_from_ir(self, ir: dict, mode: str = "auto") -> dict:
        """统一入口：根据 HMI 类型和用户选择的模式，自动路由到对应生成路线。

        V4.1 修复：变量导入必须在画面导入之前。
        流程: normalize → validate → VariableEngine.generate → sync_tags → verify → import screen

        参数:
            ir: 校验后的 HMI 画面 IR。
            mode: 生成模式 — auto | unified_direct | classic_template_xml | simaticml。

        返回:
            {"ok": True, "mode": "...", "hmi_type": "...", "screen_name": "...", ...}
        """
        from .hmi_ir import validate_ir as _validate
        from .tag_binding_normalizer import (
            normalize_legacy_tag_bindings,
            assert_legacy_tags_complete,
        )

        meta = ir.get("meta", {})
        screen_name = meta.get("screen_name", "Screen_1")

        # V4.1: Step 0 — normalize before validation
        try:
            ir = normalize_legacy_tag_bindings(ir)
        except ValueError as e:
            return {"ok": False, "error": f"变量绑定规范化失败：{e}",
                    "mode": mode, "hmi_type": "Unknown",
                    "screen_name": screen_name, "warnings": [], "details": {}}

        try:
            ir = _validate(ir)
        except Exception as e:
            return {"ok": False, "error": f"IR 校验失败：{e}",
                    "mode": mode, "hmi_type": "Unknown",
                    "screen_name": screen_name, "warnings": [], "details": {}}

        # V4.1: Step 0.5 — re-normalize after validation
        try:
            ir = normalize_legacy_tag_bindings(ir)
        except ValueError as e:
            return {"ok": False, "error": f"校验后变量规范化失败：{e}",
                    "mode": mode, "hmi_type": "Unknown",
                    "screen_name": screen_name, "warnings": [], "details": {}}

        # V4.1: Step 0.6 — VariableEngine.generate to fill missing tags
        from .variable_engine import VariableEngine
        engine = VariableEngine()
        try:
            ir = engine.generate(ir)
        except Exception as e:
            return {"ok": False, "error": f"VariableEngine.generate 失败：{e}",
                    "mode": mode, "hmi_type": "Unknown",
                    "screen_name": screen_name, "warnings": [], "details": {}}

        # V4.1: Step 0.7 — assert tags complete
        try:
            assert_legacy_tags_complete(ir)
        except ValueError as e:
            return {"ok": False, "error": f"变量不完整，终止画面导入：{e}",
                    "mode": mode, "hmi_type": "Unknown",
                    "screen_name": screen_name, "warnings": [], "details": {}}

        # V4.1: Step 0.8 — sync_tags before any screen import
        tag_sync_result = None
        tag_names = [t.get("name", "") for t in ir.get("tags", []) if t.get("name")]
        if tag_names and self._project:
            tag_sync_result = self.sync_tags(ir.get("tags", []))
            if not tag_sync_result.get("ok"):
                return {
                    "ok": False,
                    "mode": mode,
                    "hmi_type": "Unknown",
                    "screen_name": screen_name,
                    "message": f"HMI 变量同步失败，终止画面导入。错误: {tag_sync_result.get('errors', [])}",
                    "warnings": [],
                    "details": {"tag_sync": tag_sync_result},
                }

            # Verify tags exist after sync
            self._verify_hmi_tags_exist(tag_names)

        caps = self.get_hmi_capabilities()
        is_basic = bool(caps.get("is_basic"))

        # 自动判断模式
        if mode == "auto":
            if caps["is_unified"] and self.cfg.get("unified_direct", {}).get("enabled", True):
                mode = "unified_direct"
            elif caps["is_classic"] and self.cfg.get("classic_template", {}).get("enabled", True):
                mode = "classic_template_xml"
            else:
                mode = "simaticml"

        warnings = list(caps.get("warnings", []))
        details: dict = {}

        # ---- Unified 直接绘制 ----
        if mode == "unified_direct":
            if not caps["is_unified"]:
                fallback = "classic_template_xml" if caps.get("is_classic") else "simaticml"
                warnings.append(
                    f"当前 HMI 类型为 {caps['hmi_software_type']}，"
                    f"不支持 Unified 直接绘制，已回退到 {fallback}。"
                )
                mode = fallback
            else:
                result = self.create_unified_screen_from_ir(ir)
                result["mode"] = mode
                result["hmi_type"] = caps["hmi_software_type"]
                result.setdefault("details", {})
                return result

        # ---- 经典模板 XML ----
        if mode == "classic_template_xml":
            if not caps["is_classic"]:
                warnings.append(
                    f"当前 HMI 类型为 {caps['hmi_software_type']}，"
                    f"模板 XML 模式仅支持经典 HMI，已回退到 simaticml。"
                )
                mode = "simaticml"
            else:
                tmpl_cfg = self.cfg.get("classic_template", {})
                template_xml_path = ir.get("meta", {}).get("template_xml") or tmpl_cfg.get("template_xml_path", "")

                if not template_xml_path or not os.path.exists(template_xml_path):
                    msg = (
                        f"模板 XML 路径无效或不存在：{template_xml_path}。"
                        f"请先在博途中基于目标 HMI 设备导出模板画面 XML。"
                    )
                    if is_basic:
                        warnings.append(msg)
                        return {
                            "ok": False,
                            "mode": "classic_template_xml",
                            "hmi_type": caps["hmi_software_type"],
                            "screen_name": screen_name,
                            "message": (
                                "Basic/KTP Basic 面板已启用，但 Basic 画面导入必须使用同型号 Basic 面板导出的模板 XML。"
                                "请配置 openness.classic_template.template_xml_path 后重试。"
                            ),
                            "warnings": warnings,
                            "details": details,
                        }
                    warnings.append(msg + "已回退到 simaticml。")
                    mode = "simaticml"
                else:
                    try:
                        with open(template_xml_path, "r", encoding="utf-8") as f:
                            template_xml = f.read()

                        from .template_xml_generator import generate_from_template_xml
                        new_xml, gen_warnings = generate_from_template_xml(ir, template_xml)
                        warnings.extend(gen_warnings)

                        # 落盘生成的 XML
                        import os as _os
                        base_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
                        gen_dir = tmpl_cfg.get("generated_xml_dir", "exports/generated_from_template")
                        if not _os.path.isabs(gen_dir):
                            gen_dir = _os.path.join(base_dir, gen_dir)
                        _os.makedirs(gen_dir, exist_ok=True)

                        import datetime
                        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                        gen_xml_path = _os.path.join(gen_dir, f"{screen_name}_{ts}.xml")
                        with open(gen_xml_path, "w", encoding="utf-8") as f:
                            f.write(new_xml)

                        details["template_xml_path"] = template_xml_path
                        details["generated_xml_path"] = gen_xml_path
                        details["generated_xml"] = new_xml

                        # 导入
                        import_result = self.import_screen_xml(
                            gen_xml_path,
                            screen_folder=self.cfg.get("screen_folder", ""),
                            import_option=tmpl_cfg.get("import_option", "Override"),
                        )

                        # V4.1: tags 已在入口处同步，此处仅附加 tag_sync 到结果
                        if tag_sync_result and tag_sync_result.get("created"):
                            warnings.append(
                                f"已同步 {len(tag_sync_result['created'])} 个变量到 HMI 变量表"
                            )

                        return {
                            "ok": import_result.get("imported", False),
                            "mode": "classic_template_xml",
                            "hmi_type": caps["hmi_software_type"],
                            "screen_name": screen_name,
                            "message": import_result.get("message") or import_result.get("error", ""),
                            "warnings": warnings,
                            "details": details,
                            "tag_sync": tag_sync_result,
                        }
                    except Exception as e:
                        if is_basic:
                            warnings.append(f"Basic 模板 XML 生成失败：{e}")
                            return {
                                "ok": False,
                                "mode": "classic_template_xml",
                                "hmi_type": caps["hmi_software_type"],
                                "screen_name": screen_name,
                                "message": "Basic/KTP Basic 面板模板 XML 生成失败，未回退到 SimaticML，以避免生成与 Basic 设备不兼容的 XML。",
                                "warnings": warnings,
                                "details": details,
                            }
                        warnings.append(f"模板 XML 生成失败：{e}，已回退到 simaticml。")
                        mode = "simaticml"

        # ---- SimaticML 旧流程（兼容保留） ----
        if mode == "simaticml":
            if is_basic:
                warnings.append(
                    "当前目标为 Basic/KTP Basic。SimaticML 从零生成不一定兼容 Basic 设备，"
                    "建议改用 classic_template_xml 并使用同型号 Basic 面板导出的模板 XML。"
                )
            from .simaticml_generator import generate_simaticml

            cfg = self.cfg
            tia_version = cfg.get("tia_version", "V18")
            ref_xml = cfg.get("output", {}).get("reference_xml", "")
            if not ref_xml:
                ref_xml = self.output_cfg.get("reference_xml", "")

            xml = generate_simaticml(ir, tia_version, ref_xml)

            import os as _os
            base_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
            export_dir = _os.path.join(base_dir, self.output_cfg.get("export_dir", "exports"))
            _os.makedirs(export_dir, exist_ok=True)

            import datetime
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            xml_path = _os.path.join(export_dir, f"{screen_name}_{ts}.xml")
            encoding = self.output_cfg.get("encoding", "utf-8-sig")
            with open(xml_path, "w", encoding=encoding) as f:
                f.write(xml)

            details["xml_path"] = xml_path
            details["xml"] = xml

            import_result = self.import_screen(xml_path)

            # V4.1: tags 已在入口处同步
            if tag_sync_result and tag_sync_result.get("created"):
                warnings.append(
                    f"已同步 {len(tag_sync_result['created'])} 个变量到 HMI 变量表"
                )

            return {
                "ok": import_result.get("imported", False),
                "mode": "simaticml",
                "hmi_type": caps["hmi_software_type"],
                "screen_name": screen_name,
                "message": import_result.get("message", ""),
                "warnings": warnings,
                "details": details,
                "tag_sync": tag_sync_result,
            }

        # 不应到达
        return {"ok": False, "error": f"未知模式: {mode}",
                "mode": mode, "hmi_type": "Unknown",
                "screen_name": screen_name, "warnings": warnings, "details": {}}

    # ------------------------------------------------------------------
    # 统一导出封装（核心修复：不再传 str 给 Screen.Export）
    # ------------------------------------------------------------------
    def _export_screen_to_file(self, screen, xml_path: str) -> dict:
        """使用 TIA Portal Openness 导出 HMI Screen 到 XML 文件。

        策略（按顺序尝试，每步失败都会记录到 attempts）：
        1. screen.Export(FileInfo, ExportOptions.WithDefaults) — 直接调用
        2. screen.Export(FileInfo) — 单参数直接调用
        3. .NET InvokeMember — 用 Binder 绕过 pythonnet 重载解析
        4. .NET 反射 MethodInfo.Invoke — 遍历所有 Export 重载逐一尝试

        重要：pythonnet 3.x 中 Python list 不会自动转为 System.Type[]，
        因此 GetMethod(name, flags, binder, Type[], modifiers) 的 types 参数
        必须用 Array.CreateInstance 构建。
        """
        from pathlib import Path

        result: dict = {
            "ok": False,
            "xml_path": str(xml_path),
            "warnings": [],
            "attempts": [],
        }

        try:
            xml_path = str(Path(xml_path).resolve())
            Path(xml_path).parent.mkdir(parents=True, exist_ok=True)

            # TIA V16 的 ExportOptions.WithDefaults 不允许覆盖已存在的文件，
            # 必须先删除已有文件再导出。
            import os as _os
            if _os.path.exists(xml_path):
                try:
                    _os.remove(xml_path)
                except Exception as rm_err:
                    result["warnings"].append(
                        f"无法删除已有文件 {xml_path}：{rm_err}"
                    )

            from System.IO import FileInfo  # type: ignore
            file_info = FileInfo(xml_path)

            # ================================================================
            # 导入依赖（全部一次性导入，便于后续反射和 InvokeMember 使用）
            # ================================================================
            from System.Reflection import BindingFlags  # type: ignore
            from System import Array                     # type: ignore
            from System import Object as SystemObject    # type: ignore

            export_options_cls = None   # ExportOptions 类对象
            export_options_import_err = None

            try:
                from Siemens.Engineering import ExportOptions  # type: ignore
                export_options_cls = ExportOptions
            except Exception as e:
                export_options_import_err = str(e)
                result["warnings"].append(
                    "无法导入 Siemens.Engineering.ExportOptions："
                    f"{e}"
                )

            # ================================================================
            # 辅助：构建 System.Object[] 参数数组
            # ================================================================
            def _make_args(*items):
                """创建 System.Object[] 数组，传入 pythonnet .NET 对象。"""
                arr = Array.CreateInstance(SystemObject, len(items))
                for i, item in enumerate(items):
                    arr[i] = item
                return arr

            # ================================================================
            # 诊断：收集 screen 对象的类型信息（不阻塞后续导出尝试）
            # ================================================================
            screen_type = None
            all_methods = []
            export_methods = []
            screen_type_name = "Unknown"

            try:
                screen_type = screen.GetType()
                screen_type_name = str(screen_type.FullName or screen_type.Name)
                result["warnings"].append(f"Screen 对象类型：{screen_type_name}")

                all_methods = list(screen_type.GetMethods())
                export_methods = [m for m in all_methods if m.Name == "Export"]
                result["warnings"].append(
                    f"Screen 共有 {len(all_methods)} 个方法，"
                    f"其中 {len(export_methods)} 个名为 Export"
                )

                for m in export_methods:
                    params = list(m.GetParameters())
                    sig = ", ".join(
                        str(p.ParameterType.FullName or p.ParameterType.Name)
                        for p in params
                    )
                    result["attempts"].append({
                        "method": "diagnostic",
                        "detail": f"发现重载: Export({sig})",
                        "param_count": len(params),
                    })

                if not export_methods:
                    candidate_names = [
                        m.Name for m in all_methods
                        if any(kw in m.Name.lower()
                               for kw in ("export", "save", "write", "serialize"))
                    ]
                    result["warnings"].append(
                        f"未找到 Export 方法。可能相关的替代方法：{candidate_names}"
                    )
            except Exception as diag_e:
                result["warnings"].append(
                    f"无法获取 screen 类型信息（不影响后续导出尝试）：{diag_e}"
                )

            # ================================================================
            # 尝试 1: screen.Export(FileInfo, ExportOptions.WithDefaults)
            # ================================================================
            if export_options_cls is not None:
                try:
                    screen.Export(file_info, export_options_cls.WithDefaults)
                    result["ok"] = True
                    result["xml_path"] = xml_path
                    result["method"] = (
                        "screen.Export(FileInfo, ExportOptions.WithDefaults)"
                    )
                    return result
                except Exception as e:
                    result["attempts"].append({
                        "method": "1: screen.Export(FileInfo, ExportOptions.WithDefaults)",
                        "error": str(e),
                    })

            # ================================================================
            # 尝试 2: screen.Export(FileInfo) — 单参数
            # ================================================================
            try:
                screen.Export(file_info)
                result["ok"] = True
                result["xml_path"] = xml_path
                result["method"] = "screen.Export(FileInfo)"
                return result
            except Exception as e:
                result["attempts"].append({
                    "method": "2: screen.Export(FileInfo)",
                    "error": str(e),
                })

            # ================================================================
            # 尝试 3: Type.InvokeMember — .NET 原生 Binder 解析
            # InvokeMember 使用 .NET 自身的重载解析（而非 pythonnet 的），
            # 能正确处理 FileInfo/ExportOptions 类型匹配。
            # ================================================================
            invoke_flags = (
                BindingFlags.InvokeMethod
                | BindingFlags.Public
                | BindingFlags.Instance
            )

            # 3a: FileInfo + ExportOptions.WithDefaults
            if export_methods and len(export_methods) >= 1 and export_options_cls is not None:
                try:
                    args = _make_args(file_info, export_options_cls.WithDefaults)
                    screen_type.InvokeMember(
                        "Export", invoke_flags, None, screen, args
                    )
                    result["ok"] = True
                    result["xml_path"] = xml_path
                    result["method"] = (
                        "InvokeMember: Export(FileInfo, ExportOptions.WithDefaults)"
                    )
                    return result
                except Exception as e:
                    result["attempts"].append({
                        "method": "3a: InvokeMember(FileInfo, ExportOptions.WithDefaults)",
                        "error": str(e),
                    })

            # 3b: FileInfo 单参数
            if export_methods:
                try:
                    args = _make_args(file_info)
                    screen_type.InvokeMember(
                        "Export", invoke_flags, None, screen, args
                    )
                    result["ok"] = True
                    result["xml_path"] = xml_path
                    result["method"] = "InvokeMember: Export(FileInfo)"
                    return result
                except Exception as e:
                    result["attempts"].append({
                        "method": "3b: InvokeMember(FileInfo)",
                        "error": str(e),
                    })

            # 3c: string 路径
            if export_methods:
                try:
                    from System import String as SystemString  # type: ignore
                    args = _make_args(SystemString(xml_path) if callable(SystemString) else xml_path)
                    screen_type.InvokeMember(
                        "Export", invoke_flags, None, screen, args
                    )
                    result["ok"] = True
                    result["xml_path"] = xml_path
                    result["method"] = "InvokeMember: Export(string)"
                    return result
                except Exception as e:
                    result["attempts"].append({
                        "method": "3c: InvokeMember(string)",
                        "error": str(e),
                    })

            # ================================================================
            # 尝试 4: 遍历所有 Export MethodInfo，逐个用 MethodInfo.Invoke 调用
            # 构建正确的 System.Object[] 参数数组，完全绕过 pythonnet 解析
            # ================================================================
            for m in export_methods:
                params = list(m.GetParameters())
                param_count = len(params)
                param_names = [
                    str(p.ParameterType.FullName or p.ParameterType.Name)
                    for p in params
                ]
                sig_label = f"Export({', '.join(param_names)})"

                # 根据参数名/类型智能构建参数
                invoke_args = []
                skipped = False
                for p in params:
                    ptn = str(p.ParameterType.FullName or p.ParameterType.Name)
                    if "FileInfo" in ptn:
                        invoke_args.append(file_info)
                    elif "ExportOptions" in ptn:
                        if export_options_cls is not None:
                            invoke_args.append(export_options_cls.WithDefaults)
                        else:
                            skipped = True
                            break
                    elif "String" in ptn:
                        invoke_args.append(xml_path)
                    elif "Stream" in ptn:
                        # Stream 类型：无法从这里构造，跳过
                        skipped = True
                        break
                    else:
                        # 未知类型，传 None 碰运气
                        invoke_args.append(None)

                if skipped:
                    result["attempts"].append({
                        "method": f"4: MethodInfo.Invoke → {sig_label}",
                        "error": f"跳过（无法构造参数类型：{param_names}）",
                    })
                    continue

                try:
                    args_array = _make_args(*invoke_args)
                    m.Invoke(screen, args_array)
                    result["ok"] = True
                    result["xml_path"] = xml_path
                    result["method"] = f"MethodInfo.Invoke: {sig_label}"
                    return result
                except Exception as e:
                    result["attempts"].append({
                        "method": f"4: MethodInfo.Invoke → {sig_label}",
                        "error": str(e),
                    })

            # ================================================================
            # 尝试 5: 搜索非 "Export" 名的导出方法（SaveAs, ExportToFile 等）
            # ================================================================
            alt_patterns = ["ExportToFile", "SaveAs", "Save", "WriteTo", "Serialize"]
            for m in all_methods:
                mname = m.Name
                if mname == "Export" or not any(
                    kw.lower() in mname.lower() for kw in alt_patterns
                ):
                    continue
                params = list(m.GetParameters())
                param_names = [
                    str(p.ParameterType.FullName or p.ParameterType.Name)
                    for p in params
                ]
                sig_label = f"{mname}({', '.join(param_names)})"

                invoke_args = []
                skipped = False
                for p in params:
                    ptn = str(p.ParameterType.FullName or p.ParameterType.Name)
                    if "FileInfo" in ptn:
                        invoke_args.append(file_info)
                    elif "String" in ptn:
                        invoke_args.append(xml_path)
                    elif "ExportOptions" in ptn and export_options_cls:
                        invoke_args.append(export_options_cls.WithDefaults)
                    else:
                        skipped = True
                        break

                if skipped:
                    continue

                try:
                    args_array = _make_args(*invoke_args)
                    m.Invoke(screen, args_array)
                    result["ok"] = True
                    result["xml_path"] = xml_path
                    result["method"] = f"MethodInfo.Invoke (alternative): {sig_label}"
                    return result
                except Exception as e:
                    result["attempts"].append({
                        "method": f"5: 替代方法 MethodInfo.Invoke → {sig_label}",
                        "error": str(e),
                    })

            # ================================================================
            # 全部失败 — 汇总错误信息
            # ================================================================
            result["message"] = (
                f"导出画面失败：{screen_type_name} 上的 Export() "
                "所有调用方式均失败。"
                "已尝试：直接调用、InvokeMember、MethodInfo.Invoke。"
                f"共发现 {len(export_methods)} 个 Export 重载。"
            )
            if export_options_import_err:
                result["message"] += (
                    f" 注意：ExportOptions 导入也失败：{export_options_import_err}"
                )
            return result

        except Exception as e:
            result["ok"] = False
            result["message"] = f"导出画面异常：{e}"
            return result

    # ------------------------------------------------------------------
    # 画面查找辅助方法
    # ------------------------------------------------------------------
    def _find_screen_by_name(self, hmi_software, screen_name: str = "") -> tuple:
        """根据名称查找 HMI 画面。

        参数:
            hmi_software: HMI 软件对象。
            screen_name: 画面名称。为空则返回第一个可用画面。

        返回:
            (screen_object_or_None, warnings_list)
        """
        warnings: list = []

        try:
            screen_folder = hmi_software.ScreenFolder
        except Exception as e:
            return None, [f"无法访问 ScreenFolder：{e}"]

        all_screens = self._collect_screens(screen_folder)

        if not all_screens:
            return None, warnings

        if not screen_name:
            first = all_screens[0]
            w = f"未指定画面名称，已自动选择第一个画面 '{str(first.Name)}'。"
            warnings.append(w)
            return first, warnings

        for s in all_screens:
            try:
                if str(s.Name) == screen_name:
                    return s, warnings
            except Exception:
                continue

        # 找不到指定画面
        available = []
        for s in all_screens:
            try:
                available.append(str(s.Name))
            except Exception:
                pass
        warnings.append(f"未找到画面 '{screen_name}'。可用画面: {available}")
        return None, warnings

    def _collect_screens(self, folder) -> list:
        """递归收集 ScreenFolder 中所有画面（含子文件夹）。

        pythonnet 下 .NET collection 的遍历可能和 Python list 不同，
        需要用 try/except 包裹每个操作。
        """
        screens: list = []
        try:
            for s in folder.Screens:
                screens.append(s)
        except Exception:
            pass

        # 递归子文件夹
        try:
            for sub_folder in folder.Folders:
                try:
                    screens.extend(self._collect_screens(sub_folder))
                except Exception:
                    pass
        except Exception:
            pass

        return screens

    def _list_available_screens(self, hmi_software) -> list:
        """列出所有可用画面名称（调试/错误信息用）。"""
        try:
            screen_folder = hmi_software.ScreenFolder
        except Exception:
            return []
        all_screens = self._collect_screens(screen_folder)
        names = []
        for s in all_screens:
            try:
                names.append(str(s.Name))
            except Exception:
                pass
        return names

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


# ========================================================================
# V4.2: HMI 变量容器解析 — 反射探测 + 家族感知路由
# ========================================================================

def _resolve_hmi_tag_container(sw, hmi_family: str) -> dict:
    """解析 HMI 变量容器，根据 HMI 家族返回正确的 Tag API 路径。

    不再硬编码 sw.TagTables。改为通过 _try_get_attr 反射探测可用属性，
    并根据 HMI 家族 (Basic/Comfort/Classic/Unified) 选择正确的变量集合。

    参数:
        sw: TIA HMI software 对象（真实 .NET 对象，来自 _find_hmi_software()）。
        hmi_family: HMI 家族字符串 ("Basic", "Comfort", "Classic", "Unified", "Unknown")。

    返回:
        {
            "ok": bool,
            "family": str,
            "access_path": str,          # 实际使用的 API 路径（用于诊断）
            "existing_names": set[str],  # 已存在的变量名集合
            "diagnostics": [str],        # 诊断消息列表
        }
    """
    from backend.openness.diagnostics_utils import enumerate_tag_names

    result: dict = {
        "ok": False,
        "family": hmi_family,
        "access_path": "",
        "existing_names": set(),
        "diagnostics": [],
    }

    if hmi_family in ("Basic", "Comfort", "Classic"):
        # --- Classic 路径 ---
        # 优先: TagFolder.DefaultTagTable.Tags
        tag_folder = _try_get_attr(sw, "TagFolder")
        if tag_folder is not None:
            default_table = _try_get_attr(tag_folder, "DefaultTagTable")
            if default_table is not None:
                tags_coll = _try_get_attr(default_table, "Tags")
                if tags_coll is not None:
                    result["existing_names"] = set(enumerate_tag_names(tags_coll))
                    result["access_path"] = "TagFolder.DefaultTagTable.Tags"
                    result["ok"] = True
                    return result

            # Fallback: TagFolder.TagTables[0]
            tag_tables = _try_get_attr(tag_folder, "TagTables")
            if tag_tables is not None:
                try:
                    table_list = list(tag_tables)
                    if table_list:
                        tags_coll = _try_get_attr(table_list[0], "Tags")
                        if tags_coll is not None:
                            result["existing_names"] = set(
                                enumerate_tag_names(tags_coll)
                            )
                            result["access_path"] = "TagFolder.TagTables[0].Tags"
                            result["ok"] = True
                            return result
                except Exception:
                    pass

        # Fallback: sw.TagTables 直接访问（某些 TIA 版本）
        direct_tables = _try_get_attr(sw, "TagTables")
        if direct_tables is not None:
            try:
                table_list = list(direct_tables)
                if table_list:
                    tags_coll = _try_get_attr(table_list[0], "Tags")
                    if tags_coll is not None:
                        result["existing_names"] = set(
                            enumerate_tag_names(tags_coll)
                        )
                        result["access_path"] = "sw.TagTables[0].Tags (direct)"
                        result["ok"] = True
                        return result
            except Exception:
                pass

        # 全部失败 — 返回结构化诊断
        result["diagnostics"].append(
            f"无法解析 Classic HMI 变量容器。"
            f"对象类型: {_net_type_name(sw)}，"
            f"HMI family: {hmi_family}，"
            f"已尝试路径: TagFolder.DefaultTagTable.Tags, "
            f"TagFolder.TagTables[0].Tags, sw.TagTables[0]"
        )
        return result

    elif hmi_family == "Unified":
        # --- Unified 路径：hmiSoftware.Tags 直接集合 ---
        tags_coll = _try_get_attr(sw, "Tags")
        if tags_coll is not None:
            result["existing_names"] = set(enumerate_tag_names(tags_coll))
            result["access_path"] = "hmiSoftware.Tags (Unified direct)"
            result["ok"] = True
        else:
            result["diagnostics"].append(
                f"无法解析 Unified HMI 变量容器。"
                f"对象类型: {_net_type_name(sw)}，"
                f"HMI family: {hmi_family}，"
                f"已尝试路径: hmiSoftware.Tags"
            )
        return result

    else:
        # --- 未知家族：反射探测所有已知路径 ---
        probed: dict[str, bool] = {}
        for attr in ("TagFolder", "TagTables", "Tags"):
            probed[attr] = _try_get_attr(sw, attr) is not None
        result["diagnostics"].append(
            f"无法解析 HMI 变量容器：未知的 HMI 家族 '{hmi_family}'。"
            f"当前对象类型为 {_net_type_name(sw)}，"
            f"已尝试路径: {[attr for attr, ok in probed.items()]}，"
            f"可用属性探测结果: {probed}。"
            f"请确认当前传入的是 hmi_software 对象，"
            f"而不是 target/capability wrapper。"
        )
        return result


# ========================================================================
# 模块级辅助函数：Unified 对象反射操作
# ========================================================================

def _net_type_name(obj) -> str:
    """获取 .NET 对象的完整类型名（容错）。"""
    try:
        return type(obj).FullName or type(obj).__name__
    except Exception:
        return type(obj).__name__


def _describe_dotnet_object_safe(obj) -> dict:
    """安全描述 .NET 对象以生成诊断信息。绝不抛出。"""
    if obj is None:
        return {"dotnet_full_name": "None", "properties": {}}
    info: dict = {}
    try:
        info["dotnet_full_name"] = str(obj.GetType().FullName)
    except Exception:
        info["dotnet_full_name"] = type(obj).__name__
    info["properties"] = {}
    for attr in ("TagFolder", "TagTables", "Tags", "ScreenFolder", "Name"):
        try:
            v = getattr(obj, attr, None)
            if v is not None:
                info["properties"][attr] = str(type(v).__name__)
        except Exception:
            info["properties"][attr] = "<error reading>"
    return info


def _try_get_attr(obj, name: str):
    """安全获取 .NET 对象属性，不存在时返回 None（不抛异常）。"""
    try:
        return getattr(obj, name)
    except Exception:
        return None


def _try_set_attr(obj, name: str, value) -> bool:
    """安全设置 .NET 对象属性，失败时返回 False。"""
    try:
        setattr(obj, name, value)
        return True
    except Exception:
        return False


def _try_call(obj, method_name: str, *args):
    """安全调用 .NET 对象方法，失败时返回 None。"""
    try:
        method = getattr(obj, method_name)
        return method(*args)
    except Exception:
        return None


def _create_screen_item(screen, candidate_type_names: list, name: str):
    """尝试使用候选类型名创建 ScreenItem。

    返回创建的 ScreenItem 对象，或 None（全部失败时）。
    """
    for type_name in candidate_type_names:
        try:
            # 通用模式：Screen.ScreenItems.Create(type_name, name)
            items = screen.ScreenItems
            return items.Create(type_name, name)
        except Exception:
            pass

    # 备选：直接通过类型对象创建
    for type_name in candidate_type_names:
        try:
            item = _try_call(screen.ScreenItems, "Create" + type_name, name)
            if item is not None:
                return item
        except Exception:
            pass

    return None


def _hex_to_argb_int(hex_color: str) -> int:
    """#RRGGBB → ARGB 整数（WinCC Unified 常用）。"""
    c = (hex_color or "#000000").lstrip("#")
    if len(c) == 6:
        r, g, b = int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
        return (255 << 24) | (r << 16) | (g << 8) | b
    return 0xFF000000
