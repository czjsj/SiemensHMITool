# -*- coding: utf-8 -*-
"""
V5.5 集成回归测试 — 验证变量类型推断与模板变量替换。

对应 V5.5修复方案.md Step 0 的最小复现用例。
完整流水线: VariableEngine -> Tag XML 构建 (HmiTagXmlBuilder) -> 画面 XML 生成 (ScreenXmlBuilder)。

验证点:
  1. BTN_START data_type == "Bool"
  2. BTN_STOP  data_type == "Bool"
  3. STS_RUNNING data_type == "Bool"
  4. IO_SPEED_SETPOINT data_type == "Real"
  5. 生成画面 XML 中不含模板变量名
  6. 生成画面 XML 中包含生成变量名
  7. 按钮事件 TagName 引用生成变量（非模板变量）
  8. 所有控件类型不导致变量回退为 Int
"""
import copy
import os
import sys
import xml.etree.ElementTree as ET

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.variable_engine import VariableEngine
from backend.backends.classic.tag_xml_builder import HmiTagXmlBuilder
from backend.backends.classic.screen_xml_builder import ScreenXmlBuilder
from backend.tag_binding_normalizer import normalize_legacy_tag_bindings


# ---------------------------------------------------------------------------
# 模板变量名 — 用于泄漏检测
# ---------------------------------------------------------------------------

TEMPLATE_VARIABLE_NAMES: list[str] = [
    "Template_BTN_Tag",
    "Template_BTN_Toggle_Tag",
    "Template_BTN_Set_Tag",
    "Template_LMP_Tag",
    "Template_LMP_Alarm_Tag",
    "Template_ProcessTag",
    "Template_Button_Tag",
]


