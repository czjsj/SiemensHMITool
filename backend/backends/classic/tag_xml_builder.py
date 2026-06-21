# -*- coding: utf-8 -*-
"""Classic XML Tag/Table XML Builder — 生成 Tag XML。

基于真实 Basic 单变量导出文件格式生成变量表和变量。
V3.2: 增强为真实 Basic 导出格式，支持 DefaultTagTable 导入。

注意: 本模块生成的 <SW.Tag> 是 Siemens.Engineering.SW.Tag (PLC Software Tag 类型)，
不是 HMI Tag 类型。TIA Portal 的 Hmi.Tag.TagComposition.Import 会拒绝 SW.Tag XML。
当 output_kind="hmi_tags" 时，方法会抛出 NotImplementedError。

正确的 HMI Tag XML 格式需要从 TIA Portal 中手动导出一个真实的 HMI Tag 来获取
（即在 TIA Portal 中右键 HMI tag table -> Export，然后分析导出的 XML 结构）。
在此之前，HMI tag 创建应使用 API 方式 (TagComposition.Create) 而非 XML 导入。
"""
from __future__ import annotations
import copy
import io
import os
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from backend.domain.ir_v2 import TagSpec
from backend.domain.enums import TagScope
import logging
logger = logging.getLogger(__name__)


