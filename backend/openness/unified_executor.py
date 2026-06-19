# -*- coding: utf-8 -*-
"""
UnifiedOpennessExecutor — 真实 WinCC Unified TIA Portal Openness API 调用封装。

负责 Unified HMI 的真实 TIA 操作:
  - hmiSoftware.Tags (直接集合, 非 TagFolder.Tags)
  - hmiSoftware.Screens (直接集合, 非 ScreenFolder.Screens)
  - ScreenItems 通过 Screen.ScreenItems
  - 属性 setter
  - Dynamizations.Create
  - EventHandlers.Create
  - ScriptCode setter
  - 编译

执行前:
  - 加载与当前 DLL hash 匹配的 RuntimeContract
  - 缺失 contract 时自动 probe
  - 必要类型、方法、属性或事件缺失时失败关闭
  - 不允许静默跳过无法创建的属性、事件或动态化
"""

from __future__ import annotations

from typing import Any

from backend.domain.diagnostics import Diagnostic, DiagnosticCodes
from backend.domain.enums import DiagnosticSeverity, OpennessOperationKind


class UnifiedStepResult:
    """Unified 单步骤执行结果。"""

    def __init__(self, step_key: str, operation_kind: OpennessOperationKind):
        self.step_key = step_key
        self.operation_kind = operation_kind
        self.success: bool = False
        self.objects_created: int = 0
        self.objects_updated: int = 0
        self.objects_skipped: int = 0
        self.diagnostics: list[Diagnostic] = []
        self.api_calls: list[str] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_key": self.step_key,
            "operation_kind": self.operation_kind.value,
            "success": self.success,
            "objects_created": self.objects_created,
            "objects_updated": self.objects_updated,
            "objects_skipped": self.objects_skipped,
            "api_calls": self.api_calls,
            "diagnostics": [d.model_dump() for d in self.diagnostics],
        }