class TestV55IntegrationRegression:
    """V5.5 集成回归测试 — 完整流水线。"""

    @pytest.fixture
    def v55_ir(self):
        """V5.5修复方案.md Step 0 的精确 IR。

        包含:
          btn_start:     button (momentary), tag_binding=BTN_START
          btn_stop:      button (toggle),    tag_binding=BTN_STOP
          lamp_running:  indicator,          tag_binding=STS_RUNNING
          io_speed:      io_field,           tag_binding=IO_SPEED_SETPOINT, data_type=Real
        """
        return {
            "meta": {
                "screen_name": "TestScreen",
                "hmi_type": "Comfort",
                "resolution": "1280x800",
            },
            "objects": [
                {
                    "id": "btn_start",
                    "type": "button",
                    "text": "启动",
                    "behavior": "momentary",
                    "tag_binding": "BTN_START",
                    "x": 100, "y": 100, "width": 120, "height": 40,
                },
                {
                    "id": "btn_stop",
                    "type": "button",
                    "text": "停止",
                    "behavior": "toggle",
                    "tag_binding": "BTN_STOP",
                    "x": 250, "y": 100, "width": 120, "height": 40,
                },
                {
                    "id": "lamp_running",
                    "type": "indicator",
                    "text": "运行状态",
                    "tag_binding": "STS_RUNNING",
                    "x": 100, "y": 200, "width": 60, "height": 60,
                },
                {
                    "id": "io_speed",
                    "type": "io_field",
                    "text": "速度设定",
                    "tag_binding": "IO_SPEED_SETPOINT",
                    "data_type": "Real",
                    "x": 100, "y": 300, "width": 160, "height": 40,
                },
            ],
            "tags": [],
            "scripts": [],
        }

    # ==================================================================
    # V5.5 完整流水线集成测试
    # ==================================================================

    def test_full_pipeline_v55_regression(self, v55_ir):
        """V5.5 回归：完整流水线 VariableEngine -> Tag XML -> Screen XML。

        使用 V5.5修复方案.md Step 0 的精确 IR，覆盖：
          - 变量类型推断（按钮/指示灯=Bool, IOField=Real）
          - HMI Tag XML DataType 正确性
          - 画面 XML 变量引用（无模板变量泄露）
        """
        # ---- 类型规范化：将 IR 中的小写 type 归一化（修复后应内置到 normalize 中） ----
        ir = copy.deepcopy(v55_ir)
        _normalize_object_types(ir)
        _normalize_behavior_to_tag_mode(ir)

        # ==============================================================
        # Phase 1: VariableEngine 变量生成和类型推断
        # ==============================================================
        engine = VariableEngine()
        enriched_ir = engine.generate(ir)

        tags = enriched_ir.get("tags", [])
        tag_by_name = {t["name"]: t for t in tags}

        # 确保 4 个变量均已生成且名称正确
        assert len(tags) == 4, (
            f"应生成 4 个变量，实际 {len(tags)}: {sorted(tag_by_name.keys())}"
        )

        # --- 断言 1: BTN_START 类型为 Bool ---
        assert "BTN_START" in tag_by_name, (
            f"缺失 BTN_START。已生成: {sorted(tag_by_name.keys())}"
        )
        assert tag_by_name["BTN_START"]["data_type"] == "Bool", (
            f"BTN_START 应为 Bool，实际: {tag_by_name['BTN_START']['data_type']}"
        )

        # --- 断言 2: BTN_STOP 类型为 Bool ---
        assert "BTN_STOP" in tag_by_name, (
            f"缺失 BTN_STOP。已生成: {sorted(tag_by_name.keys())}"
        )
        assert tag_by_name["BTN_STOP"]["data_type"] == "Bool", (
            f"BTN_STOP 应为 Bool，实际: {tag_by_name['BTN_STOP']['data_type']}"
        )

        # --- 断言 3: STS_RUNNING 类型为 Bool ---
        assert "STS_RUNNING" in tag_by_name, (
            f"缺失 STS_RUNNING。已生成: {sorted(tag_by_name.keys())}"
        )
        assert tag_by_name["STS_RUNNING"]["data_type"] == "Bool", (
            f"STS_RUNNING 应为 Bool，实际: {tag_by_name['STS_RUNNING']['data_type']}"
        )

        # --- 断言 4: IO_SPEED_SETPOINT 类型为 Real ---
        assert "IO_SPEED_SETPOINT" in tag_by_name, (
            f"缺失 IO_SPEED_SETPOINT。已生成: {sorted(tag_by_name.keys())}"
        )
        assert tag_by_name["IO_SPEED_SETPOINT"]["data_type"] == "Real", (
            f"IO_SPEED_SETPOINT 应为 Real，实际: {tag_by_name['IO_SPEED_SETPOINT']['data_type']}"
        )

        # ==============================================================
        # Phase 2: HMI Tag XML 构建与 DataType 验证
        # ==============================================================
        hmi_builder = HmiTagXmlBuilder()
        tag_xml = hmi_builder.build_batch_tags_xml(tags)

        # 解析 XML 并验证 DataType
        ns = "http://www.siemens.com/automation/HmiTagML"
        tag_root = ET.fromstring(tag_xml)
        tag_elements = tag_root.findall(f".//{{{ns}}}Hmi.Tag.Tag")
        assert len(tag_elements) == 4, (
            f"HMI Tag XML 应包含 4 个 <Hmi.Tag.Tag>，实际 {len(tag_elements)}"
        )

        # V5.5R8: DataType 不在 XML 中，由 _correct_tag_data_types_after_import 通过 API 修正
        xml_types = _extract_xml_tag_types(tag_elements, ns)
        for tag_name in ("BTN_START", "BTN_STOP", "STS_RUNNING", "IO_SPEED_SETPOINT"):
            assert tag_name in xml_types, f"Tag XML 缺少 {tag_name}"
            # DataType 不在 XML 中，expected_types 由 API 层处理

        # ==============================================================
        # Phase 3: 画面 XML 生成 — 变量引用与模板泄露检测
        # ==============================================================
        # 使用独立的 IR 副本构建 ScreenSpec
        ir_screen = copy.deepcopy(v55_ir)
        _normalize_object_types(ir_screen)
        _normalize_behavior_to_tag_mode(ir_screen)
        ir_screen = normalize_legacy_tag_bindings(ir_screen)

        project = engine.enrich(ir_screen)
        assert len(project.screens) == 1

        screen_builder = ScreenXmlBuilder()
        screen_xml = screen_builder.build_screen(project.screens[0])

        # --- 断言 5: 画面 XML 中包含生成变量名 (BTN_START, BTN_STOP, STS_RUNNING, IO_SPEED_SETPOINT) ---
        generated_vars = ["BTN_START", "BTN_STOP", "STS_RUNNING", "IO_SPEED_SETPOINT"]
        for var in generated_vars:
            assert var in screen_xml, (
                f"画面 XML 中缺失生成变量 '{var}'"
            )

        # --- 断言 6: 画面 XML 中不含模板变量名 ---
        leaked = [tv for tv in TEMPLATE_VARIABLE_NAMES if tv in screen_xml]
        assert not leaked, (
            f"模板变量泄露到画面 XML: {leaked}"
        )

        # --- 断言 7: 事件 FunctionList 中 TagName 引用生成变量 ---
        screen_root = ET.fromstring(screen_xml)
        event_tag_names = _extract_event_tagnames(screen_root)
        for name in event_tag_names:
            assert name not in TEMPLATE_VARIABLE_NAMES, (
                f"事件 TagName='{name}' 是模板变量，应替换为生成变量"
            )
            assert name in tag_by_name, (
                f"事件 TagName='{name}' 未在变量表中找到"
            )

        # --- 断言 8: ProcessTag 中引用生成变量 ---
        process_tags = _extract_process_tags(screen_root)
        for pt in process_tags:
            assert pt not in TEMPLATE_VARIABLE_NAMES, (
                f"ProcessTag='{pt}' 是模板变量，应替换为生成变量"
            )

    # ==================================================================
    # 专项回归测试
    # ==================================================================

    def test_button_variable_type_never_int(self, v55_ir):
        """按钮变量绝对不能回退为 Int。"""
        ir = copy.deepcopy(v55_ir)
        _normalize_object_types(ir)
        _normalize_behavior_to_tag_mode(ir)

        engine = VariableEngine()
        result = engine.generate(ir)
        tags = {t["name"]: t for t in result.get("tags", [])}

        for name in ("BTN_START", "BTN_STOP"):
            assert name in tags, f"缺失 {name}"
            assert tags[name]["data_type"] == "Bool", (
                f"{name} = {tags[name]['data_type']}（应为 Bool，禁止回退为 Int）"
            )

    def test_indicator_variable_type_never_int(self, v55_ir):
        """指示灯变量绝对不能回退为 Int。"""
        ir = copy.deepcopy(v55_ir)
        _normalize_object_types(ir)
        _normalize_behavior_to_tag_mode(ir)

        engine = VariableEngine()
        result = engine.generate(ir)
        tags = {t["name"]: t for t in result.get("tags", [])}

        assert "STS_RUNNING" in tags, "缺失 STS_RUNNING"
        assert tags["STS_RUNNING"]["data_type"] == "Bool", (
            f"STS_RUNNING = {tags['STS_RUNNING']['data_type']}（应为 Bool，禁止回退为 Int）"
        )

    def test_iofield_explicit_real_not_overridden(self, v55_ir):
        """IOField 显式 data_type=Real 必须保持 Real，不能被覆盖为 Int。"""
        ir = copy.deepcopy(v55_ir)
        _normalize_object_types(ir)
        _normalize_behavior_to_tag_mode(ir)

        engine = VariableEngine()
        result = engine.generate(ir)
        tags = {t["name"]: t for t in result.get("tags", [])}

        assert "IO_SPEED_SETPOINT" in tags, "缺失 IO_SPEED_SETPOINT"
        assert tags["IO_SPEED_SETPOINT"]["data_type"] == "Real", (
            f"IO_SPEED_SETPOINT = {tags['IO_SPEED_SETPOINT']['data_type']}（应为 Real，禁止回退为 Int）"
        )

    def test_all_variables_not_int(self, v55_ir):
        """端到端：所有变量类型都不能是 Int（除非是 SymbolicIOField）。"""
        ir = copy.deepcopy(v55_ir)
        _normalize_object_types(ir)
        _normalize_behavior_to_tag_mode(ir)

        engine = VariableEngine()
        result = engine.generate(ir)
        tags = result.get("tags", [])

        # 该 IR 不含 SymbolicIOField，因此所有变量都不应是 Int
        for t in tags:
            assert t["data_type"] != "Int", (
                f"变量 {t['name']} 类型为 Int，但 IR 中无 SymbolicIOField，"
                f"所有控件类型应推断为 Bool 或 Real"
            )

    # ==================================================================
    # V5.5R3 专项：AI 输出 Int → VariableEngine 必须纠正并回写
    # ==================================================================

    def test_ai_generated_int_types_corrected_to_bool(self):
        """核心回归：模拟 AI 将所有变量输出为 Int，VariableEngine 必须纠正。

        这是第二轮修复失败的根因：
        - AI 可能输出 tags=[{name:"BTN_Start", data_type:"Int"}]
        - VariableEngine.enrich() 正确修正 project.tags 中的 data_type
        - 但 generate() 的回填循环只添加新 tag，不更新已有 tag 的 data_type
        - 导致 ir["tags"] 仍保留 AI 的 Int，sync_tags 把 Int 写入 TIA Portal
        """
        ir = {
            "meta": {"screen_name": "TestIntCorrection", "resolution": "1280x800"},
            "tags": [
                {"name": "BTN_Start", "data_type": "Int", "address": "", "comment": "AI输出Int"},
                {"name": "STS_Running", "data_type": "Int", "address": "", "comment": "AI输出Int"},
            ],
            "objects": [
                {"id": "BTN_Start", "type": "Button", "text": "启动",
                 "tag_mode": "momentary", "process_tag": "BTN_Start",
                 "x": 100, "y": 100, "width": 120, "height": 40},
                {"id": "LMP_Run", "type": "Indicator", "text": "运行",
                 "process_tag": "STS_Running",
                 "x": 200, "y": 100, "radius": 24},
            ],
            "scripts": [],
        }

        engine = VariableEngine()
        result = engine.generate(ir)

        tags = {t["name"]: t for t in result.get("tags", [])}

        # 按钮变量必须被纠正为 Bool
        assert "BTN_Start" in tags, f"缺失 BTN_Start，tags: {sorted(tags.keys())}"
        assert tags["BTN_Start"]["data_type"] == "Bool", (
            f"BTN_Start data_type={tags['BTN_Start']['data_type']}（AI 输出 Int，必须纠正为 Bool）"
        )

        # 指示灯变量必须被纠正为 Bool
        assert "STS_Running" in tags, f"缺失 STS_Running，tags: {sorted(tags.keys())}"
        assert tags["STS_Running"]["data_type"] == "Bool", (
            f"STS_Running data_type={tags['STS_Running']['data_type']}（AI 输出 Int，必须纠正为 Bool）"
        )

    def test_ai_generated_int_type_not_synced_to_legacy_tags(self):
        """验证 project.tags 修正后确实回写到 ir['tags']。

        本测试直接检查 generate() 输出的 ir['tags'] 数组，
        确保每个已存在的 tag 的 data_type 都被 project 中的正确值覆盖。
        """
        ir = {
            "meta": {"screen_name": "TestLegacySync", "resolution": "1280x800"},
            "tags": [
                {"name": "BTN_TestBtn", "data_type": "Int", "address": "%M0.0"},
                {"name": "STS_TestInd", "data_type": "Int", "address": "%M1.0"},
                {"name": "IO_TestSpeed", "data_type": "Int", "address": "%MD10"},
            ],
            "objects": [
                {"id": "BTN_TestBtn", "type": "Button", "text": "测试按钮",
                 "tag_mode": "momentary", "process_tag": "BTN_TestBtn",
                 "x": 100, "y": 100, "width": 120, "height": 40},
                {"id": "LMP_TestInd", "type": "Indicator", "text": "测试指示灯",
                 "process_tag": "STS_TestInd",
                 "x": 200, "y": 100, "radius": 24},
                {"id": "IO_TestSpeed", "type": "IOField", "text": "速度",
                 "process_tag": "IO_TestSpeed",
                 "x": 100, "y": 200, "width": 120, "height": 40},
            ],
            "scripts": [],
        }

        engine = VariableEngine()
        result = engine.generate(ir)

        # 直接检查 ir['tags'] 中的 data_type
        legacy_tags = {t["name"]: t for t in result.get("tags", [])}

        assert legacy_tags["BTN_TestBtn"]["data_type"] == "Bool", (
            f"ir['tags'] 中 BTN_TestBtn={legacy_tags['BTN_TestBtn']['data_type']}，应为 Bool"
        )
        assert legacy_tags["STS_TestInd"]["data_type"] == "Bool", (
            f"ir['tags'] 中 STS_TestInd={legacy_tags['STS_TestInd']['data_type']}，应为 Bool"
        )
        assert legacy_tags["IO_TestSpeed"]["data_type"] == "Real", (
            f"ir['tags'] 中 IO_TestSpeed={legacy_tags['IO_TestSpeed']['data_type']}，应为 Real"
        )


