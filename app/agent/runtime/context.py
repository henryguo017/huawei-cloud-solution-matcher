# -*- coding: utf-8 -*-
"""L4-P2 Agent Runtime · 上下文装配与压缩（context.py）

两块职责，都是宿主职责③（上下文管理）的落地：

1. **装配**：把「角色与政策 + 技能包口径 + 长程记忆 + 客户上下文 + 宿主核验事实」
   组装成一条 system 消息。稳定前缀放前面，便于 prompt cache 命中。
   —— 注意：这里没有"可用工具清单"，工具以结构化 schema 随请求下发（C2）。

2. **压缩**：FC 循环的 messages 会随轮次持续增长（老管线每步独立 prompt，不存在此问题），
   达到窗口占比阈值时，把早期轮次摘要成一条"阶段性工作记忆"system 消息，
   保留最近 N 轮原文。压缩失败则退化为硬截断，**保证任务能继续**。
"""

import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.agent.runtime.schema import message_shape  # 压缩产物校验（孤儿 tool_calls 检测）

logger = logging.getLogger(__name__)

# ── 政策块：通用部分（自主性 + 工作准则）+ 按意图切换的「交付姿态」──
#
# 为什么把姿态做成随意图切换（L4-P1）：
#   控制流（自主性、计划机制、工具选择）是**通用的**，与用户问什么无关；
#   但**交付姿态**必须随意图变 —— 否则会重犯历史实锤 bug：
#     2026-09-09 线上，自主分支无条件按"售前方案"姿态出稿，"你会玩王者荣耀吗？"
#     也产出 14 章游戏行业方案书。
#   当时的兜底手段是「范围门」（只放 solution/competitor 进 FC）。P1 把它正解为
#   「姿态随意图」，从而可以安全放开意图范围 —— 门由"内容判断"退化为"路径判断"
#   （见 fc_takes_over：只排除确定性/瞬时的 greeting/account/export）。
_AUTONOMY_BLOCK = """你是华为云售前智能体，运行在原生 function calling 运行时上。

## 你的自主性（这是你与普通问答机器人的区别）
- 你能看到完整工具清单及其参数 schema。**调用哪些工具、以什么顺序、调用几次、何时收尾，全部由你决定**。
- 当你不需要再调用工具时，直接输出最终答案（一条不带工具调用的消息）——这条消息就是交付给用户的正文。
- 计划由你自己维护：**只要任务预计需要两次及以上工具调用（或涉及检索 / 比对），第一步就先调用 `update_plan` 发布计划**，
  之后随时可以改写。它是**你自己的待办清单**。
  **两条硬性要求**：
  ① 若你已连续调用工具 ≥2 次却仍未发布过计划，**必须立刻补发一次 `update_plan` 再继续**；
  ② **交付前计划必须闭合**——每一步要么 `done`，要么 `skipped` 并在 note 里写清原因。
     若交付时仍有未闭合步骤，宿主会把它们退回给你，由你自己决定补做还是标 skipped。
     不要为了好看而虚标 `done`：某步实际没做，就如实标 `skipped`。
  执行顺序仍完全由你决定（计划**不锁死**顺序）；只有确认「单步即可完成」的小任务才可以不发计划。

## 工作准则
1. **先读懂用户要什么**：关键信息缺失且无法从上下文推断时，在最终消息里向用户提出
   1-2 个关键澄清问题（尽量给候选选项），不要凭空生成内容。
   **交付姿态以用户实际诉求为准**：下面「输出契约」是按系统意图预判给的姿态；若你读题后发现
   不符（例：用户只是让你算个数、问一个知识点，却被预判为"要一份方案"），**以用户真实诉求为准** ——
   直接给出他要的东西，不要硬套模板。**你的判断优先于预判。**
2. **按需检索**：方案资料用 `search_kb`（可换关键词多次调用）；用户提到竞品用 `search_competitor`；
   需要知识库以外的实时信息用 `web_search`（需要精读正文时再用 `web_extract`）。
   与本地知识库无关的任务（算术、数据处理、闲聊）**不要检索**，直接答。
3. **严谨**：不得编造华为云产品、案例、数据、客户名或金额。只依据工具返回的资料作答；
   引用资料时标注来源文件名（如：据《xxx.docx》）。
4. **提效**：同一套多步检索需要重复执行 ≥2 次时，用 `register_dynamic_tool` 组合成 `dyn_` 工具再复用。
5. **成本/报价**：先用 `mcp__cost__cost_reference_list` 取 SKU 目录，再用 `mcp__cost__cost_calc` 测算。
   **金额一律以工具返回为准，不得自行估算金额**。
6. **客户档案**：查询用 `mcp__crm__client_list` / `mcp__crm__match_history`；
   写入（`client_add` / `client_update`）会弹窗请用户确认——若用户拒绝或失败，必须如实说明"未写入"。
7. **计算与导出**：精确计算 / 数据整理用 `run_python` 沙箱（**不要心算**）；导出文档用 `generate_doc`
   （宿主会在终稿产出后再落文件，你调用后只需告知用户导出已发起即可）。
8. **错误自愈**：工具报错时阅读错误信息，调整参数或更换工具重试；不要重复同样的错误调用。"""

