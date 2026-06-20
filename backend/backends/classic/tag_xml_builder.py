# -*- coding: utf-8 -*-
"""Classic XML Tag/Table XML Builder — 生成 HMI Tag XML。

基于真实 Basic 单变量导出文件格式生成变量表和变量。
V3.2: 增强为真实 Basic 导出格式，支持 DefaultTagTable 导入。
"""
from __future__ import annotations
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from backend.domain.ir_v2 import TagSpec
from backend.domain.enums import TagScope


class TagXmlBuilder:
    """HMI Tag XML 生成器。

    生成符合 TIA Portal 格式的 Tag Table 和 Tag XML。
    基于目标版本真实 Basic 导出 fragment。
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

        根对象为正式 HMI Tag，可直接导入 DefaultTagTable。
        每个变量生成一个由真实 Basic 单变量导出文件派生的 XML。

        参数:
            tag: 变量规格
            output_kind: 'hmi_tags' (默认) 生成 HMI Tag XML 用于
                         Hmi.Tag.TagComposition.Import；
                         'plc_blocks' 生成 PLC Blocks 包裹格式用于兼容旧场景。

        'hmi_tags' 格式:
          <Document>
            <Engineering version="V16"/>
            <SW.Tag>...</SW.Tag>
          </Document>

        'plc_blocks' 格式 (旧版):
          <Document>
            <Engineering version="V16"/>
            <SW.Blocks>
              <SW.Tag>...</SW.Tag>
            </SW.Blocks>
          </Document>
        """
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

        indent = "    " if output_kind == "hmi_tags" else "    "
        tag_indent = "    " if output_kind == "hmi_tags" else "    "

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
        """为多个变量生成批量导出 XML（直接 TagComposition.Import 格式）。

        ⚠️ HMI tag XML 不得包含 <SW.Blocks> 包装。
        SW.Blocks 是 PLC 软件块容器，TagComposition.Import 期望 SW.Tag 类型。

        参数:
            tags: 变量规格列表
            table_name: 表名（用于旧版兼容）
            output_kind: 'hmi_tags' (默认) 生成无 SW.Blocks 的 HMI Tag XML；
                         'plc_blocks' 生成兼容旧格式的 SW.Blocks 包裹格式。
        """
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
            tag_indent = "    " if output_kind == "hmi_tags" else "    "
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
