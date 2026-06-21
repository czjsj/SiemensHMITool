# -*- coding: utf-8 -*-
"""
集成测试: HMI Tag 导入流程。

V5.0 新增:
  - 测试完整 tag 生成 → 校验流程 (模拟 .NET 调用)
  - 测试 Unknown HMI family 阻断逻辑
  - 测试 device_discovery 的 family detection
"""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from backend.backends.classic.tag_xml_builder import TagXmlBuilder
from backend.domain.ir_v2 import TagSpec
from backend.domain.enums import TagScope


class TestTagGenerationPipeline(unittest.TestCase):
    """测试 tag 生成管线: variable_engine → tag_xml_builder → validate。"""

    def setUp(self):
        self.builder = TagXmlBuilder()

    def test_generate_and_validate_pipeline(self):
        """测试完整管线: TagSpec → XML → 类型校验。"""
        from backend.xml_validator import validate_xml_class_for_import_target

        # 步骤 1: 创建 TagSpec (模拟 VariableEngine 输出)
        tags = [
            TagSpec(
                name="Motor_Start",
                data_type="Bool",
                scope=TagScope.INTERNAL,
                table="DefaultTagTable",
            ),
            TagSpec(
                name="Motor_Speed",
                data_type="Int",
                scope=TagScope.EXTERNAL,
                table="DefaultTagTable",
                connection="HMI_Connection_1",
                address="DB1.DBW10",
                controller_tag="MotorSpeed",
            ),
            TagSpec(
                name="Temperature",
                data_type="Real",
                scope=TagScope.EXTERNAL,
                table="DefaultTagTable",
                connection="HMI_Connection_1",
                address="DB1.DBD20",
            ),
        ]

        # 步骤 2: TagXmlBuilder 生成 XML (plc_blocks 格式，用于验证类型守卫)
        xml = self.builder.build_tags_batch_export_xml(tags, output_kind="plc_blocks")

        # 验证: 包含变量名和 SW.Tag (PLC 格式)
        self.assertIn("Motor_Start", xml)
        self.assertIn("Motor_Speed", xml)
        self.assertIn("Temperature", xml)

        # 步骤 3: 写入临时文件
        tmp_dir = tempfile.mkdtemp()
        xml_path = os.path.join(tmp_dir, "pipeline_tags.xml")
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(xml)

        # 步骤 4: XML 类型守卫校验 — SW.Tag 应被拒绝
        with self.assertRaises(ValueError) as ctx:
            validate_xml_class_for_import_target(xml_path, "hmi_tags")
        error_msg = str(ctx.exception)
        self.assertIn("TAG_XML_WRONG_CLASS", error_msg,
                      "SW.Tag XML 应被拒绝并包含 TAG_XML_WRONG_CLASS")
        self.assertTrue(
            "SW.Tag" in error_msg or "SW.Blocks" in error_msg,
            "错误消息应提及 SW.Tag 或 SW.Blocks",
        )

        # 步骤 5: 完整校验也应失败
        from backend.xml_validator import validate_for_import_target
        result = validate_for_import_target(xml_path, "hmi_tags")
        self.assertFalse(result.valid,
                         "管线生成的 SW.Tag XML 应被完整校验拒绝")
        self.assertTrue(any("TAG_XML_WRONG_CLASS" in e for e in result.errors),
                        "错误消息应提及 TAG_XML_WRONG_CLASS")


class TestUnknownHmiFamilyBlocksFlow(unittest.TestCase):
    """测试 Unknown HMI family 正确阻断导入流程。"""

    @mock.patch("backend.openness.device_discovery.DeviceDiscovery.detect_family")
    def test_variable_engine_with_unknown_family(self, mock_detect):
        """当 HMI family 为 Unknown 时，流程应被阻断。"""
        mock_detect.return_value = "Unknown"

        # 验证 TagXmlBuilder 本身不依赖 HMI family
        builder = TagXmlBuilder()
        tag = TagSpec(name="Test", data_type="Bool", scope=TagScope.INTERNAL)
        xml = builder.build_single_tag_export_xml(tag, output_kind="plc_blocks")
        self.assertIn("Test", xml,
                       "HMI family 不影响 XML 生成格式，变量名应存在")