# 交付姿态（按意图切换）：只影响「写成什么样」，不影响自主性与工作准则。
_CONTRACTS: Dict[str, str] = {
    "solution": """
## 输出契约（本条＝方案交付）
- 终稿结构：客户痛点与目标 → 华为云产品与技术方案 → 实施路径 → 价值与预期收益。
- 篇幅：1500-3500 字，结构清晰、可落地、面向售前汇报。
- **不做完成态承诺**：只有工具真实执行成功的动作才可表述为"已保存 / 已生成"；
  否则表述为"待你确认后执行"。
- 使用 Markdown 排版；**不要输出 Thought / Action 之类的协议文本**（你不需要它们）。""",
    "competitor": """
## 输出契约（本条＝竞品对比）
- 终稿结构：对比维度 → 双方（或多方）逐项差异 → 各自适用场景 → 选型建议。
- 篇幅：1200-3000 字；差异要落到具体产品/能力，不要空泛评价。
- **不做完成态承诺**：只有工具真实执行成功的动作才可表述为"已保存 / 已生成"。
- 使用 Markdown 排版；**不要输出 Thought / Action 之类的协议文本**（你不需要它们）。""",
    "knowledge_q": """
## 输出契约（本条＝知识问答，**不是方案交付**）
- 直接回答用户问的问题，条理清晰即可。
- **不要套用方案模板**：不要写"客户痛点 / 实施路径 / 价值与预期收益"这类章节，
  **不要写成长篇方案书** —— 用户问的是一个知识点，别答成一份报告。
- 篇幅以答清为准（通常 300-1200 字），必要时用小标题或分点。
- 依据工具返回的资料作答并标注来源；**不要输出 Thought / Action 之类的协议文本**。""",
    "general": """
## 输出契约（本条＝通用对话 / 直接任务，**不是方案交付**）
- **先判断用户真正要什么**：闲聊就自然简短地回应；提问就直接答；让算/让整理就给出结果。
- **不要套用方案模板**：不要写"客户痛点 / 实施路径 / 价值与预期收益"这类章节，
  **不要写成长篇方案书** —— 除非用户明确要一份方案。
- 篇幅与形式随任务走（一句话的问题就给一句话的答案）；计算类必须给出算式与结果。
- **不要输出 Thought / Action 之类的协议文本**。""",
    "file_ops": """
## 输出契约（本条＝文件 / 附件操作）
- 说明你做了什么、结果如何；若需要用户确认或上传，明确告知下一步动作。
- **不要写成长篇方案书**；**不要输出 Thought / Action 之类的协议文本**。""",
}
_DEFAULT_CONTRACT = _CONTRACTS["general"]

