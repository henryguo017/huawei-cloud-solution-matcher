"""
华为云解决方案「统一增强生成」共享 Prompt 模块

设计目标：
- 标准模式 (solution_matcher) 与 智能(Agent)模式 (harness) 共用同一套增强生成指令，
  保证三种匹配模式（标准 / 向导 / 智能）产出的方案书质量一致、可用。
- 关键能力：
  1. 防幻觉硬约束（ROI/案例只引资料，缺失写『需进一步核实』）
  2. 受众与话术（决策层业务语言、差异化竞品对比）
  3. 完整售前方案书结构（14 章，含竞品对比）
  4. 行业剧本注入
  5. Markdown → 章节结构解析（供报告生成器消费）

所有函数均为纯函数（不依赖实例 / 不调用 LLM），便于两种模式复用与单测。
"""

from typing import Dict, Any, List


# ============================================================
# 1. 基础行（行业 / 需求结构化）
# ============================================================
def build_industry_line(industry: str) -> str:
    if industry:
        return f"客户所属行业：{industry}\n"
    return "客户所属行业：未明确（请基于需求推断，并在『需求分析』中说明你的假设）\n"


def build_analysis_line(demand_analysis: Dict[str, Any]) -> str:
    if not demand_analysis:
        return ""
    ap = demand_analysis.get("pain_points") or []
    asc = demand_analysis.get("scenarios") or []
    ak = demand_analysis.get("keywords") or []
    if not (ap or asc or ak):
        return ""
    return (
        "已结构化需求（用于增强针对性，仅作参考）：\n"
        f"- 痛点：{'、'.join(ap)}\n"
        f"- 场景：{'、'.join(asc)}\n"
        f"- 检索关键词：{'、'.join(ak)}\n"
    )


# ============================================================
# 2. 防幻觉硬约束
# ============================================================
def build_anti_hallucination() -> str:
    return (
        "【防幻觉硬约束】\n"
        "1. 第9节『投资回报分析』中的任何数字、第10节『成功案例参考』中的任何案例，"
        "只能来自下方【相关资料】中明确给出的内容。\n"
        "2. 若资料中未提供对应数字或案例，必须明确写明『需进一步核实 / 以实际为准』，"
        "严禁编造具体数值、客户名称或案例细节。\n"
        "3. 引用资料时可在句末标注来源文件名（如：据《xxx》）。\n"
    )


# ============================================================
# 3. 受众与话术
# ============================================================
def build_audience_tone() -> str:
    return (
        "【受众与话术】\n"
        "面向客户决策层（非技术人员）：用业务语言讲价值（降本 / 增效 / 合规 / 控风险），"
        "少堆砌技术参数；竞品对比使用『差异化优势』框架，客观、不贬低对手；"
        "整体语气专业、有说服力，像资深售前顾问。\n"
    )


# ============================================================
# 4. 输出范例（few-shot）
# ============================================================
def build_few_shot() -> str:
    return (
        "【输出范例（仅参考风格，数字必须来自资料，无资料则标注『需进一步核实』）】\n"
        "## 4. 推荐方案与核心能力\n"
        "- 预测性维护：通过振动/温度传感 + AI 模型将非计划停机从年均12次降至4次以内（据《工业互联网预测性维护方案》）。\n"
        "- 质检效率提升5倍：AI视觉替代人工目检，漏检率由2%降至0.3%。\n"
    )


