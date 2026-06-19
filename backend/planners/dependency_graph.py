# -*- coding: utf-8 -*-
"""
部署依赖图：构建拓扑顺序，保证变量先于画面、连接先于变量等。

不依赖 Flask、pythonnet 或 Siemens DLL。
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any


class DependencyGraph:
    """简单有向无环图 (DAG) 用于部署步骤排序。"""

    def __init__(self):
        self._nodes: set[str] = set()
        self._edges: dict[str, set[str]] = defaultdict(set)  # from → {to}
        self._reverse: dict[str, set[str]] = defaultdict(set)  # to → {from}

    def add_node(self, node_id: str):
        """添加节点。"""
        self._nodes.add(node_id)

    def add_edge(self, from_id: str, to_id: str):
        """添加依赖边 from → to（to 依赖 from，from 先执行）。"""
        self._nodes.add(from_id)
        self._nodes.add(to_id)
        self._edges[from_id].add(to_id)
        self._reverse[to_id].add(from_id)

    def has_cycle(self) -> bool:
        """检测是否存在环。"""
        return len(self.topological_sort()) != len(self._nodes)

    def topological_sort(self) -> list[str]:
        """拓扑排序，返回执行顺序列表。"""
        in_degree: dict[str, int] = {n: 0 for n in self._nodes}
        for from_id, to_set in self._edges.items():
            for to_id in to_set:
                in_degree[to_id] = in_degree.get(to_id, 0) + 1

        queue = deque([n for n, d in in_degree.items() if d == 0])
        result: list[str] = []

        while queue:
            node = queue.popleft()
            result.append(node)
            for neighbor in self._edges.get(node, set()):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result

    @property
    def node_count(self) -> int:
        return len(self._nodes)


def build_dependency_order(
    tag_names: set[str],
    connection_names: set[str],
    script_names: set[str],
    screen_names: set[str],
) -> list[str]:
    """为部署构建标准依赖顺序。

    顺序保证：
      连接 → 变量 → 脚本/资源 → 画面 → 绑定/事件 → 编译 → 验证

    返回拓扑排序后的阶段列表。
    """
    graph = DependencyGraph()

    # 添加所有阶段节点
    phases = [
        "P00_DISCOVERY",
        "P10_VALIDATE_DEPENDENCIES",
        "P20_CONNECTIONS",
        "P30_TAG_TABLES_AND_TAGS",
        "P40_SCRIPTS_AND_RESOURCES",
        "P50_SCREENS",
        "P60_BINDINGS_AND_EVENTS",
        "P70_COMPILE",
        "P80_VERIFY",
        "P90_SAVE",
    ]
    for p in phases:
        graph.add_node(p)

    # 添加依赖边
    graph.add_edge("P00_DISCOVERY", "P10_VALIDATE_DEPENDENCIES")
    graph.add_edge("P10_VALIDATE_DEPENDENCIES", "P20_CONNECTIONS")
    graph.add_edge("P20_CONNECTIONS", "P30_TAG_TABLES_AND_TAGS")
    graph.add_edge("P30_TAG_TABLES_AND_TAGS", "P40_SCRIPTS_AND_RESOURCES")
    graph.add_edge("P30_TAG_TABLES_AND_TAGS", "P50_SCREENS")
    graph.add_edge("P40_SCRIPTS_AND_RESOURCES", "P50_SCREENS")
    graph.add_edge("P50_SCREENS", "P60_BINDINGS_AND_EVENTS")
    graph.add_edge("P60_BINDINGS_AND_EVENTS", "P70_COMPILE")
    graph.add_edge("P70_COMPILE", "P80_VERIFY")
    graph.add_edge("P80_VERIFY", "P90_SAVE")

    return graph.topological_sort()
