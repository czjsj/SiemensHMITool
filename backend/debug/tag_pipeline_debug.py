# -*- coding: utf-8 -*-
"""
Tag Pipeline Debug — 变量管道日志和诊断摘要。

日志点覆盖:
  1. after_llm_extract_json
  2. before_validate_ir
  3. after_validate_ir
  4. before_variable_engine
  5. after_variable_engine
  6. before_validate_ir_v2
  7. after_validate_ir_v2
  8. before_build_plan
  9. after_build_plan
  10. before_tag_import
  11. after_tag_import
  12. before_screen_import
  13. after_screen_import
  14. after_compile
  15. after_verify

每个日志至少包含:
  {
    "tag_count": ...,
    "tag_names": [...],
    "object_count": ...,
    "object_refs": [...],
    "missing_tags": [...],
    "template_leaks": [...]
  }
"""

from __future__ import annotations

from typing import Any

# 须排除的敏感字段
_SENSITIVE_KEYS = {"api_key", "password", "token", "secret", "authorization"}


# ---------------------------------------------------------------------------
# Legacy IR 摘要
# ---------------------------------------------------------------------------


def summarize_legacy_ir_tags(ir: dict) -> dict:
    """从 legacy IR 生成变量摘要。"""
    from backend.tag_binding_normalizer import summarize_legacy_ir_tags as _summarize
    return _summarize(ir)


# ---------------------------------------------------------------------------
# HmiProjectSpec 摘要
# ---------------------------------------------------------------------------


def summarize_project_tags(project) -> dict:
    """从 HmiProjectSpec 生成变量摘要。"""
    tags_summary = []
    for t in getattr(project, "tags", []):
        tags_summary.append({
            "name": t.name,
            "data_type": t.data_type,
            "scope": t.scope.value if hasattr(t.scope, "value") else str(t.scope),
            "address": getattr(t, "address", None) or "",
            "comment": t.comment.get("zh-CN", "") if t.comment else "",
        })

    object_refs = []
    template_leaks: list[str] = []
    missing_tags: list[str] = []

    tag_names = {t.name for t in getattr(project, "tags", [])}

    for screen in getattr(project, "screens", []):
        for item in getattr(screen, "items", []):
            bt = getattr(item, "tag_binding", "") or ""
            itype = item.type.value if hasattr(item.type, "value") else str(item.type)

            object_refs.append({
                "id": item.id,
                "name": getattr(item, "name", "") or item.id,
                "type": itype,
                "binding_tag": bt,
            })

            if bt and bt not in tag_names:
                missing_tags.append(bt)

            if bt and "Template_" in bt:
                template_leaks.append(bt)

    return {
        "tag_count": len(getattr(project, "tags", [])),
        "tag_names": [t.name for t in getattr(project, "tags", [])],
        "tags": tags_summary,
        "object_count": len(object_refs),
        "object_refs": object_refs,
        "missing_tags": sorted(set(missing_tags)),
        "template_leaks": sorted(set(template_leaks)),
    }


# ---------------------------------------------------------------------------
# 部署结果摘要
# ---------------------------------------------------------------------------


def summarize_deployment_tag_result(result: dict) -> dict:
    """从部署结果生成变量阶段摘要。"""
    summary = result.get("summary", {})
    details = result.get("details", {})

    tags_created = summary.get("tags_created", 0)
    screens_created = summary.get("screens_created", 0)

    # 提取 P30 / P50 阶段结果
    step_results = details.get("step_results", [])
    tag_step = None
    screen_step = None
    for sr in step_results:
        phase = sr.get("phase", "")
        if "P30" in phase or "TAG" in phase.upper():
            tag_step = sr
        if "P50" in phase or "SCREEN" in phase.upper():
            screen_step = sr

    return {
        "deployment": {
            "p30_tags": {
                "status": tag_step.get("status", "unknown") if tag_step else "missing",
                "generated": tags_created,
                "imported": tag_step.get("objects_created", 0) if tag_step else 0,
                "missing": details.get("missing_tags", []),
            },
            "p50_screen": {
                "status": screen_step.get("status", "unknown") if screen_step else "missing",
                "imported": screens_created,
            },
            "compile": {
                "status": result.get("compile", {}).get("errors", -1) == 0,
            },
            "verify": {
                "status": result.get("verification", {}).get("success", False),
            },
        },
    }


# ---------------------------------------------------------------------------
# 管道日志记录器
# ---------------------------------------------------------------------------


class TagPipelineLogger:
    """变量管道日志器 — 在管线各阶段记录 tag 状态。

    用法:
        logger = TagPipelineLogger()
        logger.log("after_llm_extract_json", ir=ir)
        ...
        logger.log("after_verify", result=deploy_result)
        logger.flush()  # 获取完整日志
    """

    def __init__(self):
        self._entries: list[dict] = []

    def log(
        self,
        stage: str,
        ir: dict | None = None,
        project=None,
        plan=None,
        result: dict | None = None,
        extra: dict | None = None,
    ):
        """记录一个管线阶段的 tag 状态。"""
        entry: dict[str, Any] = {
            "stage": stage,
            "timestamp": "",  # 由调用方填入
        }

        if ir is not None:
            entry["legacy_ir"] = summarize_legacy_ir_tags(ir)

        if project is not None:
            entry["project"] = summarize_project_tags(project)

        if plan is not None:
            tag_steps = [s for s in getattr(plan, "steps", [])
                         if "TAG" in getattr(s, "phase", "").upper()
                         or "TAG" in getattr(s, "operation", "").upper()]
            screen_steps = [s for s in getattr(plan, "steps", [])
                            if "SCREEN" in getattr(s, "phase", "").upper()
                            or "SCREEN" in getattr(s, "operation", "").upper()]
            entry["plan"] = {
                "total_steps": len(getattr(plan, "steps", [])),
                "tag_steps": len(tag_steps),
                "screen_steps": len(screen_steps),
                "tag_before_screen": all(
                    getattr(plan, "steps", []).index(ts) < getattr(plan, "steps", []).index(ss)
                    for ts in tag_steps for ss in screen_steps
                ) if tag_steps and screen_steps else None,
            }

        if result is not None:
            entry["result"] = summarize_deployment_tag_result(result)

        if extra is not None:
            entry["extra"] = {
                k: v for k, v in extra.items()
                if k.lower() not in _SENSITIVE_KEYS
            }

        self._entries.append(entry)

    def flush(self) -> list[dict]:
        """返回并清空所有日志条目。"""
        entries = list(self._entries)
        self._entries.clear()
        return entries

    @property
    def entries(self) -> list[dict]:
        return list(self._entries)
