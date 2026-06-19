# -*- coding: utf-8 -*-
"""
生成摘要服务 — V4.0 API 响应结构。

从 HmiProjectSpec 或 legacy IR 提取：
  - understanding: AI 理解结果摘要
  - tags: 变量表
  - bindings: 控件绑定表
  - deployment: 导入/编译/验证结果摘要
"""

from __future__ import annotations

from typing import Any

from backend.domain.ir_v2 import HmiProjectSpec
from backend.domain.enums import ScreenItemType


def build_generation_summary(
    project: HmiProjectSpec,
    deployment_result: dict | None = None,
) -> dict[str, Any]:
    """构建完整的 V4.0 生成结果摘要。

    返回结构:
        {
            "understanding": {...},   # AI 理解结果
            "tags": [...],            # 变量表
            "bindings": [...],        # 控件绑定表
            "deployment": {...},      # 导入/编译/验证结果
        }
    """
    # ---- 1. Understanding (AI 理解结果) ----
    all_items = []
    for screen in project.screens:
        all_items.extend(screen.items)

    button_count = sum(1 for i in all_items if i.type == ScreenItemType.BUTTON)
    indicator_count = sum(1 for i in all_items if i.type == ScreenItemType.INDICATOR)
    io_count = sum(1 for i in all_items if i.type in (ScreenItemType.IO_FIELD, ScreenItemType.SYMBOLIC_IO_FIELD))
    text_count = sum(1 for i in all_items if i.type == ScreenItemType.TEXT)

    understanding = {
        "screen_count": len(project.screens),
        "screen_names": [s.name for s in project.screens],
        "screen_titles": [
            (s.name, s.name) for s in project.screens
        ],
        "items_count": len(all_items),
        "button_count": button_count,
        "indicator_count": indicator_count,
        "io_field_count": io_count,
        "text_count": text_count,
        "tag_count": len(project.tags),
        "connection_count": len(project.connections),
        "script_count": len(project.scripts),
    }

    # ---- 2. Tags (变量表) ----
    tags = []
    for t in project.tags:
        tags.append({
            "name": t.name,
            "data_type": t.data_type,
            "direction": t.direction.value if t.direction else "read_write",
            "scope": t.scope.value if t.scope else "internal",
            "address": t.address,
            "connection": t.connection,
            "pending_mapping": t.metadata.get("pending_mapping", False) if t.metadata else False,
            "comment": t.comment.get("zh-CN", "") if t.comment else "",
        })

    # ---- 3. Bindings (控件绑定表) ----
    bindings = []
    for screen in project.screens:
        for item in screen.items:
            item_type = item.type.value if hasattr(item.type, "value") else str(item.type)
            binding_entry = {
                "item_id": item.id,
                "item_name": item.name or item.id,
                "item_type": item_type,
                "template_ref": item.template_ref,
                "behavior": item.behavior.value if item.behavior else None,
                "indicator_mode": item.indicator_mode.value if item.indicator_mode else None,
                "tag": item.tag_binding or "",
                "event_count": len(item.events),
                "binding_count": len(item.bindings),
            }

            # 事件摘要
            event_summaries = []
            for ev in item.events:
                ev_name = ev.event.value if hasattr(ev.event, "value") else str(ev.event)
                actions = [
                    f"{a.type.value if hasattr(a.type, 'value') else str(a.type)}"
                    + (f"({a.tag})" if a.tag else "")
                    for a in ev.actions
                ]
                event_summaries.append(f"{ev_name}: {', '.join(actions)}")
            binding_entry["event_summary"] = "; ".join(event_summaries)

            # 绑定摘要
            binding_summaries = []
            for b in item.bindings:
                prop = b.property or "?"
                kind = b.kind.value if hasattr(b.kind, "value") else str(b.kind)
                tag = b.source_tag or b.tag or ""
                binding_summaries.append(f"{prop}({kind} → {tag})")
            binding_entry["binding_summary"] = "; ".join(binding_summaries)

            bindings.append(binding_entry)

    # ---- 4. Deployment (导入结果摘要) ----
    deployment = {}
    if deployment_result:
        dep = deployment_result
        deployment = {
            "status": dep.get("status", "unknown"),
            "tags_imported": dep.get("summary", {}).get("tags_created", 0) > 0,
            "screen_imported": dep.get("summary", {}).get("screens_created", 0) > 0,
            "compile_success": dep.get("compile", {}).get("errors", -1) == 0,
            "verify_success": dep.get("verification", {}).get("success", False) if dep.get("verification") else None,
            "compile_errors": dep.get("compile", {}).get("errors", 0),
            "compile_warnings": dep.get("compile", {}).get("warnings", 0),
            "tags_created": dep.get("summary", {}).get("tags_created", 0),
            "screens_created": dep.get("summary", {}).get("screens_created", 0),
            "diagnostics_count": len(dep.get("diagnostics", [])),
            "error_count": len([d for d in dep.get("diagnostics", []) if d.get("severity") == "error"]),
        }

    return {
        "understanding": understanding,
        "tags": tags,
        "bindings": bindings,
        "deployment": deployment,
    }


def build_legacy_summary(ir: dict) -> dict[str, Any]:
    """从旧 IR dict 构建简化摘要（向后兼容）。"""
    objects = ir.get("objects") or []
    tags = ir.get("tags") or []

    button_count = sum(1 for o in objects if o.get("type", "").lower() == "button")
    indicator_count = sum(1 for o in objects if o.get("type", "").lower() == "indicator")

    return {
        "understanding": {
            "screen_name": ir.get("meta", {}).get("screen_name", ""),
            "items_count": len(objects),
            "button_count": button_count,
            "indicator_count": indicator_count,
            "tag_count": len(tags),
        },
        "tags": [
            {
                "name": t.get("name", ""),
                "data_type": t.get("data_type", "?"),
                "address": t.get("address") or None,
            }
            for t in tags
        ],
        "bindings": [
            {
                "item_id": o.get("id", "?"),
                "item_type": o.get("type", "?"),
                "tag": o.get("process_tag", ""),
            }
            for o in objects
        ],
        "deployment": {},
    }