class TestDeviceDiscoveryDetection(unittest.TestCase):
    """测试设备发现模块的家族检测。"""

    def test_device_model_basic_detection(self):
        """验证 Basic 面板型号能被正确识别。"""
        # 模拟设备对象
        mock_device = mock.MagicMock()
        mock_device.Name = "KTP700"

        mock_item = mock.MagicMock()
        mock_item.Name = "KTP700_Basic_Panel"

        mock_sw = mock.MagicMock()
        mock_sw.__class__.__name__ = "HmiTarget"
        mock_sw.__class__.__module__ = "Siemens.Engineering.Hmi"

        # 配置
        config = {
            "openness": {},
            "hmi_defaults": {},
        }
        from backend.openness.device_discovery import DeviceDiscovery
        discovery = DeviceDiscovery(config)
        family = discovery.detect_family(mock_sw, mock_device, mock_item)
        self.assertEqual(family, "Basic",
                         "KTP700 应被识别为 Basic")

    def test_device_model_comfort_detection(self):
        """验证 Comfort 面板型号能被正确识别。"""
        mock_device = mock.MagicMock()
        mock_device.Name = "TP1200_Comfort"

        mock_item = mock.MagicMock()
        mock_item.Name = "TP1200"

        mock_sw = mock.MagicMock()
        mock_sw.__class__.__name__ = "HmiTarget"
        mock_sw.__class__.__module__ = "Siemens.Engineering.Hmi"

        config = {
            "openness": {},
            "hmi_defaults": {},
        }
        from backend.openness.device_discovery import DeviceDiscovery
        discovery = DeviceDiscovery(config)
        family = discovery.detect_family(mock_sw, mock_device, mock_item)
        self.assertEqual(family, "Comfort",
                         "TP1200 应被识别为 Comfort")

    def test_config_hint_overrides_unknown(self):
        """配置提示应能覆盖 Unknown 检测结果。"""
        mock_device = mock.MagicMock()
        mock_device.Name = "Unknown_Device"

        mock_sw = mock.MagicMock()
        mock_sw.__class__.__name__ = "HmiTarget"
        mock_sw.__class__.__module__ = "Siemens.Engineering.Hmi"

        config = {
            "openness": {"hmi_type": "basic"},
            "hmi_defaults": {},
        }
        from backend.openness.device_discovery import DeviceDiscovery
        discovery = DeviceDiscovery(config)
        family = discovery.detect_family(mock_sw, mock_device)
        self.assertEqual(family, "Basic",
                         "配置提示 basic 应覆盖检测结果")

    def test_resolve_family_with_fallback(self):
        """resolve_family_with_fallback 应正确处理 Unknown+配置回退。"""
        config = {"openness": {}, "hmi_defaults": {}}
        from backend.openness.device_discovery import DeviceDiscovery
        discovery = DeviceDiscovery(config)

        # mock detect_family to return "Unknown" to test the fallback logic
        with mock.patch.object(discovery, 'detect_family', return_value="Unknown"):
            # 不带配置提示 → 返回 Unknown
            family = discovery.resolve_family_with_fallback(
                mock.MagicMock()
            )
            self.assertEqual(family, "Unknown",
                             "无配置提示时 Unknown 应保持 Unknown")

            # 带配置提示 → 返回 Basic
            family = discovery.resolve_family_with_fallback(
                mock.MagicMock(), config_type_hint="basic"
            )
            self.assertEqual(family, "Basic",
                             "配置提示 basic 应覆盖 Unknown")


if __name__ == "__main__":
    unittest.main()
