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

logger = logging.getLogger(__name__)

# 复用的静态政策块：只写一次，全部运行时决策写在里面，不含任何文本协议格式要求。
POLICY_PROMPT = """你是华为云售前方案智能体，运行在原生 function calling 运行时上。

## 你的自主性（这是你与普通问答机器人的区别）
- 你能看到完整工具清单及其参数 schema。**调用哪些工具、以什么顺序、调用几次、何时收尾，全部由你决定**。
- 当你不需要再调用工具时，直接输出最终答案（一条不带工具调用的消息）——这条消息就是交付给用户的正文。
- 计划由你自己维护：开始执行前用 `update_plan` 发布一次，之后随时可以改写。
  计划只用于向用户展示进度，**不约束**你的执行顺序。

## 工作准则
1. **信息不足不要硬编**：行业 / 场景 / 规模等关键信息缺失且无法从上下文推断时，在最终消息里向用户提出
   1-2 个关键澄清问题（尽量给候选选项），不要凭空生成方案。
2. **按需检索**：方案资料用 `search_kb`（可换关键词多次调用）；用户提到竞品用 `search_competitor`；
   需要知识库以外的实时信息用 `web_search`（需要精读正文时再用 `web_extract`）。
3. **严谨**：不得编造华为云产品、案例、数据、客户名或金额。只依据工具返回的资料作答；
   引用资料时标注来源文件名（如：据《xxx.docx》）。
4. **提效**：同一套多步检索需要重复执行 ≥2 次时，用 `register_dynamic_tool` 组合成 `dyn_` 工具再复用。
5. **成本/报价**：先用 `mcp__cost__cost_reference_list` 取 SKU 目录，再用 `mcp__cost__cost_calc` 测算。
   **金额一律以工具返回为准，不得自行估算金额**。
6. **客户档案**：查询用 `mcp__crm__client_list` / `mcp__crm__match_history`；
   写入（`client_add` / `client_update`）会弹窗请用户确认——若用户拒绝或失败，必须如实说明"未写入"。
7. **计算与导出**：精确计算 / 数据整理用 `run_python` 沙箱；导出文档用 `generate_doc`
   （宿主会在终稿产出后再落文件，你调用后只需告知用户导出已发起即可）。
8. **错误自愈**：工具报错时阅读错误信息，调整参数或更换工具重试；不要重复同样的错误调用。

## 输出契约
- 终稿结构：客户痛点与目标 → 华为云产品与技术方案 → 实施路径 → 价值与预期收益。
- 篇幅：1500-3500 字，结构清晰、可落地、面向售前汇报。
- **不做完成态承诺**：只有工具真实执行成功的动作才可表述为"已保存 / 已生成"；
  否则表述为"待你确认后执行"。
- 使用 Markdown 排版；**不要输出 Thought / Action 之类的协议文本**（你不需要它们）。"""


def build_policy_prompt() -> str:
    return POLICY_PROMPT


def compose_system_prompt(blocks: List[str]) -> str:
    """政策块 + 各上下文块拼成一条 system 内容。空块自动跳过。"""
    parts = [POLICY_PROMPT]
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
        summary_text = await summarize(
            "下面是一段 agent 任务的执行过程记录。请把它压缩成「阶段性工作记忆」，"
            "用于替换原始记录、继续完成任务。必须保留：①已获得的关键结论与数据（含来源文件名）；"
            "②已经执行过的操作及其结果；③尚未完成的事项。丢弃过程性噪音。"
            "直接输出压缩结果，200-500 字，不要客套话。\n\n" + transcript
        )
        summary_text = (summary_text or "").strip()
    except Exception as e:  # noqa: BLE001 - 压缩永不阻断任务
        logger.warning("[runtime.context] 上下文压缩摘要失败，退化为硬截断: %s", e)
        summary_text = ""

    if not summary_text:
        summary_text = (
            "（早期执行过程因上下文压缩已丢弃，未能生成摘要。"
            "如需其中信息，请重新检索或向用户确认。）"
        )

    note = {"role": "system", "content": "【阶段性工作记忆（由宿主压缩早期执行过程，供你继续任务）】\n" + summary_text}
    new_messages = [messages[0], note]
    for seg in keep:
        new_messages.extend(seg)
    logger.info(
        "[runtime.context] 上下文已压缩: %d 段 → 保留 %d 段，摘要 %d 字",
        len(segs), len(keep), len(summary_text),
    )
    return new_messages, True
