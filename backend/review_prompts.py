# -*- coding: utf-8 -*-
"""
审查与修正提示词
================
包含视觉审查任务模板（动态注入通过阈值）、修正模式提示词、
以及 Siemens HMI 画面设计标准参考。

通过/不通过判定由后端代码用 score >= threshold 权威决定，
LLM 只需返回 score，不需要返回 pass 字段。

本版重点优化：
1. 强化对"间距过小 / 对齐不齐 / 页面过密"的识别；
2. 审查输出尽量可操作，让再生成阶段更容易修正；
3. 兼容 Basic / Comfort / Unified 的一般性 HMI 版式审查。
"""
import json

SIEMENS_COLOR_REFERENCE = """
【Siemens HMI 标准色参考】
- 运行/正常/启动: 绿色 #27D17F
- 故障/停止/报警: 红色 #E25563
- 一般状态/主题色: 青色 #14E0B1
- 熄灭/关闭/深灰: #3A4250
- 文字浅色(深色背景下): #E6EDF3
- 文字辅色: #C9D3DE
- 文字暗色(浅色按钮上): #06281F
- 背景深色: #1F2630
- IO域边框: 蓝色 #2A86FF (文本IO域) / 紫色 #8A5CFF (符号IO域)
- 输入框背景: #0E1622
""".strip()

def build_hmi_review_task(threshold: int = 70) -> str:
    """构建 HMI 视觉审查任务提示词，动态注入通过阈值。

    通过/不通过的判定由后端代码用 score >= threshold 权威决定，
    LLM 只需返回 score，不需要返回 pass 字段。
    """
    return f"""
你是西门子 WinCC / 博途(TIA Portal) HMI 画面设计审查专家。
请仔细审查这张 HMI 画面预览图，按照以下 Siemens HMI 工程标准逐项评估。
只描述图中可见内容，不要凭空推测。

{SIEMENS_COLOR_REFERENCE}

【核心审查原则】
- 优先识别：重叠、越界、间距过小、对齐不齐、区块混乱、文字可读性差。
- 间距问题请尽量具体：指出“哪两个对象过近”或“哪一行过密”。
- 若页面质量尚可，也要指出最值得优先优化的 1~3 个点。
- 重点关注工程交付质量，而不是艺术风格。

【评估维度】

1. 布局清晰度与对齐 (layout_alignment)
   - 同类对象（按钮/IO域/指示灯）是否严格对齐排列？
   - 标题区、控制区、状态区、参数区等信息分区是否清晰？
   - 是否存在对象堆叠在左上角、整体重心失衡、局部过密而其他区域过空的情况？
   - 对于同一行对象，如果水平间距小于约 20px，应视为“过近”；
     对于区块之间，如果垂直间距小于约 20px，应视为“过密”。

2. 组件尺寸与间距 (component_sizing)
   - 按钮尺寸是否适合操作（建议宽度 ≥ 120px, 高度 ≥ 50px）？
   - IO 域尺寸是否适合显示数值（建议宽度 ≥ 140px, 高度 ≥ 40px）？
   - 指示灯半径是否合适（建议 20~30px）？
   - 同类组件尺寸是否一致？
   - 标签与对应控件的距离是否太远或太近？

3. 颜色规范 (color_conventions)
   - 运行/启动类是否使用绿色系？
   - 停止/故障/报警类是否使用红色系？
   - 背景与文字的对比度是否足够？
   - 是否有颜色语义混乱的情况？

4. 文字可读性 (text_readability)
   - 所有中文标签是否完整、清晰、未被截断？
   - 标题字号是否突出（建议 24~28px）？
   - 标签字号是否合适（建议 12~16px）？
   - 按钮文字是否简洁、居中、清晰？
   - 是否存在多行文字挤压、文本与控件边框过近的情况？

5. 元素完整性 (completeness)
   - 画面是否有标题？
   - 每个指示灯是否都有标签说明其含义？
   - 每个 IO 域是否都有标签和/或单位标注？
   - 按钮功能是否通过文字明确标识？
   - 是否存在需求中提到但画面中缺失的元素？

6. 整体专业质量 (professional_quality)
   - 画面布局是否整洁、符合工程交付标准？
   - 是否有多余、无用、意义不明的元素？
   - 整体视觉是否达到专业 HMI 工程画面的水准？
   - 空白区域的使用是否合理（既不过密也不过疏）？

【输出要求】
返回严格 JSON（不要 Markdown 代码块包裹）：
{{
  "score": 0到100的整数,
  "categories": {{
    "layout_alignment":    {{"pass": true/false, "issues": ["具体问题1", ...]}},
    "component_sizing":    {{"pass": true/false, "issues": [...]}},
    "color_conventions":   {{"pass": true/false, "issues": [...]}},
    "text_readability":    {{"pass": true/false, "issues": [...]}},
    "completeness":        {{"pass": true/false, "issues": [...]}},
    "professional_quality":{{"pass": true/false, "issues": [...]}}
  }},
  "summary": "整体中文评价，一句话总结画面质量",
  "critical_issues": ["必须立即修复的关键问题"],
  "suggestions": ["可执行的改进建议"]
}}

注意：
- 如果某类问题不存在，issues 留空数组，pass 设为 true。
- score 应客观反映整体质量（0-100 整数）。
  本次审查的通过阈值为 {threshold} 分：score >= {threshold} 为通过，score < {threshold} 为未通过。
  一般参考：90+ 优秀，70~89 良好，50~69 需改进，<50 不合格。
- 只把真正严重的问题放进 critical_issues，例如：关键元素缺失、严重重叠、明显越界、按钮挤在一起难以操作。
- suggestions 尽量写成可执行建议，例如：
  "将三枚按钮整理为同一行并拉开 24px 以上间距"；
  "将状态指示灯整体下移，与标题区拉开距离"；
  "把参数显示区改成两列等宽布局"。
""".strip()

