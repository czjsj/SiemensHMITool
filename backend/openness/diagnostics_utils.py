# -*- coding: utf-8 -*-
"""
诊断工具模块 — 异常链收集、.NET 对象描述、Tag 枚举、XML 结构检查。

提供变量导入流程中需要的所有诊断辅助函数，
用于精确定位 Import 失败的根因。
"""

from __future__ import annotations

import hashlib
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


def _safe_attr(obj, name: str) -> str | None:
    """安全获取对象属性，不抛出异常。"""
    try:
        value = getattr(obj, name, None)
        return None if value is None else str(value)
    except Exception:
        return None


def _safe_dotnet_type(obj) -> str | None:
    """安全获取 .NET 对象的 FullName 类型。"""
    try:
        return str(obj.GetType().FullName)
    except Exception:
        return None


def collect_exception_chain(exc: BaseException) -> list[dict[str, Any]]:
    """递归收集 Python + .NET 异常链。
    
    遍历 InnerException / __cause__ / __context__ 直到链尾。
    """
    result = []
    current = exc
    visited = set()

    while current is not None and id(current) not in visited:
        visited.add(id(current))

        entry: dict[str, Any] = {
            "python_type": type(current).__name__,
            "message": str(current),
            "dotnet_type": _safe_dotnet_type(current),
            "stack_trace": _safe_attr(current, "StackTrace"),
            "source": _safe_attr(current, "Source"),
        }
        result.append(entry)

        # 优先 .NET InnerException，其次 Python __cause__ / __context__
        current = (
            getattr(current, "InnerException", None)
            or getattr(current, "__cause__", None)
            or getattr(current, "__context__", None)
        )

    return result


def describe_dotnet_object(obj) -> dict[str, Any] | None:
    """描述 .NET 对象的类型、程序集、名称等信息。
    
    返回 None 如果 obj 为 None。
    """
    if obj is None:
        return None

    result: dict[str, Any] = {
        "python_type": type(obj).__name__,
    }

    try:
        dotnet_type = obj.GetType()
        result.update({
            "dotnet_full_name": str(dotnet_type.FullName),
            "assembly": str(dotnet_type.Assembly.FullName),
        })
    except Exception as exc:
        result["reflection_error"] = str(exc)

    try:
        result["name"] = str(obj.Name)
    except Exception:
        pass

    return result


def enumerate_tag_names(tags) -> list[str]:
    """安全枚举 Tags 集合中所有变量名称。
    
    参数:
        tags: DefaultTagTable.Tags 或类似可迭代集合
        
    返回:
        变量名列表，无法读取时标记为 '<unreadable>'
    """
    result = []
    try:
        for tag in tags:
            try:
                result.append(str(tag.Name))
            except Exception:
                result.append("<unreadable>")
    except Exception:
        pass
    return result


def find_tag(tags, name: str):
    """在 Tags 集合中按名称查找变量。
    
    返回找到的 tag 对象或 None。
    """
    try:
        # 先尝试 Find 方法（如果存在）
        if hasattr(tags, "Find"):
            try:
                found = tags.Find(name)
                if found is not None:
                    return found
            except Exception:
                pass
        # 回退：遍历查找
        for tag in tags:
            try:
                if str(tag.Name) == name:
                    return tag
            except Exception:
                continue
    except Exception:
        pass
    return None


def inspect_xml_document(xml_path: str) -> dict[str, Any]:
    """XML 结构诊断 — 提取根标签、命名空间、BOM、对象类型等。
    
    用于对比真实 TIA 导出 XML 与系统生成 XML 的结构差异。
    """
    result: dict[str, Any] = {
        "path": str(Path(xml_path).resolve()),
        "exists": os.path.isfile(xml_path),
    }

    if not result["exists"]:
        return result

    raw = Path(xml_path).read_bytes()
    result.update({
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bom": _detect_bom(raw),
        "encoding": _detect_xml_encoding(raw),
    })

    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        result.update({
            "root_tag": root.tag,
            "root_local_name": _local_name(root.tag),
            "root_attributes": dict(root.attrib),
            "namespaces": _extract_namespaces(raw),
            "object_types": sorted({
                _local_name(element.tag)
                for element in root.iter()
                if "." in _local_name(element.tag)
            }),
            "composition_names": sorted({
                element.attrib["CompositionName"]
                for element in root.iter()
                if "CompositionName" in element.attrib
            }),
            "element_count": sum(1 for _ in root.iter()),
        })
    except Exception as exc:
        result["parse_error"] = str(exc)

    return result


def _detect_bom(raw: bytes) -> str | None:
    """检测文件 BOM 类型。"""
    if raw.startswith(b"\xef\xbb\xbf"):
        return "UTF-8-BOM"
    if raw.startswith(b"\xff\xfe"):
        return "UTF-16-LE-BOM"
    if raw.startswith(b"\xfe\xff"):
        return "UTF-16-BE-BOM"
    return None


def _detect_xml_encoding(raw: bytes) -> str | None:
    """从 XML declaration 中提取 encoding 声明。"""
    try:
        # 只看前 200 字节
        header = raw[:200].decode("ascii", errors="replace")
        if "encoding=" in header:
            start = header.index("encoding=") + len("encoding=")
            quote = header[start]
            end = header.index(quote, start + 1)
            return header[start + 1:end]
    except Exception:
        pass
    return None


def _local_name(tag: str) -> str:
    """提取去除命名空间后的本地标签名。"""
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _extract_namespaces(raw: bytes) -> list[str]:
    """提取 XML 中声明的命名空间 URI。"""
    namespaces = []
    try:
        text = raw[:2000].decode("utf-8", errors="replace")
        import re
        for match in re.finditer(r'xmlns(?::\w+)?="([^"]+)"', text):
            ns = match.group(1)
            if ns not in namespaces:
                namespaces.append(ns)
    except Exception:
        pass
    return namespaces
