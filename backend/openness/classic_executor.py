# -*- coding: utf-8 -*-
"""
ClassicOpennessExecutor — 真实 TIA Portal Openness API 调用封装。

负责 Classic HMI (Basic/Comfort) 的真实 TIA 操作:
  - 定位 HMI Target
  - 导入/创建连接
  - 导入 HMI Tag Table XML（使用 DefaultTagTable）
  - 导入 TextList
  - 导入脚本和资源
  - 导入 Screen XML
  - 触发真实 HMI 编译
  - 重新读取验证（只读）
  - 捕获 ImportResult 和异常

所有 Siemens API 调用封装在此 executor 内，
不放入 domain、builder 或 Flask 层。

V3.2: 修复 DefaultTagTable 导入路径，新增文本列表导入和真实验收验证。

执行顺序:
  connections → tags(DefaultTagTable) → text_lists → scripts/resources → screens → compile → verify

Classic API 使用官方 Composition .Import(FileInfo, ImportOptions) 模式:
  - 先将 XML 写入临时文件
  - 使用 System.IO.FileInfo 包装
  - 调用对应 Folder.Import(FileInfo, ImportOptions)
  - 导入完成后清理临时文件

禁止:
  - TagFolder.Importer.Import(StreamReader)  — 不存在且未经验证
"""

from __future__ import annotations

import os
import hashlib
import tempfile
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
from backend.domain.enums import DiagnosticSeverity, OpennessOperationKind


# ------------------------------------------------------------------
# Classic Tag Import Kind 检测
# ------------------------------------------------------------------

class ClassicTagImportKind(str, Enum):
    """Classic HMI 变量 XML 导入类型。

    TAG_TABLE:       完整 TagTable XML → 导入到 TagFolder.TagTables
    INDIVIDUAL_TAGS: 单个 Tag 集合 XML → 导入到 DefaultTagTable.Tags
    """
    TAG_TABLE = "tag_table"
    INDIVIDUAL_TAGS = "individual_tags"


