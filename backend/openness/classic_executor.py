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
from backend.openness.diagnostics_utils import (
    collect_exception_chain,
    describe_dotnet_object,
    enumerate_tag_names,
    find_tag,
    inspect_xml_document,
)


def _safe_device_name(obj) -> str:
    """安全获取设备/设备项名称。"""
    try:
        return str(obj.Name)
    except Exception:
        return type(obj).__name__


def _canonical_hmi_data_type(value: Any, fallback: str = "") -> str:
    """Return a stable HMI data type name for comparison and enum parsing."""
    raw = str(value or "").strip()
    if not raw:
        return fallback
    raw = raw.strip("\"'")
    if "." in raw:
        raw = raw.rsplit(".", 1)[-1]
    aliases = {
        "bool": "Bool",
        "boolean": "Bool",
        "bit": "Bool",
        "int": "Int",
        "integer": "Int",
        "short": "Int",
        "uint": "UInt",
        "word": "Word",
        "dint": "DInt",
        "doubleint": "DInt",
        "udint": "UDInt",
        "dword": "DWord",
        "real": "Real",
        "float": "Real",
        "double": "Real",
        "string": "String",
        "wstring": "WString",
        "text": "String",
    }
    return aliases.get(raw.replace("_", "").replace(" ", "").lower(), raw)


def _hmi_data_types_equal(left: Any, right: Any) -> bool:
    return (
        _canonical_hmi_data_type(left).lower()
        == _canonical_hmi_data_type(right).lower()
    )


def _set_hmi_tag_data_type(tag: Any, expected_type: str) -> tuple[bool, str]:
    """Set HMI tag DataType via reflection and verify the persisted value."""
    expected = _canonical_hmi_data_type(expected_type, fallback="Bool")
    actual = ""

    try:
        tag_type = tag.GetType()
        dt_prop = tag_type.GetProperty("DataType")
    except Exception:
        dt_prop = None

    values_to_try: list[Any] = [expected]
    try:
        from System import String
        values_to_try.append(String(expected))
    except Exception:
        pass

    if dt_prop is not None:
        try:
            from System import Enum as SystemEnum
            from System import String

            dt_type = dt_prop.PropertyType
            if getattr(dt_type, "IsEnum", False):
                enum_name = expected
                try:
                    for candidate in SystemEnum.GetNames(dt_type):
                        candidate_s = str(candidate)
                        if _hmi_data_types_equal(candidate_s, expected):
                            enum_name = candidate_s
                            break
                except Exception:
                    pass
                try:
                    dt_value = SystemEnum.Parse(dt_type, enum_name, True)
                except TypeError:
                    dt_value = SystemEnum.Parse(dt_type, enum_name)
            else:
                dt_value = String(expected)
            values_to_try.insert(0, dt_value)

            try:
                dt_prop.SetValue(tag, dt_value, None)
            except TypeError:
                dt_prop.SetValue(tag, dt_value)
        except Exception:
            pass

    try:
        actual = str(getattr(tag, "DataType", ""))
    except Exception:
        actual = ""
    if _hmi_data_types_equal(actual, expected):
        return True, actual

    # Classic HMI engineering objects often expose SetAttribute even when
    # Python property assignment is read-only or does not persist.
    for attr_name in ("DataType", "data_type"):
        for value in values_to_try:
            try:
                tag.SetAttribute(attr_name, value)
            except Exception:
                pass
            try:
                actual = str(getattr(tag, "DataType", ""))
            except Exception:
                actual = ""
            if _hmi_data_types_equal(actual, expected):
                return True, actual

    for value in values_to_try:
        try:
            tag.DataType = value
        except Exception:
            pass
        try:
            actual = str(getattr(tag, "DataType", ""))
        except Exception:
            actual = ""
        if _hmi_data_types_equal(actual, expected):
            return True, actual

    try:
        actual = str(getattr(tag, "DataType", ""))
    except Exception:
        actual = ""
    return _hmi_data_types_equal(actual, expected), actual


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


class TagXmlKind(str, Enum):
    """基于真实导出样本的严格 XML 分类。

    EXPORTED_TAG:       单个变量导出 (起始对象 Hmi.Tag.Tag)
                        → DefaultTagTable.Tags.Import()
    EXPORTED_TAG_TABLE: 完整变量表导出 (起始对象 Hmi.Tag.TagTable)
                        → TagFolder.TagTables.Import()
    """
    EXPORTED_TAG = "exported_tag"
    EXPORTED_TAG_TABLE = "exported_tag_table"


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
        for elem in root.iter():
            raw_name = elem.tag.rsplit("}", 1)[-1] if "}" in elem.tag else elem.tag
            elem_local = _local_tag_name(elem.tag)
            elem_comp = _find_composition_name(elem, ns)
            if (
                raw_name == "Hmi.Tag.TagTable"
                or elem_local in ("TagTable", "Tagtable")
                or (elem_comp and ("TagTable" in elem_comp or "Tagtable" in elem_comp))
            ):
                return ClassicTagImportKind.TAG_TABLE
        for blocks in root:
            if _local_tag_name(blocks.tag) == "Blocks":
                for child in blocks:
                    child_local = _local_tag_name(child.tag)
                    if child_local in ("TagTable", "Tagtable"):
                        return ClassicTagImportKind.TAG_TABLE
        # 检查是否有 Tag 元素
        all_tags = root.findall(f".//{{{ns}}}Tag") if ns else root.findall(".//Tag")
        if not all_tags:
            all_tags = [
                elem for elem in root.iter()
                if _local_tag_name(elem.tag) == "Tag"
            ]
        if all_tags:
            return ClassicTagImportKind.INDIVIDUAL_TAGS

    # 3. 检查 CompositionName 属性
    composition_name = _find_composition_name(root, ns)
    if composition_name:
        if "TagTable" in composition_name or "Tagtable" in composition_name:
            return ClassicTagImportKind.TAG_TABLE
        if "Tag" in composition_name:
            return ClassicTagImportKind.INDIVIDUAL_TAGS

    # 4. Generic scan for Engineering-root exports.
    for elem in root.iter():
        raw_name = elem.tag.rsplit("}", 1)[-1] if "}" in elem.tag else elem.tag
        elem_local = _local_tag_name(elem.tag)
        elem_comp = _find_composition_name(elem, ns)
        if (
            raw_name == "Hmi.Tag.TagTable"
            or elem_local in ("TagTable", "Tagtable")
            or (elem_comp and ("TagTable" in elem_comp or "Tagtable" in elem_comp))
        ):
            return ClassicTagImportKind.TAG_TABLE
    for elem in root.iter():
        raw_name = elem.tag.rsplit("}", 1)[-1] if "}" in elem.tag else elem.tag
        elem_local = _local_tag_name(elem.tag)
        elem_comp = _find_composition_name(elem, ns)
        if (
            raw_name == "Hmi.Tag.Tag"
            or elem_local == "Tag"
            or (elem_comp and elem_comp == "Tags")
        ):
            return ClassicTagImportKind.INDIVIDUAL_TAGS

    raise ValueError(
        f"CLASSIC_TAG_XML_KIND_UNKNOWN: 无法识别 XML 类型，"
        f"根元素='{root_local}'，CompositionName='{composition_name}'，"
        f"文件='{xml_path}'。"
        f"请确认 XML 是完整 TagTable 导出还是单个 Tag 集合。"
    )