class TagXmlBuilder:
    """Tag XML 生成器。

    生成符合 TIA Portal 格式的 PLC Tag Table 和 Tag XML。
    基于目标版本真实 Basic 导出 fragment。

    注意: 本类生成的 <SW.Tag> 是 PLC Software Tag 类型，不是 HMI Tag 类型。
    HMI tag XML 格式尚未确定（需要从 TIA Portal 导出真实 HMI Tag 来逆向），
    因此 output_kind="hmi_tags" 会抛出 NotImplementedError。
    HMI tag 创建应使用 TIA Portal Openness API (TagComposition.Create)。
    """

    # 支持的数据类型
    SUPPORTED_DATA_TYPES = {"Bool", "Int", "DInt", "Real", "Word", "String", "WString"}

    def __init__(self):
        self._ns = "http://www.siemens.com/automation/SimaticML"

    # ------------------------------------------------------------------
    # 单变量导出 XML — 真实 Basic 格式
    # ------------------------------------------------------------------

    def build_single_tag_export_xml(
        self, tag: TagSpec, output_kind: str = "hmi_tags",
    ) -> str:
        """为单个变量生成真实 Basic 导出 XML。

        根对象为正式 PLC Tag，可直接导入 PLC DefaultTagTable。

        参数:
            tag: 变量规格
            output_kind: 'hmi_tags' (默认) — 当前不支持，抛出 NotImplementedError；
                         'plc_blocks' 生成 PLC Blocks 包裹格式用于兼容旧场景。

        'plc_blocks' 格式:
          <Document>
            <Engineering version="V16"/>
            <SW.Blocks>
              <SW.Tag>...</SW.Tag>
            </SW.Blocks>
          </Document>
        """
        # 注意: <SW.Tag> 是 Siemens.Engineering.SW.Tag (PLC Software Tag 类型)。
        # TIA Portal 的 Hmi.Tag.TagComposition.Import 会拒绝此格式。
        # 正确的 HMI Tag XML 格式需要从 TIA Portal 中手动导出真实 HMI Tag 来获取。
        # 在获得正确格式之前，HMI tag 创建应使用 API (TagComposition.Create)。
        if output_kind == "hmi_tags":
            raise NotImplementedError(
                "HMI Tag XML format not yet known. Use API-based tag creation "
                "(TagComposition.Create) instead of XML import. "
                "Cannot generate SW.Tag for HMI tag import - "
                "SW.Tag is Siemens.Engineering.SW.Tag (PLC Software Tag type), "
                "rejected by Hmi.Tag.TagComposition.Import."
            )

        doc_id = str(uuid.uuid4()).replace("-", "")[:8]
        tag_id = str(uuid.uuid4()).replace("-", "")[:8]

        lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            f'<Document ID="{doc_id}" xmlns="{self._ns}">',
            '  <Engineering version="V16"/>',
        ]

        if output_kind == "plc_blocks":
            blocks_id = str(uuid.uuid4()).replace("-", "")[:8]
            lines.append(f'  <SW.Blocks ID="{blocks_id}">')

        tag_indent = "    "

        lines.append(f'{tag_indent}<SW.Tag ID="{tag_id}">')
        lines.append(f'  {tag_indent}<AttributeList>')
        lines.append(f'    {tag_indent}<Name>{xml_escape(tag.name)}</Name>')
        lines.append(f'    {tag_indent}<DataType>{xml_escape(tag.data_type)}</DataType>')

        if tag.scope == TagScope.EXTERNAL:
            if tag.connection:
                lines.append(f'    {tag_indent}<Connection>{xml_escape(tag.connection)}</Connection>')
            if tag.address:
                lines.append(f'    {tag_indent}<Address>{xml_escape(tag.address)}</Address>')
            if tag.controller_tag:
                lines.append(f'    {tag_indent}<ControllerTag>{xml_escape(tag.controller_tag)}</ControllerTag>')
            if tag.acquisition_cycle:
                lines.append(f'    {tag_indent}<AcquisitionCycle>{xml_escape(tag.acquisition_cycle)}</AcquisitionCycle>')
        else:
            lines.append(f'    {tag_indent}<Connection></Connection>')

        lines.append(f'  {tag_indent}</AttributeList>')

        if tag.initial_value is not None:
            lines.append(f'  {tag_indent}<StartValue>{xml_escape(str(tag.initial_value))}</StartValue>')

        lines.append(f'{tag_indent}</SW.Tag>')

        if output_kind == "plc_blocks":
            lines.append('  </SW.Blocks>')

        lines.append('</Document>')

        return "\n".join(lines)

    def build_tags_batch_export_xml(
        self, tags: list[TagSpec], table_name: str = "DefaultTagTable",
        output_kind: str = "hmi_tags",
    ) -> str:
        """为多个变量生成批量导出 XML。

        参数:
            tags: 变量规格列表
            table_name: 表名（用于旧版兼容）
            output_kind: 'hmi_tags' (默认) — 当前不支持，抛出 NotImplementedError；
                         'plc_blocks' 生成 PLC Blocks 包裹格式用于兼容旧场景。

        'plc_blocks' 格式:
          <Document>
            <Engineering version="V16"/>
            <SW.Blocks>
              <SW.Tag>...</SW.Tag>
              ...
            </SW.Blocks>
          </Document>
        """
        # 注意: <SW.Tag> 是 Siemens.Engineering.SW.Tag (PLC Software Tag 类型)。
        # TIA Portal 的 Hmi.Tag.TagComposition.Import 会拒绝此格式。
        # 正确的 HMI Tag XML 格式需要从 TIA Portal 中手动导出真实 HMI Tag 来获取。
        # 在获得正确格式之前，HMI tag 创建应使用 API (TagComposition.Create)。
        if output_kind == "hmi_tags":
            raise NotImplementedError(
                "HMI Tag XML format not yet known. Use API-based tag creation "
                "(TagComposition.Create) instead of XML import. "
                "Cannot generate SW.Tag for HMI tag import - "
                "SW.Tag is Siemens.Engineering.SW.Tag (PLC Software Tag type), "
                "rejected by Hmi.Tag.TagComposition.Import."
            )

        doc_id = str(uuid.uuid4()).replace("-", "")[:8]

        lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            f'<Document ID="{doc_id}" xmlns="{self._ns}">',
            '  <Engineering version="V16"/>',
        ]

        if output_kind == "plc_blocks":
            blocks_id = str(uuid.uuid4()).replace("-", "")[:8]
            lines.append(f'  <SW.Blocks ID="{blocks_id}">')

        for tag in tags:
            tag_id = str(uuid.uuid4()).replace("-", "")[:8]
            tag_indent = "    "
            lines.append(f'{tag_indent}<SW.Tag ID="{tag_id}">')
            lines.append(f'  {tag_indent}<AttributeList>')
            lines.append(f'    {tag_indent}<Name>{xml_escape(tag.name)}</Name>')
            lines.append(f'    {tag_indent}<DataType>{xml_escape(tag.data_type)}</DataType>')
            if tag.scope == TagScope.EXTERNAL:
                if tag.connection:
                    lines.append(f'    {tag_indent}<Connection>{xml_escape(tag.connection)}</Connection>')
                if tag.address:
                    lines.append(f'    {tag_indent}<Address>{xml_escape(tag.address)}</Address>')
                if tag.controller_tag:
                    lines.append(f'    {tag_indent}<ControllerTag>{xml_escape(tag.controller_tag)}</ControllerTag>')
                if tag.acquisition_cycle:
                    lines.append(f'    {tag_indent}<AcquisitionCycle>{xml_escape(tag.acquisition_cycle)}</AcquisitionCycle>')
            else:
                lines.append(f'    {tag_indent}<Connection></Connection>')
            lines.append(f'  {tag_indent}</AttributeList>')
            if tag.initial_value is not None:
                lines.append(f'  {tag_indent}<StartValue>{xml_escape(str(tag.initial_value))}</StartValue>')
            lines.append(f'{tag_indent}</SW.Tag>')

        if output_kind == "plc_blocks":
            lines.append('  </SW.Blocks>')

        lines.append('</Document>')

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 文本列表 XML 生成 (SymbolicIOField 专用)
    # ------------------------------------------------------------------

    def build_text_list_xml(
        self,
        list_name: str,
        entries: list[tuple[int, str]],
        languages: list[str] | None = None,
    ) -> str:
        """为 SymbolicIOField 生成文本列表 XML。

        参数:
            list_name: 文本列表名称
            entries: [(value, text), ...] 如 [(0, "停止"), (1, "手动"), (2, "自动")]
            languages: 语言列表，默认 ["zh-CN"]

        格式基于 TIA Portal TextList 导出:
          <Document>
            <SW.Blocks>
              <SW.TextList>
                <AttributeList><Name>xxx</Name></AttributeList>
                <ObjectList>
                  <SW.TextListEntry>...</SW.TextListEntry>
                </ObjectList>
              </SW.TextList>
            </SW.Blocks>
          </Document>
        """
        langs = languages or ["zh-CN"]
        doc_id = str(uuid.uuid4()).replace("-", "")[:8]
        blocks_id = str(uuid.uuid4()).replace("-", "")[:8]
        sid = str(uuid.uuid4()).replace("-", "")[:8]

        lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            f'<Document ID="{doc_id}" xmlns="{self._ns}">',
            '  <Engineering version="V16"/>',
            f'  <SW.Blocks ID="{blocks_id}">',
            f'    <SW.TextList ID="{sid}">',
            '      <AttributeList>',
            f'        <Name>{xml_escape(list_name)}</Name>',
            '      </AttributeList>',
            '      <ObjectList>',
        ]

        for value, text in entries:
            entry_id = str(uuid.uuid4()).replace("-", "")[:8]
            lines.append(f'        <SW.TextListEntry ID="{entry_id}">')
            lines.append('          <AttributeList>')
            lines.append(f'            <Value>{value}</Value>')
            for lang in langs:
                lines.append(f'            <Text Language="{xml_escape(lang)}">{xml_escape(text)}</Text>')
            lines.append('          </AttributeList>')
            lines.append('        </SW.TextListEntry>')

        lines.extend([
            '      </ObjectList>',
            '    </SW.TextList>',
            '  </SW.Blocks>',
            '</Document>',
        ])

        return "\n".join(lines)

    @staticmethod
    def make_default_mode_text_list() -> tuple[str, list[tuple[int, str]]]:
        """为模式选择 SIO 创建默认文本列表。

        返回: (list_name, entries)
        """
        return "ModeTextList", [
            (0, "停止"),
            (1, "手动"),
            (2, "自动"),
        ]

    # ------------------------------------------------------------------
    # 旧版兼容方法 (V2.x)
    # ------------------------------------------------------------------

    def build_tag_table(self, table_name: str) -> str:
        sid = str(uuid.uuid4())
        return (
            f'<SW.Blocks>'
            f'<SW.TagTable ID="{sid}" Name="{xml_escape(table_name)}">'
            f'</SW.TagTable>'
            f'</SW.Blocks>'
        )

    def build_internal_tag(self, tag: TagSpec) -> str:
        sid = str(uuid.uuid4())
        tag_xml = f'<SW.Tag ID="{sid}" Name="{xml_escape(tag.name)}" DataType="{xml_escape(tag.data_type)}">'
        tag_xml += '<AttributeList>'
        tag_xml += f'<Name>{xml_escape(tag.name)}</Name>'
        tag_xml += f'<DataType>{xml_escape(tag.data_type)}</DataType>'
        tag_xml += '<Connection></Connection>'
        tag_xml += '</AttributeList>'
        if tag.initial_value is not None:
            tag_xml += f'<StartValue>{xml_escape(str(tag.initial_value))}</StartValue>'
        tag_xml += '</SW.Tag>'
        return tag_xml

    def build_external_tag(self, tag: TagSpec) -> str:
        sid = str(uuid.uuid4())
        tag_xml = f'<SW.Tag ID="{sid}" Name="{xml_escape(tag.name)}" DataType="{xml_escape(tag.data_type)}">'
        tag_xml += '<AttributeList>'
        tag_xml += f'<Name>{xml_escape(tag.name)}</Name>'
        tag_xml += f'<DataType>{xml_escape(tag.data_type)}</DataType>'
        if tag.connection:
            tag_xml += f'<Connection>{xml_escape(tag.connection)}</Connection>'
        if tag.controller_tag:
            tag_xml += f'<ControllerTag>{xml_escape(tag.controller_tag)}</ControllerTag>'
        elif tag.address:
            tag_xml += f'<Address>{xml_escape(tag.address)}</Address>'
        if tag.acquisition_cycle:
            tag_xml += f'<AcquisitionCycle>{xml_escape(tag.acquisition_cycle)}</AcquisitionCycle>'
        tag_xml += '</AttributeList>'
        if tag.initial_value is not None:
            tag_xml += f'<StartValue>{xml_escape(str(tag.initial_value))}</StartValue>'
        tag_xml += '</SW.Tag>'
        return tag_xml

    def build_tags_xml(self, tags: list[TagSpec], table_name: str = "AI_Generated") -> str:
        """为所有变量生成完整 Tags XML 块。（旧版兼容）"""
        parts = [f'<Tags Table="{xml_escape(table_name)}">']
        for tag in tags:
            if tag.scope.value == "external":
                parts.append(self.build_external_tag(tag))
            else:
                parts.append(self.build_internal_tag(tag))
        parts.append('</Tags>')
        return "\n".join(parts)