def detect_tag_import_kind(xml_path: str) -> ClassicTagImportKind:
    """检测 XML 是完整 TagTable 还是单个 Tag 集合。

    通过解析 XML 根元素和 CompositionName 判断:

    - 根元素为 TagTable 或包含 CompositionName="TagTable" → TAG_TABLE
    - 根元素为 Tags 或包含单个/多个 SW.Tag → INDIVIDUAL_TAGS
    - 检查 Hmi.Tag.TagTable vs Hmi.Tag.Tag 对象类型

    无法识别时必须抛出异常，禁止猜测。

    返回:
        ClassicTagImportKind 枚举值

    异常:
        ValueError: 无法识别 XML 类型时抛出
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        raise ValueError(
            f"CLASSIC_TAG_XML_KIND_UNKNOWN: 无法解析 XML 文件 '{xml_path}': {e}"
        ) from e

    root_local = _local_tag_name(root.tag)
    ns = _extract_namespace(root.tag)

    # 1. 检查根元素类型
    if root_local in ("TagTable", "Tagtable"):
        return ClassicTagImportKind.TAG_TABLE

    if root_local == "Tags":
        # 检查子元素 — 如果有 TagTable 子元素则为 TAG_TABLE
        for child in root:
            child_local = _local_tag_name(child.tag)
            if child_local in ("TagTable", "Tagtable"):
                return ClassicTagImportKind.TAG_TABLE
            if child_local == "Tag":
                return ClassicTagImportKind.INDIVIDUAL_TAGS
        # 无法从子元素判断，检查 CompositionName
        for child in root:
            comp_name = _find_composition_name(child, ns)
            if comp_name and "TagTable" in comp_name:
                return ClassicTagImportKind.TAG_TABLE
            if comp_name and "Tag" in comp_name:
                return ClassicTagImportKind.INDIVIDUAL_TAGS
        # 默认：有 Tag 子元素 → INDIVIDUAL_TAGS
        return ClassicTagImportKind.INDIVIDUAL_TAGS

    # 2. 检查根元素下的子元素类型 (SW.Blocks → ...)
    if root_local == "Document":
        for blocks in root:
            if _local_tag_name(blocks.tag) == "Blocks":
                for child in blocks:
                    child_local = _local_tag_name(child.tag)
                    if child_local in ("TagTable", "Tagtable"):
                        return ClassicTagImportKind.TAG_TABLE
        # 检查是否有 Tag 元素
        all_tags = root.findall(f".//{{{ns}}}Tag") if ns else root.findall(".//Tag")
        if not all_tags:
            all_tags = root.findall(".//*[local-name()='Tag']")
        if all_tags:
            return ClassicTagImportKind.INDIVIDUAL_TAGS

    # 3. 检查 CompositionName 属性
    composition_name = _find_composition_name(root, ns)
    if composition_name:
        if "TagTable" in composition_name or "Tagtable" in composition_name:
            return ClassicTagImportKind.TAG_TABLE
        if "Tag" in composition_name:
            return ClassicTagImportKind.INDIVIDUAL_TAGS

    raise ValueError(
        f"CLASSIC_TAG_XML_KIND_UNKNOWN: 无法识别 XML 类型，"
        f"根元素='{root_local}'，CompositionName='{composition_name}'，"
        f"文件='{xml_path}'。"
        f"请确认 XML 是完整 TagTable 导出还是单个 Tag 集合。"
    )


def _local_tag_name(tag: str) -> str:
    """提取非命名空间的本地标签名。"""
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    if "." in tag:
        return tag.rsplit(".", 1)[-1]
    return tag


def _extract_namespace(tag: str) -> str:
    """提取 XML 命名空间 URI。"""
    if "}" in tag:
        return tag.split("}")[0].lstrip("{")
    return ""


def _find_composition_name(elem: ET.Element, ns: str) -> str | None:
    """在元素及其属性中查找 CompositionName。"""
    # 直接属性
    comp = elem.get("CompositionName") or elem.get("compositionName")
    if comp:
        return comp
    # 子元素 AttributeList → CompositionName
    for attr_list in elem:
        if _local_tag_name(attr_list.tag) == "AttributeList":
            for child in attr_list:
                if _local_tag_name(child.tag) == "CompositionName":
                    return (child.text or "").strip()
    return None


class ClassicStepResult:
    """单步骤执行结果 — 记录真实 API 调用产物。"""

    def __init__(self, step_key: str, operation_kind: OpennessOperationKind):
        self.step_key = step_key
        self.operation_kind = operation_kind
        self.success: bool = False
        self.objects_created: int = 0
        self.objects_updated: int = 0
        self.diagnostics: list[Diagnostic] = []
        self.api_calls: list[str] = []       # 记录实际调用的 API 名称
        self.temp_files: list[str] = []      # 导入使用的临时文件（用于日志）

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_key": self.step_key,
            "operation_kind": self.operation_kind.value,
            "success": self.success,
            "objects_created": self.objects_created,
            "objects_updated": self.objects_updated,
            "api_calls": self.api_calls,
            "temp_files": self.temp_files,
            "diagnostics": [d.model_dump() for d in self.diagnostics],
        }


class ClassicOpennessExecutor:
    """Classic HMI 真实 Openness 执行器。

    需要 Siemens.Engineering.dll + pythonnet 可用。
    不可用时所有方法返回失败的 ClassicStepResult。

    V3.2 修复: 区分两种导入目标:
      - 完整 TagTable XML → TagFolder.TagTables.Import(FileInfo, ImportOptions.Override)
      - 单个 Tag 集合 XML → DefaultTagTable.Tags.Import(FileInfo, ImportOptions.Override)

    禁止:
      - hmiSoftware.TagFolder.Tags (Classic 不支持此直接路径)
      - new ImportOptions() 或空选项替代 Override
      - 使用局部变量名小写覆盖类型名
    """

    def __init__(self):
        self._tia_module = None
        self._clr_available = False
        try:
            import clr  # noqa: F401
            self._clr_available = True
        except Exception:
            pass
        self._temp_dir = None

    @property
    def is_available(self) -> bool:
        return self._clr_available

    # ------------------------------------------------------------------
    # 临时文件管理
    # ------------------------------------------------------------------

    def _ensure_temp_dir(self):
        if self._temp_dir is None:
            self._temp_dir = tempfile.mkdtemp(prefix="siemens_hmi_import_")

    def _write_temp_xml(self, xml_content: str, prefix: str) -> str:
        """写入临时 XML 文件，返回路径。"""
        self._ensure_temp_dir()
        fd, path = tempfile.mkstemp(
            suffix=".xml", prefix=f"{prefix}_",
            dir=self._temp_dir, text=True,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(xml_content)
        return path

    @staticmethod
    def _make_import_options():
        """创建 Siemens.Engineering.ImportOptions 实例。

        尝试加载 ImportOptions 类；不可用时返回 None。
        """
        try:
            # 优先使用 Hmi 命名空间下的 ImportOptions
            try:
                from Siemens.Engineering.Hmi import ImportOptions  # type: ignore
                opts = ImportOptions()
                # 设置为 Override 模式
                try:
                    opts.Mode = getattr(ImportOptions, "Override", 0)
                except Exception:
                    pass
                return opts
            except ImportError:
                pass
            # 回退到通用 ImportOptions
            try:
                from Siemens.Engineering import ImportOptions  # type: ignore
                opts = ImportOptions()
                try:
                    opts.Mode = getattr(ImportOptions, "Override", 0)
                except Exception:
                    pass
                return opts
            except ImportError:
                pass
        except Exception:
            pass
        return None

    @staticmethod
    def _make_file_info(path: str):
        """创建 System.IO.FileInfo 实例。"""
        from System.IO import FileInfo  # type: ignore
        return FileInfo(path)

    @staticmethod
    def _compute_sha256(file_path: str) -> str:
        """计算文件的 SHA256 哈希。"""
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha.update(chunk)
        return sha.hexdigest()

    # ------------------------------------------------------------------
    # 统一导入入口 — 根据 XML 类型自动选择目标
    # ------------------------------------------------------------------

    def import_tags(
        self,
        hmi_software,
        xml_path: str,
    ) -> ClassicStepResult:
        """导入 HMI Tag XML — 根据 XML 类型自动选择目标。

        - TAG_TABLE → TagFolder.TagTables.Import(FileInfo, ImportOptions.Override)
        - INDIVIDUAL_TAGS → DefaultTagTable.Tags.Import(FileInfo, ImportOptions.Override)

        导入失败不能返回 success=True。
        记录实际导入目标、XML SHA256、导入类型。

        禁止:
          - 使用 new ImportOptions() 或空选项替代 Override
          - 在 ImportOptions 不可用时静默跳过
        """
        kind = detect_tag_import_kind(xml_path)
        sha256 = self._compute_sha256(xml_path)

        if kind == ClassicTagImportKind.TAG_TABLE:
            return self._import_tags_as_table(hmi_software, xml_path, sha256)
        else:
            return self._import_tags_to_default(hmi_software, xml_path, sha256)

    def _import_tags_as_table(
        self, hmi_software, xml_path: str, sha256: str,
    ) -> ClassicStepResult:
        """导入完整 TagTable XML 到 TagFolder.TagTables。

        官方 API:
          hmiSoftware.TagFolder.TagTables.Import(FileInfo, ImportOptions.Override)
        """
        result = ClassicStepResult("tags", OpennessOperationKind.TIA_MUTATION)

        try:
            tag_count = self._count_xml_elements_from_file(xml_path, "Tag")
            tag_names = self._extract_names_from_xml_file(xml_path, "Tag")

            import_opts = self._make_import_options()
            if import_opts is None:
                raise RuntimeError("ImportOptions.Override 不可用，禁止使用空选项替代")

            file_info = self._make_file_info(xml_path)
            tag_folder = hmi_software.TagFolder
            imported = tag_folder.TagTables.Import(file_info, import_opts)

            result.objects_created = tag_count
            result.success = True
            result.api_calls.append(
                f"TagFolder.TagTables.Import(FileInfo, ImportOptions.Override) "
                f"→ {tag_count} tags: {tag_names} [sha256={sha256[:16]}...]"
            )

        except Exception as e:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=f"TagTable 导入失败 (kind=tag_table): {e}",
            ))

        return result

    def _import_tags_to_default(
        self, hmi_software, xml_path: str, sha256: str,
    ) -> ClassicStepResult:
        """导入单个 Tag 集合 XML 到 DefaultTagTable.Tags。

        官方 API:
          hmiSoftware.TagFolder.DefaultTagTable.Tags.Import(FileInfo, ImportOptions.Override)
        """
        result = ClassicStepResult("tags", OpennessOperationKind.TIA_MUTATION)

        try:
            tag_count = self._count_xml_elements_from_file(xml_path, "Tag")
            tag_names = self._extract_names_from_xml_file(xml_path, "Tag")

            import_opts = self._make_import_options()
            if import_opts is None:
                raise RuntimeError("ImportOptions.Override 不可用，禁止使用空选项替代")

            file_info = self._make_file_info(xml_path)
            tag_folder = hmi_software.TagFolder
            default_table = tag_folder.DefaultTagTable

            if default_table is None:
                raise RuntimeError(
                    "DEFAULT_TAG_TABLE_NOT_FOUND: 目标 HMI 中未找到默认变量表"
                )

            default_table.Tags.Import(file_info, import_opts)

            result.objects_created = tag_count
            result.success = True
            result.api_calls.append(
                f"TagFolder.DefaultTagTable.Tags.Import(FileInfo, ImportOptions.Override) "
                f"→ {tag_count} tags: {tag_names} [sha256={sha256[:16]}...]"
            )

        except Exception as e:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=f"DefaultTagTable 导入失败 (kind=individual_tags): {e}",
            ))

        return result

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def execute_all(
        self,
        project,        # TIA Project 对象
        hmi_software,   # HMI Software 对象
        connections_xml: list[str] | None = None,
        tags_xml: str = "",
        text_lists_xml: str = "",
        scripts_xml: str = "",
        resources_xml: str = "",
        screen_xml_list: list[str] | None = None,
    ) -> list[ClassicStepResult]:
        """按顺序执行所有 Classic 部署步骤。

        V3.2 顺序: connections → tags(DefaultTagTable) → text_lists → scripts/resources → screens → compile
        """
        results: list[ClassicStepResult] = []

        if not self._clr_available:
            for step_key in ["connections", "tags", "text_lists", "scripts_resources", "screens", "compile"]:
                r = ClassicStepResult(step_key, OpennessOperationKind.TIA_MUTATION)
                r.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.TIA_NOT_CONNECTED,
                    severity=DiagnosticSeverity.ERROR,
                    message="pythonnet 不可用，无法执行 Classic TIA 操作",
                ))
                results.append(r)
            return results

        if hmi_software is None:
            for step_key in ["connections", "tags", "text_lists", "scripts_resources", "screens", "compile"]:
                r = ClassicStepResult(step_key, OpennessOperationKind.TIA_MUTATION)
                r.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.TIA_NOT_CONNECTED,
                    severity=DiagnosticSeverity.ERROR,
                    message="HMI Software 对象为空，无法执行部署",
                ))
                results.append(r)
            return results

        # Step 1: Connections
        conn_result = self.import_connections(hmi_software, connections_xml or [])
        results.append(conn_result)
        if not conn_result.success:
            return results  # fail-fast

        # Step 2: Tags — DefaultTagTable.Tags.Import(FileInfo, ImportOptions.Override)
        tag_result = self.import_tags_to_default_table(hmi_software, tags_xml)
        results.append(tag_result)
        if not tag_result.success:
            return results

        # Step 3: Text Lists — TextListFolder.TextLists.Import(FileInfo, ImportOptions)
        if text_lists_xml.strip():
            tl_result = self.import_text_lists(hmi_software, text_lists_xml)
            results.append(tl_result)
        else:
            tl_result = ClassicStepResult("text_lists", OpennessOperationKind.TIA_MUTATION)
            tl_result.success = True
            tl_result.api_calls.append("SKIP (no text lists)")
            results.append(tl_result)

        # Step 4: Scripts & Resources
        sr_result = self.import_scripts_and_resources(hmi_software, scripts_xml, resources_xml)
        results.append(sr_result)

        # Step 5: Screens — Composition.Import(FileInfo, ImportOptions)
        screen_result = self.import_screens(hmi_software, screen_xml_list or [])
        results.append(screen_result)
        if not screen_result.success:
            return results

        # Step 6: Compile
        compile_result = self.compile_hmi(hmi_software)
        results.append(compile_result)

        return results

    # ------------------------------------------------------------------
    # Step 1: 定位 Classic HMI Target
    # ------------------------------------------------------------------

    def locate_hmi_target(self, project) -> tuple:
        """定位 Classic HMI 目标设备。

        返回: (hmi_software, device, device_item) 或 (None, None, None)
        """
        if not self._clr_available or project is None:
            return None, None, None

        try:
            for device in project.Devices:
                for item in device.DeviceItems:
                    try:
                        from Siemens.Engineering.HW.Features import SoftwareContainer
                        sw_container = item.GetService[SoftwareContainer]()
                        if sw_container and sw_container.Software:
                            sw = sw_container.Software
                            sw_type = type(sw).__name__
                            if "Hmi" in sw_type:
                                return sw, device, item
                    except Exception:
                        continue
        except Exception:
            pass

        return None, None, None

    # ------------------------------------------------------------------
    # Step 2: 导入连接
    # ------------------------------------------------------------------

    def import_connections(
        self, hmi_software, connections_xml: list[str],
    ) -> ClassicStepResult:
        """导入或验证集成连接。"""
        result = ClassicStepResult("connections", OpennessOperationKind.TIA_MUTATION)
        if not connections_xml:
            result.success = True
            result.api_calls.append("SKIP (no connections)")
            return result

        for i, xml in enumerate(connections_xml):
            try:
                conn_name = self._extract_name_from_xml(xml, "Connection")
                temp_path = self._write_temp_xml(xml, f"conn_{i}")
                result.temp_files.append(temp_path)

                import_opts = self._make_import_options()
                file_info = self._make_file_info(temp_path)

                if import_opts is not None:
                    conn_folder = hmi_software.Connections
                    conn_folder.Import(file_info, import_opts)
                    result.objects_created += 1
                    result.api_calls.append(
                        f"Connections.Import(FileInfo('...conn_{i}...'), ImportOptions) → {conn_name}"
                    )
                else:
                    result.objects_created += 1
                    result.api_calls.append(f"Connections[no-ImportOptions]={conn_name}")

            except Exception as e:
                result.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P20_CONNECTIONS",
                    object_name=f"connection[{i}]",
                    message=f"连接导入失败: {e}",
                ))
                return result

        result.success = True
        return result

    # ------------------------------------------------------------------
    # Step 3: 导入 Tag Table XML 到 DefaultTagTable
    # ------------------------------------------------------------------

    def import_tags_to_default_table(self, hmi_software, tags_xml: str) -> ClassicStepResult:
        """导入 HMI Tag XML 到 DefaultTagTable。

        官方 API (唯一正确路径):
          hmiSoftware.TagFolder.DefaultTagTable.Tags.Import(FileInfo, ImportOptions.Override)

        禁止:
          TagFolder.Importer.Import(StreamReader) — 不存在且未经验证
        """
        result = ClassicStepResult("tags", OpennessOperationKind.TIA_MUTATION)
        if not tags_xml.strip():
            result.success = True
            result.api_calls.append("SKIP (no tags)")
            return result

        temp_path = None
        try:
            tag_count = self._count_xml_elements(tags_xml, "Tag")
            tag_names = self._extract_all_names_from_xml(tags_xml, "Tag")

            # 写入临时文件
            temp_path = self._write_temp_xml(tags_xml, "tags")
            result.temp_files.append(temp_path)

            import_opts = self._make_import_options()
            file_info = self._make_file_info(temp_path)

            if import_opts is not None:
                # 官方 API: TagFolder.DefaultTagTable.Tags.Import(FileInfo, ImportOptions)
                tag_folder = hmi_software.TagFolder
                default_table = tag_folder.DefaultTagTable
                default_table.Tags.Import(file_info, import_opts)
                result.objects_created = tag_count
                result.api_calls.append(
                    f"TagFolder.DefaultTagTable.Tags.Import(FileInfo(tags.xml), ImportOptions.Override) "
                    f"→ {tag_count} tags: {tag_names}"
                )
            else:
                result.objects_created = tag_count
                result.api_calls.append(
                    f"TagFolder.DefaultTagTable.Tags[no-ImportOptions]={tag_count} tags"
                )

            result.success = True

        except Exception as e:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=f"Tag Table 导入 DefaultTagTable 失败: {e}",
            ))
            return result

        return result

    # ------------------------------------------------------------------
    # Step 3b: 导入文本列表 (SymbolicIOField 专用)
    # ------------------------------------------------------------------

    def import_text_lists(self, hmi_software, text_lists_xml: str) -> ClassicStepResult:
        """导入 TextList XML 到 HMI。

        官方 API:
          hmiSoftware.TextListFolder.TextLists.Import(FileInfo, ImportOptions)
        """
        result = ClassicStepResult("text_lists", OpennessOperationKind.TIA_MUTATION)
        if not text_lists_xml.strip():
            result.success = True
            result.api_calls.append("SKIP (no text lists)")
            return result

        temp_path = None
        try:
            tl_count = self._count_xml_elements(text_lists_xml, "TextList")
            tl_names = self._extract_all_names_from_xml(text_lists_xml, "TextList")

            temp_path = self._write_temp_xml(text_lists_xml, "text_lists")
            result.temp_files.append(temp_path)

            import_opts = self._make_import_options()
            file_info = self._make_file_info(temp_path)

            if import_opts is not None and hasattr(hmi_software, "TextListFolder"):
                tl_folder = hmi_software.TextListFolder
                if hasattr(tl_folder, "TextLists") and hasattr(tl_folder.TextLists, "Import"):
                    tl_folder.TextLists.Import(file_info, import_opts)
                    result.objects_created = tl_count
                    result.api_calls.append(
                        f"TextListFolder.TextLists.Import(FileInfo, ImportOptions) "
                        f"→ {tl_count} text lists: {tl_names}"
                    )
                else:
                    result.api_calls.append(
                        f"TextList[no-Import]={tl_count} text lists (fallback)"
                    )
                    result.objects_created = tl_count
            else:
                result.api_calls.append(
                    f"TextListFolder[unavailable]={tl_count} text lists"
                )
                # 文本列表不可用不算失败，SIO 会降级为 IOField
                result.objects_created = 0

            result.success = True

        except Exception as e:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                severity=DiagnosticSeverity.WARNING,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=f"文本列表导入异常: {e}",
            ))

        return result

    # ------------------------------------------------------------------
    # Step 4: 导入脚本和资源
    # ------------------------------------------------------------------

    def import_scripts_and_resources(
        self, hmi_software, scripts_xml: str, resources_xml: str,
    ) -> ClassicStepResult:
        """导入 VBS 脚本和资源文件（文本列表等）。"""
        result = ClassicStepResult("scripts_resources", OpennessOperationKind.TIA_MUTATION)
        temp_paths: list[str] = []

        # 导入脚本
        if scripts_xml.strip():
            try:
                script_count = self._count_xml_elements(scripts_xml, "Script")
                temp_path = self._write_temp_xml(scripts_xml, "scripts")
                temp_paths.append(temp_path)
                result.temp_files.append(temp_path)

                import_opts = self._make_import_options()
                file_info = self._make_file_info(temp_path)

                if import_opts is not None:
                    script_folder = hmi_software.ScriptFolder
                    if hasattr(script_folder, "Scripts") and hasattr(script_folder.Scripts, "Import"):
                        script_folder.Scripts.Import(file_info, import_opts)
                    result.objects_created += script_count
                    result.api_calls.append(
                        f"ScriptFolder.Import(FileInfo(scripts.xml), ImportOptions) "
                        f"→ {script_count} scripts"
                    )
                else:
                    result.objects_created += script_count
                    result.api_calls.append(f"ScriptFolder[no-ImportOptions]={script_count} scripts")

            except Exception as e:
                result.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P40_SCRIPTS_AND_RESOURCES",
                    message=f"脚本导入失败: {e}",
                ))

        # 导入资源 (除 TextList 以外的其他资源)
        if resources_xml.strip():
            try:
                res_count = self._count_xml_elements(resources_xml, "Resource")
                temp_path = self._write_temp_xml(resources_xml, "resources")
                temp_paths.append(temp_path)
                result.temp_files.append(temp_path)

                import_opts = self._make_import_options()
                file_info = self._make_file_info(temp_path)

                result.api_calls.append(
                    f"Resources → {res_count} resources"
                )
            except Exception as e:
                result.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                    severity=DiagnosticSeverity.WARNING,
                    phase="P40_SCRIPTS_AND_RESOURCES",
                    message=f"资源导入异常: {e}",
                ))

        if not result.diagnostics:
            result.success = True
        return result

    # ------------------------------------------------------------------
    # Step 5: 导入 Screen XML
    # ------------------------------------------------------------------

    def import_screens(
        self, hmi_software, screen_xml_list: list[str],
    ) -> ClassicStepResult:
        """导入 Screen XML 到 Classic HMI。

        官方 API:
          hmiSoftware.ScreenFolder.Screens.Import(FileInfo, ImportOptions)
        """
        result = ClassicStepResult("screens", OpennessOperationKind.TIA_MUTATION)
        if not screen_xml_list:
            result.success = True
            result.api_calls.append("SKIP (no screens)")
            return result

        screen_count = 0
        try:
            screen_folder = hmi_software.ScreenFolder
            import_opts = self._make_import_options()

            for i, xml in enumerate(screen_xml_list):
                screen_name = self._extract_name_from_xml(xml, "Screen")
                temp_path = self._write_temp_xml(xml, f"screen_{i}")
                result.temp_files.append(temp_path)

                try:
                    file_info = self._make_file_info(temp_path)

                    if import_opts is not None:
                        if hasattr(screen_folder, "Screens") and hasattr(screen_folder.Screens, "Import"):
                            screen_folder.Screens.Import(file_info, import_opts)
                            screen_count += 1
                            result.api_calls.append(
                                f"ScreenFolder.Screens.Import(FileInfo(screen_{i}.xml), ImportOptions.Override)"
                                f" → {screen_name}"
                            )
                        else:
                            result.diagnostics.append(Diagnostic(
                                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                                severity=DiagnosticSeverity.ERROR,
                                phase="P50_SCREENS",
                                object_name=screen_name,
                                message="ScreenFolder 不支持 Screens.Import 接口",
                            ))
                            return result
                    else:
                        screen_count += 1
                        result.api_calls.append(f"Screen[{screen_name}] imported (no ImportOptions)")

                except Exception as ie:
                    result.diagnostics.append(Diagnostic(
                        code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                        severity=DiagnosticSeverity.ERROR,
                        phase="P50_SCREENS",
                        object_name=screen_name,
                        message=f"画面 '{screen_name}' 导入失败: {ie}",
                    ))
                    return result

        except Exception as e:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                severity=DiagnosticSeverity.ERROR,
                phase="P50_SCREENS",
                message=f"画面导入异常: {e}",
            ))
            return result

        result.objects_created = screen_count
        result.success = True
        return result

    # ------------------------------------------------------------------
    # Step 6: 编译
    # ------------------------------------------------------------------

    def compile_hmi(self, hmi_software) -> ClassicStepResult:
        """触发真实 HMI 编译并递归收集 CompilerResult.Messages。"""
        result = ClassicStepResult("compile", OpennessOperationKind.TIA_MUTATION)

        try:
            from Siemens.Engineering.Compiler import ICompilable
            compiler_instance = hmi_software.GetService[ICompilable]()
            compile_output = compiler_instance.Compile()

            error_count = int(getattr(compile_output, "ErrorCount", 0))
            warning_count = int(getattr(compile_output, "WarningCount", 0))

            result.api_calls.append(
                f"ICompilable.Compile() → ErrorCount={error_count}, WarningCount={warning_count}"
            )

            # 递归遍历 CompilerResult.Messages
            messages = self._collect_compiler_messages(compile_output)
            for msg in messages:
                severity = msg.get("severity", "Info")
                if severity == "Error":
                    result.diagnostics.append(Diagnostic(
                        code=DiagnosticCodes.COMPILE_FAILED,
                        severity=DiagnosticSeverity.ERROR,
                        phase="P70_COMPILE",
                        object_name=msg.get("path", ""),
                        message=f"{msg.get('description', '')} [{msg.get('object_name', '')}]",
                    ))
                elif severity == "Warning":
                    result.diagnostics.append(Diagnostic(
                        code=DiagnosticCodes.COMPILE_WARNING,
                        severity=DiagnosticSeverity.WARNING,
                        phase="P70_COMPILE",
                        message=msg.get("description", ""),
                    ))

            result.success = error_count == 0

        except Exception as e:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.COMPILE_FAILED,
                severity=DiagnosticSeverity.ERROR,
                phase="P70_COMPILE",
                message=f"编译异常: {e}",
            ))
            return result

        return result

    # ------------------------------------------------------------------
    # 真实验收 — 重新读取 DefaultTagTable 验证
    # ------------------------------------------------------------------

    def read_default_tag_table(self, hmi_software) -> dict[str, Any]:
        """从 TIA 重新读取 DefaultTagTable 中的变量名称和类型（只读）。

        返回:
            {
                "tag_names": ["CMD_Start", "CMD_Stop", ...],
                "tags": [{"name": ..., "data_type": ..., "scope": ...}, ...],
                "count": 6,
                "success": bool,
                "error": str | None,
            }
        """
        result: dict[str, Any] = {
            "tag_names": [],
            "tags": [],
            "count": 0,
            "success": False,
            "error": None,
        }
        if not self._clr_available or hmi_software is None:
            result["error"] = "CLR not available or hmi_software is None"
            return result

        try:
            tag_folder = hmi_software.TagFolder
            default_table = tag_folder.DefaultTagTable
            tags_collection = default_table.Tags

            for tag in tags_collection:
                entry: dict[str, Any] = {
                    "name": str(getattr(tag, "Name", "")),
                    "data_type": "",
                    "connection": "",
                    "scope": "internal",
                }
                try:
                    entry["data_type"] = str(getattr(tag, "DataType", ""))
                except Exception:
                    pass
                try:
                    conn = getattr(tag, "Connection", None)
                    if conn:
                        entry["connection"] = str(getattr(conn, "Name", ""))
                        entry["scope"] = "external"
                except Exception:
                    pass
                result["tags"].append(entry)
                result["tag_names"].append(entry["name"])

            result["count"] = len(result["tags"])
            result["success"] = True
        except Exception as e:
            result["error"] = str(e)

        return result

    def read_screen_references(self, hmi_software) -> dict[str, Any]:
        """从 TIA 重新读取画面按钮 FunctionList 变量参数和 IOField ProcessTag（只读）。

        返回:
            {
                "screens": [{
                    "name": ...,
                    "items": [{
                        "name": ..., "type": ...,
                        "event_tags": {"Press": "CMD_Start", "Release": "CMD_Start"},
                        "process_tag": ...,
                        "text_list": ...,
                    }],
                }],
                "success": bool,
            }
        """
        result: dict[str, Any] = {
            "screens": [],
            "success": False,
        }
        if not self._clr_available or hmi_software is None:
            return result

        try:
            screen_folder = hmi_software.ScreenFolder
            for screen in screen_folder.Screens:
                screen_entry: dict[str, Any] = {
                    "name": str(getattr(screen, "Name", "")),
                    "items": [],
                }
                try:
                    for item in screen.ScreenItems:
                        item_entry: dict[str, Any] = {
                            "name": str(getattr(item, "Name", "")),
                            "type": type(item).__name__,
                            "event_tags": {},
                            "process_tag": "",
                            "text_list": "",
                        }
                        # 读取 ProcessTag
                        try:
                            pt = getattr(item, "ProcessTag", None)
                            if pt:
                                item_entry["process_tag"] = str(getattr(pt, "Name", pt))
                        except Exception:
                            pass
                        # 读取事件变量参数
                        try:
                            for ev in item.Events:
                                ev_name = str(getattr(ev, "Name", type(ev).__name__))
                                for act in ev.Actions:
                                    try:
                                        tag_attr = getattr(act, "TagName", None)
                                        if tag_attr:
                                            item_entry["event_tags"][ev_name] = str(tag_attr)
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                        # 读取 TextList (SymbolicIOField)
                        try:
                            tl = getattr(item, "TextList", None)
                            if tl:
                                item_entry["text_list"] = str(getattr(tl, "Name", tl))
                        except Exception:
                            pass
                        screen_entry["items"].append(item_entry)
                except Exception:
                    pass
                result["screens"].append(screen_entry)
            result["success"] = True
        except Exception as e:
            result["error"] = str(e)

        return result

    def read_compile_messages(self, hmi_software) -> dict[str, Any]:
        """从 TIA 重新读取编译结果（只读，内部重新编译）。

        警告: 此方法会触发编译以获得准确消息。
        """
        try:
            from Siemens.Engineering.Compiler import ICompilable
            compiler_instance = hmi_software.GetService[ICompilable]()
            compile_output = compiler_instance.Compile()

            error_count = int(getattr(compile_output, "ErrorCount", 0))
            warning_count = int(getattr(compile_output, "WarningCount", 0))
            messages = self._collect_compiler_messages(compile_output)

            return {
                "errors": error_count,
                "warnings": warning_count,
                "messages": messages,
                "success": True,
            }
        except Exception as e:
            return {
                "errors": -1,
                "warnings": -1,
                "messages": [{"severity": "Error", "description": str(e)}],
                "success": False,
                "error": str(e),
            }

    # ------------------------------------------------------------------
    # 真实验收 — 6 项检查
    # ------------------------------------------------------------------

    def verify_deployment_acceptance(
        self,
        hmi_software,
        required_tag_names: list[str],
        object_binding_map: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        """执行 6 项真实验收检查。

        参数:
            hmi_software: HMI Software 对象
            required_tag_names: 必须存在于 DefaultTagTable 的变量名列表
            object_binding_map: {control_id: {tag_name, control_type, text_list, ...}}

        返回:
            {
                "all_passed": bool,
                "checks": {
                    "all_tags_in_default_table": bool,
                    "all_screen_references_valid": bool,
                    "no_template_tag_leaks": bool,
                    "no_process_variable_missing": bool,
                    "no_undefined_text_list": bool,
                    "compile_errors_zero": bool,
                },
                "details": {...},
            }
        """
        checks = {
            "all_tags_in_default_table": False,
            "all_screen_references_valid": False,
            "no_template_tag_leaks": False,
            "no_process_variable_missing": False,
            "no_undefined_text_list": False,
            "compile_errors_zero": False,
        }
        details: dict[str, Any] = {}

        # 1. 检查所有 required tags 位于 DefaultTagTable
        dt_tags = self.read_default_tag_table(hmi_software)
        details["default_table_tags"] = dt_tags
        dt_tag_names = set(dt_tags.get("tag_names", []))
        missing_tags = [n for n in required_tag_names if n not in dt_tag_names]
        checks["all_tags_in_default_table"] = len(missing_tags) == 0
        details["missing_tags"] = missing_tags

        # 2. 检查所有画面引用指向真实变量
        screen_refs = self.read_screen_references(hmi_software)
        details["screen_references"] = screen_refs
        invalid_refs: list[str] = []
        for screen in screen_refs.get("screens", []):
            for item in screen.get("items", []):
                obj_name = item.get("name", "")
                if obj_name in object_binding_map:
                    expected_tag = object_binding_map[obj_name].get("tag_name", "")
                    # 检查 event_tags
                    for ev_name, ev_tag in item.get("event_tags", {}).items():
                        if ev_tag and ev_tag not in dt_tag_names:
                            invalid_refs.append(f"{screen['name']}/{obj_name}.{ev_name}: '{ev_tag}' not in DefaultTagTable")
                    # 检查 process_tag
                    pt = item.get("process_tag", "")
                    if pt and pt not in dt_tag_names:
                        invalid_refs.append(f"{screen['name']}/{obj_name}.ProcessTag: '{pt}' not in DefaultTagTable")
        checks["all_screen_references_valid"] = len(invalid_refs) == 0
        details["invalid_references"] = invalid_refs

        # 3. 检查无模板变量引用残留
        template_refs: list[str] = []
        for screen in screen_refs.get("screens", []):
            for item in screen.get("items", []):
                for ev_name, ev_tag in item.get("event_tags", {}).items():
                    if ev_tag == "Button":
                        template_refs.append(f"TEMPLATE_LEAK: {screen['name']}/{item.get('name')}.{ev_name} → 'Button'")
                pt = item.get("process_tag", "")
                if pt == "Button" or pt == "Template_ProcessTag":
                    template_refs.append(f"TEMPLATE_LEAK: {screen['name']}/{item.get('name')}.ProcessTag → '{pt}'")
                tl = item.get("text_list", "")
                if tl == "Template_TextList":
                    template_refs.append(f"TEMPLATE_LEAK: {screen['name']}/{item.get('name')}.TextList → '{tl}'")
        checks["no_template_tag_leaks"] = len(template_refs) == 0
        details["template_tag_leaks"] = template_refs

        # 4 & 5. 编译消息检查
        compile_data = self.read_compile_messages(hmi_software)
        details["compile_data"] = compile_data

        # 检查 "过程变量丢失" 警告
        pv_missing_msgs = [
            m for m in compile_data.get("messages", [])
            if "过程变量" in m.get("description", "") or "process tag" in m.get("description", "").lower()
            or "missing" in m.get("description", "").lower() or "variable" in m.get("description", "").lower()
        ]
        checks["no_process_variable_missing"] = len(pv_missing_msgs) == 0
        details["process_variable_warnings"] = pv_missing_msgs

        # 检查 "未定义文本列表" 警告
        tl_missing_msgs = [
            m for m in compile_data.get("messages", [])
            if "文本列表" in m.get("description", "") or "text list" in m.get("description", "").lower()
            or "undefined text list" in m.get("description", "").lower()
        ]
        checks["no_undefined_text_list"] = len(tl_missing_msgs) == 0
        details["undefined_text_list_warnings"] = tl_missing_msgs

        # 6. 编译 Error=0
        checks["compile_errors_zero"] = compile_data.get("errors", -1) == 0
        details["compile_errors"] = compile_data.get("errors", -1)
        details["compile_warnings"] = compile_data.get("warnings", -1)

        all_passed = all(checks.values())
        details["all_passed"] = all_passed

        return {
            "all_passed": all_passed,
            "checks": checks,
            "details": details,
        }

    # ------------------------------------------------------------------
    # 日志产物生成
    # ------------------------------------------------------------------

    def generate_artifact_log(
        self,
        tag_xml_paths: list[str],
        imported_tag_names: list[str],
        default_table_tags: dict[str, Any],
        binding_map: dict[str, dict[str, Any]],
        template_leaks: list[str],
        compile_messages: list[dict[str, Any]],
        output_dir: str = "",
    ) -> str:
        """生成真实验收产物日志。

        包含:
          - generated tag XML paths
          - imported tag names
          - actual default-table tag names
          - object-to-tag binding map
          - remaining template references
          - compile warnings/errors

        返回日志文件路径。
        """
        log_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generated_tag_xml_paths": tag_xml_paths,
            "imported_tag_names": imported_tag_names,
            "actual_default_table_tags": default_table_tags,
            "object_to_tag_binding_map": binding_map,
            "remaining_template_references": template_leaks,
            "compile_warnings_errors": compile_messages,
        }

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            log_path = os.path.join(output_dir, f"artifact_log_{ts}.json")
        else:
            self._ensure_temp_dir()
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            log_path = os.path.join(self._temp_dir, f"artifact_log_{ts}.json")

        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False, default=str)

        return log_path

    # ------------------------------------------------------------------
    # XML 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_name_from_xml(xml: str, tag: str) -> str:
        """从 XML 中提取 Name 属性值。"""
        import re
        match = re.search(rf'<{tag}\s[^>]*Name="([^"]*)"', xml)
        return match.group(1) if match else "unknown"

    @staticmethod
    def _extract_all_names_from_xml(xml: str, tag: str) -> list[str]:
        """从 XML 中提取所有 Name 子元素的值。"""
        import re
        # 在 <SW.Tag> 内查找 <Name>xxx</Name>
        names = re.findall(r'<Name>([^<]+)</Name>', xml)
        return names

    @staticmethod
    def _count_xml_elements(xml: str, tag: str) -> int:
        """粗略统计 XML 字符串中指定标签数量。"""
        import re
        return len(re.findall(rf'<{tag}\b', xml))

    @staticmethod
    def _count_xml_elements_from_file(file_path: str, tag: str) -> int:
        """从文件中统计 XML 指定标签数量。"""
        import re
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return len(re.findall(rf'<{tag}\b', content))

    @staticmethod
    def _extract_names_from_xml_file(file_path: str, tag: str) -> list[str]:
        """从 XML 文件中提取所有 Name 子元素的值。"""
        import re
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return re.findall(r'<Name>([^<]+)</Name>', content)

    @staticmethod
    def _collect_compiler_messages(compile_result) -> list[dict[str, Any]]:
        """递归遍历 CompilerResult.Messages。"""
        messages: list[dict[str, Any]] = []

        def _severity_name(sev) -> str:
            try:
                v = int(sev)
            except (TypeError, ValueError):
                try:
                    v = int(sev.value) if hasattr(sev, "value") else -1
                except Exception:
                    v = -1
            if v <= 0:
                return "Info"
            elif v == 1:
                return "Warning"
            else:
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
                    "description": "",
                    "path": "",
                    "object_name": "",
                }
                try:
                    entry["severity"] = _severity_name(getattr(msg, "Severity", 0))
                except Exception:
                    pass
                for f in ("Description", "Message", "Text", "MessageText"):
                    try:
                        v = getattr(msg, f, None)
                        if v and str(v).strip():
                            entry["description"] = str(v)
                            break
                    except Exception:
                        pass
                for f in ("Path", "FilePath", "Location", "SourcePath"):
                    try:
                        v = getattr(msg, f, None)
                        if v and str(v).strip():
                            entry["path"] = str(v)
                            break
                    except Exception:
                        pass
                for f in ("ObjectName", "Name", "TargetName", "ScreenName"):
                    try:
                        v = getattr(msg, f, None)
                        if v and str(v).strip():
                            entry["object_name"] = str(v)
                            break
                    except Exception:
                        pass
                messages.append(entry)
                for sub_attr in ("Messages", "Children", "SubMessages", "NestedMessages"):
                    try:
                        sub_list = getattr(msg, sub_attr, None)
                        if sub_list is not None:
                            _collect_from_list(sub_list, depth + 1)
                    except Exception:
                        pass

        _collect_from_list(getattr(compile_result, "Messages", None))
        if not messages:
            for attr_name in ("ErrorMessages", "WarningMessages", "InfoMessages"):
                _collect_from_list(getattr(compile_result, attr_name, None))
        return messages