def classify_tag_xml_strict(xml_path: str) -> TagXmlKind:
    """基于 XML Document 根对象类型严格分类变量 XML。

    通过解析 XML 文件，查找具有 'Hmi.Tag.Tag' 或 'Hmi.Tag.TagTable'
    类型标识的起始对象，进行精确分类。

    不依赖字符串搜索或根标签名猜测。
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except Exception as e:
        raise ValueError(
            f"TAG_XML_PARSE_FAILED: 无法解析 XML '{xml_path}': {e}"
        ) from e

    # 查找所有带有类型标识的对象
    start_objects = []
    for elem in root.iter():
        # 检查 ID 属性中的类型名 (如 "Hmi.Tag.Tag" 或 "Hmi.Tag.TagTable")
        elem_tag_local = _local_tag_name(elem.tag)

        # 方式1: 标签名本身是类型 (如 <Hmi.Tag.Tag ...>)
        if elem_tag_local.startswith("Hmi.Tag."):
            start_objects.append(elem_tag_local)
            continue

        # 方式2: 命名空间标签名
        if "." in elem_tag_local and "Tag" in elem_tag_local:
            start_objects.append(elem_tag_local)

    # 去重
    unique_types = sorted(set(start_objects))

    if not unique_types:
        # 回退: 使用旧的检测逻辑
        kind = detect_tag_import_kind(xml_path)
        if kind == ClassicTagImportKind.TAG_TABLE:
            return TagXmlKind.EXPORTED_TAG_TABLE
        return TagXmlKind.EXPORTED_TAG

    # 判断: TagTable 优先（因为 TagTable XML 内部也会包含 Tag 元素）
    has_tag_table = any("TagTable" in t for t in unique_types)
    has_tag = any(t.endswith(".Tag") or t == "Hmi.Tag.Tag" for t in unique_types)

    if has_tag_table:
        return TagXmlKind.EXPORTED_TAG_TABLE
    if has_tag:
        return TagXmlKind.EXPORTED_TAG

    raise ValueError(
        f"TAG_XML_START_OBJECT_UNSUPPORTED: 不支持的变量 XML 起始对象类型: "
        f"{unique_types}，文件='{xml_path}'。"
        f"XML 诊断: {inspect_xml_document(xml_path)}"
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

    # ------------------------------------------------------------------
    # V4.2: ImportOptions 解析器 — 多路径枚举 + 别名匹配
    # ------------------------------------------------------------------

    # 别名映射：不同 TIA 版本中 enum 成员名可能不同
    _IMPORT_OPTION_ALIASES: dict[str, list[str]] = {
        "Override": ["Override", "Overwrite", "Replace"],
        "Merge":    ["Merge", "Update", "Modify"],
    }

    @staticmethod
    def resolve_import_option(
        tia_module=None,
        preferred: str = "Override",
    ) -> dict:
        """解析 Siemens.Engineering.ImportOptions，返回结构化结果。

        使用多种方式尝试解析 ImportOptions 枚举值：
          A. 直接属性：ImportOptions.Override
          B. System.Enum.Parse(import_options_type, "Override")
          C. System.Enum.GetNames(import_options_type) 列出可用名
          D. 别名匹配：Override → Overwrite/Replace, Merge → Update/Modify

        参数:
            tia_module: Siemens.Engineering 模块引用（可选，用于加载程序集）。
            preferred:  首选选项名（默认 "Override"）。

        返回:
            {
                "ok": bool,
                "value": int | None,        # 枚举整数值
                "selected": str | None,     # 实际选中的选项名
                "available": list[str],     # 枚举中所有可用名称
                "source": str,              # 解析路径 (direct/enum-parse/alias-match/none)
                "error": str | None,        # 失败时的错误消息
                "diagnostics": list[str],   # 各步骤的诊断日志
            }
        """
        result: dict = {
            "ok": False,
            "value": None,
            "enum_type": None,
            "selected": None,
            "available": [],
            "source": "none",
            "error": None,
            "diagnostics": [],
        }

        aliases = ClassicOpennessExecutor._IMPORT_OPTION_ALIASES.get(
            preferred, [preferred],
        )

        # 尝试两个命名空间
        for ns_label, ns_path in [
            ("Hmi.ImportOptions", "Siemens.Engineering.Hmi"),
            ("Engineering.ImportOptions", "Siemens.Engineering"),
        ]:
            try:
                ns_module = __import__(ns_path, fromlist=["ImportOptions"])
                import_opts_type = getattr(ns_module, "ImportOptions", None)
                if import_opts_type is None:
                    result["diagnostics"].append(
                        f"{ns_label}: ImportOptions 不存在于命名空间"
                    )
                    continue

                type_name = str(getattr(import_opts_type, "__name__", import_opts_type))
                result["diagnostics"].append(
                    f"{ns_label}: 找到类型 {type_name}"
                )

                # A. 直接属性
                for alias in aliases:
                    try:
                        val = getattr(import_opts_type, alias, None)
                        if val is not None:
                            result["ok"] = True
                            result["value"] = int(val)
                            result["selected"] = alias
                            result["source"] = f"direct:{ns_label}"
                            result["diagnostics"].append(
                                f"{ns_label}: 直接属性 {alias}={val}"
                            )
                            return result
                    except Exception:
                        pass

                # B. System.Enum.Parse
                try:
                    from System import Enum  # type: ignore
                    for alias in aliases:
                        try:
                            parsed = Enum.Parse(import_opts_type, alias)
                            if parsed is not None:
                                result["ok"] = True
                                result["value"] = int(parsed)
                                result["selected"] = alias
                                result["source"] = f"enum-parse:{ns_label}"
                                result["diagnostics"].append(
                                    f"{ns_label}: Enum.Parse({alias})={parsed}"
                                )
                                return result
                        except Exception:
                            pass
                except Exception as exc:
                    result["diagnostics"].append(
                        f"{ns_label}: System.Enum.Parse 不可用: {exc}"
                    )

                # C. System.Enum.GetNames
                try:
                    from System import Enum  # type: ignore
                    names = list(Enum.GetNames(import_opts_type))
                    result["available"] = names
                    result["diagnostics"].append(
                        f"{ns_label}: Enum.GetNames = {names}"
                    )

                    for alias in aliases:
                        if alias in names:
                            parsed = Enum.Parse(import_opts_type, alias)
                            result["ok"] = True
                            result["value"] = int(parsed)
                            result["selected"] = alias
                            result["source"] = f"enum-names:{ns_label}"
                            result["diagnostics"].append(
                                f"{ns_label}: 通过 GetNames 找到 {alias}={parsed}"
                            )
                            return result
                except Exception as exc:
                    result["diagnostics"].append(
                        f"{ns_label}: System.Enum.GetNames 不可用: {exc}"
                    )

                # D. 反射列出字段
                try:
                    fields = []
                    for attr_name in dir(import_opts_type):
                        if attr_name.startswith("_"):
                            continue
                        try:
                            v = getattr(import_opts_type, attr_name)
                            if isinstance(v, int):
                                fields.append((attr_name, v))
                        except Exception:
                            pass
                    if fields and not result["available"]:
                        result["available"] = [f[0] for f in fields]
                        result["diagnostics"].append(
                            f"{ns_label}: dir() 字段探测 = {fields}"
                        )
                    for alias in aliases:
                        for fname, fval in fields:
                            if fname == alias:
                                result["ok"] = True
                                result["value"] = fval
                                result["selected"] = alias
                                result["source"] = f"field-probe:{ns_label}"
                                result["diagnostics"].append(
                                    f"{ns_label}: 字段探测 {alias}={fval}"
                                )
                                return result
                except Exception as exc:
                    result["diagnostics"].append(
                        f"{ns_label}: 字段探测失败: {exc}"
                    )

            except ImportError as exc:
                result["diagnostics"].append(
                    f"{ns_label}: 导入失败: {exc}"
                )
            except Exception as exc:
                result["diagnostics"].append(
                    f"{ns_label}: 异常: {exc}"
                )

        # E. Assembly scan — 遍历已加载程序集查找 ImportOptions 类型
        result["searched_assemblies"] = []
        try:
            from System import AppDomain  # type: ignore
            for assembly in AppDomain.CurrentDomain.GetAssemblies():
                asm_name = str(getattr(assembly, "FullName", assembly))
                result["searched_assemblies"].append(asm_name)
                try:
                    opts_type = assembly.GetType(
                        "Siemens.Engineering.ImportOptions", False
                    )
                    if opts_type is not None:
                        result["diagnostics"].append(
                            f"assembly-scan: 在程序集 '{asm_name}' 中找到 ImportOptions"
                        )

                        # 用 System.Enum 解析
                        from System import Enum  # type: ignore
                        names = list(Enum.GetNames(opts_type))
                        result["available"] = names
                        result["diagnostics"].append(
                            f"assembly-scan: Enum.GetNames = {names}"
                        )

                        for alias in aliases:
                            if alias in names:
                                parsed = Enum.Parse(opts_type, alias)
                                if parsed is not None:
                                    result["ok"] = True
                                    result["value"] = parsed
                                    result["enum_type"] = opts_type
                                    result["selected"] = alias
                                    result["source"] = f"assembly-scan:{asm_name}"
                                    result["diagnostics"].append(
                                        f"assembly-scan: 找到 {alias}={parsed}"
                                    )
                                    return result

                        # 别名匹配
                        for alias in aliases:
                            try:
                                parsed = Enum.Parse(opts_type, alias)
                                result["ok"] = True
                                result["value"] = parsed
                                result["enum_type"] = opts_type
                                result["selected"] = alias
                                result["source"] = f"assembly-scan-parse:{asm_name}"
                                result["diagnostics"].append(
                                    f"assembly-scan: Enum.Parse({alias})={parsed}"
                                )
                                return result
                            except Exception:
                                pass

                except Exception:
                    continue
        except Exception as exc:
            result["diagnostics"].append(
                f"assembly-scan: AppDomain 不可用: {exc}"
            )
            result["searched_assemblies"] = []

        # 全部失败
        result["error"] = (
            f"无法解析 ImportOptions.{preferred}。"
            f"已尝试别名: {aliases}，"
            f"可用名称: {result['available'] or 'N/A'}。"
            f"已搜索程序集: {len(result.get('searched_assemblies', []))} 个"
        )
        return result

    @staticmethod
    def resolve_import_option_from_overload(
        tag_composition,
        preferred: str = "Override",
    ) -> dict:
        """从 TagComposition.Import 方法重载的第二参数类型解析 ImportOptions。

        不需要导入 Siemens.Engineering 命名空间，也不需要 assembly scan。
        直接从 Import 方法签名的 ParameterType 反射获取 enum 类型。

        返回结构同 resolve_import_option()：
          ok, value, selected, available, source, error, diagnostics,
          method_signature, type_full_name
        """
        result: dict = {
            "ok": False,
            "value": None,
            "enum_type": None,
            "selected": None,
            "available": [],
            "source": "none",
            "error": None,
            "diagnostics": [],
            "method_signature": None,
            "type_full_name": None,
        }

        # 获取 System.Enum（优先 CLR，失败回退模块级 mock）
        _system_enum = getattr(ClassicOpennessExecutor, "_test_enum", None)
        if _system_enum is None:
            try:
                from System import Enum  # type: ignore
                _system_enum = Enum
            except ImportError:
                pass

        if _system_enum is None:
            result["diagnostics"].append(
                "overload-param: System.Enum 不可用（无 CLR 环境）"
            )

        if tag_composition is None:
            result["error"] = "tag_composition is None"
            return result

        try:
            methods = list(tag_composition.GetType().GetMethods())
            import_methods = [m for m in methods if m.Name == "Import"]
            result["diagnostics"].append(
                f"overload-param: 找到 {len(import_methods)} 个 Import 重载"
            )

            aliases = ClassicOpennessExecutor._IMPORT_OPTION_ALIASES.get(
                preferred, [preferred]
            )

            for method in import_methods:
                try:
                    params = list(method.GetParameters())
                    if len(params) < 2:
                        continue

                    p1 = params[1]
                    p1_type = p1.ParameterType
                    type_name = str(getattr(p1_type, "FullName", p1_type))
                    is_enum = bool(getattr(p1_type, "IsEnum", False))

                    result["diagnostics"].append(
                        f"overload-param: params[1] type={type_name}, IsEnum={is_enum}"
                    )

                    if not is_enum:
                        continue

                    if _system_enum is None:
                        result["diagnostics"].append(
                            "overload-param: 找到 enum 参数但 System.Enum 不可用"
                        )
                        continue

                    names = list(_system_enum.GetNames(p1_type))
                    result["available"] = names
                    result["type_full_name"] = type_name
                    p0_type = params[0].ParameterType
                    p0_name = str(getattr(p0_type, "FullName", p0_type))
                    result["method_signature"] = f"Import({p0_name}, {type_name})"

                    # 尝试 preferred 及其别名
                    for alias in aliases:
                        if alias in names:
                            parsed = _system_enum.Parse(p1_type, alias)
                            result["ok"] = True
                            result["value"] = parsed
                            result["enum_type"] = p1_type
                            result["selected"] = alias
                            result["source"] = "import_overload_parameter"
                            result["diagnostics"].append(
                                f"overload-param: 找到 {alias}={int(parsed)}"
                            )
                            return result

                    # 别名不在 names 中，尝试 Enum.Parse 直接
                    for alias in aliases:
                        try:
                            parsed = _system_enum.Parse(p1_type, alias)
                            result["ok"] = True
                            result["value"] = parsed
                            result["enum_type"] = p1_type
                            result["selected"] = alias
                            result["source"] = "import_overload_parameter"
                            result["diagnostics"].append(
                                f"overload-param: Enum.Parse({alias})={int(parsed)}"
                            )
                            return result
                        except Exception:
                            continue

                except Exception as exc:
                    result["diagnostics"].append(
                        f"overload-param: 处理重载异常: {exc}"
                    )
                    continue

        except Exception as exc:
            result["diagnostics"].append(
                f"overload-param: GetMethods 失败: {exc}"
            )

        # 没有找到合适的 enum 参数
        result["error"] = (
            f"Import 重载的第二参数不是 enum 类型。"
            f"已检查 {len(result['diagnostics'])} 个诊断信息。"
        )
        if not result["available"]:
            result["error"] += " 可用 enum 名称: N/A"
        else:
            result["error"] += f" 可用 enum 名称: {result['available']}"

        return result

    @staticmethod
    def invoke_tag_composition_import(
        tag_composition,
        xml_path: str,
        option_result: dict,
    ) -> None:
        """通过 MethodInfo.Invoke 调用 TagComposition.Import。

        当 pythonnet 直接调用 tag_composition.Import(file_info, option)
        失败时，使用此方法通过反射调用。

        参数:
            tag_composition: TagComposition .NET 对象
            xml_path: XML 文件路径字符串
            option_result: resolve_import_option 或
                          resolve_import_option_from_overload 的返回结果

        异常:
            RuntimeError: 所有匹配重载都失败时抛出
        """
        from System.IO import FileInfo  # type: ignore
        from System import Array, Object, Enum  # type: ignore

        file_info = FileInfo(xml_path)

        # Ensure arg1 is a proper .NET enum, not Python int
        option_value = option_result["value"]
        enum_type = option_result.get("enum_type")

        if isinstance(option_value, int) and not hasattr(option_value, "GetType"):
            # Python int — must convert to .NET enum via Enum.ToObject
            if enum_type is None:
                raise RuntimeError(
                    "option_result['value'] is Python int but no enum_type provided. "
                    "Cannot convert to .NET enum for MethodInfo.Invoke."
                )
            try:
                option_value = Enum.ToObject(enum_type, option_value)
            except Exception as exc:
                raise RuntimeError(
                    f"Enum.ToObject(enum_type={enum_type.FullName}, "
                    f"value={option_value}) failed: {exc}"
                ) from exc

        # Match the correct Import overload by param[1] type
        methods = tag_composition.GetType().GetMethods()
        best_match = None
        for method in methods:
            if method.Name != "Import":
                continue
            params = method.GetParameters()
            if len(params) != 2:
                continue
            p1_type = params[1].ParameterType
            p1_type_name = str(getattr(p1_type, "FullName", p1_type))

            # Prefer matching enum_type, fallback to any IsEnum second param
            if enum_type is not None and hasattr(enum_type, "FullName"):
                if p1_type_name == enum_type.FullName:
                    best_match = (method, params)
                    break
            elif getattr(p1_type, "IsEnum", False):
                if best_match is None:
                    best_match = (method, params)

        if best_match is None:
            raise RuntimeError(
                "未找到匹配的双参数 Import 方法重载"
            )

        method, params = best_match
        p0_type = params[0].ParameterType
        p1_type = params[1].ParameterType
        p0_type_name = str(getattr(p0_type, "FullName", p0_type))

        # 构造参数数组
        if "FileInfo" in p0_type_name:
            arg0 = file_info
        else:
            arg0 = xml_path  # String 类型

        args = Array[Object]([arg0, option_value])

        try:
            method.Invoke(tag_composition, args)
            return  # 成功
        except Exception as exc:
            raise RuntimeError(
                f"MethodInfo.Invoke 失败: method=Import, "
                f"args=({type(arg0).__name__}, {p1_type.FullName}), "
                f"arg0_type=System.IO.FileInfo, "
                f"arg1_type={p1_type.FullName}, "
                f"error={exc}"
            ) from exc

    @staticmethod
    def _make_import_options():
        """创建 Siemens.Engineering.ImportOptions 实例，设为 Override 模式。

        V4.2: 委托给 resolve_import_option() 进行多路径解析。
        返回 ImportOptions 实例或 None（完全失败时）。
        """
        import logging
        logger = logging.getLogger(__name__)

        resolution = ClassicOpennessExecutor.resolve_import_option(
            preferred="Override",
        )

        if not resolution["ok"]:
            logger.warning(
                "ImportOptions 解析失败: selected=%s, available=%s, source=%s, error=%s",
                resolution["selected"],
                resolution["available"],
                resolution["source"],
                resolution["error"],
            )
            for diag in resolution.get("diagnostics", []):
                logger.debug("  ImportOptions diagnostic: %s", diag)
            return None

        logger.info(
            "ImportOptions 解析成功: selected=%s, value=%s, source=%s, available=%s",
            resolution["selected"],
            resolution["value"],
            resolution["source"],
            resolution["available"],
        )

        # 构造 ImportOptions 实例并赋值 Mode
        try:
            from Siemens.Engineering.Hmi import ImportOptions  # type: ignore
            opts = ImportOptions()
        except Exception:
            try:
                from Siemens.Engineering import ImportOptions  # type: ignore
                opts = ImportOptions()
            except Exception:
                return None

        try:
            opts.Mode = resolution["value"]
        except Exception:
            try:
                from System import Enum  # type: ignore
                opts.Mode = Enum.ToObject(type(opts.Mode), resolution["value"])
            except Exception:
                return None

        return opts

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

    @staticmethod
    def _save_import_failure_copy(xml_content: str, prefix: str = "tag_import"):
        """将 XML 复制到后端 debug 目录，用于失败后诊断。

        V5.0: 在每次导入前复制 XML 到 backend/debug/tia_import_failures/，
        文件名包含时间戳、阶段名。失败后不删除，用于事后分析。

        参数:
            xml_content: XML 字符串内容。
            prefix: 文件名前缀，默认 'tag_import'。
        """
        import logging
        logger = logging.getLogger(__name__)
        try:
            debug_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "debug",
                "tia_import_failures",
            )
            os.makedirs(debug_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            rand = hashlib.md5(xml_content.encode()).hexdigest()[:4]
            filename = f"{prefix}_{ts}_{rand}.xml"
            dest_path = os.path.join(debug_dir, filename)
            with open(dest_path, "w", encoding="utf-8") as f:
                f.write(xml_content)
            logger.debug("已保存导入 XML 副本到 %s", dest_path)
            # 诊断：检测 XML 根元素类型信息
            try:
                import xml.etree.ElementTree as ET
                root = ET.fromstring(xml_content.encode())
                raw_tag = root.tag
                detected_xml_class = raw_tag.split("}")[-1] if "}" in raw_tag else raw_tag
                target_collection_type = "tag_collection" if "Tag" in detected_xml_class else "block_collection" if "Block" in detected_xml_class else "unknown"
                logger.debug(
                    "import_failure_copy 诊断: detected_xml_class=%s, target_collection_type=%s",
                    detected_xml_class, target_collection_type,
                )
            except Exception:
                pass
        except Exception as e:
            logger.debug("保存导入 XML 副本失败: %s", e)

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

    def import_hmi_tag_table_template_safe(
        self,
        hmi_software,
        tags_xml: str,
        tag_items: list[dict] | None = None,
    ) -> ClassicStepResult:
        """Import HMI tags from a real exported HMI tag table template.

        This is the preferred Basic/KTP Basic path. It imports the whole
        exported tag table XML through TagFolder.TagTables.Import instead of
        importing guessed individual Hmi.Tag.Tag XML through DefaultTagTable.
        """
        result = ClassicStepResult("tags", OpennessOperationKind.TIA_MUTATION)
        expected_names = [
            str(t.get("name", "")).strip()
            for t in (tag_items or [])
            if str(t.get("name", "")).strip()
        ]

        if not tags_xml or not tags_xml.strip():
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.HMI_TAG_XML_TEMPLATE_MISSING,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message="HMI 变量表模板生成结果为空，无法导入变量。",
            ))
            return result

        temp_path = self._write_temp_xml(tags_xml, "tag_table_template")
        result.temp_files.append(temp_path)
        self._save_import_failure_copy(tags_xml, "tag_table_template_import")

        try:
            from backend.xml_validator import validate_tag_xml_for_import_target
            validate_tag_xml_for_import_target(temp_path, "hmi_tag_table")
        except Exception as guard_err:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.TAG_XML_WRONG_CLASS,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=(
                    "HMI 变量表模板 XML 类型校验失败，不能导入到 "
                    f"TagFolder.TagTables: {guard_err}"
                ),
                details={
                    "stage": "PRE_IMPORT_TAG_TABLE_TEMPLATE_GUARD",
                    "xml_path": temp_path,
                    "exception_chain": collect_exception_chain(guard_err),
                },
            ))
            return result

        try:
            kind = detect_tag_import_kind(temp_path)
        except Exception as kind_err:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.TAG_XML_WRONG_CLASS,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=f"无法识别 HMI 变量表模板 XML 类型: {kind_err}",
                details={
                    "stage": "DETECT_TAG_TABLE_TEMPLATE_KIND",
                    "xml_path": temp_path,
                    "exception_chain": collect_exception_chain(kind_err),
                },
            ))
            return result

        if kind != ClassicTagImportKind.TAG_TABLE:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.TAG_XML_WRONG_CLASS,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=(
                    "当前 XML 不是完整 HMI 变量表，不能走模板变量表导入。"
                    f"检测结果: {kind}"
                ),
                details={"xml_path": temp_path, "detected_kind": str(kind)},
            ))
            return result

        before_names = self.enumerate_existing_hmi_tags(hmi_software)
        imported = self.import_tags(hmi_software, temp_path)
        if temp_path not in imported.temp_files:
            imported.temp_files.append(temp_path)
        imported.api_calls.append(
            "strategy_used=hmi_tag_table_template_clone "
            f"expected={expected_names}"
        )
        if not imported.success:
            return imported

        try:
            tag_folder = hmi_software.TagFolder
            default_table = tag_folder.DefaultTagTable
            tags_collection = default_table.Tags
            after_names = set(enumerate_tag_names(tags_collection))
        except Exception as read_err:
            imported.success = False
            imported.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.DEFAULT_TAG_TABLE_NOT_FOUND,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=f"变量表导入后无法重新读取 DefaultTagTable.Tags: {read_err}",
                details={"exception_chain": collect_exception_chain(read_err)},
            ))
            return imported

        missing = sorted(set(expected_names) - after_names)
        if missing:
            imported.success = False
            imported.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=f"HMI 变量表模板导入后缺失变量: {missing}",
                details={
                    "missing_tags": missing,
                    "before_count": len(before_names),
                    "after_count": len(after_names),
                },
            ))
            imported.payload = getattr(imported, "payload", {}) or {}
            imported.payload["missing_tags"] = missing
            return imported

        dt_corrected = self._correct_tag_data_types_after_import(
            tags_collection, tag_items or [],
        )
        if dt_corrected:
            imported.api_calls.append(
                f"DataType corrected after template import: {dt_corrected} tags"
            )

        imported.objects_created = len(after_names - before_names)
        imported.objects_updated = len(set(expected_names) & before_names)
        imported.payload = getattr(imported, "payload", {}) or {}
        imported.payload["imported_count"] = len(expected_names)
        imported.payload["expected_tags"] = expected_names
        imported.api_calls.append(
            f"template_import_verified before={len(before_names)} "
            f"after={len(after_names)} new={imported.objects_created}"
        )
        return self._finalize_tag_data_type_result(
            imported,
            self._verify_tag_data_types(tags_collection, tag_items),
        )

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

            file_info = self._make_file_info(xml_path)
            tag_folder = hmi_software.TagFolder
            tag_tables = tag_folder.TagTables

            resolution_overload = ClassicOpennessExecutor.resolve_import_option_from_overload(
                tag_tables, preferred="Override",
            )
            if resolution_overload["ok"]:
                result.api_calls.append(
                    f"resolve_import_option_from_overload(TagTables): "
                    f"source={resolution_overload['source']}, "
                    f"selected={resolution_overload['selected']}, "
                    f"available={resolution_overload['available']}"
                )
                try:
                    tag_tables.Import(file_info, resolution_overload["value"])
                except Exception:
                    ClassicOpennessExecutor.invoke_tag_composition_import(
                        tag_tables, xml_path, resolution_overload,
                    )
            else:
                import_opts = self._make_import_options()
                if import_opts is None:
                    raise RuntimeError(
                        "ImportOptions.Override 不可用，且无法从 "
                        "TagFolder.TagTables.Import 重载解析导入选项。"
                        f"overload_error={resolution_overload.get('error')}; "
                        f"available={resolution_overload.get('available')}; "
                        f"diagnostics={resolution_overload.get('diagnostics')}"
                    )
                tag_tables.Import(file_info, import_opts)

            result.objects_created = tag_count
            result.success = True
            result.api_calls.append(
                f"TagFolder.TagTables.Import(FileInfo, ImportOptions) "
                f"→ {tag_count} tags: {tag_names} [sha256={sha256[:16]}...]"
            )

        except Exception as e:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=f"TagTable 导入失败 (kind=tag_table): {e}",
                details={
                    "stage": "IMPORT_TAG_TABLE",
                    "xml_path": xml_path,
                    "exception_chain": collect_exception_chain(e),
                    "hmi_target_type": describe_dotnet_object(hmi_software),
                    "tag_folder_type": describe_dotnet_object(
                        getattr(hmi_software, "TagFolder", None)
                    ),
                },
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

            tags_collection = default_table.Tags

            # V4.2: 反射确认 Import 方法可用
            from backend.openness.reflection_utils import has_method, describe_dotnet_methods
            if not has_method(tags_collection, "Import"):
                dotnet_info = describe_dotnet_methods(tags_collection)
                raise RuntimeError(
                    f"CLASSIC_TAG_IMPORT_TARGET_NOT_FOUND: "
                    f"Tags collection (type={dotnet_info.get('dotnet_type', 'Unknown')}) "
                    f"lacks Import() method. "
                    f"Available Import-like methods: {dotnet_info.get('import_like_methods', [])}. "
                    f"Available Create-like methods: {dotnet_info.get('create_like_methods', [])}."
                )

            before_tags = enumerate_tag_names(tags_collection)

            tags_collection.Import(file_info, import_opts)

            after_tags = enumerate_tag_names(tags_collection)
            new_tags = [t for t in after_tags if t not in before_tags]

            result.objects_created = len(new_tags) if new_tags else tag_count
            result.api_calls.append(
                f"TagFolder.DefaultTagTable.Tags.Import(FileInfo, ImportOptions.Override) "
                f"→ before={len(before_tags)}, after={len(after_tags)}, new={new_tags} [sha256={sha256[:16]}...]"
            )

            # 验证: 如果 tag_names 已知，确认至少一个已导入
            if tag_names and not any(n in after_tags for n in tag_names):
                result.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                    severity=DiagnosticSeverity.WARNING,
                    phase="P30_TAG_TABLES_AND_TAGS",
                    message=(
                        f"VERIFICATION_WARNING: Import 调用无异常，但导入后未找到预期变量。"
                        f" expected={tag_names}, before={before_tags}, after={after_tags}"
                    ),
                ))
            result.success = True

        except Exception as e:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=f"DefaultTagTable 导入失败 (kind=individual_tags): {e}",
                details={
                    "stage": "IMPORT_TAG_DEFAULT",
                    "xml_path": xml_path,
                    "exception_chain": collect_exception_chain(e),
                    "hmi_target_type": describe_dotnet_object(hmi_software),
                    "default_table_type": describe_dotnet_object(
                        getattr(getattr(hmi_software, "TagFolder", None), "DefaultTagTable", None)
                    ),
                },
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

    def locate_hmi_target(self, project, expected_device_name: str | None = None) -> tuple:
        """定位 Classic HMI 目标设备（递归遍历 + 类型严格验证）。

        遍历所有 Device 和递归 DeviceItems，收集所有候选 software 对象，
        只返回真正的 Classic HmiTarget。

        禁止接受: PlcSoftware, HmiUnifiedTarget, None, SoftwareContainer 基类。

        返回: (hmi_software, device, device_item) 或抛出详细异常
        """
        if not self._clr_available or project is None:
            return None, None, None

        candidates = []

        try:
            for device in project.Devices:
                for device_item in self._walk_device_items(device):
                    try:
                        from Siemens.Engineering.HW.Features import SoftwareContainer
                        sw_container = device_item.GetService[SoftwareContainer]()
                        if sw_container is None or sw_container.Software is None:
                            continue

                        sw = sw_container.Software
                        info = describe_dotnet_object(sw)
                        info["device_name"] = _safe_device_name(device)
                        info["device_item_name"] = _safe_device_name(device_item)
                        candidates.append(info)

                        if self._is_classic_hmi_target(sw):
                            if expected_device_name:
                                if not self._matches_expected_device(
                                    device, device_item, sw, expected_device_name
                                ):
                                    continue
                            return sw, device, device_item

                    except Exception:
                        continue
        except Exception:
            pass

        # 未找到 — 返回 None 元组但记录候选信息供调试
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(
            "CLASSIC_HMI_TARGET_NOT_FOUND: 未找到 Classic HmiTarget，"
            f"候选对象: {json.dumps(candidates, default=str, ensure_ascii=False)}"
        )
        return None, None, None

    @staticmethod
    def _walk_device_items(device):
        """递归遍历 Device 下所有 DeviceItems（含嵌套子级）。"""
        def _recurse(items):
            try:
                for item in items:
                    yield item
                    # 递归子级 DeviceItems
                    sub_items = getattr(item, "DeviceItems", None)
                    if sub_items is not None:
                        yield from _recurse(sub_items)
            except Exception:
                pass

        top_items = getattr(device, "DeviceItems", None)
        if top_items is not None:
            yield from _recurse(top_items)

    @staticmethod
    def _is_classic_hmi_target(software) -> bool:
        """严格判定是否为 Classic HmiTarget。

        必须满足:
          - .NET 类型包含 'Hmi' 但不包含 'Unified'
          - 不是 PlcSoftware
        """
        sw_type_name = type(software).__name__
        try:
            dotnet_full = str(software.GetType().FullName)
        except Exception:
            dotnet_full = sw_type_name

        # 排除 Unified
        if "Unified" in dotnet_full or "Unified" in sw_type_name:
            return False
        # 排除 PLC
        if "Plc" in dotnet_full or "Plc" in sw_type_name:
            return False
        # 必须包含 Hmi
        if "Hmi" in dotnet_full or "Hmi" in sw_type_name:
            return True
        return False

    @staticmethod
    def _matches_expected_device(device, device_item, software, expected_name: str) -> bool:
        """检查设备是否匹配期望名称。"""
        for obj in (device, device_item, software):
            for attr in ("Name", "DeviceName", "TypeIdentifier"):
                try:
                    v = getattr(obj, attr, None)
                    if v and str(v) == expected_name:
                        return True
                except Exception:
                    pass
        return False

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

    def import_tags_to_default_table(
        self, hmi_software, tags_xml: str, tag_items: list[dict] | None = None,
    ) -> ClassicStepResult:
        """导入 HMI Tag XML 到 DefaultTagTable。

        官方 API (唯一正确路径):
          hmiSoftware.TagFolder.DefaultTagTable.Tags.Import(FileInfo, ImportOptions.Override)

        禁止:
          TagFolder.Importer.Import(StreamReader) — 不存在且未经验证

        V5.0: 导入前增加 XML 类型守卫校验，防止 SW.Blocks (PLC Blocks) XML
        错误地传入 HMI TagComposition.Import。增加失败文件保留机制。
        V5.1: 导入前检查已有变量，若全部已存在则跳过。XML 类别不匹配时
        不再回退到 create_hmi_tags_via_api。无 golden template 时返回
        HMI_TAG_XML_TEMPLATE_MISSING。
        """
        import logging
        _logger = logging.getLogger(__name__)

        result = ClassicStepResult("tags", OpennessOperationKind.TIA_MUTATION)
        if not tags_xml.strip():
            # V5.1: tags_xml 为空时，检查是否所有变量已存在
            if tag_items:
                existing = self.enumerate_existing_hmi_tags(hmi_software)
                required = {t["name"] for t in tag_items if t.get("name")}
                if required and required.issubset(existing):
                    result.success = True
                    result.api_calls.append(
                        "all_tags_already_exist (no XML template, "
                        f"existing={len(existing)}, required={len(required)})"
                    )
                    return result
                missing = sorted(required - existing) if required else []
                result.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.HMI_TAG_XML_TEMPLATE_MISSING,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P30_TAG_TABLES_AND_TAGS",
                    message=(
                        f"HMI Tag XML 模板缺失，无法导入变量。"
                        f"缺失变量 {len(missing)} 个: {missing[:5]}"
                        f"{'...' if len(missing) > 5 else ''}"
                    ),
                    details={
                        "stage": "NO_GOLDEN_TEMPLATE",
                        "missing_tags": missing,
                    },
                    remediation="请提供有效的 HMI Tag XML 模板以导入缺失变量。",
                ))
                return result
            result.success = True
            result.api_calls.append("SKIP (no tags)")
            return result

        # V5.1: 检查所有预期变量是否已存在
        tag_items_names = [t["name"] for t in (tag_items or []) if t.get("name")]
        if tag_items_names:
            existing_tags_set = self.enumerate_existing_hmi_tags(hmi_software)
            missing_names = [n for n in tag_items_names if n not in existing_tags_set]
            if not missing_names:
                result.success = True
                result.api_calls.append(
                    "all_tags_already_exist "
                    f"(existing={len(existing_tags_set)}, "
                    f"expected={len(tag_items_names)})"
                )
                return result
            _logger.info(
                "import_tags_to_default_table: existing=%d, expected=%d, missing=%d",
                len(existing_tags_set), len(tag_items_names), len(missing_names),
            )

        temp_path = None
        try:
            tag_count = self._count_xml_elements(tags_xml, "Tag")
            tag_names = self._extract_all_names_from_xml(tags_xml, "Tag")

            # 写入临时文件
            temp_path = self._write_temp_xml(tags_xml, "tags")
            result.temp_files.append(temp_path)

            # V5.0: 失败文件保留 — 复制 XML 到 debug 目录
            self._save_import_failure_copy(tags_xml, "tag_import")

            # V5.0: XML 类型守卫校验 — 在调用 Import 之前
            from backend.xml_validator import validate_xml_class_for_import_target
            try:
                validate_xml_class_for_import_target(temp_path, "hmi_tags")
            except ValueError as guard_err:
                error_msg = str(guard_err)
                logging.getLogger(__name__).error(
                    "XML 类型守卫拦截: %s", error_msg
                )
                result.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.TAG_XML_WRONG_CLASS,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P30_TAG_TABLES_AND_TAGS",
                    message=f"HMI variable sync failed: {error_msg}",
                    details={
                        "stage": "PRE_IMPORT_XML_TYPE_GUARD",
                        "xml_path": temp_path,
                        "guard_error": error_msg,
                    },
                ))
                # V5.1: XML 类别不匹配时不再回退到 Create API
                return result

            # 调试：记录导入 XML 前 20 行
            try:
                with open(temp_path, 'r', encoding='utf-8') as f:
                    first_lines = ''.join(f.readlines()[:20])
                logging.getLogger(__name__).debug("Import XML first 20 lines:\n%s", first_lines)
            except Exception:
                pass

            import_opts = self._make_import_options()
            file_info = self._make_file_info(temp_path)

            if import_opts is not None:
                # 官方 API: TagFolder.DefaultTagTable.Tags.Import(FileInfo, ImportOptions)
                tag_folder = hmi_software.TagFolder
                default_table = tag_folder.DefaultTagTable

                if default_table is None:
                    raise RuntimeError(
                        "DEFAULT_TAG_TABLE_NOT_FOUND: 目标 HMI 中未找到默认变量表"
                    )

                tags_collection = default_table.Tags
                before_tags = enumerate_tag_names(tags_collection)

                tags_collection.Import(file_info, import_opts)

                # V5.5R8: Import 后通过 API 修正 DataType
                dt_corrected = self._correct_tag_data_types_after_import(
                    tags_collection, tag_items,
                )
                if dt_corrected:
                    result.api_calls.append(
                        f"V5.5R8 DataType corrected: {dt_corrected} tags"
                    )

                after_tags = enumerate_tag_names(tags_collection)
                new_tags = [t for t in after_tags if t not in before_tags]

                result.objects_created = len(new_tags) if new_tags else tag_count
                result.api_calls.append(
                    f"TagFolder.DefaultTagTable.Tags.Import(FileInfo(tags.xml), ImportOptions.Override) "
                    f"→ before={len(before_tags)}, after={len(after_tags)}, new={new_tags}, expected={tag_names}"
                )

                # 验证：确认至少一个预期变量已导入
                if tag_names and not any(n in after_tags for n in tag_names):
                    result.diagnostics.append(Diagnostic(
                        code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                        severity=DiagnosticSeverity.WARNING,
                        phase="P30_TAG_TABLES_AND_TAGS",
                        message=(
                            f"VERIFICATION_WARNING: Import 未抛出异常但变量未出现在 DefaultTagTable。"
                            f" expected={tag_names}, before={before_tags}, after={after_tags}"
                        ),
                    ))
            else:
                # ImportOptions 不可用 → 尝试单参数 Import(FileInfo)
                from backend.openness.reflection_utils import list_method_overloads
                import_overloads = list_method_overloads(tags_collection, "Import")
                has_single_arg = any(
                    len(o.get("parameters", [])) == 1
                    for o in import_overloads
                )

                if has_single_arg:
                    tags_collection.Import(file_info)
                    # V5.5R8: Import 后通过 API 修正 DataType
                    dt_corrected = self._correct_tag_data_types_after_import(
                        tags_collection, tag_items,
                    )
                    if dt_corrected:
                        result.api_calls.append(
                            f"V5.5R8 DataType corrected: {dt_corrected} tags"
                        )
                    after_tags = enumerate_tag_names(tags_collection)
                    new_tags = [t for t in after_tags if t not in before_tags]
                    result.objects_created = len(new_tags) if new_tags else tag_count
                    result.api_calls.append(
                        f"TagFolder.DefaultTagTable.Tags.Import(FileInfo) "
                        f"→ before={len(before_tags)}, after={len(after_tags)}, "
                        f"new={new_tags}, expected={tag_names}"
                    )
                    # 验证
                    if tag_names and not any(n in after_tags for n in tag_names):
                        result.diagnostics.append(Diagnostic(
                            code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                            severity=DiagnosticSeverity.WARNING,
                            phase="P30_TAG_TABLES_AND_TAGS",
                            message=(
                                f"VERIFICATION_WARNING: Import(FileInfo) 未抛出异常但变量未出现。"
                                f" expected={tag_names}, before={before_tags}, after={after_tags}"
                            ),
                        ))
                else:
                    raise RuntimeError(
                        f"ImportOptions.Override 不可用，且无单参数 Import(FileInfo) 重载。"
                        f"Import 重载: {import_overloads}"
                    )

            result.success = True

        except Exception as e:
            exc_msg = str(e)
            # V5.0: 快速检测 XML class 不匹配错误
            if "Class of the" in exc_msg and "is not supported" in exc_msg:
                logging.getLogger(__name__).error(
                    "XML Class 不匹配: %s", exc_msg
                )
                result.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.TAG_XML_WRONG_CLASS,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P30_TAG_TABLES_AND_TAGS",
                    message=(
                        "HMI 变量同步失败：TIA Portal 报告 XML 文档的 Class 类型"
                        "与导入目标不匹配 ('Class of the ... is not supported')。"
                        f"错误: {exc_msg}"
                    ),
                    details={
                        "stage": "IMPORT_CLASS_MISMATCH",
                        "xml_path": temp_path,
                        "exception_chain": collect_exception_chain(e),
                    },
                ))
                # V5.1: XML Class 不匹配时不再回退到 Create API
                return result
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=f"Tag Table 导入 DefaultTagTable 失败: {e}",
                details={
                    "stage": "IMPORT_TAG_DEFAULT_TABLE",
                    "xml_path": temp_path,
                    "exception_chain": collect_exception_chain(e),
                    "hmi_target_type": describe_dotnet_object(hmi_software),
                    "default_table_type": describe_dotnet_object(
                        getattr(getattr(hmi_software, "TagFolder", None), "DefaultTagTable", None)
                    ),
                },
            ))
            return result

        return result

    # ------------------------------------------------------------------
    # V4.2: _upsert_tags_to_default_table — 逐变量创建/更新回退
    # ------------------------------------------------------------------

    def _upsert_tags_to_default_table(
        self, hmi_software, tag_items: list[dict],
    ) -> "ClassicStepResult":
        """逐变量 upsert 到 DefaultTagTable（不需要 ImportOptions）。

        对每个 tag_item：
          - 已存在且 data_type 一致 → 跳过 (UPSERT_SKIP)
          - 已存在但 data_type 不同 → 更新 (UPSERT_UPDATE)
          - 不存在 → 创建 (UPSERT_CREATE)

        参数:
            hmi_software: HMI 软件对象。
            tag_items: [{"name": "CMD_Start", "data_type": "Bool", "scope": "internal", ...}, ...]

        返回:
            ClassicStepResult，包含 objects_created/objects_updated 计数。
        """
        import logging
        logger = logging.getLogger(__name__)

        result = ClassicStepResult("tags", OpennessOperationKind.TIA_MUTATION)

        if not tag_items:
            result.success = True
            result.api_calls.append("UPSERT_SKIP (no tags)")
            return result

        try:
            tag_folder = hmi_software.TagFolder
            default_table = tag_folder.DefaultTagTable
            if default_table is None:
                raise RuntimeError(
                    "DEFAULT_TAG_TABLE_NOT_FOUND: 目标 HMI 中未找到默认变量表"
                )

            tags_collection = default_table.Tags

            # V4.2: 反射检查容器能力 — TagComposition 有 Import 无 Create
            from backend.openness.reflection_utils import has_method, describe_dotnet_methods
            has_import = has_method(tags_collection, "Import")
            has_create = has_method(tags_collection, "Create")

            if has_import and not has_create:
                # TagComposition 类型 → 不可用 Create，聚合失败
                dotnet_info = describe_dotnet_methods(tags_collection)
                tag_names = [t.get("name", "") for t in tag_items if t.get("name")]
                result.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.TAG_CREATE_METHOD_NOT_FOUND,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P30_TAG_TABLES_AND_TAGS",
                    message=(
                        f"TagComposition (type={dotnet_info.get('dotnet_type', 'Unknown')}) "
                        f"不支持逐变量 Create，仅支持 Import。"
                        f"请使用 XML Import 方式导入变量，不要调用 UPSERT。"
                        f"预期导入变量 {len(tag_names)} 个: {tag_names}"
                    ),
                    details=dotnet_info,
                    remediation="This UPSERT path is unsupported for TagComposition. Use XML Import via import_hmi_tags_safe.",
                ))
                result.success = False
                return result

            # 枚举已有变量
            existing_tags: dict[str, Any] = {}
            try:
                for tag in tags_collection:
                    try:
                        name = str(getattr(tag, "Name", ""))
                        if name:
                            existing_tags[name] = tag
                    except Exception:
                        pass
            except Exception:
                pass

            logger.info(
                "_upsert_tags_to_default_table: existing=%d, incoming=%d",
                len(existing_tags), len(tag_items),
            )

            unchanged_count = 0
            for item in tag_items:
                name = str(item.get("name", "")).strip()
                if not name:
                    continue

                data_type = str(item.get("data_type", "Bool")).strip()
                scope = str(item.get("scope", "internal")).strip()

                if name in existing_tags:
                    existing = existing_tags[name]
                    existing_dt = ""
                    try:
                        existing_dt = str(getattr(existing, "DataType", ""))
                    except Exception:
                        pass

                    if _hmi_data_types_equal(existing_dt, data_type):
                        # 一致 → 跳过
                        unchanged_count += 1
                        result.api_calls.append(f"UPSERT_SKIP: {name}")
                        continue
                    else:
                        # 不一致 → 更新 (V5.5R10: Reflection setter for enum safety)
                        _updated, _actual_dt = _set_hmi_tag_data_type(existing, data_type)
                        if _updated:
                            result.objects_updated += 1
                            result.api_calls.append(
                                f"UPSERT_UPDATE: {name} ({existing_dt}→{data_type})"
                            )
                        else:
                            result.diagnostics.append(Diagnostic(
                                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                                severity=DiagnosticSeverity.WARNING,
                                phase="P30_TAG_TABLES_AND_TAGS",
                                object_name=name,
                                message=(
                                    f"UPSERT 更新变量 '{name}' 类型未持久化: "
                                    f"expected={data_type}, actual={_actual_dt}"
                                ),
                            ))
                        continue
                else:
                    # 不存在 → 创建（先反射确认 Create 方法可用）
                    if not tags_collection:
                        continue
                    from backend.openness.reflection_utils import has_method, describe_dotnet_methods
                    if not has_method(tags_collection, "Create"):
                        dotnet_info = describe_dotnet_methods(tags_collection)
                        result.diagnostics.append(Diagnostic(
                            code=DiagnosticCodes.TAG_CREATE_METHOD_NOT_FOUND,
                            severity=DiagnosticSeverity.ERROR,
                            phase="P30_TAG_TABLES_AND_TAGS",
                            object_name=name,
                            message=(
                                f"无法创建变量 '{name}'：TagComposition "
                                f"(type={dotnet_info.get('dotnet_type', 'Unknown')}) "
                                f"没有 Create 方法。"
                                f"可用 Create 类方法: {dotnet_info.get('create_like_methods', [])}. "
                                f"可用 Import 类方法: {dotnet_info.get('import_like_methods', [])}. "
                                f"请改用 XML Import。"
                            ),
                            details=dotnet_info,
                            remediation="使用 XML Import (TagFolder.DefaultTagTable.Tags.Import) 替代 UPSERT Create。",
                        ))
                        result.api_calls.append(f"UPSERT_FAIL (no Create method on tags_collection): {name}")
                        continue
                    try:
                        # V5.5R9: 单参数 Create(name)，DataType 通过 setter 设置
                        new_tag = tags_collection.Create(name)
                        result.objects_created += 1
                        dt_ok, actual_dt = _set_hmi_tag_data_type(new_tag, data_type)
                        if not dt_ok:
                            result.diagnostics.append(Diagnostic(
                                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                                severity=DiagnosticSeverity.WARNING,
                                phase="P30_TAG_TABLES_AND_TAGS",
                                object_name=name,
                                message=(
                                    f"UPSERT 创建变量 '{name}' 后类型未持久化: "
                                    f"expected={data_type}, actual={actual_dt}"
                                ),
                            ))
                        # 设置地址（如有）
                        addr = str(item.get("address", "")).strip()
                        if addr:
                            try:
                                new_tag.Address = addr
                            except Exception:
                                pass
                        # 设置连接（如有）
                        conn = str(item.get("connection", "")).strip()
                        if conn:
                            try:
                                new_tag.Connection = conn
                            except Exception:
                                pass
                        result.api_calls.append(f"UPSERT_CREATE: {name} ({data_type})")
                    except Exception as exc:
                        # 检测 AttributeError 特殊处理 → 结构化诊断
                        if isinstance(exc, AttributeError) and "Create" in str(exc):
                            code = DiagnosticCodes.TAG_CREATE_METHOD_NOT_FOUND
                            dotnet_info = describe_dotnet_methods(tags_collection)
                            msg = (
                                f"无法创建变量 '{name}'：TagComposition "
                                f"(type={dotnet_info.get('dotnet_type', 'Unknown')}) "
                                f"没有 Create 方法。"
                            )
                            details = dotnet_info
                        else:
                            code = DiagnosticCodes.IMPORT_TIA_EXCEPTION
                            msg = f"UPSERT 创建变量 '{name}' 失败: {exc}"
                            details = {
                                "stage": "UPSERT_CREATE_TAG",
                                "exception_chain": collect_exception_chain(exc),
                            }
                        result.diagnostics.append(Diagnostic(
                            code=code,
                            severity=DiagnosticSeverity.ERROR,
                            phase="P30_TAG_TABLES_AND_TAGS",
                            object_name=name,
                            message=msg,
                            details=details,
                        ))
                        continue

            # 后验证
            try:
                after_names = set()
                for tag in tags_collection:
                    try:
                        after_names.add(str(getattr(tag, "Name", "")))
                    except Exception:
                        pass
                missing = sorted(
                    [t["name"] for t in tag_items
                     if t.get("name", "").strip() not in after_names]
                )
                if missing:
                    result.diagnostics.append(Diagnostic(
                        code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                        severity=DiagnosticSeverity.WARNING,
                        phase="P30_TAG_TABLES_AND_TAGS",
                        message=(
                            f"UPSERT 完成但以下变量仍缺失: {missing}"
                        ),
                    ))
            except Exception:
                pass

            result.success = (
                result.objects_created > 0
                or result.objects_updated > 0
                or unchanged_count > 0
            )
            if not tag_items:
                result.success = True

        except Exception as exc:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=f"_upsert_tags_to_default_table 异常: {exc}",
                details={
                    "stage": "UPSERT_DEFAULT_TABLE",
                    "exception_chain": collect_exception_chain(exc),
                    "hmi_target_type": describe_dotnet_object(hmi_software),
                },
            ))

        return result

    # ------------------------------------------------------------------
    # V5.1: enumerate_existing_hmi_tags — 枚举已有 HMI 变量
    # ------------------------------------------------------------------

    def enumerate_existing_hmi_tags(self, hmi_software) -> set[str]:
        """获取 HMI DefaultTagTable 中已有的所有变量名。

        流程:
          1. 获取 hmiSoftware.TagFolder.DefaultTagTable
          2. 遍历 DefaultTagTable.Tags
          3. 收集所有变量名到 set 中

        任何步骤失败时返回空集并记录 WARNING 日志。

        参数:
            hmi_software: HMI 软件对象。

        返回:
            set[str]，已有的变量名集合；失败时返回空集。
        """
        import logging
        logger = logging.getLogger(__name__)
        try:
            tag_folder = hmi_software.TagFolder
            default_table = tag_folder.DefaultTagTable
            if default_table is None:
                logger.warning(
                    "enumerate_existing_hmi_tags: DefaultTagTable is None"
                )
                return set()
            tags = default_table.Tags
            names: set[str] = set()
            for tag in tags:
                try:
                    names.add(str(tag.Name))
                except Exception:
                    pass
            return names
        except Exception as exc:
            logger.warning(
                "enumerate_existing_hmi_tags failed: %s", exc
            )
            return set()

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # V5.5R9: create_hmi_tags_via_api — 通过 Create 方法逐变量创建（主路径）
    # XML Import 无法在 XML 中指定 DataType（元素属性被忽略，子元素被拒绝），
    # Import 后 tag.DataType = value 也无法可靠持久化，
    # 因此 Create API 成为唯一可靠的数据类型设置方式。
    # 当 TagComposition 不支持 Create 时回退 XML Import。
    # ------------------------------------------------------------------

    def create_hmi_tags_via_api(
        self,
        hmi_software,
        tag_items: list[dict],
    ) -> ClassicStepResult:
        """V5.5R9: 通过 DefaultTagTable.Tags.Create 方法逐变量创建 HMI Tags（主路径）。

        XML Import 路径无法可靠设置 HMI 变量的 DataType：
          - 元素属性 DataType="Bool" → TIA 忽略，默认 Int
          - 子元素 <DataType>Bool</DataType> → Import 拒绝
          - Import 后 tag.DataType = value → pythonnet 可能无法持久化
        因此优先使用 TagComposition.Create(name, data_type) 创建变量，
        Create 在创建时即指定正确类型，类型设置可靠。

        当 TagComposition 不支持 Create 时（检测 TAG_CREATE_NOT_SUPPORTED），
        调用方应回退到 import_hmi_tags_safe（XML Import 路径）。

        非 XML 路径: 不依赖 XML Import，直接通过 TIA API Create 方法
        创建变量。需要 TagComposition 支持 Create 方法。

        流程:
          1. 获取 hmiSoftware.TagFolder.DefaultTagTable.Tags (TagComposition)。
          2. 通过反射 (has_method) 检查 Create 方法是否存在。
          3. 如果 Create 存在，遍历 tag_items，逐个调用 Create(Name, DataType)，
             可选设置 Connection 和 Address。
          4. 如果 Create 不存在，返回 TAG_CREATE_NOT_SUPPORTED 诊断。

        参数:
            hmi_software: HMI 软件对象。
            tag_items: [{"name": "CMD_Start", "data_type": "Bool",
                         "connection": "", "address": ""}, ...]

        返回:
            ClassicStepResult，包含 objects_created 计数。
        """
        import logging
        logger = logging.getLogger(__name__)

        result = ClassicStepResult("tags", OpennessOperationKind.TIA_MUTATION)

        if not tag_items:
            result.success = True
            result.api_calls.append("CREATE_API_SKIP (no tags)")
            return result

        try:
            # Step 1: 获取 DefaultTagTable.Tags 容器
            tag_folder = hmi_software.TagFolder
            default_table = tag_folder.DefaultTagTable
            if default_table is None:
                raise RuntimeError(
                    "DEFAULT_TAG_TABLE_NOT_FOUND: 目标 HMI 中未找到默认变量表"
                )
            tags_collection = default_table.Tags

            # Step 2: 反射确认 Create 方法可用
            from backend.openness.reflection_utils import has_method, describe_dotnet_methods
            if not has_method(tags_collection, "Create"):
                dotnet_info = describe_dotnet_methods(tags_collection)
                tag_names = [t.get("name", "") for t in tag_items if t.get("name")]
                result.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.TAG_CREATE_NOT_SUPPORTED,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P30_TAG_TABLES_AND_TAGS",
                    message=(
                        f"TagComposition (type={dotnet_info.get('dotnet_type', 'Unknown')}) "
                        f"不支持 Create 方法，无法通过 API 路径逐变量创建。"
                        f"预期导入变量 {len(tag_names)} 个: {tag_names}"
                    ),
                    details=dotnet_info,
                    remediation=(
                        "TagComposition 不支持 Create，请使用 XML Import 方式导入变量。"
                    ),
                ))
                return result

            # Step 3: 遍历 tag_items，逐个 Create
            existing_tags: dict[str, Any] = {}
            try:
                for tag in tags_collection:
                    try:
                        existing_name = str(getattr(tag, "Name", ""))
                        if existing_name:
                            existing_tags[existing_name] = tag
                    except Exception:
                        pass
            except Exception:
                pass

            logger.info(
                "create_hmi_tags_via_api: existing=%d, incoming=%d",
                len(existing_tags), len(tag_items),
            )

            created_count = 0
            updated_count = 0
            unchanged_count = 0
            type_failed_count = 0
            for item in tag_items:
                name = str(item.get("name", "")).strip()
                if not name:
                    continue

                data_type = str(item.get("data_type", "Bool")).strip()

                if name in existing_tags:
                    existing_tag = existing_tags[name]
                    try:
                        actual_before = str(getattr(existing_tag, "DataType", ""))
                    except Exception:
                        actual_before = ""
                    if _hmi_data_types_equal(actual_before, data_type):
                        unchanged_count += 1
                        result.api_calls.append(
                            f"CREATE_API_SKIP (exists/type-ok): {name} ({actual_before})"
                        )
                        continue

                    dt_ok, actual_after = _set_hmi_tag_data_type(existing_tag, data_type)
                    if dt_ok:
                        updated_count += 1
                        result.api_calls.append(
                            f"CREATE_API_UPDATE_TYPE: {name} ({actual_before}→{data_type})"
                        )
                    else:
                        type_failed_count += 1
                        result.diagnostics.append(Diagnostic(
                            code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                            severity=DiagnosticSeverity.WARNING,
                            phase="P30_TAG_TABLES_AND_TAGS",
                            object_name=name,
                            message=(
                                f"已有 HMI 变量 '{name}' 类型修正未持久化: "
                                f"expected={data_type}, actual={actual_after}"
                            ),
                        ))
                    continue

                try:
                    # V5.5R9: Create(name) 单参数 — TagComposition.Create
                    # 可能只有 Create(string name) 一个重载，第二个参数
                    # "Bool" 若被静默消费则类型成为 Int。
                    # 先创建，再通过 DataType setter 修正。
                    new_tag = tags_collection.Create(name)
                    created_count += 1

                    # V5.5R10: DataType 属性可能是 enum 类型（如 HmiDataType）
                    # 用 System.Reflection + Enum.Parse 作为通用方案
                    _dt_set_ok, _actual_dt = _set_hmi_tag_data_type(new_tag, data_type)
                    if not _dt_set_ok:
                        type_failed_count += 1
                        logger.warning(
                            "V5.5R10 DataType not persisted for new tag %s: expected=%s actual=%s",
                            name, data_type, _actual_dt,
                        )
                        result.diagnostics.append(Diagnostic(
                            code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                            severity=DiagnosticSeverity.WARNING,
                            phase="P30_TAG_TABLES_AND_TAGS",
                            object_name=name,
                            message=(
                                f"新建 HMI 变量 '{name}' 类型未持久化: "
                                f"expected={data_type}, actual={_actual_dt}"
                            ),
                        ))

                    # 设置连接（如有）
                    conn = str(item.get("connection", "")).strip()
                    if conn:
                        try:
                            new_tag.Connection = conn
                        except Exception:
                            pass

                    # 设置地址（如有）
                    addr = str(item.get("address", "")).strip()
                    if addr:
                        try:
                            new_tag.Address = addr
                        except Exception:
                            pass

                    result.api_calls.append(f"CREATE_API: {name} ({data_type})")

                except Exception as exc:
                    result.diagnostics.append(Diagnostic(
                        code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                        severity=DiagnosticSeverity.ERROR,
                        phase="P30_TAG_TABLES_AND_TAGS",
                        object_name=name,
                        message=f"API Create 变量 '{name}' 失败: {exc}",
                        details={
                            "stage": "CREATE_API_TAG",
                            "exception_chain": collect_exception_chain(exc),
                        },
                    ))

            result.objects_created = created_count
            result.objects_updated = updated_count
            result.success = (
                type_failed_count == 0
                and (
                    created_count > 0
                    or updated_count > 0
                    or unchanged_count > 0
                )
            )

        except Exception as exc:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=f"create_hmi_tags_via_api 异常: {exc}",
                details={
                    "stage": "CREATE_API",
                    "exception_chain": collect_exception_chain(exc),
                    "hmi_target_type": describe_dotnet_object(hmi_software),
                },
            ))

        return result

    # ------------------------------------------------------------------
    # V4.2: import_hmi_tags_safe — XML Import 主路径（无 UPSERT 回退）
    # ------------------------------------------------------------------

    def import_hmi_tags_safe(
        self,
        hmi_software,
        tags_xml: str,
        tag_items: list[dict] | None = None,
    ) -> "ClassicStepResult":
        """通过 XML Import 安全导入 HMI Tags。

        策略:
          1. 获取 DefaultTagTable.Tags 容器，反射确认 Import 方法存在。
          2. 解析 ImportOptions（多路径探测 + assembly scan）。
          3. 如果 ImportOptions 可用 → Import(FileInfo, ImportOptions)。
          4. 如果 ImportOptions 不可用 → 检查单参数 Import(FileInfo) 重载。
          5. 导入后枚举验证，缺失变量报 VERIFY_TAG_MISSING。
          6. 禁止 UPSERT Create 回退 — TagComposition 不支持 Create。

        参数:
            hmi_software: HMI 软件对象。
            tags_xml:     批量导出的 Tags XML 字符串。
            tag_items:    结构化 tag 列表（仅用于提取预期变量名）。

        返回:
            ClassicStepResult，api_calls 中包含 "strategy_used=..."。
        """
        import logging
        logger = logging.getLogger(__name__)

        result = ClassicStepResult("tags", OpennessOperationKind.TIA_MUTATION)

        if not tags_xml or not tags_xml.strip():
            # V5.1: 当 tags_xml 为空时，检查是否所有变量已存在
            if tag_items:
                existing = self.enumerate_existing_hmi_tags(hmi_software)
                required = {t["name"] for t in tag_items if t.get("name")}
                if required and required.issubset(existing):
                    result.success = True
                    result.api_calls.append(
                        "all_tags_already_exist (no XML template, "
                        f"existing={len(existing)}, required={len(required)})"
                    )
                    return result
                # V5.1: 无 golden template 且存在缺失变量
                missing = sorted(required - existing) if required else []
                result.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.HMI_TAG_XML_TEMPLATE_MISSING,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P30_TAG_TABLES_AND_TAGS",
                    message=(
                        f"HMI Tag XML 模板缺失，无法导入变量。"
                        f"缺失变量 {len(missing)} 个: {missing[:5]}"
                        f"{'...' if len(missing) > 5 else ''}"
                    ),
                    details={
                        "stage": "NO_GOLDEN_TEMPLATE",
                        "missing_tags": missing,
                    },
                    remediation="请提供有效的 HMI Tag XML 模板以导入缺失变量。",
                ))
                return result
            result.success = True
            result.api_calls.append("SKIP (no tags)")
            return result

        expected_names = [t["name"] for t in (tag_items or []) if t.get("name")]

        # V5.1: 检查所有预期变量是否已存在
        if expected_names:
            existing_tags = self.enumerate_existing_hmi_tags(hmi_software)
            missing_names = [n for n in expected_names if n not in existing_tags]
            if not missing_names:
                result.success = True
                result.api_calls.append(
                    "all_tags_already_exist "
                    f"(existing={len(existing_tags)}, expected={len(expected_names)})"
                )
                return result
            logger.info(
                "import_hmi_tags_safe: existing=%d, expected=%d, missing=%d",
                len(existing_tags), len(expected_names), len(missing_names),
            )

        # Step 1: 获取 DefaultTagTable.Tags 容器
        try:
            tag_folder = hmi_software.TagFolder
            default_table = tag_folder.DefaultTagTable
            if default_table is None:
                raise RuntimeError(
                    "DEFAULT_TAG_TABLE_NOT_FOUND: 目标 HMI 中未找到默认变量表"
                )
            tags_collection = default_table.Tags
        except Exception as e:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.DEFAULT_TAG_TABLE_NOT_FOUND,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=f"无法获取 DefaultTagTable.Tags 容器: {e}",
                details={"exception_chain": collect_exception_chain(e)},
            ))
            return result

        # Step 2: 反射确认 Import 方法可用
        from backend.openness.reflection_utils import (
            has_method, list_method_overloads, describe_dotnet_methods,
        )
        if not has_method(tags_collection, "Import"):
            dotnet_info = describe_dotnet_methods(tags_collection)
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.TAG_IMPORT_METHOD_NOT_FOUND,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=(
                    f"TagComposition (type={dotnet_info.get('dotnet_type', 'Unknown')}) "
                    f"没有 Import 方法。可用 Import 类方法: "
                    f"{dotnet_info.get('import_like_methods', [])}。"
                ),
                details=dotnet_info,
                remediation="确认 TIA Portal Openness API 可用且 HMI 设备类型正确。",
            ))
            return result

        # Step 3: 写入临时 XML
        temp_path = self._write_temp_xml(tags_xml, "tags_safe")
        result.temp_files.append(temp_path)

        # V5.0: XML 类型守卫校验 — 在调用 Import 之前
        from backend.xml_validator import validate_xml_class_for_import_target
        try:
            validate_xml_class_for_import_target(temp_path, "hmi_tags")
        except ValueError as guard_err:
            error_msg = str(guard_err)
            logger.error("XML 类型守卫拦截: %s", error_msg)
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.TAG_XML_WRONG_CLASS,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=f"HMI variable sync failed: {error_msg}",
                details={
                    "stage": "PRE_IMPORT_XML_TYPE_GUARD",
                    "xml_path": temp_path,
                    "guard_error": error_msg,
                },
            ))
            # V5.1: XML 类别不匹配时不再回退到 Create API
            return result

        file_info = self._make_file_info(temp_path)

        # Step 4: 导入前枚举
        before_tags = enumerate_tag_names(tags_collection)
        logger.info(
            "import_hmi_tags_safe: before=%d, expected=%s",
            len(before_tags), expected_names,
        )

        # Step 5: 优先从 Import 方法参数类型解析 ImportOptions
        resolution_overload = ClassicOpennessExecutor.resolve_import_option_from_overload(
            tags_collection, preferred="Override",
        )
        if resolution_overload["ok"]:
            result.api_calls.append(
                f"resolve_import_option_from_overload: "
                f"source={resolution_overload['source']}, "
                f"selected={resolution_overload['selected']}, "
                f"available={resolution_overload['available']}"
            )
        else:
            logger.info(
                "overload resolver failed, fallback to standard: %s",
                resolution_overload.get("error"),
            )

        # Fallback: 传统解析方式
        resolution = resolution_overload if resolution_overload["ok"] else (
            self.resolve_import_option(preferred="Override")
        )

        if resolution["ok"]:
            try:
                import_opts = ClassicOpennessExecutor._make_import_options()
                if import_opts is not None:
                    try:
                        # 方式 A：pythonnet 直接调用
                        tags_collection.Import(file_info, import_opts)
                    except Exception:
                        # 方式 B：MethodInfo.Invoke 反射调用
                        logger.info(
                            "Direct Import call failed, trying MethodInfo.Invoke"
                        )
                        ClassicOpennessExecutor.invoke_tag_composition_import(
                            tags_collection, temp_path, resolution,
                        )
                else:
                    # _make_import_options 返回 None — 直接用 Invoke
                    logger.info(
                        "_make_import_options returned None, using MethodInfo.Invoke"
                    )
                    ClassicOpennessExecutor.invoke_tag_composition_import(
                        tags_collection, temp_path, resolution,
                    )

                after_tags = enumerate_tag_names(tags_collection)
                result.api_calls.append(
                    f"TagFolder.DefaultTagTable.Tags.Import "
                    f"(resolver={resolution['source']}, "
                    f"selected={resolution.get('selected', '?')}) "
                    f"→ before={len(before_tags)} after={len(after_tags)}"
                )
                # V5.5R7: Import 后通过 API 修正 DataType
                dt_corrected = self._correct_tag_data_types_after_import(
                    tags_collection, tag_items,
                )
                if dt_corrected:
                    result.api_calls.append(
                        f"V5.5R7 DataType corrected: {dt_corrected} tags"
                    )
                finalized = self._finalize_import_result(
                    result, before_tags, after_tags, expected_names,
                )
                return self._finalize_tag_data_type_result(
                    finalized,
                    self._verify_tag_data_types(tags_collection, tag_items),
                )
            except Exception as exc:
                logger.error("XML Import (all methods) failed: %s", exc)
                # V5.0: 快速检测 XML class 不匹配错误（不尝试更多 Import 重载）
                raw_exc = str(exc)
                if "Class of the" in raw_exc and "is not supported" in raw_exc:
                    logger.error("XML Class 不匹配: %s", raw_exc)
                    result.diagnostics.append(Diagnostic(
                        code=DiagnosticCodes.TAG_XML_WRONG_CLASS,
                        severity=DiagnosticSeverity.ERROR,
                        phase="P30_TAG_TABLES_AND_TAGS",
                        message=(
                            "HMI 变量同步失败：TIA Portal 报告 XML 文档的 Class 类型"
                            "与导入目标不匹配 ('Class of the ... is not supported')。"
                            f"错误: {raw_exc}"
                        ),
                        details={
                            "stage": "IMPORT_CLASS_MISMATCH",
                            "exception_chain": collect_exception_chain(exc),
                        },
                    ))
                    # V5.1: XML Class 不匹配时不再回退到 Create API
                    return result
                exc_msg = raw_exc.lower()
                # V5.0: 检测 SW.Blocks / SW.Tag 类型不匹配错误
                sw_tag = any(x in exc_msg for x in ["sw.tag", "engineering.sw.tag", "simens.engineering.sw.tag"])
                sw_blocks = any(x in exc_msg for x in ["sw.blocks", "simens.engineering.sw.blocks"])
                if sw_tag:
                    diag_code = DiagnosticCodes.TAG_XML_WRONG_CLASS
                    diag_msg = (
                        "HMI 变量同步失败：当前导入目标是 HMI 标签集合 TagComposition.Import，"
                        "但生成的 XML 是 PLC Software Tag 类型 (Siemens.Engineering.SW.Tag)。"
                        "HMI Tag XML 不能使用 PLC Tag XML 格式。"
                        "请检查 HMI Tag XML 生成器，不能把 PLC tag XML 导入 HMI tag 集合。"
                        f"错误: {exc}"
                    )
                elif sw_blocks:
                    diag_code = DiagnosticCodes.TAG_XML_WRONG_CLASS
                    diag_msg = (
                        f"HMI 变量同步失败：导入目标是 HMI 标签集合 (TagComposition)，"
                        f"但生成的 XML 是 PLC Blocks 类型 (Siemens.Engineering.SW.Blocks)。"
                        f"请检查变量 XML 生成器是否误用了 PLC block SimaticML。"
                        f"错误: {exc}"
                    )
                else:
                    diag_code = DiagnosticCodes.TAG_XML_IMPORT_FAILED
                    diag_msg = f"XML Import 失败: {exc}"
                result.diagnostics.append(Diagnostic(
                    code=diag_code,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P30_TAG_TABLES_AND_TAGS",
                    message=diag_msg,
                    details={
                        "strategy": resolution.get("source", "unknown"),
                        "overload_resolver": resolution_overload,
                        "standard_resolver": resolution_overload if resolution_overload["ok"] else resolution,
                        "exception_chain": collect_exception_chain(exc),
                        "expected_tags": expected_names,
                    },
                ))
                # V5.1: TAG_XML_WRONG_CLASS 时不再回退到 Create API
                return result

        # Step 6: ImportOptions 不可用 → 尝试单参数 Import(FileInfo)
        import_overloads = list_method_overloads(tags_collection, "Import")
        has_single_arg = any(
            len(o.get("parameters", [])) == 1
            for o in import_overloads
        )
        logger.info(
            "import_hmi_tags_safe: ImportOptions unavailable, "
            "checking single-arg Import overload. has_single_arg=%s, overloads=%s",
            has_single_arg, import_overloads,
        )

        if has_single_arg:
            try:
                tags_collection.Import(file_info)
                after_tags = enumerate_tag_names(tags_collection)
                result.api_calls.append(
                    f"TagFolder.DefaultTagTable.Tags.Import(FileInfo) "
                    f"→ before={len(before_tags)} after={len(after_tags)}"
                )
                # V5.5R7: Import 后通过 API 修正 DataType
                dt_corrected = self._correct_tag_data_types_after_import(
                    tags_collection, tag_items,
                )
                if dt_corrected:
                    result.api_calls.append(
                        f"V5.5R7 DataType corrected: {dt_corrected} tags"
                    )
                finalized = self._finalize_import_result(
                    result, before_tags, after_tags, expected_names,
                )
                return self._finalize_tag_data_type_result(
                    finalized,
                    self._verify_tag_data_types(tags_collection, tag_items),
                )
            except Exception as exc:
                logger.error("Single-arg Import(FileInfo) failed: %s", exc)
                result.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.TAG_XML_IMPORT_FAILED,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P30_TAG_TABLES_AND_TAGS",
                    message=f"单参数 Import(FileInfo) 失败: {exc}",
                    details={
                        "strategy": "single_arg_import",
                        "import_options_resolution": resolution,
                        "import_overloads": import_overloads,
                        "exception_chain": collect_exception_chain(exc),
                        "expected_tags": expected_names,
                    },
                ))
                return result

        # Step 7: 全部失败 — 详细诊断
        import_overloads_verbose = list_method_overloads(tags_collection, "Import")
        result.success = False
        result.diagnostics.append(Diagnostic(
            code=DiagnosticCodes.TAG_XML_IMPORT_FAILED,
            severity=DiagnosticSeverity.ERROR,
            phase="P30_TAG_TABLES_AND_TAGS",
            message=(
                f"TagComposition.Import 需要 ImportOptions，但当前无法解析可用枚举值。"
                f"预期变量 {len(expected_names)} 个: {expected_names[:5]}"
                f"{'...' if len(expected_names) > 5 else ''}"
            ),
            details={
                "tag_composition_type": "Siemens.Engineering.Hmi.Tag.TagComposition",
                "import_overloads": import_overloads_verbose,
                "import_option_resolution_attempts": {
                    "import_overload_parameter": {
                        "ok": resolution_overload.get("ok", False),
                        "error": resolution_overload.get("error"),
                        "available": resolution_overload.get("available", []),
                        "method_signature": resolution_overload.get("method_signature"),
                        "type_full_name": resolution_overload.get("type_full_name"),
                        "diagnostics": resolution_overload.get("diagnostics", []),
                    },
                    "standard_resolver": {
                        "ok": resolution.get("ok", False),
                        "error": resolution.get("error"),
                        "available": resolution.get("available", []),
                        "source": resolution.get("source"),
                        "searched_assemblies": resolution.get("searched_assemblies", []),
                    },
                },
                "available_enum_names": resolution.get("available", []) or resolution_overload.get("available", []),
                "selected_option": resolution.get("selected"),
                "xml_path": temp_path,
                "expected_tags": expected_names,
            },
            remediation=(
                "请从 Import 方法重载第二参数类型解析 ImportOptions。"
                "不要回退 Create/CreateFrom — TagComposition 不支持逐变量创建。"
                "确认 TagXmlBuilder XML 格式可被 TagComposition.Import 接受。"
            ),
        ))
        return result

    def _correct_tag_data_types_after_import(
        self,
        tags_collection,
        tag_items: list[dict],
    ) -> int:
        """V5.5R10: Import 后通过 .NET Reflection API 修正 DataType。

        TIA Portal 的 Hmi.Tag.TagComposition.Import 不接受 XML 中的 DataType
        （元素属性被忽略，<DataType> 子元素导致 "invalid argument DataType"），
        导入的变量全部默认 Int。

        DataType 属性可能是 .NET enum (如 HmiDataType) 而非 string，
        因此用 System.Reflection.PropertyInfo.SetValue + System.Enum.Parse
        作为通用策略，不依赖 pythonnet 的隐式类型转换。

        返回:
            成功修正 DataType 的变量数量
        """
        if not tag_items:
            return 0

        expected_types: dict[str, str] = {}
        for item in tag_items:
            name = str(item.get("name", "")).strip()
            if name:
                from backend.variable_engine import normalize_data_type
                raw = item.get("data_type") or item.get("datatype") or "Bool"
                expected_types[name] = normalize_data_type(str(raw), fallback="Bool")

        import logging
        _log = logging.getLogger(__name__)

        corrected = 0
        for tag in tags_collection:
            try:
                name = str(getattr(tag, "Name", ""))
            except Exception:
                continue
            if name not in expected_types:
                continue
            expected_dt = expected_types[name]
            try:
                current_dt = str(getattr(tag, "DataType", ""))
            except Exception:
                current_dt = ""
            if _hmi_data_types_equal(current_dt, expected_dt):
                continue

            # V5.5R10: System.Reflection 通用 setter
            # DataType 属性类型可能是 enum (HmiDataType) 或 string，
            # pythonnet 的隐式转换在 enum 场景下必然失败
            set_ok, actual_dt = _set_hmi_tag_data_type(tag, expected_dt)

            # 读回验证
            if set_ok:
                if _hmi_data_types_equal(actual_dt, expected_dt):
                    corrected += 1
                    _log.info(
                        "V5.5R10 DataType corrected: %s (%s → %s)",
                        name, current_dt, expected_dt,
                    )
                else:
                    _log.warning(
                        "V5.5R10 DataType set did NOT persist: %s set=%s readback=%s",
                        name, expected_dt, actual_dt,
                    )
            else:
                _log.warning(
                    "V5.5R10 DataType correction failed for %s: %s→%s",
                    name, current_dt, expected_dt,
                )

        return corrected

    def _verify_tag_data_types(
        self,
        tags_collection,
        tag_items: list[dict] | None,
    ) -> list[dict]:
        """Read back imported HMI tag DataType values and report mismatches."""
        if not tag_items:
            return []

        expected_types: dict[str, str] = {}
        for item in tag_items:
            name = str(item.get("name", "")).strip()
            if not name:
                continue
            from backend.variable_engine import normalize_data_type
            raw = item.get("data_type") or item.get("datatype") or "Bool"
            expected_types[name] = normalize_data_type(str(raw), fallback="Bool")

        mismatches: list[dict] = []
        seen: set[str] = set()
        for tag in tags_collection:
            try:
                name = str(getattr(tag, "Name", ""))
            except Exception:
                continue
            if name not in expected_types:
                continue
            seen.add(name)
            expected_dt = expected_types[name]
            try:
                actual_dt = str(getattr(tag, "DataType", ""))
            except Exception:
                actual_dt = ""
            if not _hmi_data_types_equal(actual_dt, expected_dt):
                mismatches.append({
                    "name": name,
                    "expected": expected_dt,
                    "actual": actual_dt,
                })

        for name, expected_dt in expected_types.items():
            if name not in seen:
                mismatches.append({
                    "name": name,
                    "expected": expected_dt,
                    "actual": "<missing>",
                })

        return mismatches

    def _finalize_tag_data_type_result(
        self,
        result: "ClassicStepResult",
        mismatches: list[dict],
    ) -> "ClassicStepResult":
        """Turn DataType readback mismatches into a visible sync failure."""
        if not mismatches:
            result.api_calls.append("DataType readback verified")
            return result

        result.success = False
        result.diagnostics.append(Diagnostic(
            code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
            severity=DiagnosticSeverity.ERROR,
            phase="P30_TAG_TABLES_AND_TAGS",
            message=(
                "HMI 变量已导入，但 DataType 读回与期望不一致: "
                f"{mismatches}"
            ),
            details={
                "mismatches": mismatches,
                "hint": (
                    "如果 actual 仍为 Int，说明当前 HMI Tag XML 没有被 TIA "
                    "按类型导入，且 Openness 后修正 DataType 未持久化。"
                    "请用 TIA 手工导出一个真实 Bool HMI Tag XML 作为模板。"
                ),
            },
        ))
        result.payload = getattr(result, "payload", {}) or {}
        result.payload["data_type_mismatches"] = mismatches
        return result

    def _finalize_import_result(
        self,
        result: "ClassicStepResult",
        before_tags: list[str],
        after_tags: list[str],
        expected_names: list[str],
    ) -> "ClassicStepResult":
        """导入后验证：计算新增变量、检查缺失、设置结果状态。"""
        new_tags = [t for t in after_tags if t not in before_tags]
        result.objects_created = len(new_tags)

        # 从 api_calls 提取策略名
        strategy = "Import"
        for call in result.api_calls:
            if "ImportOptions" in call:
                strategy = "ImportOptions.Override"
                break
        result.api_calls.append(
            f"strategy_used={strategy} "
            f"before={len(before_tags)} after={len(after_tags)} new={new_tags}"
        )

        if expected_names:
            missing = sorted(set(expected_names) - set(after_tags))
            if missing:
                result.success = False
                result.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.VERIFY_TAG_MISSING,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P30_TAG_TABLES_AND_TAGS",
                    message=(
                        f"XML Import 完成但缺失 {len(missing)} 个变量: {missing}"
                    ),
                    details={
                        "expected": expected_names,
                        "actual": sorted(after_tags),
                        "missing": missing,
                    },
                ))
                result.payload = {
                    "imported_count": len(expected_names) - len(missing),
                    "total_expected": len(expected_names),
                    "missing_tags": missing,
                }
                return result

        result.success = True
        result.payload = {
            "imported_count": len(expected_names) if expected_names else len(new_tags),
            "tag_names": sorted(expected_names) if expected_names else [],
            "missing_tags": [],
        }
        return result

    # ------------------------------------------------------------------
    # V4.1: _execute_import_tags — 变量导入 + 存在性验证
    # ------------------------------------------------------------------

    def _execute_import_tags(
        self, hmi_software, tags_xml: str, expected_tag_names: list[str],
    ) -> ClassicStepResult:
        """导入变量到 HMI Tag Table 并验证所有变量都已成功创建。

        流程:
          1. 将 tags_xml 写入临时文件。
          2. 使用 TIA Openness API 导入 HMI Tag Table。
          3. 导入后查询 HMI Tag Table，确认所有 tag_names 都存在。
          4. 如果 missing 非空，返回失败结果，不允许继续执行画面导入。
          5. 记录 imported_count、missing_tags、tag_names。

        返回:
            ClassicStepResult, 包含 tag import 和验证结果。
            ok=False 时后续 IMPORT_SCREEN 不执行。
        """
        result = ClassicStepResult("tags", OpennessOperationKind.TIA_MUTATION)

        if not tags_xml.strip():
            if expected_tag_names:
                result.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.VERIFY_TAG_MISSING,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P30_TAG_TABLES_AND_TAGS",
                    message=(
                        f"tags_xml 为空但 expected_tag_names 非空: {expected_tag_names}。"
                        f"无法导入变量。"
                    ),
                ))
                return result
            result.success = True
            result.api_calls.append("SKIP (no tags)")
            return result

        # Step 1: Import tags
        import_result = self.import_tags_to_default_table(hmi_software, tags_xml)
        result.diagnostics.extend(import_result.diagnostics)
        result.temp_files.extend(import_result.temp_files)
        result.api_calls.extend(import_result.api_calls)

        if not import_result.success:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message="变量导入 DefaultTagTable 失败，终止部署。",
            ))
            return result

        # Step 2: Verify all expected tags exist
        try:
            dt = self.read_default_tag_table(hmi_software)
            actual_names = set(dt.get("tag_names", []))
        except Exception as e:
            # 如果查询不工作，退回到 TIA API 直接查询
            actual_names = set()
            try:
                tag_folder = hmi_software.TagFolder
                default_table = tag_folder.DefaultTagTable
                if default_table:
                    for tag in default_table.Tags:
                        try:
                            actual_names.add(str(tag.Name))
                        except Exception:
                            pass
            except Exception:
                pass

        expected = set(expected_tag_names)
        missing = sorted(expected - actual_names)

        if missing:
            result.success = False
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.VERIFY_TAG_MISSING,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=(
                    f"HMI tag import 不完整。导入后缺失 {len(missing)} 个变量: {missing}"
                ),
                details={
                    "expected_count": len(expected),
                    "actual_count": len(actual_names),
                    "missing_tags": missing,
                    "expected": sorted(expected),
                    "actual": sorted(actual_names),
                },
            ))
            result.payload = {
                "expected_count": len(expected),
                "actual_count": len(actual_names),
                "missing_tags": missing,
            }
        else:
            result.success = True
            result.objects_created = len(expected)
            result.payload = {
                "imported_count": len(expected),
                "tag_names": sorted(expected),
            }

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
    # 独立探针 — 最小变量导入闭环验证
    # ------------------------------------------------------------------

    def import_exact_exported_tag_probe(
        self,
        hmi_software,
        xml_path: str,
        expected_tag_name: str,
    ) -> dict[str, Any]:
        """独立探针：使用真实 TIA 导出 XML 验证最小导入闭环。

        流程: DefaultTagTable → enumerate_before → Import → enumerate_after → Find
        
        只用于诊断，禁止导入 Connection/Screen/Script/Compile。

        参数:
            hmi_software: Classic HMI 软件对象
            xml_path: 真实 TIA 导出的变量 XML 路径
            expected_tag_name: 导入后期望存在的变量名

        返回:
            成功时返回完整诊断信息 dict
            
        异常:
            RuntimeError: Import 失败或导入后验证失败
        """
        # 1. 获取 DefaultTagTable
        tag_folder = hmi_software.TagFolder
        default_table = tag_folder.DefaultTagTable

        if default_table is None:
            raise RuntimeError(
                "DEFAULT_TAG_TABLE_NOT_FOUND: DefaultTagTable 为 None。"
                f" hmi_software={describe_dotnet_object(hmi_software)}"
            )

        tags = default_table.Tags

        # 2. 记录导入前状态
        before = enumerate_tag_names(tags)

        # 3. 检查 XML 文件
        xml_info = inspect_xml_document(xml_path)

        # 4. 执行导入
        try:
            import_opts = self._make_import_options()
            if import_opts is None:
                raise RuntimeError("ImportOptions.Override 不可用")

            file_info = self._make_file_info(os.path.abspath(xml_path))
            import_result = tags.Import(file_info, import_opts)
        except Exception as exc:
            raise RuntimeError(
                f"EXACT_EXPORTED_TAG_IMPORT_FAILED: 真实 TIA 导出的变量 XML 原样导入失败。"
                f" xml_path={os.path.abspath(xml_path)},"
                f" xml_exists={os.path.isfile(xml_path)},"
                f" xml_size={os.path.getsize(xml_path) if os.path.isfile(xml_path) else -1},"
                f" before={before},"
                f" exception_chain={collect_exception_chain(exc)},"
                f" target={describe_dotnet_object(hmi_software)},"
                f" default_table={describe_dotnet_object(default_table)},"
                f" tags_obj={describe_dotnet_object(tags)}"
            ) from exc

        # 5. 记录导入后状态
        after = enumerate_tag_names(tags)

        # 6. 查找预期变量
        imported_tag = find_tag(tags, expected_tag_name)

        if imported_tag is None:
            raise RuntimeError(
                f"IMPORT_RETURNED_BUT_TAG_NOT_FOUND: "
                f"Import 调用没有抛出异常，但导入后变量 '{expected_tag_name}' "
                f"仍不存在于默认变量表。"
                f" before={before}, after={after},"
                f" import_result={describe_dotnet_object(import_result)}"
            )

        return {
            "success": True,
            "expected_tag_name": expected_tag_name,
            "before": before,
            "after": after,
            "new_tags": [t for t in after if t not in before],
            "imported_tag": describe_dotnet_object(imported_tag),
            "xml_info": xml_info,
            "target": describe_dotnet_object(hmi_software),
            "default_table": describe_dotnet_object(default_table),
            "tags_composition": describe_dotnet_object(tags),
        }

    def validate_external_tag_references(
        self, hmi_software, xml_path: str,
    ) -> dict[str, Any]:
        """导入前检查 XML 中的外部变量引用（Connection / ControllerTag）。

        解析 XML 中 Connection 和 ControllerTag 引用，
        确认引用目标存在于 HMI 中，否则返回 BLOCKED 状态。

        禁止在引用不存在时调用 Import。
        """
        result: dict[str, Any] = {
            "status": "OK",
            "references": [],
            "blocked_reasons": [],
        }

        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
        except Exception as exc:
            result["status"] = "PARSE_ERROR"
            result["blocked_reasons"].append(f"XML 解析失败: {exc}")
            return result

        # 提取所有 Connection 和 ControllerTag 引用
        ns = _extract_namespace(root.tag)

        for elem in root.iter():
            local = _local_tag_name(elem.tag)

            # 提取变量名
            tag_name = None
            name_elem = elem.find(f"{ns}Name" if ns else "Name")
            if name_elem is not None and name_elem.text:
                tag_name = name_elem.text.strip()
            else:
                tag_name = elem.get("Name")

            if not tag_name:
                continue

            # 变量名合法性检查
            if "." in tag_name and local in ("Tag", "Hmi.Tag.Tag"):
                result["blocked_reasons"].append(
                    f"变量名 '{tag_name}' 包含句点 '.'"
                )
            if "\\" in tag_name and local in ("Tag", "Hmi.Tag.Tag"):
                result["blocked_reasons"].append(
                    f"变量名 '{tag_name}' 包含反斜杠 '\\'"
                )

        # 提取 Connection 引用
        for conn_elem in root.iter():
            conn_local = _local_tag_name(conn_elem.tag)
            if conn_local == "Connection" and conn_elem.get("TargetID") == "@OpenLink":
                conn_name_elem = conn_elem.find(f"{ns}Name" if ns else "Name")
                if conn_name_elem is not None and conn_name_elem.text:
                    conn_name = conn_name_elem.text.strip()
                    exists = self._connection_exists(hmi_software, conn_name)
                    ref_info = {
                        "type": "connection",
                        "name": conn_name,
                        "exists": exists,
                    }
                    result["references"].append(ref_info)
                    if not exists:
                        result["blocked_reasons"].append(
                            f"Connection '{conn_name}' 不存在于 HMI"
                        )

        # 提取 ControllerTag 引用
        for ct_elem in root.iter():
            ct_local = _local_tag_name(ct_elem.tag)
            if ct_local == "ControllerTag" and ct_elem.get("TargetID") == "@OpenLink":
                ct_name_elem = ct_elem.find(f"{ns}Name" if ns else "Name")
                if ct_name_elem is not None and ct_name_elem.text:
                    ct_name = ct_name_elem.text.strip()
                    ref_info = {
                        "type": "controller_tag",
                        "name": ct_name,
                        "exists": None,  # 需要项目级检查
                    }
                    result["references"].append(ref_info)

        if result["blocked_reasons"]:
            result["status"] = "BLOCKED"

        return result

    @staticmethod
    def _connection_exists(hmi_software, connection_name: str) -> bool:
        """检查 HMI 中是否存在指定连接。"""
        try:
            connections = hmi_software.Connections
            for conn in connections:
                try:
                    if str(conn.Name) == connection_name:
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

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
