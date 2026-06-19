# -*- coding: utf-8 -*-
"""
ObjectQueryService — 从 TIA 项目重新读取真实对象（只读，永无副作用）。

原则:
  1. 只读 — 永不允许调用 Compile() 或任何修改操作。
  2. 不重新编译 — compile messages 必须由外部传入 compiled_result。
  3. 路径感知 — Classic vs Unified 走不同 API 路径。
  4. 持久化 — 查询结果、编译消息、快照落盘为 JSON。
  5. 反向导出 — 可导出 Screens XML 用于对比验证。

Classic 路径 (V3.2 修复):
  hmiSoftware.TagFolder.DefaultTagTable.Tags    ← 默认变量表
  hmiSoftware.TagFolder.TagTables[i].Tags       ← 自定义变量表
  hmiSoftware.ScreenFolder.Screens
  hmiSoftware.ScriptFolder.Scripts

  禁止: hmiSoftware.TagFolder.Tags (Classic 不支持此直接路径)

Unified 路径:
  hmiSoftware.Tags       (直接集合)
  hmiSoftware.Screens    (直接集合)
  hmiSoftware.Scripts    (直接集合, 如果有)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any


class ObjectQueryService:
    """从真实 TIA 项目读取对象（只读）。"""

    def __init__(self, export_dir: str = ""):
        self._clr_available = False
        try:
            import clr  # noqa: F401
            self._clr_available = True
        except Exception:
            pass
        self._export_dir = export_dir or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "..", "exports", "tia_query",
        )

    @property
    def is_available(self) -> bool:
        return self._clr_available

    # ------------------------------------------------------------------
    # 完整查询 — 只读
    # ------------------------------------------------------------------

    def query_full_snapshot(
        self, hmi_software,
        compiled_result: dict | None = None,
        family: str = "comfort",
    ) -> dict[str, Any]:
        """查询完整项目快照（只读）。

        compiled_result: 已编译的结果 dict（来自 HmiCompiler.compile()）。
                         不可为 None 时内部调用 Compile()。
        family: "basic" | "comfort" | "unified" — 决定 API 路径。
        """
        if not self._clr_available or hmi_software is None:
            return _empty_snapshot("NOT_CONNECTED: cannot query TIA objects")

        unified = family == "unified"

        tags = self.query_tags(hmi_software, unified=unified)
        screens = self.query_screens(hmi_software, unified=unified)
        events = self.query_event_handlers(hmi_software, unified=unified)
        bindings = self.query_dynamizations(hmi_software, unified=unified)
        scripts = self.query_scripts(hmi_software, unified=unified)

        # compile messages: 只能从外部传入，绝不内部调用 Compile()
        if compiled_result is None:
            compile_msgs = {
                "errors": -1, "warnings": -1,
                "messages": [{"severity": "Info",
                              "description": "No compiled_result provided — query service never compiles.",
                              "path": "", "object_name": ""}],
            }
        else:
            compile_msgs = compiled_result

        return {
            "tags": tags,
            "screens": screens,
            "events": events,
            "bindings": bindings,
            "scripts": scripts,
            "compile": compile_msgs,
        }

    # ------------------------------------------------------------------
    # Tags 查询
    # ------------------------------------------------------------------

    def query_tags(
        self, hmi_software, unified: bool = False,
    ) -> list[dict[str, Any]]:
        """从 TIA 项目读取所有 HMI Tags。

        Classic (V3.2 修复):
          遍历 DefaultTagTable.Tags + 所有 TagTables[i].Tags
          禁止: hmiSoftware.TagFolder.Tags (Classic 不支持此直接路径)

        Unified:
          hmiSoftware.Tags (直接集合)
        """
        tags: list[dict[str, Any]] = []
        if not self._clr_available or hmi_software is None:
            return tags

        try:
            if unified:
                # Unified: direct collection
                tags_collection = hmi_software.Tags
                for tag in tags_collection:
                    entry = self._read_tag_entry(tag, table_name="", is_default_table=True)
                    tags.append(entry)
            else:
                # Classic: 遍历 DefaultTagTable + 所有自定义 TagTables
                tags.extend(self._query_classic_tags(hmi_software))
        except Exception:
            pass

        return tags

    def _query_classic_tags(self, hmi_software) -> list[dict[str, Any]]:
        """Classic 路径: 遍历 DefaultTagTable.Tags + TagTables[i].Tags。

        禁止: hmiSoftware.TagFolder.Tags
        """
        result: list[dict[str, Any]] = []
        visited_table_names: set[str] = set()

        tag_folder = hmi_software.TagFolder

        # 1. 默认变量表
        default_table = tag_folder.DefaultTagTable
        if default_table is not None:
            table_name = "DefaultTagTable"
            try:
                for tag in default_table.Tags:
                    entry = self._read_tag_entry(tag, table_name=table_name, is_default_table=True)
                    result.append(entry)
            except Exception:
                pass
            visited_table_names.add(table_name)

        # 2. 自定义变量表
        try:
            for table in tag_folder.TagTables:
                try:
                    table_name = str(getattr(table, "Name", ""))
                except Exception:
                    table_name = ""

                if table_name in visited_table_names:
                    continue
                visited_table_names.add(table_name)

                try:
                    for tag in table.Tags:
                        entry = self._read_tag_entry(tag, table_name=table_name, is_default_table=False)
                        result.append(entry)
                except Exception:
                    pass
        except Exception:
            pass

        return result

    @staticmethod
    def _read_tag_entry(
        tag, table_name: str = "", is_default_table: bool = True,
    ) -> dict[str, Any]:
        """读取单个 Tag 的快照条目。

        V3.2: 新增 table_name 和 is_default_table 字段。
        """
        entry: dict[str, Any] = {
            "name": str(getattr(tag, "Name", "")),
            "data_type": "", "connection": "",
            "scope": "internal", "controller_tag": "",
            "table_name": table_name,
            "is_default_table": is_default_table,
        }
        try:
            entry["data_type"] = str(getattr(tag, "DataType", ""))
        except Exception:
            pass
        try:
            conn = getattr(tag, "Connection", None)
            if conn:
                entry["connection"] = str(getattr(conn, "Name", ""))
        except Exception:
            pass
        try:
            if getattr(tag, "Length", None) is not None or entry["connection"]:
                entry["scope"] = "external"
        except Exception:
            pass
        try:
            ctrl_tag = getattr(tag, "ControllerTag", None)
            if ctrl_tag:
                entry["controller_tag"] = str(getattr(ctrl_tag, "Name", ""))
        except Exception:
            pass
        return entry

    # ------------------------------------------------------------------
    # Screens 查询
    # ------------------------------------------------------------------

    def query_screens(
        self, hmi_software, unified: bool = False,
    ) -> list[dict[str, Any]]:
        """从 TIA 项目读取所有 Screens 及 ScreenItems。

        Classic:  hmiSoftware.ScreenFolder.Screens
        Unified:  hmiSoftware.Screens
        """
        screens: list[dict[str, Any]] = []
        if not self._clr_available or hmi_software is None:
            return screens

        try:
            if unified:
                screens_collection = hmi_software.Screens
            else:
                screens_collection = hmi_software.ScreenFolder.Screens

            for screen in screens_collection:
                entry: dict[str, Any] = {
                    "name": str(getattr(screen, "Name", "")),
                    "width": 0, "height": 0,
                    "items": [],
                }
                try:
                    entry["width"] = int(getattr(screen, "Width", 0))
                    entry["height"] = int(getattr(screen, "Height", 0))
                except Exception:
                    pass
                entry["items"] = self.query_screen_items(screen)
                screens.append(entry)
        except Exception:
            pass

        return screens

    def query_screen_items(self, screen) -> list[dict[str, Any]]:
        """查询单个 Screen 中所有 ScreenItems。"""
        items: list[dict[str, Any]] = []
        try:
            for item in screen.ScreenItems:
                entry: dict[str, Any] = {
                    "name": str(getattr(item, "Name", "")),
                    "type": "",
                    "x": 0, "y": 0,
                    "width": 0, "height": 0,
                }
                try:
                    entry["type"] = type(item).__name__.replace(
                        "Hmi", "").lower()
                except Exception:
                    entry["type"] = "unknown"
                for attr, key in [("Left", "x"), ("Top", "y"),
                                   ("Width", "width"), ("Height", "height")]:
                    try:
                        entry[key] = int(getattr(item, attr, 0))
                    except Exception:
                        pass
                items.append(entry)
        except Exception:
            pass
        return items

    # ------------------------------------------------------------------
    # Dynamizations 查询
    # ------------------------------------------------------------------

    def query_dynamizations(
        self, hmi_software, unified: bool = False,
    ) -> list[dict[str, Any]]:
        """从 TIA 项目读取所有 Dynamizations。"""
        dynamizations: list[dict[str, Any]] = []
        if not self._clr_available or hmi_software is None:
            return dynamizations

        try:
            screens_coll = (hmi_software.Screens if unified
                            else hmi_software.ScreenFolder.Screens)
            for screen in screens_coll:
                for item in screen.ScreenItems:
                    item_name = str(getattr(item, "Name", ""))
                    try:
                        for dyn in item.Dynamizations:
                            entry = self._read_dynamization_entry(
                                item_name, dyn)
                            dynamizations.append(entry)
                    except Exception:
                        pass
        except Exception:
            pass

        return dynamizations

    @staticmethod
    def _read_dynamization_entry(item_name: str, dyn) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "item_id": item_name,
            "property": "", "kind": "", "source_tag": "",
        }
        try:
            entry["kind"] = type(dyn).__name__.replace(
                "Dynamization", "").replace("Hmi", "").lower()
        except Exception:
            pass
        try:
            entry["property"] = str(getattr(dyn, "PropertyName", ""))
        except Exception:
            pass
        try:
            entry["source_tag"] = str(getattr(dyn, "TagName", ""))
        except Exception:
            try:
                tag = getattr(dyn, "Tag", None)
                if tag:
                    entry["source_tag"] = str(getattr(tag, "Name", ""))
            except Exception:
                pass
        return entry

    # ------------------------------------------------------------------
    # EventHandlers 查询
    # ------------------------------------------------------------------

    def query_event_handlers(
        self, hmi_software, unified: bool = False,
    ) -> list[dict[str, Any]]:
        """从 TIA 项目读取所有 EventHandlers。"""
        events: list[dict[str, Any]] = []
        if not self._clr_available or hmi_software is None:
            return events

        try:
            screens_coll = (hmi_software.Screens if unified
                            else hmi_software.ScreenFolder.Screens)
            for screen in screens_coll:
                for item in screen.ScreenItems:
                    item_name = str(getattr(item, "Name", ""))
                    try:
                        for ev in item.Events:
                            entry = self._read_event_entry(item_name, ev)
                            events.append(entry)
                    except Exception:
                        pass
        except Exception:
            pass

        return events

    @staticmethod
    def _read_event_entry(item_name: str, ev) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "item_id": item_name,
            "event": "", "action_type": "",
            "tag": "", "screen": "", "script": "",
        }
        try:
            entry["event"] = type(ev).__name__.replace(
                "Event", "").replace("Hmi", "").lower()
        except Exception:
            pass
        try:
            for act in ev.Actions:
                try:
                    entry["action_type"] = type(act).__name__.replace(
                        "Action", "").replace("Hmi", "").lower()
                except Exception:
                    pass
                for attr, key in [("TagName", "tag"),
                                   ("ScreenName", "screen"),
                                   ("ScriptName", "script")]:
                    try:
                        v = getattr(act, attr, None)
                        if v:
                            entry[key] = str(v)
                    except Exception:
                        pass
        except Exception:
            pass
        return entry

    # ------------------------------------------------------------------
    # Scripts 查询
    # ------------------------------------------------------------------

    def query_scripts(
        self, hmi_software, unified: bool = False,
    ) -> list[dict[str, Any]]:
        """从 TIA 项目读取所有 Scripts。

        Classic:  hmiSoftware.ScriptFolder.Scripts
        Unified:  根据实际 API — 可能直接 hmiSoftware.Scripts 或无
        """
        scripts: list[dict[str, Any]] = []
        if not self._clr_available or hmi_software is None:
            return scripts

        try:
            # Unified 优先尝试直接 Scripts，回退 ScriptFolder
            if unified and hasattr(hmi_software, "Scripts"):
                scripts_coll = hmi_software.Scripts
            else:
                scripts_coll = hmi_software.ScriptFolder.Scripts

            for script in scripts_coll:
                entry: dict[str, Any] = {
                    "name": str(getattr(script, "Name", "")),
                    "language": "", "body_length": 0,
                }
                try:
                    entry["language"] = str(
                        getattr(script, "Language", "")).lower()
                except Exception:
                    pass
                try:
                    body = getattr(script, "Code", "")
                    if body:
                        entry["body_length"] = len(str(body))
                except Exception:
                    pass
                scripts.append(entry)
        except Exception:
            pass

        return scripts

    # ------------------------------------------------------------------
    # 反向导出 — 部署后导出 Screens XML 用于对比
    # ------------------------------------------------------------------

    def export_screens_xml(
        self, hmi_software, unified: bool = False,
    ) -> list[dict[str, Any]]:
        """反向导出 Screens XML（只读，用于对比验证）。

        返回: [{"screen_name": str, "xml": str, "exported_at": iso}, ...]
        """
        exports: list[dict[str, Any]] = []
        if not self._clr_available or hmi_software is None:
            return exports

        ts = datetime.now(timezone.utc).isoformat()

        try:
            from System.IO import FileInfo
            import tempfile

            screens_coll = (hmi_software.Screens if unified
                            else hmi_software.ScreenFolder.Screens)

            for screen in screens_coll:
                screen_name = str(getattr(screen, "Name", ""))
                try:
                    fd, tmp = tempfile.mkstemp(
                        suffix=".xml", prefix=f"rev_export_{screen_name}_")
                    os.close(fd)

                    # Classic: screen.Export(FileInfo(path), ExportOptions)
                    export_opts = self._make_export_options()
                    file_info = FileInfo(tmp)

                    if export_opts:
                        screen.Export(file_info, export_opts)
                    else:
                        screen.Export(file_info)

                    with open(tmp, "r", encoding="utf-8") as f:
                        xml = f.read()

                    exports.append({
                        "screen_name": screen_name,
                        "xml": xml,
                        "exported_at": ts,
                        "temp_path": tmp,
                    })
                except Exception:
                    exports.append({
                        "screen_name": screen_name,
                        "xml": "",
                        "exported_at": ts,
                        "error": f"Export failed for {screen_name}",
                    })
        except Exception:
            pass

        return exports

    @staticmethod
    def _make_export_options():
        try:
            try:
                from Siemens.Engineering.Hmi import ExportOptions  # type: ignore
                return ExportOptions()
            except ImportError:
                pass
            from Siemens.Engineering import ExportOptions  # type: ignore
            return ExportOptions()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # 持久化 — 快照、编译消息、导入日志
    # ------------------------------------------------------------------

    def save_snapshot(
        self, snapshot: dict[str, Any], plan_id: str = "",
    ) -> str:
        """保存查询快照为 JSON。"""
        os.makedirs(self._export_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        fname = f"snapshot_{plan_id}_{ts}.json" if plan_id else f"snapshot_{ts}.json"
        path = os.path.join(self._export_dir, fname)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False, default=str)
        return path

    def save_compile_messages(
        self, compile_result: dict[str, Any], plan_id: str = "",
    ) -> str:
        """保存编译消息为 JSON。"""
        os.makedirs(self._export_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        fname = f"compile_{plan_id}_{ts}.json" if plan_id else f"compile_{ts}.json"
        path = os.path.join(self._export_dir, fname)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(compile_result, f, indent=2, ensure_ascii=False, default=str)
        return path

    def save_import_log(
        self, step_results: list[dict[str, Any]], plan_id: str = "",
    ) -> str:
        """保存导入步骤日志为 JSON。"""
        os.makedirs(self._export_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        fname = f"import_log_{plan_id}_{ts}.json" if plan_id else f"import_log_{ts}.json"
        path = os.path.join(self._export_dir, fname)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(step_results, f, indent=2, ensure_ascii=False, default=str)
        return path

    def save_reverse_export_xml(
        self, exports: list[dict[str, Any]], plan_id: str = "",
    ) -> list[str]:
        """保存反向导出的 Screens XML 到磁盘。"""
        os.makedirs(self._export_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        saved: list[str] = []
        for e in exports:
            sn = e.get("screen_name", "unknown")
            fname = f"rev_export_{sn}_{plan_id}_{ts}.xml" if plan_id else f"rev_export_{sn}_{ts}.xml"
            path = os.path.join(self._export_dir, fname)
            with open(path, "w", encoding="utf-8") as f:
                f.write(e.get("xml", ""))
            saved.append(path)
        return saved


def _empty_snapshot(reason: str) -> dict[str, Any]:
    return {
        "tags": [], "screens": [],
        "events": [], "bindings": [],
        "scripts": [],
        "compile": {"errors": 0, "warnings": 0,
                     "messages": [{"severity": "Info", "description": reason,
                                   "path": "", "object_name": ""}]},
    }
