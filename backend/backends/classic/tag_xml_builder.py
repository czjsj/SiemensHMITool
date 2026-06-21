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
import os
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from backend.domain.ir_v2 import TagSpec
from backend.domain.enums import TagScope


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
            <Hmi.Tag.Tag ID="1" CompositionName="Tags" DataType="Bool">
              <AttributeList>
                <Name>...</Name>
                <Connection>...</Connection>
                <DefaultTagTable>DefaultTagTable</DefaultTagTable>
              </AttributeList>
            </Hmi.Tag.Tag>
          </Engineering>

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
            f'  <Hmi.Tag.Tag ID="{tag_id}" CompositionName="Tags" DataType="{xml_escape(data_type)}">',
            "    <AttributeList>",
            f"      <Name>{xml_escape(tag_name)}</Name>",
        ]

        # <Address> 在 Hmi.Tag.Tag AttributeList 中不被 TIA 支持，省略
        if connection:
            lines.append(f"      <Connection>{xml_escape(connection)}</Connection>")

        # <DefaultTagTable> 不被 Hmi.Tag.Tag 导入支持，omit；导入目标已指定表
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
            data_type = item.get("data_type", "Bool")
            address = item.get("address", "")
            connection = item.get("connection", "")
            comment = item.get("comment", "")
            default_tag_table = item.get("default_tag_table", "DefaultTagTable")

            lines.append(f'  <Hmi.Tag.Tag ID="{tag_id}" CompositionName="Tags" DataType="{xml_escape(data_type)}">')
            lines.append("    <AttributeList>")
            lines.append(f"      <Name>{xml_escape(tag_name)}</Name>")

            # <Address> 在 Hmi.Tag.Tag AttributeList 中不被 TIA 支持，省略
            if connection:
                lines.append(f"      <Connection>{xml_escape(connection)}</Connection>")

            # <DefaultTagTable> 不被 Hmi.Tag.Tag 导入支持，omit；导入目标已指定表
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
