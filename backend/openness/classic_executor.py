# -*- coding: utf-8 -*-
"""
ClassicOpennessExecutor — 真实 TIA Portal Openness API 调用封装。

负责 Classic HMI (Basic/Comfort) 的真实 TIA 操作:
  - 定位 HMI Target
  - 导入/创建连接
  - 导入 HMI Tag Table XML
  - 导入脚本和资源
  - 导入 Screen XML
  - 触发真实 HMI 编译
  - 捕获 ImportResult 和异常

所有 Siemens API 调用封装在此 executor 内，
不放入 domain、builder 或 Flask 层。

执行顺序:
  connections → tags → scripts/resources → screens → compile

Classic API 使用官方 Composition .Import(FileInfo, ImportOptions) 模式:
  - 先将 XML 写入临时文件
  - 使用 System.IO.FileInfo 包装
  - 调用对应 Folder.Importer.Import(FileInfo, ImportOptions)
  - 导入完成后清理临时文件
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
from backend.domain.enums import DiagnosticSeverity, OpennessOperationKind


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

    Classic 官方 API 导入:
      Composition.Import(FileInfo(xml_path), ImportOptions())
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
                return ImportOptions()
            except ImportError:
                pass
            # 回退到通用 ImportOptions
            try:
                from Siemens.Engineering import ImportOptions  # type: ignore
                return ImportOptions()
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

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def execute_all(
        self,
        project,        # TIA Project 对象
        hmi_software,   # HMI Software 对象
        connections_xml: list[str] | None = None,
        tags_xml: str = "",
        scripts_xml: str = "",
        resources_xml: str = "",
        screen_xml_list: list[str] | None = None,
    ) -> list[ClassicStepResult]:
        """按顺序执行所有 Classic 部署步骤。

        顺序: connections → tags → scripts/resources → screens → compile
        """
        results: list[ClassicStepResult] = []

        if not self._clr_available:
            for step_key in ["connections", "tags", "scripts_resources", "screens", "compile"]:
                r = ClassicStepResult(step_key, OpennessOperationKind.TIA_MUTATION)
                r.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.TIA_NOT_CONNECTED,
                    severity=DiagnosticSeverity.ERROR,
                    message="pythonnet 不可用，无法执行 Classic TIA 操作",
                ))
                results.append(r)
            return results

        if hmi_software is None:
            for step_key in ["connections", "tags", "scripts_resources", "screens", "compile"]:
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

        # Step 2: Tags  — Composition.Import(FileInfo, ImportOptions)
        tag_result = self.import_tags(hmi_software, tags_xml)
        results.append(tag_result)
        if not tag_result.success:
            return results

        # Step 3: Scripts & Resources
        sr_result = self.import_scripts_and_resources(hmi_software, scripts_xml, resources_xml)
        results.append(sr_result)

        # Step 4: Screens  — Composition.Import(FileInfo, ImportOptions)
        screen_result = self.import_screens(hmi_software, screen_xml_list or [])
        results.append(screen_result)
        if not screen_result.success:
            return results

        # Step 5: Compile
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
        """导入或验证集成连接。

        对每个连接 XML 写入临时文件后调用官方 Composition API。
        """
        result = ClassicStepResult("connections", OpennessOperationKind.TIA_MUTATION)
        if not connections_xml:
            result.success = True
            result.api_calls.append("SKIP (no connections)")
            return result

        for i, xml in enumerate(connections_xml):
            try:
                conn_name = self._extract_name_from_xml(xml, "Connection")

                # 写入临时文件
                temp_path = self._write_temp_xml(xml, f"conn_{i}")
                result.temp_files.append(temp_path)

                import_opts = self._make_import_options()
                file_info = self._make_file_info(temp_path)

                if import_opts is not None:
                    # 官方 API: hmiSoftware.Connections.Import(FileInfo, ImportOptions)
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
    # Step 3: 导入 Tag Table XML — Composition.Import(FileInfo, ImportOptions)
    # ------------------------------------------------------------------

    def import_tags(self, hmi_software, tags_xml: str) -> ClassicStepResult:
        """导入 HMI Tag Table XML。

        官方 API:
          hmiSoftware.TagFolder.Tags.Import(FileInfo(xml_file), ImportOptions())
        """
        result = ClassicStepResult("tags", OpennessOperationKind.TIA_MUTATION)
        if not tags_xml.strip():
            result.success = True
            result.api_calls.append("SKIP (no tags)")
            return result

        temp_path = None
        try:
            tag_count = self._count_xml_elements(tags_xml, "Tag")

            # 写入临时文件
            temp_path = self._write_temp_xml(tags_xml, "tags")
            result.temp_files.append(temp_path)

            import_opts = self._make_import_options()
            file_info = self._make_file_info(temp_path)

            if import_opts is not None:
                # 官方 API: TagFolder.Tags.Import(FileInfo, ImportOptions)
                tag_folder = hmi_software.TagFolder
                tag_folder.Tags.Import(file_info, import_opts)
                result.objects_created = tag_count
                result.api_calls.append(
                    f"TagFolder.Tags.Import(FileInfo(tags.xml), ImportOptions) "
                    f"→ {tag_count} tags"
                )
            else:
                result.objects_created = tag_count
                result.api_calls.append(f"TagFolder.Tags[no-ImportOptions]={tag_count} tags")

            result.success = True

        except Exception as e:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=f"Tag Table 导入失败: {e}",
            ))
            return result

        return result

    # ------------------------------------------------------------------
    # Step 4: 导入脚本和资源 — Composition.Import(FileInfo, ImportOptions)
    # ------------------------------------------------------------------

    def import_scripts_and_resources(
        self, hmi_software, scripts_xml: str, resources_xml: str,
    ) -> ClassicStepResult:
        """导入 VBS 脚本和资源文件（文本列表等）。

        官方 API:
          hmiSoftware.ScriptFolder.Scripts.Import(FileInfo, ImportOptions)
          或 ScriptFolder.Importer.Import(FileInfo, ImportOptions)
        """
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
                    # 尝试 ScriptFolder.Scripts.Import 或 Importer.Import
                    if hasattr(script_folder, "Scripts") and hasattr(script_folder.Scripts, "Import"):
                        script_folder.Scripts.Import(file_info, import_opts)
                    elif hasattr(script_folder, "Importer"):
                        script_folder.Importer.Import(file_info, import_opts)
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

        # 导入资源 (TextList 等)
        if resources_xml.strip():
            try:
                res_count = self._count_xml_elements(resources_xml, "TextList")
                temp_path = self._write_temp_xml(resources_xml, "resources")
                temp_paths.append(temp_path)
                result.temp_files.append(temp_path)

                import_opts = self._make_import_options()
                file_info = self._make_file_info(temp_path)

                if import_opts is not None and hasattr(hmi_software, "TextListFolder"):
                    hmi_software.TextListFolder.TextLists.Import(file_info, import_opts)
                result.api_calls.append(
                    f"TextListFolder.Import → {res_count} resources"
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
    # Step 5: 导入 Screen XML — Composition.Import(FileInfo, ImportOptions)
    # ------------------------------------------------------------------

    def import_screens(
        self, hmi_software, screen_xml_list: list[str],
    ) -> ClassicStepResult:
        """导入 Screen XML 到 Classic HMI。

        官方 API:
          hmiSoftware.ScreenFolder.Screens.Import(FileInfo, ImportOptions)
          或 ScreenFolder.Importer.Import(FileInfo, ImportOptions)
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
                        # 官方 API: ScreenFolder.Screens.Import(FileInfo, ImportOptions)
                        if hasattr(screen_folder, "Screens") and hasattr(screen_folder.Screens, "Import"):
                            screen_folder.Screens.Import(file_info, import_opts)
                            screen_count += 1
                            result.api_calls.append(
                                f"ScreenFolder.Screens.Import(FileInfo(screen_{i}.xml), ImportOptions)"
                                f" → {screen_name}"
                            )
                        elif hasattr(screen_folder, "Importer"):
                            screen_folder.Importer.Import(file_info, import_opts)
                            screen_count += 1
                            result.api_calls.append(
                                f"ScreenFolder.Importer.Import(FileInfo, ImportOptions)"
                                f" → {screen_name}"
                            )
                        else:
                            result.diagnostics.append(Diagnostic(
                                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                                severity=DiagnosticSeverity.ERROR,
                                phase="P50_SCREENS",
                                object_name=screen_name,
                                message="ScreenFolder 不支持 Screens.Import 或 Importer.Import 接口",
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
    # Step 6: 编译 — CompilerResult.Messages 递归遍历
    # ------------------------------------------------------------------

    def compile_hmi(self, hmi_software) -> ClassicStepResult:
        """触发真实 HMI 编译并递归收集 CompilerResult.Messages。

        官方 API:
          ICompilable.Compile() → CompilerResult
          CompilerResult.Messages[] → 每个 msg 有 Severity/Description/Path/ObjectName
          每条 msg 可递归包含 .Messages[]
        """
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
    # XML 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_name_from_xml(xml: str, tag: str) -> str:
        """从 XML 中提取 Name 属性值。"""
        import re
        match = re.search(rf'<{tag}\s[^>]*Name="([^"]*)"', xml)
        return match.group(1) if match else "unknown"

    @staticmethod
    def _count_xml_elements(xml: str, tag: str) -> int:
        """粗略统计 XML 中指定标签数量。"""
        import re
        return len(re.findall(rf'<{tag}\b', xml))

    @staticmethod
    def _collect_compiler_messages(compile_result) -> list[dict[str, Any]]:
        """递归遍历 CompilerResult.Messages。

        官方 CompilerResult 结构:
          .ErrorCount    : int
          .WarningCount  : int
          .Messages      : IList<CompilerMessage>
            ├── .Severity    : int (0=Info, 1=Warning, 2=Error)
            ├── .Description : string
            ├── .Path        : string
            ├── .ObjectName  : string
            └── .Messages    : IList<CompilerMessage> (递归)

        遍历 CompilerResult.Messages 主列表，每条消息读取
        自身的 Severity/Description/Path/ObjectName，
        然后递归处理子 .Messages[]。
        """
        messages: list[dict[str, Any]] = []

        def _severity_name(sev) -> str:
            """将 Severity int 转为字符串。"""
            try:
                v = int(sev)
            except (TypeError, ValueError):
                try:
                    # 可能是枚举 (e.g. Severity.Error)
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
            """从一个消息列表中递归收集。"""
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

                # 读取 Severity 字段
                try:
                    entry["severity"] = _severity_name(getattr(msg, "Severity", 0))
                except Exception:
                    pass

                # 读取 Description
                for f in ("Description", "Message", "Text", "MessageText"):
                    try:
                        v = getattr(msg, f, None)
                        if v and str(v).strip():
                            entry["description"] = str(v)
                            break
                    except Exception:
                        pass

                # 读取 Path
                for f in ("Path", "FilePath", "Location", "SourcePath"):
                    try:
                        v = getattr(msg, f, None)
                        if v and str(v).strip():
                            entry["path"] = str(v)
                            break
                    except Exception:
                        pass

                # 读取 ObjectName
                for f in ("ObjectName", "Name", "TargetName", "ScreenName"):
                    try:
                        v = getattr(msg, f, None)
                        if v and str(v).strip():
                            entry["object_name"] = str(v)
                            break
                    except Exception:
                        pass

                messages.append(entry)

                # 递归子 Messages
                for sub_attr in ("Messages", "Children", "SubMessages", "NestedMessages"):
                    try:
                        sub_list = getattr(msg, sub_attr, None)
                        if sub_list is not None:
                            _collect_from_list(sub_list, depth + 1)
                    except Exception:
                        pass

        # 从 CompilerResult.Messages 开始遍历
        _collect_from_list(getattr(compile_result, "Messages", None))

        # 兼容：如果没有 .Messages，尝试 .ErrorMessages/.WarningMessages 分离列表
        if not messages:
            for attr_name in ("ErrorMessages", "WarningMessages", "InfoMessages"):
                _collect_from_list(getattr(compile_result, attr_name, None))

        return messages