# ============================================================
# 5. 完整售前方案书结构（14 章，含竞品对比）
# ============================================================
def build_format_block() -> str:
    return (
        "请严格按以下 Markdown 格式回答（章节标题必须带 ## 编号；"
        "不要使用 *** / --- 等装饰分隔符，直接用 ## 分节即可）：\n"
        "## 1. 执行摘要\n"
        "（面向决策层，200字以内：一句话价值主张 + 3个核心要点，尽量量化）\n"
        "## 2. 需求分析\n"
        "（客户业务背景、核心痛点量化、建设目标与可衡量的成功标准）\n"
        "## 3. 方案总体架构\n"
        "（分层描述：边缘接入层 / 网络与连接层 / 平台层 / AI能力层 / 应用层；说明各层职责与协同关系）\n"
        "## 4. 推荐方案与核心能力\n"
        "（主推方案概述 + 3-5项核心能力，每项对应一个痛点）\n"
        "## 5. 产品组合与定位\n"
        "（用 Markdown 表格呈现：| 产品 | 在本方案中的角色 | 关键能力 | 适用场景 |；每个产品说明其定位）\n"
        "## 6. 竞品对比（差异化优势）\n"
        "（若已检索竞品资料：用客观『差异化优势』框架对比华为云与竞品，注明来源；"
        "若无竞品资料，写明『本次未指定竞品，可补充竞品名称以获取对比』，不得编造竞品弱点）\n"
        "## 7. 关键业务价值\n"
        "（用业务语言讲降本/增效/合规/控风险；量化优先，无依据标注『需进一步核实』）\n"
        "## 8. 典型部署与实施路径\n"
        "（分3个阶段，每阶段写：阶段目标 + 关键任务 + 交付物 + 周期）\n"
        "## 9. 投资回报分析\n"
        "（测算口径 + 区间估计 + 投资回收期；数字须来自【相关资料】，否则标注『需进一步核实』）\n"
        "## 10. 成功案例参考\n"
        "（可引用华为云公开案例，注明行业与成效；无确切来源标注『需进一步核实』）\n"
        "## 11. 服务保障与支持\n"
        "（7x24支持、专家服务、POC验证、培训认证等具体保障）\n"
        "## 12. 商务与报价指引\n"
        "（说明常见计费模式[按需/包年/按量]与商务流程，标注『具体以华为云官方报价为准』）\n"
        "## 13. 风险与应对\n"
        "（3-5个主要风险 + 对应的应对措施）\n"
        "## 14. 下一步行动建议\n"
        "（3步具体行动，含技术交流 / POC / 推广计划）\n"
        "每个章节至少3-5个具体要点，避免空泛；能用量化处务必量化；"
        "可在章节内用 ### 细分小标题增强层次。\n"
    )


# ============================================================
# 6. 行业剧本注入
# ============================================================
def build_playbook_text(playbook: Dict[str, Any], industry: str) -> str:
    if not industry or industry not in playbook:
        return ""
    pb = playbook.get(industry, {})
    lines = [f"【{industry}行业作战手册（内部参考，用于贴合行业语境，不代表对外承诺）】"]
    if pb.get("pain_points"):
        lines.append("常见痛点：" + "、".join(pb["pain_points"]))
    if pb.get("scenarios"):
        lines.append("典型场景：" + "、".join(pb["scenarios"]))
    if pb.get("regulatory"):
        lines.append("监管/合规要点：" + "、".join(pb["regulatory"]))
    if pb.get("huawei_products"):
        lines.append("常用华为云产品组合：" + "、".join(pb["huawei_products"]))
    if pb.get("roi"):
        lines.append("ROI 量化口径参考：" + "、".join(pb["roi"]))
    return "\n".join(lines)


# ============================================================
# 7. Markdown → 章节结构解析（供报告生成器消费）
# ============================================================
def parse_markdown_to_chapters(markdown: str) -> List[Dict[str, Any]]:
    """把 Markdown 方案解析为章节结构（与 report_generator 的章节格式一致）

    支持：## 章节标题 / ### 子章节标题；正文按行累积到对应章节。
    """
    chapters = []
    lines = (markdown or "").split("\n")
    current_chapter = None
    current_content: List[str] = []

    for line in lines:
        if line.startswith("## "):
            if current_chapter:
                current_chapter["content"] = "\n".join(current_content).strip()
                chapters.append(current_chapter)
            current_chapter = {"title": line[3:].strip(), "content": "", "sections": []}
            current_content = []
        elif line.startswith("### "):
            if current_content and current_chapter:
                current_chapter["content"] = "\n".join(current_content).strip()
                current_content = []
            if current_chapter:
                current_chapter["sections"].append({"title": line[4:].strip(), "content": ""})
        else:
            if current_chapter and current_chapter.get("sections"):
                current_chapter["sections"][-1]["content"] += line + "\n"
            else:
                current_content.append(line)

    if current_chapter:
        current_chapter["content"] = "\n".join(current_content).strip()
        chapters.append(current_chapter)
    return chapters