IMAGE_ANALYSIS_TASK = """
你是一位 HMI 画面设计需求分析师。请分析这张参考图片/图纸，提取其中与 HMI 画面设计相关的信息。

关注以下内容：
1. 图中显示了哪些参数/变量（如温度、压力、转速、流量、液位等）？它们的单位和量程大致如何？
2. 有哪些控制元素（按钮、开关、选择器、手自动切换等）？
3. 有哪些状态指示（运行、停止、故障、报警、就绪等）？
4. 整体的画面布局方式（上下分区、左右分区、仪表盘式等）？
5. 是否有特殊的图形元素（管道、流程图、设备图标、曲线图等）？
6. 文字标签使用什么语言？有哪些关键标注？
7. 是否存在值得复用的排版模式（如按钮区、状态区、参数区的组织方式）？

请用中文按以下 JSON 格式输出：
{
  "summary": "对参考图的整体描述",
  "parameters": ["参数1及单位", "参数2及单位", ...],
  "controls": ["控制元素1", ...],
  "status_indicators": ["状态指示1", ...],
  "layout_style": "布局风格描述",
  "special_elements": ["特殊图形元素", ...],
  "hmi_suggestions": "根据此参考图，对设计 HMI 画面的建议"
}
只描述图中可见内容，不要凭空推测。
""".strip()

REGENERATION_SYSTEM_ADDENDUM = """
【审查反馈改进模式】

你正在根据视觉审查反馈修正之前生成的 HMI 画面 IR。
请遵守以下原则：

1. 逐项修正审查中 issues 指出的具体问题。
2. 特别关注 critical_issues —— 这些是必须修复的关键问题。
3. 保留审查未指出问题的正确部分（不要过度修改）。
4. 若审查指出缺少元素，在正确位置新增对象并在 tags/text_lists 中声明关联变量。
5. 若审查指出布局/尺寸问题，优先处理：重叠、越界、按钮过密、区块过密、同类对象不对齐。
6. 若审查指出颜色不合规范，参照 Siemens 标准色修正。
7. 若审查指出文字问题，修正标签、标题的文字内容和字号。
8. 修改后输出完整的 IR JSON（用 ```json 代码块包裹），不要省略任何已有对象。
""".strip()


def build_review_feedback_text(review_result: dict, pass_threshold: int = 70) -> str:
    """将视觉审查结果转换为模型更容易执行的修正反馈文本。

    通过/不通过由后端用 score >= pass_threshold 权威判定，
    不再采信 LLM 返回的 pass 字段。
    """
    lines = []

    score = review_result.get("score", 0)
    passed = score >= pass_threshold
    lines.append(f"审查结果: {'通过 ✓' if passed else '未通过 ✗'}（评分: {score}/100，通过阈值: {pass_threshold}）")
    lines.append(f"整体评价: {review_result.get('summary', '无')}")
    lines.append("")

    critical = review_result.get("critical_issues") or []
    if critical:
        lines.append("## 关键问题（必须修复）")
        for i, issue in enumerate(critical, 1):
            lines.append(f"{i}. {issue}")
        lines.append("")

    categories = review_result.get("categories") or {}
    cat_labels = {
        "layout_alignment": "布局与对齐",
        "component_sizing": "组件尺寸与间距",
        "color_conventions": "颜色规范",
        "text_readability": "文字可读性",
        "completeness": "元素完整性",
        "professional_quality": "专业质量",
    }
    for cat_key, cat_label in cat_labels.items():
        cat = categories.get(cat_key, {})
        issues = cat.get("issues") or []
        if issues:
            lines.append(f"## {cat_label}")
            for i, issue in enumerate(issues, 1):
                lines.append(f"{i}. {issue}")
            lines.append("")

    suggestions = review_result.get("suggestions") or []
    if suggestions:
        lines.append("## 改进建议")
        for i, suggestion in enumerate(suggestions, 1):
            lines.append(f"{i}. {suggestion}")
        lines.append("")

    return "\n".join(lines)


def build_regeneration_messages(
    requirement: str,
    previous_ir: dict,
    review_result: dict,
    pass_threshold: int = 70,
) -> list:
    """构建修正模式 messages。"""
    feedback_text = build_review_feedback_text(review_result, pass_threshold=pass_threshold)
    ir_json = json.dumps(previous_ir, ensure_ascii=False, indent=2)

    system_content = (
        "你是一名资深的西门子 WinCC / 博途(TIA Portal) HMI 画面工程师。\n"
        + REGENERATION_SYSTEM_ADDENDUM
    )

    user_content = f"""【原需求】
{requirement}

【上一版生成的 IR（需要修正）】
```json
{ir_json}
```

【视觉审查反馈】
{feedback_text}

请根据上述审查反馈修正 IR，输出修正后的完整 IR JSON（用 ```json 代码块包裹）。
只修正被指出的问题，保持其他部分不变。确保所有 tags、text_lists、scripts 的交叉引用完整。
"""

    return [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_content},
    ]