# 不进原生运行时的意图（确定性 / 瞬时路径）：
#   greeting —— 礼节寒暄，legacy 有模板直答，走 FC 只是白烧一次 LLM 调用；
#   account  —— 账户信息查询，确定性查库，不需要模型自主规划；
#   export   —— 导出是一次**确定性文件动作**（绑 `_last_draft`），不该由模型即兴发挥。
# 其余意图（solution / competitor / knowledge_q / general / file_ops）一律进 FC，
# 姿态由 build_policy_prompt(intent) 决定 —— 这正是 P1「取消范围门」的落地方式。
FC_LEGACY_INTENTS: tuple = ("greeting", "account", "export")


def fc_takes_over(intent: str) -> bool:
    """该意图是否交给原生运行时（FC）接管。见上方 FC_LEGACY_INTENTS 的排除理由。"""
    return (intent or "").strip() not in FC_LEGACY_INTENTS


def build_policy_prompt(intent: str = "solution") -> str:
    """按意图裁出完整政策：通用块（自主性 + 工作准则）+ 该意图的交付姿态。"""
    contract = _CONTRACTS.get((intent or "").strip(), _DEFAULT_CONTRACT)
    return _AUTONOMY_BLOCK + "\n" + contract


# 向后兼容别名：默认按方案姿态（旧调用方行为不变）
POLICY_PROMPT = build_policy_prompt("solution")


def compose_system_prompt(blocks: List[str], intent: str = "solution") -> str:
    """政策块（按意图切姿态）+ 各上下文块拼成一条 system 内容。空块自动跳过。"""
    parts = [build_policy_prompt(intent)]
    for b in (blocks or []):
        if isinstance(b, str) and b.strip():
            parts.append(b.strip())
    return "\n\n".join(parts)


# ───────────────────────── token 估算与压缩 ─────────────────────────

def estimate_tokens(text: str) -> int:
    """中英混排粗估（约 1.6 字符 / token），仅用于预算与压缩触发，非精确分词。"""
    if not text:
        return 0
    return max(1, int(len(text) / 1.6))


def messages_tokens(messages: List[Dict[str, Any]]) -> int:
    total = 0
    for m in (messages or []):
        if not isinstance(m, dict):
            continue
        total += estimate_tokens(str(m.get("content") or ""))
        # reasoning_content 也必须计入：thinking 模式下它随 assistant 消息**回传**（且是真实
        # 输入 token），不计会让窗口/压缩阈值系统性低估 → 压缩迟迟不触发（2026-09-13 修复引入）。
        total += estimate_tokens(str(m.get("reasoning_content") or ""))
        for tc in (m.get("tool_calls") or []):
            fn = (tc or {}).get("function") or {}
            total += estimate_tokens(str(fn.get("name") or "")) + estimate_tokens(str(fn.get("arguments") or ""))
        total += 8  # 角色与结构开销
    return total


