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

import re
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
        "【来源引用——最高优先级硬性要求，不可省略】\n"
        "**每一条**包含具体数字、产品名、案例、方案细节的句子，必须在句末标注来源编号。\n"
        "格式：[资料N]（N 对应上方【相关资料】中的资料序号）。\n"
        "示例：非计划停机降低50%[资料1]；OEE提升15%[资料2]；某汽车厂年省300万[资料1][资料3]。\n"
        "若一句话综合了多份资料，标注全部：[资料1][资料3]。\n"
        "若某个数字/案例在所有资料中都找不到，必须写『需进一步核实』——绝不允许编造。\n"
        "**违反后果：未标注来源的具体数据将被视为编造，整份方案可信度为零。**\n\n"

        "【引用归属约束】\n"
        "【相关资料】中每条都标明了『类型：华为云方案』或『类型：竞品方案』。\n"
        "1. 第1-5、7-14章（主方案相关）只能引用类型为『华为云方案』的资料，"
        "严禁用竞品资料为华为云产品能力背书。\n"
        "2. 仅第6章『竞品对比（差异化优势）』可引用类型为『竞品方案』的资料。\n"
        "3. 若主方案某论述在华为云资料中找不到依据，写『需进一步核实』，不得转引竞品资料充当华为依据。\n\n"

        "【防幻觉约束】\n"
        "1. 第9节『投资回报分析』的任何金额/ROI数字、第10节『成功案例参考』的任何客户名称与效果数据，\n"
        "   只能来自下方【相关资料】，缺失则写『需进一步核实 / 以实际为准』。\n"
        "2. 严禁出现无法对应到任一 [资料N] 的具体客户名或精确数值。\n"
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
        "【输出范例（仅参考风格；数字须来自资料并标注 [资料N]，无资料则写『需进一步核实』）】\n"
        "## 4. 推荐方案与核心能力\n"
        "- 预测性维护：通过振动/温度传感 + AI 模型将非计划停机从年均12次降至4次以内[资料1]（据《工业互联网预测性维护方案》）。\n"
        "- 质检效率提升5倍：AI视觉替代人工目检，漏检率由2%降至0.3%[资料1]。\n"
    )


# ============================================================
# 5. 完整售前方案书结构（14 章，含竞品对比）
# ============================================================
def build_format_block() -> str:
    return (
        "请严格按以下 Markdown 格式回答（章节标题必须带 ## 编号；"
        "不要使用 *** / --- 等装饰分隔符，直接用 ## 分节即可）：\n"
        "## 1. 执行摘要\n"
        "（面向决策层，200字以内，**必须用下面这种结构化格式，逐行输出，不要写成一整段**：\n"
        "　第一行『价值主张：』+ 一句话（不超过60字，尽量量化）；\n"
        "　第二行『核心要点：』；\n"
        "　之后每行一个要点，用『- 』开头（共3个要点，每个要点一句话，尽量量化）：\n"
        "　　价值主张：……\n"
        "　　核心要点：\n"
        "　　- 要点1：……\n"
        "　　- 要点2：……\n"
        "　　- 要点3：……）\n"
        "## 2. 需求分析\n"
        "（客户业务背景、核心痛点量化、建设目标与可衡量的成功标准）\n"
        "## 3. 方案总体架构\n"
        "（分层描述：边缘接入层 / 网络与连接层 / 平台层 / AI能力层 / 应用层；说明各层职责与协同关系）\n"
        "## 4. 推荐方案与核心能力\n"
        "（主推方案概述 + 3-5项核心能力，每项对应一个痛点；**每条能力要点后必须标注[资料N]**）\n"
        "## 5. 产品组合与定位\n"
        "（用 Markdown 表格呈现：| 产品 | 在本方案中的角色 | 关键能力 | 适用场景 |；产品能力描述标[资料N]）\n"
        "## 6. 竞品对比（差异化优势）\n"
        "（若已检索竞品资料：客观对比并注明来源[资料N]；若无竞品资料，写明『未指定竞品』，不得编造竞品弱点）\n"
        "## 7. 关键业务价值\n"
        "（降本/增效/合规/控风险；**所有量化数字后必须标注[资料N]，无依据写『需进一步核实』**）\n"
        "## 8. 典型部署与实施路径\n"
        "（分3个阶段：阶段目标 + 关键任务 + 交付物 + 周期）\n"
        "## 9. 投资回报分析\n"
        "（测算口径 + 区间估计 + 投资回收期；**每一项金额和数字后必须标注[资料N]，否则写『需进一步核实』**）\n"
        "## 10. 成功案例参考\n"
        "（每个案例的客户名、效果数字后必须标注[资料N]；无确切来源写『需进一步核实』）\n"
        "## 11. 服务保障与支持\n"
        "（7x24支持、专家服务、POC验证、培训认证等具体保障）\n"
        "## 12. 商务与报价指引\n"
        "（说明常见计费模式[按需/包年/按量]与商务流程，标注『具体以华为云官方报价为准』）\n"
        "## 13. 风险与应对\n"
        "（3-5个主要风险 + 对应的应对措施）\n"
        "## 14. 下一步行动建议\n"
        "（3步具体行动：技术交流 / POC验证 / 推广计划）\n"

        "【输出前自检——缺一不可】\n"
        "□ 第4/5/7/9/10章中每条含数字/案例的句子末尾都有 [资料N] 或『需进一步核实』\n"
        "□ 不存在任何裸写的精确数值（如『50%』『300万』『95%』）没有对应 [资料N]\n"
        "□ 不存在编造的客户名称或项目名称\n"
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
# ============================================================
# 参考资料节（让 [资料N] 标注可追溯，杜绝悬空引用）
# ============================================================
def _extract_ref_field(meta: str, key: str) -> str:
    """从 [资料N | 来源:.. | 行业:.. | 类型:..] 的元数据串中提取某个字段"""
    m = re.search(rf'{key}\s*[:：]\s*([^|]+)', meta)
    return m.group(1).strip() if m else ""


def build_references_section(context: str) -> str:
    """从带来源标注的 context 解析出 [资料N] 映射，生成文档末尾的『参考资料』节。

    正文中的 [资料N] 标注若没有对应出处说明，读者无法得知其指向哪份资料，
    标注反而制造困惑。本函数在答案末尾追加一节，把每个 [资料N] 映射回真实出处
    （来源文件名 / 行业 / 类型），使方案书自包含、可追溯。

    Args:
        context: 已格式化为 [资料N | 来源:... | 行业:... | 类型:...] 的参考材料上下文
    Returns:
        "## 15. 参考资料\\n\\n- [资料1] ..." 形式的 Markdown 字符串；无有效资料时返回 ""
    """
    if not context or not context.strip():
        return ""
    ref_items: List[str] = []
    pattern = re.compile(r'\[资料(\d+)\s*\|(.*?)\]', re.DOTALL)
    for m in pattern.finditer(context):
        idx = m.group(1)
        meta = m.group(2)
        source = _extract_ref_field(meta, '来源')
        industry = _extract_ref_field(meta, '行业')
        dtype = _extract_ref_field(meta, '类型')
        if not (source or industry or dtype):
            continue
        fields = [f"[资料{idx}]"]
        if source:
            fields.append(f"来源：{source}")
        if industry:
            fields.append(f"行业：{industry}")
        if dtype:
            fields.append(f"类型：{dtype}")
        ref_items.append("- " + " ｜ ".join(fields))
    if not ref_items:
        return ""
    return "\n\n## 15. 参考资料\n\n" + "\n".join(ref_items) + "\n"


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
