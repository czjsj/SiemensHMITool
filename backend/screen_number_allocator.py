# -*- coding: utf-8 -*-
"""
Screen Number Allocator — TIA HMI XML 导入管线第三层
=======================================================

职责：主动分配唯一 screen number，防止导入时冲突。

对应提示词规范中的 AllocateNumber：
  int AllocateNumber(List<int> used)
  {
      int n = 1;
      while (used.Contains(n)) n++;
      return n;
  }

核心规则：
  - screen number 必须唯一（同一 ScreenFolder 内不可重复）
  - 优先使用已用号码中最小的空缺（紧凑分配）
  - 也支持 max+1 策略（兼容旧行为）
  - 与 XmlValidator 协作：Validator 检查 Number 节点存在性，Allocator 负责分配

这是管线的第三层，位于 MultilingualTextBuilder 之上、XmlValidator 之下。
"""
import re


class ScreenNumberAllocator:
    """TIA Portal Screen Number 分配器。

    使用方式：
        allocator = ScreenNumberAllocator()
        allocator.register_existing([1, 2, 5])
        new_number = allocator.allocate()
        # → 3（最小空缺）
    """

    def __init__(self, strategy: str = "compact"):
        """
        参数:
            strategy: 分配策略。
              - "compact": 使用已用号码中最小的空缺（推荐）
              - "max_plus_one": 使用 max(existing) + 1
        """
        if strategy not in ("compact", "max_plus_one"):
            raise ValueError(f"无效的分配策略 '{strategy}'，可选: compact, max_plus_one")
        self.strategy = strategy
        self._used_numbers: set = set()
        self._reserved: set = set()

    def register_existing(self, numbers: list):
        """注册已使用的 screen numbers（从博途已有画面收集）。

        参数:
            numbers: 已使用的 screen number 列表。
        """
        for n in numbers:
            try:
                self._used_numbers.add(int(n))
            except (TypeError, ValueError):
                pass

    def register_xml_numbers(self, xml_content: str):
        """从 XML 内容中提取并注册所有 <Number> 节点值。

        参数:
            xml_content: 画面 XML 内容字符串。
        """
        for m in re.finditer(
            r'<(\w+:)?Number>(\d+)</(\w+:)?Number>',
            xml_content,
            re.IGNORECASE,
        ):
            try:
                self._used_numbers.add(int(m.group(2)))
            except (TypeError, ValueError):
                pass

    def allocate(self) -> int:
        """分配一个新的唯一 screen number。

        根据策略返回一个未被使用的 screen number：
          - compact: 返回最小空隙（如已有 [1,2,5] → 返回 3）
          - max_plus_one: 返回 max + 1（如已有 [1,2,5] → 返回 6）

        返回:
            可安全使用的 int screen number。
        """
        if self.strategy == "compact":
            return self._allocate_compact()
        return self._allocate_max_plus_one()

    def _allocate_compact(self) -> int:
        """紧凑分配：从 1 开始找第一个未被占用的号码。"""
        n = 1
        while n in self._used_numbers or n in self._reserved:
            n += 1
        self._reserved.add(n)
        return n

    def _allocate_max_plus_one(self) -> int:
        """max+1 策略。"""
        if not self._used_numbers:
            n = 1
        else:
            n = max(self._used_numbers) + 1
        while n in self._reserved:
            n += 1
        self._reserved.add(n)
        return n

    def remove_number_nodes(self, xml_content: str) -> str:
        """从 XML 中安全删除所有 <Number> 节点（让 TIA 自动分配）。

        参数:
            xml_content: 画面 XML 内容。

        返回:
            删除 <Number> 节点后的 XML 字符串。
        """
        return re.sub(
            r'[ \t]*<(\w+:)?Number>\d+</(\w+:)?Number>\s*\n?',
            '',
            xml_content,
            flags=re.IGNORECASE,
        )

    def detect_conflicts(self, xml_content: str) -> dict:
        """检测 XML 中的 screen number 是否与已注册号码冲突。

        返回:
            {
                "has_conflict": True/False,
                "xml_numbers": [1, 3, ...],
                "conflicted": [1, ...],       # 冲突的号码
                "used_numbers": sorted(self._used_numbers),
                "suggested": 2,               # 建议的下一个可用号码
            }
        """
        result = {
            "has_conflict": False,
            "xml_numbers": [],
            "conflicted": [],
            "used_numbers": sorted(self._used_numbers),
            "suggested": self.allocate() if not self._reserved else None,
        }

        for m in re.finditer(
            r'<(\w+:)?Number>(\d+)</(\w+:)?Number>',
            xml_content,
            re.IGNORECASE,
        ):
            num = int(m.group(2))
            result["xml_numbers"].append(num)
            if num in self._used_numbers:
                result["conflicted"].append(num)
                result["has_conflict"] = True

        return result

    @property
    def used_count(self) -> int:
        return len(self._used_numbers)

    @property
    def next_available(self) -> int:
        """预览下一个可用号码（不占位）。"""
        n = 1
        while n in self._used_numbers or n in self._reserved:
            n += 1
        return n