class HmiTagXmlBuilder:
    """HMI Tag XML 生成器。

    生成符合 TIA Portal 格式的 HMI Tag XML，用于 Hmi.Tag.TagComposition.Import。
    XML 根元素为 <Engineering>，内部包含 <Hmi.Tag.Tag> 元素。

    与 TagXmlBuilder（生成 PLC SW.Tag）不同，本类生成的是 HMI 侧变量 XML，
    可被 TIA Portal Openness 的 Hmi.Tag.TagComposition.Import 正确接收。
    """

    def __init__(self):
        self._golden_template_dir = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..", "..", "references", "golden_hmi_tags")
        )
        self._golden_template_path = os.path.join(self._golden_template_dir, "individual_tag.xml")

    def build_individual_tag_xml(
        self,
        tag_name: str,
        data_type: str,
        address: str = "",
        connection: str = "",
        comment: str = "",
        default_tag_table: str = "DefaultTagTable",
    ) -> str:
        """为单个 HMI 变量生成 XML。

        生成的 XML 结构:
          <Engineering version="V16" ...>
            <Hmi.Tag.Tag ID="1" CompositionName="Tags">
              <AttributeList>
                <Name>...</Name>
                <DataType>Bool</DataType>
                ...
              </AttributeList>
            </Hmi.Tag.Tag>
          </Engineering>

        注意: DataType 仅作为 <AttributeList> 内的子元素存在，
        不作为 <Hmi.Tag.Tag> 的元素属性。两者同时存在会导致 TIA Portal
        Import 抛出 "The type of the argument 'DataType' (System.String) is invalid"。

        注意: <Address> 元素在 Hmi.Tag.Tag 的 AttributeList 中不被 TIA Portal 支持，
        应通过 <Connection> 关联 PLC 连接来间接绑定地址。

        参数:
            tag_name: 变量名称
            data_type: 数据类型 (Bool, Int, DInt, Real, String 等)
            address: PLC 地址 (如 "%DB1.DBX0.0")
            connection: 关联的连接名称
            comment: 变量注释
            default_tag_table: 所属变量表名，默认 "DefaultTagTable"
        """
        tag_id = str(uuid.uuid4()).replace("-", "")[:8]

        lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            '<Engineering version="V16" xmlns="http://www.siemens.com/automation/HmiTagML">',
            f'  <Hmi.Tag.Tag ID="{tag_id}" CompositionName="Tags">',
            "    <AttributeList>",
            f"      <Name>{xml_escape(tag_name)}</Name>",
        ]

        # DataType is intentionally not written here. On Basic/KTP Basic
        # panels, TIA Openness rejects Hmi.Tag.Tag XML containing
        # <DataType>Bool</DataType> with:
        # "The type of the argument 'DataType' (System.String) is invalid".
        # The type must be corrected after import via the Openness API.

        if connection:
            lines.append(f"      <Connection>{xml_escape(connection)}</Connection>")

        if comment:
            lines.append(f"      <Comment>{xml_escape(comment)}</Comment>")

        lines.extend([
            "    </AttributeList>",
            "  </Hmi.Tag.Tag>",
            "</Engineering>",
        ])

        return "\n".join(lines)

    def build_batch_tags_xml(self, tag_items: list[dict]) -> str:
        """为多个 HMI 变量生成批量 XML。

        所有变量的 <Hmi.Tag.Tag> 元素包含在同一个 <Engineering> 根元素中，
        每个元素拥有唯一 ID。

        参数:
            tag_items: 变量字典列表，每个字典包含以下键:
                - name (str): 变量名称 (必须)
                - data_type (str): 数据类型 (必须)
                - address (str, 可选): PLC 地址
                - connection (str, 可选): 关联连接名
                - comment (str, 可选): 注释
                - default_tag_table (str, 可选): 变量表名，默认 "DefaultTagTable"

        返回:
            包含所有变量的完整 XML 字符串
        """
        lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            '<Engineering version="V16" xmlns="http://www.siemens.com/automation/HmiTagML">',
        ]

        for item in tag_items:
            tag_id = str(uuid.uuid4()).replace("-", "")[:8]
            tag_name = item.get("name", "")
            raw_type = item.get("data_type") or item.get("datatype") or item.get("type")
            if not raw_type:
                logger.warning("Tag '%s' has no data_type, fallback to Bool", item.get("name", "<unknown>"))
                data_type = "Bool"
            else:
                from backend.variable_engine import normalize_data_type
                data_type = normalize_data_type(raw_type, fallback="Bool")
            # V5.5R3: 最后一公里安全网 — 基于变量名前缀强制纠正
            # 确保 BTN_/MEM_/STS_/LMP_ 前缀变量写入 XML 时一定为 Bool
            _bool_prefixes = ("BTN_", "MEM_", "STS_", "LMP_")
            for prefix in _bool_prefixes:
                if tag_name.startswith(prefix) and data_type != "Bool":
                    logger.warning("XML安全网: %s data_type %s → Bool", tag_name, data_type)
                    data_type = "Bool"
                    break
            address = item.get("address", "")
            connection = item.get("connection", "")
            comment = item.get("comment", "")
            default_tag_table = item.get("default_tag_table", "DefaultTagTable")

            lines.append(f'  <Hmi.Tag.Tag ID="{tag_id}" CompositionName="Tags">')
            lines.append("    <AttributeList>")
            lines.append(f"      <Name>{xml_escape(tag_name)}</Name>")

            if connection:
                lines.append(f"      <Connection>{xml_escape(connection)}</Connection>")

            if comment:
                lines.append(f"      <Comment>{xml_escape(comment)}</Comment>")

            lines.append("    </AttributeList>")
            lines.append("  </Hmi.Tag.Tag>")

        lines.append("</Engineering>")

        return "\n".join(lines)

    def get_golden_template_path(self) -> str | None:
        """返回 golden template 文件的绝对路径。

        如果文件存在返回路径字符串，否则返回 None。
        """
        if os.path.isfile(self._golden_template_path):
            return self._golden_template_path
        return None

    def generate_from_golden_template(
        self,
        tag_name: str,
        data_type: str,
        address: str = "",
        connection: str = "",
        comment: str = "",
        default_tag_table: str = "DefaultTagTable",
    ) -> str:
        """基于 golden template 生成 HMI Tag XML。

        如果 golden template 文件存在，读取并替换占位符:
            {{TAG_NAME}}, {{DATA_TYPE}}, {{ADDRESS}},
            {{CONNECTION}}, {{COMMENT}}, {{DEFAULT_TAG_TABLE}}

        如果 template 不存在或读取失败，回退到 build_individual_tag_xml()。

        参数:
            tag_name: 变量名称
            data_type: 数据类型
            address: PLC 地址
            connection: 连接名称
            comment: 注释
            default_tag_table: 变量表名
        """
        if not self.get_golden_template_path():
            return self.build_individual_tag_xml(
                tag_name, data_type, address, connection, comment, default_tag_table,
            )

        try:
            with open(self._golden_template_path, "r", encoding="utf-8") as f:
                template = f.read()

            replacements = {
                "{{TAG_NAME}}": tag_name,
                "{{DATA_TYPE}}": data_type,
                "{{ADDRESS}}": address,
                "{{CONNECTION}}": connection,
                "{{COMMENT}}": comment,
                "{{DEFAULT_TAG_TABLE}}": default_tag_table,
            }
            for placeholder, value in replacements.items():
                template = template.replace(placeholder, value)

            return template
        except Exception:
            return self.build_individual_tag_xml(
                tag_name, data_type, address, connection, comment, default_tag_table,
            )