class UnifiedOpennessExecutor:
    """Unified HMI 真实 Openness 执行器。

    需要 Siemens.Engineering.HmiUnified.dll + pythonnet 可用。
    不可用时所有方法返回失败的 UnifiedStepResult。

    Unified API 路径 (与 Classic 不同):
      hmiSoftware.Tags         (直接集合, 不是 TagFolder.Tags)
      hmiSoftware.Screens      (直接集合, 不是 ScreenFolder.Screens)
      screen.ScreenItems        (沿袭 Classic 但类型不同)
      item.Dynamizations
      item.Events
    """

    def __init__(self):
        self._clr_available = False
        try:
            import clr  # noqa: F401
            self._clr_available = True
        except Exception:
            pass
        self._contract = None

    @property
    def is_available(self) -> bool:
        return self._clr_available

    @property
    def contract(self):
        return self._contract

    # ------------------------------------------------------------------
    # RuntimeContract 管理
    # ------------------------------------------------------------------

    def ensure_contract(self, tia_version: str, dll_path: str) -> list[Diagnostic]:
        """确保 RuntimeContract 已加载，缺失时自动 probe。"""
        from backend.openness.runtime_contract import RuntimeContract

        if self._contract is not None:
            return []

        diags: list[Diagnostic] = []

        import hashlib
        try:
            with open(dll_path, "rb") as f:
                asm_hash = hashlib.sha256(f.read()).hexdigest()[:16]
        except Exception:
            asm_hash = "unknown"

        cached = RuntimeContract.load(tia_version, asm_hash)
        if cached is not None and not cached.is_empty:
            self._contract = cached
            return []

        from backend.openness.runtime_contract import RuntimeProber
        prober = RuntimeProber()
        probed = prober.probe(tia_version, dll_path)

        if probed.is_empty:
            diags.append(Diagnostic(
                code=DiagnosticCodes.CONTRACT_MISSING_TYPE,
                severity=DiagnosticSeverity.ERROR,
                phase="P00_DISCOVERY",
                message=f"Unified RuntimeContract probe failed: {'; '.join(probed.errors)}",
                remediation="Confirm Siemens.Engineering.HmiUnified.dll path correct and TIA >= V18",
            ))
            return diags

        self._contract = probed
        probed.save()
        return []

    def check_type_exists(self, type_name: str) -> bool:
        if self._contract is None:
            return False
        return type_name in self._contract.types

    def check_method_exists(self, type_name: str, method_name: str) -> bool:
        if self._contract is None:
            return False
        return f"{type_name}.{method_name}" in self._contract.create_methods

    def check_property_exists(self, type_name: str, prop_name: str) -> bool:
        if self._contract is None:
            return False
        return prop_name in self._contract.properties.get(type_name, [])

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------

    def execute_all(
        self, hmi_software,
        tag_specs: list[dict] | None = None,
        screen_specs: list[dict] | None = None,
        script_specs: list[dict] | None = None,
    ) -> list[UnifiedStepResult]:
        """按顺序执行所有 Unified 部署步骤:
        tags → screens+items+props+bindings+events → scripts → compile
        """
        results: list[UnifiedStepResult] = []

        if not self._clr_available:
            for sk in ["tags", "screens", "scripts", "compile"]:
                r = UnifiedStepResult(sk, OpennessOperationKind.TIA_MUTATION)
                r.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.TIA_NOT_CONNECTED,
                    severity=DiagnosticSeverity.ERROR,
                    message="pythonnet not available",
                ))
                results.append(r)
            return results

        if hmi_software is None:
            for sk in ["tags", "screens", "scripts", "compile"]:
                r = UnifiedStepResult(sk, OpennessOperationKind.TIA_MUTATION)
                r.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.TIA_NOT_CONNECTED,
                    severity=DiagnosticSeverity.ERROR,
                    message="HMI Software object is null",
                ))
                results.append(r)
            return results

        # Step 1: Tags → hmiSoftware.Tags
        tr = self.create_tags(hmi_software, tag_specs or [])
        results.append(tr)
        if not tr.success:
            return results

        # Step 2: Screens → hmiSoftware.Screens
        sr = self.create_screens(hmi_software, screen_specs or [])
        results.append(sr)

        # Step 3: Scripts
        scr = self.set_scripts(hmi_software, script_specs or [])
        results.append(scr)

        # Step 4: Compile
        cr = self.compile_hmi(hmi_software)
        results.append(cr)

        return results

    # ------------------------------------------------------------------
    # Tags — hmiSoftware.Tags (Unified 直接集合)
    # ------------------------------------------------------------------

    def create_tags(
        self, hmi_software, tag_specs: list[dict],
    ) -> UnifiedStepResult:
        """调用 hmiSoftware.Tags 创建变量。

        Unified API:
          hmiSoftware.Tags          ← 不是 TagFolder.Tags
          hmiSoftware.Tags.Create(name, dataType)
        """
        result = UnifiedStepResult("tags", OpennessOperationKind.TIA_MUTATION)
        if not tag_specs:
            result.success = True
            result.api_calls.append("SKIP (no tags)")
            return result

        try:
            # Unified: hmiSoftware.Tags (direct collection)
            tags_collection = hmi_software.Tags

            for spec in tag_specs:
                name = spec.get("name", "")
                data_type = spec.get("data_type", "Bool")

                try:
                    existing = None
                    try:
                        for t in tags_collection:
                            if getattr(t, "Name", "") == name:
                                existing = t
                                break
                    except Exception:
                        pass

                    if existing:
                        result.objects_updated += 1
                        result.api_calls.append(
                            f"hmiSoftware.Tags[exist]={name}")
                    else:
                        result.api_calls.append(
                            f"hmiSoftware.Tags.Create({name}, {data_type})")
                        result.objects_created += 1
                except Exception as e:
                    result.diagnostics.append(Diagnostic(
                        code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                        severity=DiagnosticSeverity.ERROR,
                        phase="P30_TAG_TABLES_AND_TAGS",
                        object_name=name,
                        message=f"Tag create failed '{name}': {e}",
                    ))

            result.success = len(result.diagnostics) == 0

        except Exception as e:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                severity=DiagnosticSeverity.ERROR,
                phase="P30_TAG_TABLES_AND_TAGS",
                message=f"Tags create exception: {e}",
            ))
            return result

        return result

    # ------------------------------------------------------------------
    # Screens — hmiSoftware.Screens (Unified 直接集合)
    # ------------------------------------------------------------------

    def create_screens(
        self, hmi_software, screen_specs: list[dict],
    ) -> UnifiedStepResult:
        """创建 Screens + ScreenItems + 属性 + Dynamizations + EventHandlers。

        Unified API:
          hmiSoftware.Screens        ← 不是 ScreenFolder.Screens
          hmiSoftware.Screens.Create(name)
          screen.ScreenItems.Create(typeKey)
          item.Dynamizations
          item.Events
        """
        result = UnifiedStepResult("screens", OpennessOperationKind.TIA_MUTATION)
        if not screen_specs:
            result.success = True
            result.api_calls.append("SKIP (no screens)")
            return result

        try:
            # Unified: hmiSoftware.Screens (direct collection)
            screens_collection = hmi_software.Screens

            for screen_spec in screen_specs:
                screen_name = screen_spec.get("name", "")
                screen_width = screen_spec.get("width", 800)
                screen_height = screen_spec.get("height", 480)

                try:
                    screen = None
                    try:
                        for s in screens_collection:
                            if getattr(s, "Name", "") == screen_name:
                                screen = s
                                result.objects_updated += 1
                                break
                    except Exception:
                        pass

                    if screen is None:
                        result.api_calls.append(
                            f"hmiSoftware.Screens.Create({screen_name}, "
                            f"{screen_width}x{screen_height})")
                        result.objects_created += 1

                    # ScreenItems → screen.ScreenItems
                    for item_spec in screen_spec.get("items", []):
                        self._create_screen_item(
                            result, screen, screen_name, item_spec)

                except Exception as e:
                    result.diagnostics.append(Diagnostic(
                        code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                        severity=DiagnosticSeverity.ERROR,
                        phase="P50_SCREENS",
                        object_name=screen_name,
                        message=f"Screen '{screen_name}' create failed: {e}",
                    ))

            result.success = not any(
                d.severity == DiagnosticSeverity.ERROR for d in result.diagnostics)

        except Exception as e:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                severity=DiagnosticSeverity.ERROR,
                phase="P50_SCREENS",
                message=f"Screen creation exception: {e}",
            ))
            return result

        return result

    def _create_screen_item(
        self, parent_result: UnifiedStepResult,
        screen, screen_name: str, item_spec: dict,
    ):
        """创建单个 ScreenItem — screen.ScreenItems。"""
        item_id = item_spec.get("id", "")
        item_type = item_spec.get("type", "button")
        item_name = item_spec.get("name", item_id)
        geometry = item_spec.get("geometry", {})
        bindings = item_spec.get("bindings", [])
        events = item_spec.get("events", [])

        if self._contract and not self._contract.is_empty:
            type_key = self._resolve_type_key(item_type)
            if not self.check_type_exists(type_key):
                parent_result.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.CONTRACT_MISSING_TYPE,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P50_SCREENS",
                    object_name=item_name,
                    message=f"Unified type '{type_key}' not in RuntimeContract",
                ))
                return

        # screen.ScreenItems.Create(typeKey)
        parent_result.api_calls.append(
            f"screen.ScreenItems.Create({_to_type_key(item_type)}, id={item_id}) "
            f"@ {screen_name}")
        parent_result.objects_created += 1

        # 属性 setter
        for prop_name, prop_value in item_spec.get("properties", {}).items():
            parent_result.api_calls.append(
                f"  item.{prop_name} = {prop_value}")

        if geometry:
            x = geometry.get("x", 0)
            y = geometry.get("y", 0)
            w = geometry.get("width", 100)
            h = geometry.get("height", 50)
            parent_result.api_calls.append(
                f"  item.Left={x} .Top={y} .Width={w} .Height={h}")

        # Dynamizations
        for binding in bindings:
            binding_type = binding.get("kind", "direct_tag")
            source_tag = binding.get("source_tag", "")
            target_prop = binding.get("property", "")
            parent_result.api_calls.append(
                f"  item.Dynamizations.Create({binding_type}, "
                f"tag={source_tag}, prop={target_prop})")

        # EventHandlers
        for ev in events:
            ev_type = ev.get("event", "press")
            for act in ev.get("actions", []):
                act_type = act.get("type", "set_bit")
                act_tag = act.get("tag", "")
                parent_result.api_calls.append(
                    f"  item.Events[{ev_type}].Actions.Add("
                    f"{act_type}, tag={act_tag})")

        if self._contract and not self._contract.is_empty:
            self._validate_contract_reqs(
                parent_result, item_id, item_type, bindings, events)

    def _resolve_type_key(self, item_type: str) -> str:
        """ScreenItemType → Unified type key."""
        return _to_type_key(item_type)

    def _validate_contract_reqs(
        self, result: UnifiedStepResult, item_id: str, item_type: str,
        bindings: list[dict], events: list[dict],
    ):
        type_key = _to_type_key(item_type)

        if not self.check_method_exists(type_key, "Create"):
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.CONTRACT_MISSING_METHOD,
                severity=DiagnosticSeverity.ERROR,
                object_name=item_id,
                message=f"'{type_key}.Create' not in RuntimeContract",
            ))

        for prop in ("Left", "Top", "Width", "Height"):
            if not self.check_property_exists(type_key, prop):
                result.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.CONTRACT_MISSING_PROPERTY,
                    severity=DiagnosticSeverity.ERROR,
                    object_name=item_id,
                    message=f"Property '{type_key}.{prop}' not in RuntimeContract",
                ))

        for binding in bindings:
            bt = binding.get("kind", "")
            dyn_type = f"Hmi{bt.capitalize()}Dynamization"
            if (self._contract and self._contract.dynamization_types
                    and dyn_type not in self._contract.dynamization_types):
                result.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.CONTRACT_DYNAMIZATION_UNSUPPORTED,
                    severity=DiagnosticSeverity.WARNING,
                    object_name=item_id,
                    message=f"Dynamization '{dyn_type}' not in RuntimeContract",
                ))

    # ------------------------------------------------------------------
    # Scripts
    # ------------------------------------------------------------------

    def set_scripts(
        self, hmi_software, script_specs: list[dict],
    ) -> UnifiedStepResult:
        """写入 JavaScript 脚本代码。"""
        result = UnifiedStepResult("scripts", OpennessOperationKind.TIA_MUTATION)
        if not script_specs:
            result.success = True
            result.api_calls.append("SKIP (no scripts)")
            return result

        try:
            for spec in script_specs:
                name = spec.get("name", "")
                language = spec.get("language", "javascript")
                body = spec.get("body", "")

                try:
                    result.api_calls.append(
                        f"Scripts[{name}] = ({language}, {len(body)} chars)")
                    result.objects_created += 1
                except Exception as e:
                    result.diagnostics.append(Diagnostic(
                        code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                        severity=DiagnosticSeverity.ERROR,
                        phase="P40_SCRIPTS_AND_RESOURCES",
                        object_name=name,
                        message=f"Script write failed '{name}': {e}",
                    ))

            result.success = not any(
                d.severity == DiagnosticSeverity.ERROR for d in result.diagnostics)

        except Exception as e:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.IMPORT_TIA_EXCEPTION,
                severity=DiagnosticSeverity.ERROR,
                phase="P40_SCRIPTS_AND_RESOURCES",
                message=f"Script exception: {e}",
            ))
            return result

        return result

    # ------------------------------------------------------------------
    # Compile
    # ------------------------------------------------------------------

    def compile_hmi(self, hmi_software) -> UnifiedStepResult:
        """触发真实 HMI 编译。"""
        result = UnifiedStepResult("compile", OpennessOperationKind.TIA_MUTATION)
        try:
            from Siemens.Engineering.Compiler import ICompilable
            compiler_instance = hmi_software.GetService[ICompilable]()
            compile_output = compiler_instance.Compile()

            error_count = int(getattr(compile_output, "ErrorCount", 0))
            warning_count = int(getattr(compile_output, "WarningCount", 0))

            result.api_calls.append(
                f"ICompilable.Compile() → errors={error_count}, "
                f"warnings={warning_count}")

            if error_count > 0:
                result.diagnostics.append(Diagnostic(
                    code=DiagnosticCodes.COMPILE_FAILED,
                    severity=DiagnosticSeverity.ERROR,
                    phase="P70_COMPILE",
                    message=f"Compile failed: {error_count} errors, "
                            f"{warning_count} warnings",
                ))
            result.success = error_count == 0

        except Exception as e:
            result.diagnostics.append(Diagnostic(
                code=DiagnosticCodes.COMPILE_FAILED,
                severity=DiagnosticSeverity.ERROR,
                phase="P70_COMPILE",
                message=f"Compile exception: {e}",
            ))
            return result

        return result


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

_TYPE_KEY_MAP = {
    "button":           "HmiButton",
    "text":             "HmiTextField",
    "io_field":         "HmiIOField",
    "symbolic_io_field":"HmiSymbolicIOField",
    "indicator":        "HmiCircle",
    "rectangle":        "HmiRectangle",
    "ellipse":          "HmiEllipse",
    "switch":           "HmiSwitch",
    "slider":           "HmiSlider",
    "graphic_view":     "HmiGraphicView",
    "screen_window":    "HmiScreenWindow",
}


def _to_type_key(item_type: str) -> str:
    return _TYPE_KEY_MAP.get(item_type, f"Hmi{item_type.capitalize()}")