# ======================================================================
# 辅助函数
# ======================================================================

def _normalize_object_types(ir: dict) -> None:
    """将 IR 对象中的小写 type 归一化（button -> Button, indicator -> Indicator 等）。

    V5.5 修复后此逻辑应内置于 normalize_legacy_tag_bindings 或 validate_ir。
    """
    type_map = {
        "button": "Button",
        "indicator": "Indicator",
        "io_field": "IOField",
        "symbolic_io_field": "SymbolicIOField",
        "text": "Text",
        "switch": "Switch",
        "slider": "Slider",
    }
    for obj in ir.get("objects", []):
        raw = obj.get("type", "")
        if raw in type_map:
            obj["type"] = type_map[raw]


def _normalize_behavior_to_tag_mode(ir: dict) -> None:
    """将 Button 的 behavior 字段映射为 tag_mode。

    V5.5 修复后此逻辑应内置于 VariableEngine 或 LegacyIrAdapter。
    """
    behavior_to_tag_mode = {
        "momentary": "momentary",
        "toggle": "toggle",
        "set": "set",
        "reset": "reset",
    }
    for obj in ir.get("objects", []):
        if obj.get("type") in ("Button", "button"):
            behavior = obj.get("behavior", "")
            if behavior in behavior_to_tag_mode:
                obj.setdefault("tag_mode", behavior_to_tag_mode[behavior])