def _split_segments(messages: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """把 messages[1:] 切成"轮次段"：assistant(+其 tool 结果) 为一段，孤立 user 为一段。"""
    rest = messages[1:]
    segs: List[List[Dict[str, Any]]] = []
    i = 0
    while i < len(rest):
        m = rest[i]
        role = m.get("role")
        if role == "assistant":
            seg = [m]
            i += 1
            while i < len(rest) and rest[i].get("role") == "tool":
                seg.append(rest[i])
                i += 1
            segs.append(seg)
        else:
            segs.append([m])
            i += 1
    return segs


async def compact_messages(
    messages: List[Dict[str, Any]],
    keep_turns: int,
    summarize: Callable[[str], Any],
) -> Tuple[List[Dict[str, Any]], bool]:
    """压缩早期轮次为一条阶段性工作记忆。

    返回 (new_messages, compacted)。任何失败都不抛异常：
      - 摘要调用失败 → 硬截断（丢弃被压缩的原文）并附一行说明，保证上下文不爆裂。
    """
    if not messages or len(messages) < 3:
        return messages, False
    segs = _split_segments(messages)
    if len(segs) <= max(1, int(keep_turns)):
        return messages, False

    old = segs[:-max(1, int(keep_turns))]
    keep = segs[-max(1, int(keep_turns)):]

    lines = []
    for seg in old:
        for m in seg:
            role = m.get("role")
            content = str(m.get("content") or "")
            if role == "assistant" and m.get("tool_calls"):
                names = "、".join((tc.get("function") or {}).get("name", "") for tc in m["tool_calls"])
                lines.append(f"[助手决定调用] {names}；说明：{content[:200]}")
            elif role == "tool":
                lines.append(f"[工具结果] {content[:600]}")
            elif role == "assistant":
                lines.append(f"[助手输出] {content[:300]}")
            elif role == "user":
                lines.append(f"[用户] {content[:200]}")
    transcript = "\n".join(lines)[:12000]

    summary_text = ""
    try:
        # L4-P2-2（2026-09-13）：摘要指令收紧。压缩最大的风险不是丢细节，而是**丢掉任务锚点** ——
        # 一旦模型忘了"用户到底要什么 / 计划进行到哪"，压缩后就会跑偏或重新做已完成的步。
        # 故强制保留：①用户原始诉求 ②计划各步状态 ③已完成步的结论与数据（含来源）④未完成事项。
        summary_text = await summarize(
            "下面是一段 agent 任务的执行过程记录。请把它压缩成「阶段性工作记忆」，"
            "用于替换原始记录、继续完成任务。**必须逐项保留（缺一不可）**：\n"
            "①【用户原始诉求】用户最初要什么（原话关键部分）；\n"
            "②【计划进度】计划各步骤的当前状态（完成/进行中/未开始/已放弃及原因）；\n"
            "③【已确认的结论与数据】已完成步骤得到的关键结论、数字与来源文件名 —— 这些是后续输出的依据；\n"
            "④【尚未完成】还差什么。\n"
            "丢弃过程性噪音（重复检索、失败尝试的具体报错等）。"
            "直接输出压缩结果，200-600 字，按①②③④分点，不要客套话。\n\n" + transcript
        )
        summary_text = (summary_text or "").strip()
    except Exception as e:  # noqa: BLE001 - 压缩永不阻断任务
        logger.warning("[runtime.context] 上下文压缩摘要失败，退化为硬截断: %s", e)
        summary_text = ""

    if not summary_text:
        # 硬截断兜底：即使摘要失败，**任务锚点也必须保留**（否则压缩后必然跑偏）。
        summary_text = (
            "（早期执行过程因上下文压缩且摘要生成失败而丢弃。）\n"
            "请立即重新确认：① 用户的原始诉求（见本轮 user 消息）；② 你的计划进行到哪一步；\n"
            "③ 已完成步骤的结论需重新获取 —— 如需其中信息，请重新检索，不要凭空编造。"
        )

    note = {"role": "system", "content": "【阶段性工作记忆（由宿主压缩早期执行过程，供你继续任务）】\n" + summary_text}
    new_messages = [messages[0], note]
    for seg in keep:
        new_messages.extend(seg)

    # ── L4-P2-2 压缩产物校验（fail-safe）：非法则**放弃本次压缩**，绝不腐蚀上下文 ──
    # 两个必须成立的不变式：
    #   ① messages[0] 仍是原 system 政策块（否则模型失去身份/契约/工具纪律）；
    #   ② 无孤儿 tool_calls（assistant.tool_calls 必须紧跟足量 tool 回填，否则 DeepSeek 直接 400）。
    if not isinstance(messages[0], dict) or messages[0].get("role") != "system":
        logger.error(
            "[runtime.context] 压缩产物校验失败：messages[0] 非 system（role=%r）→ 放弃本次压缩",
            (messages[0] or {}).get("role") if isinstance(messages[0], dict) else type(messages[0]).__name__,
        )
        return messages, False
    _shape = message_shape(new_messages)
    if "orphan" in _shape:
        logger.error(
            "[runtime.context] 压缩产物校验失败：出现孤儿 tool_calls（shape=%s）→ 放弃本次压缩（宁可超窗不可 400）",
            _shape[:400],
        )
        return messages, False

    logger.info(
        "[runtime.context] 上下文已压缩: %d 段 → 保留 %d 段，摘要 %d 字，压缩前 %s → 压缩后 %s tokens",
        len(segs), len(keep), len(summary_text),
        messages_tokens(messages), messages_tokens(new_messages),
    )
    return new_messages, True