class HmiTagTableTemplateBuilder:
    """Build HMI tag table XML by cloning real TIA-exported tag nodes.

    Basic/KTP Basic panels reject guessed HMI tag XML when DataType is passed
    as a plain string. This builder uses a real exported HMI tag table as the
    structural source, then only replaces values inside the exported shape.
    """

    def build_from_template(
        self,
        template_xml: str,
        tag_items: list[dict],
    ) -> tuple[str, list[str]]:
        """Return a generated HMI tag table XML and non-fatal warnings."""
        warnings: list[str] = []
        if not template_xml or not template_xml.strip():
            raise ValueError("HMI 变量表模板 XML 为空。")

        self._register_namespaces(template_xml)
        root = ET.fromstring(template_xml.encode("utf-8"))
        tag_entries = self._find_tag_entries(root)
        if not tag_entries:
            raise ValueError(
                "HMI 变量表模板中没有找到可复制的 Hmi.Tag.Tag 节点。"
            )

        existing_by_name: dict[str, tuple[ET.Element, ET.Element]] = {}
        for parent, elem in tag_entries:
            name = self._get_attr_text(elem, "Name")
            if name:
                existing_by_name[name] = (parent, elem)

        prototype_by_type: dict[str, ET.Element] = {}
        first_prototype = tag_entries[0][1]
        for _parent, elem in tag_entries:
            dt = self._canonical_type(self._get_data_type(elem))
            if dt and dt not in prototype_by_type:
                prototype_by_type[dt] = elem

        append_parent = self._choose_append_parent(tag_entries)
        names_to_generate = {
            str(item.get("name", "")).strip()
            for item in tag_items
            if str(item.get("name", "")).strip()
        }
        for name in names_to_generate:
            found = existing_by_name.get(name)
            if found:
                parent, elem = found
                try:
                    parent.remove(elem)
                except ValueError:
                    pass

        for item in tag_items:
            name = str(item.get("name", "")).strip()
            if not name:
                continue

            raw_type = item.get("data_type") or item.get("datatype") or item.get("type")
            from backend.variable_engine import normalize_data_type
            data_type = normalize_data_type(str(raw_type or "Bool"), fallback="Bool")
            if name.startswith(("BTN_", "MEM_", "STS_", "LMP_")):
                data_type = "Bool"

            prototype = prototype_by_type.get(
                self._canonical_type(data_type),
                first_prototype,
            )
            clone = copy.deepcopy(prototype)
            self._refresh_ids(clone)
            self._set_attr_text(clone, "Name", name, warnings, required=True)
            self._set_data_type(clone, data_type, warnings)

            scope = str(item.get("scope", "")).lower()
            address = str(item.get("address", "") or "").strip()
            connection = str(item.get("connection", "") or "").strip()
            controller_tag = str(item.get("controller_tag", "") or "").strip()
            comment = str(item.get("comment", "") or "").strip()
            is_external = bool(address or connection or controller_tag or scope == "external")

            if is_external:
                self._set_attr_text(clone, "Connection", connection, warnings)
                if controller_tag:
                    self._set_attr_text(clone, "ControllerTag", controller_tag, warnings)
                if address:
                    self._set_attr_text(clone, "Address", address, warnings)
            else:
                self._set_attr_text(clone, "Connection", "", warnings)
                self._set_attr_text(clone, "ControllerTag", "", warnings)
                self._set_attr_text(clone, "Address", "", warnings)

            if comment:
                self._set_attr_text(clone, "Comment", comment, warnings)

            append_parent.append(clone)

        xml_body = ET.tostring(root, encoding="unicode")
        return '<?xml version="1.0" encoding="utf-8"?>\n' + xml_body, warnings

    @staticmethod
    def _register_namespaces(xml_text: str) -> None:
        try:
            for _event, ns in ET.iterparse(io.StringIO(xml_text), events=("start-ns",)):
                prefix, uri = ns
                ET.register_namespace(prefix or "", uri)
        except Exception:
            pass

    @staticmethod
    def _qname_without_ns(tag: str) -> str:
        return tag.rsplit("}", 1)[-1] if "}" in tag else tag

    @classmethod
    def _short_name(cls, tag: str) -> str:
        qname = cls._qname_without_ns(tag)
        return qname.rsplit(".", 1)[-1] if "." in qname else qname

    @classmethod
    def _is_hmi_tag_element(cls, elem: ET.Element) -> bool:
        qname = cls._qname_without_ns(elem.tag)
        short = cls._short_name(elem.tag)
        if short != "Tag":
            return False
        if qname.startswith("SW."):
            return False
        return cls._find_attr_child(elem, "Name") is not None

    @classmethod
    def _find_tag_entries(cls, root: ET.Element) -> list[tuple[ET.Element, ET.Element]]:
        entries: list[tuple[ET.Element, ET.Element]] = []
        for parent in root.iter():
            for child in list(parent):
                if cls._is_hmi_tag_element(child):
                    entries.append((parent, child))
        if cls._is_hmi_tag_element(root):
            raise ValueError(
                "当前模板是单个 HMI Tag，不是完整 HMI 变量表。"
                "请导出 DefaultTagTable 作为变量表模板。"
            )
        return entries

    @classmethod
    def _choose_append_parent(
        cls,
        tag_entries: list[tuple[ET.Element, ET.Element]],
    ) -> ET.Element:
        parent_counts: dict[int, tuple[ET.Element, int]] = {}
        for parent, _elem in tag_entries:
            key = id(parent)
            if key not in parent_counts:
                parent_counts[key] = (parent, 0)
            parent_counts[key] = (parent, parent_counts[key][1] + 1)
        return max(parent_counts.values(), key=lambda x: x[1])[0]

    @classmethod
    def _find_attr_list(cls, elem: ET.Element) -> ET.Element | None:
        for child in list(elem):
            if cls._short_name(child.tag) == "AttributeList":
                return child
        return None

    @classmethod
    def _find_link_list(cls, elem: ET.Element) -> ET.Element | None:
        for child in list(elem):
            if cls._short_name(child.tag) == "LinkList":
                return child
        return None

    @classmethod
    def _find_attr_child(cls, elem: ET.Element, name: str) -> ET.Element | None:
        attr_list = cls._find_attr_list(elem)
        if attr_list is None:
            return None
        for child in list(attr_list):
            if cls._short_name(child.tag) == name:
                return child
        return None

    @classmethod
    def _get_attr_text(cls, elem: ET.Element, name: str) -> str:
        child = cls._find_attr_child(elem, name)
        return (child.text or "").strip() if child is not None else ""

    @classmethod
    def _set_attr_text(
        cls,
        elem: ET.Element,
        name: str,
        value: str,
        warnings: list[str],
        required: bool = False,
    ) -> bool:
        child = cls._find_attr_child(elem, name)
        if child is None:
            if required:
                warnings.append(f"模板变量节点缺少 {name} 字段，无法写入 {value!r}。")
            return False
        child.text = value
        return True

    @classmethod
    def _get_link_name_text(cls, elem: ET.Element, link_name: str) -> str:
        link_list = cls._find_link_list(elem)
        if link_list is None:
            return ""
        for link in list(link_list):
            if cls._short_name(link.tag) != link_name:
                continue
            for child in list(link):
                if cls._short_name(child.tag) == "Name":
                    return (child.text or "").strip()
        return ""

    @classmethod
    def _set_link_name_text(
        cls,
        elem: ET.Element,
        link_name: str,
        value: str,
    ) -> bool:
        link_list = cls._find_link_list(elem)
        if link_list is None:
            return False
        for link in list(link_list):
            if cls._short_name(link.tag) != link_name:
                continue
            for child in list(link):
                if cls._short_name(child.tag) == "Name":
                    child.text = value
                    return True
        return False

    @classmethod
    def _get_data_type(cls, elem: ET.Element) -> str:
        return (
            cls._get_attr_text(elem, "DataType")
            or cls._get_link_name_text(elem, "HmiDataType")
            or cls._get_link_name_text(elem, "DataType")
        )

    @classmethod
    def _set_data_type(
        cls,
        elem: ET.Element,
        data_type: str,
        warnings: list[str],
    ) -> None:
        written = False
        if cls._set_attr_text(elem, "DataType", data_type, warnings):
            written = True
        if cls._set_link_name_text(elem, "DataType", data_type):
            written = True
        if cls._set_link_name_text(elem, "HmiDataType", data_type):
            written = True

        if not written:
            warnings.append(
                f"模板变量节点缺少 DataType/HmiDataType 链接，无法写入 {data_type!r}。"
            )

    @staticmethod
    def _canonical_type(value: str) -> str:
        raw = str(value or "").strip().strip("\"'")
        if "." in raw:
            raw = raw.rsplit(".", 1)[-1]
        aliases = {
            "bool": "Bool",
            "boolean": "Bool",
            "int": "Int",
            "integer": "Int",
            "uint": "UInt",
            "dint": "DInt",
            "real": "Real",
            "word": "Word",
            "string": "String",
            "wstring": "WString",
        }
        return aliases.get(raw.lower(), raw)

    @classmethod
    def _refresh_ids(cls, elem: ET.Element) -> None:
        for current in elem.iter():
            if "ID" in current.attrib:
                current.set("ID", uuid.uuid4().hex[:8])
            if cls._short_name(current.tag) == "ID" and current.text:
                current.text = uuid.uuid4().hex[:8]