def _extract_xml_tag_types(tag_elements: list, ns: str) -> dict[str, str]:
    """从 HmiTagXmlBuilder 生成的 XML 中提取 {tag_name: ""} 映射。

    V5.5R8: DataType 不在 XML 中（TIA Import 拒绝 <DataType> 子元素，
    也不读取元素属性）。类型由 _correct_tag_data_types_after_import 修正。
    本函数仅用于验证 tag 名称存在性。
    """
    result = {}
    for elem in tag_elements:
        attr_list = elem.find(f".//{{{ns}}}AttributeList")
        dt = ""
        if attr_list is not None:
            dt_el = attr_list.find(f"{{{ns}}}DataType")
            if dt_el is not None and dt_el.text:
                dt = dt_el.text.strip()
        name_el = elem.find(f".//{{{ns}}}Name")
        if name_el is not None and name_el.text:
            result[name_el.text.strip()] = dt
    return result


def _extract_event_tagnames(screen_root: ET.Element) -> list[str]:
    """提取画面 XML 中所有事件 TagName 引用的变量名。"""
    result = []
    for elem in screen_root.iter():
        local = _local_tag(elem)
        if local == "TagName" and elem.text and elem.text.strip():
            result.append(elem.text.strip())
    return result


def _extract_process_tags(screen_root: ET.Element) -> list[str]:
    """提取画面 XML 中所有 ProcessTag 引用的变量名。"""
    result = []
    for elem in screen_root.iter():
        local = _local_tag(elem)
        if local == "ProcessTag" and elem.text and elem.text.strip():
            result.append(elem.text.strip())
    return result


def _local_tag(elem: ET.Element) -> str:
    """提取元素的本地标签名（去掉命名空间前缀）。"""
    tag = elem.tag
    if "}" in tag:
        return tag.split("}")[-1]
    return tag
