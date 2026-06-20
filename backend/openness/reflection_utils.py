# -*- coding: utf-8 -*-
"""
.NET 方法反射工具。

通过 pythonnet/CLR 调用 System.Reflection 探测 .NET 对象的类型和方法。
所有函数 try/except 包裹，永不抛出；失败返回空结果 + 诊断信息。

使用示例:
    from backend.openness.reflection_utils import has_method, describe_dotnet_methods
    if has_method(tags_collection, "Create"):
        new_tag = tags_collection.Create(name, data_type)
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def describe_dotnet_methods(obj: Any) -> dict[str, Any]:
    """探测 .NET 对象的方法和属性，返回结构化字典。

    返回值:
        {
            "dotnet_type": "Siemens.Engineering.Hmi.TagComposition",
            "method_count": 42,
            "method_names": ["Create", "Delete", ...],
            "create_like_methods": ["Create", "CreateTag", ...],
            "import_like_methods": ["Import", "ImportXml", ...],
            "properties": {"Count": "System.Int32", "Name": "System.String"},
            "error": None,
        }
    """
    if obj is None:
        return {
            "dotnet_type": "None",
            "method_count": 0,
            "method_names": [],
            "create_like_methods": [],
            "import_like_methods": [],
            "properties": {},
            "error": None,
        }

    result: dict[str, Any] = {
        "dotnet_type": None,
        "method_count": 0,
        "method_names": [],
        "create_like_methods": [],
        "import_like_methods": [],
        "properties": {},
        "error": None,
    }

    try:
        dotnet_type = obj.GetType()
        result["dotnet_type"] = str(dotnet_type.FullName)

        try:
            methods = list(dotnet_type.GetMethods())
            result["method_count"] = len(methods)
            method_names = sorted({m.Name for m in methods})
            result["method_names"] = method_names
            result["create_like_methods"] = sorted({
                m.Name for m in methods if "Create" in m.Name
            })
            result["import_like_methods"] = sorted({
                m.Name for m in methods if "Import" in m.Name
            })
        except Exception as e:
            logger.debug("GetMethods() failed: %s", e)
            result["method_names"] = []
            result["method_count"] = 0

        # 探测关键属性
        try:
            for prop_name in ("Count", "Length", "Item", "Name"):
                try:
                    prop = dotnet_type.GetProperty(prop_name)
                    if prop is not None:
                        result["properties"][prop_name] = str(prop.PropertyType.FullName)
                except Exception:
                    pass
        except Exception as e:
            logger.debug("GetProperty scan failed: %s", e)

    except Exception as e:
        result["error"] = str(e)
        result["dotnet_type"] = str(type(obj).__name__)

    return result


def has_method(obj: Any, method_name: str) -> bool:
    """检查 .NET 对象是否包含指定名称的方法。

    策略:
      1. 优先 GetMethod(name) 精确查找。
      2. 回退 GetMethods() 名称过滤。
      3. 最后 pythonnet hasattr 兜底。

    参数:
        obj: .NET 对象。
        method_name: 方法名（如 "Create"）。

    返回:
        True 如果对象存在该方法，否则 False。
    """
    if obj is None:
        return False

    try:
        dotnet_type = obj.GetType()
        # 策略1: 精确方法查找
        try:
            method = dotnet_type.GetMethod(method_name)
            if method is not None:
                return True
        except Exception:
            pass

        # 策略2: 遍历所有方法进行名称匹配
        try:
            methods = list(dotnet_type.GetMethods())
            return any(m.Name == method_name for m in methods)
        except Exception:
            pass
    except Exception:
        pass

    # 策略3: pythonnet 的 hasattr 兜底
    try:
        return hasattr(obj, method_name)
    except Exception:
        return False


def list_method_overloads(obj: Any, method_name: str) -> list[dict[str, Any]]:
    """列出指定方法的所有重载签名，包括参数类型的 enum 信息。

    返回值:
        [
            {
                "return_type": "Siemens.Engineering.Hmi.Tag",
                "has_enum_param": True,
                "parameters": [
                    {
                        "name": "name",
                        "type": "System.String",
                        "is_enum": False,
                        "enum_names": None,
                    },
                    {
                        "name": "options",
                        "type": "Siemens.Engineering.ImportOptions",
                        "is_enum": True,
                        "enum_names": ["None", "Override", ...],
                    },
                ],
            },
            ...
        ]
    """
    if obj is None:
        return []

    overloads: list[dict[str, Any]] = []
    try:
        dotnet_type = obj.GetType()
        methods = [
            m for m in dotnet_type.GetMethods()
            if m.Name == method_name
        ]
        for method in methods:
            try:
                params = list(method.GetParameters())
                param_list = []
                has_enum = False
                for p in params:
                    p_info: dict[str, Any] = {
                        "name": p.Name,
                        "type": str(p.ParameterType.FullName),
                        "is_enum": False,
                        "enum_names": None,
                    }
                    try:
                        is_enum = bool(p.ParameterType.IsEnum)
                        p_info["is_enum"] = is_enum
                        if is_enum:
                            has_enum = True
                            try:
                                from System import Enum  # type: ignore
                                p_info["enum_names"] = list(Enum.GetNames(p.ParameterType))
                            except Exception:
                                pass
                    except Exception:
                        pass
                    param_list.append(p_info)

                sig: dict[str, Any] = {
                    "return_type": str(method.ReturnType.FullName),
                    "has_enum_param": has_enum,
                    "parameters": param_list,
                }
                overloads.append(sig)
            except Exception as e:
                overloads.append({"error": str(e)})
    except Exception as e:
        overloads.append({"error": str(e)})

    return overloads
