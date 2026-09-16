# -*- coding: utf-8 -*-
"""L4-P2 Agent Runtime · 完成态核验（verify.py）

原则：**完成态声明必须由宿主核验。**

模型可以在正文里写"已为你保存客户档案"，但"是否真的落库"只有宿主知道。
本项目为此踩过真实的坑（模型声称已建档、实际未落库）。legacy 路径用"强制补步"兜住，
那是代码替模型决策；本模块用架构手段解决：宿主记录真实写操作，在终稿产出后核验断言，
不一致时**把问题交回模型自我修正**（一次），失败才用宿主机注兜底。
修正权仍在模型手里（符合"终稿归模型所有"），宿主只做核验与触发。
"""

import json
import logging
import re
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger(__name__)

# 写操作工具 → 事实类别（crm_read：只读查询也纳入核验——防"未查询却报出客户数据"）
FACT_KIND_BY_TOOL: Dict[str, str] = {
    "mcp__crm__client_add": "crm_write",
    "mcp__crm__client_update": "crm_write",
    "mcp__crm__client_delete": "crm_write",
    "mcp__crm__client_list": "crm_read",
    "mcp__crm__match_history": "crm_read",
    "generate_doc": "doc_export",
    "memory_write": "memory_write",   # L4 P2-4：自写记忆落库也是写操作，纳入完成态核验
}

KIND_LABEL = {
    "crm_write": "客户档案写入",
    "crm_read": "客户档案查询",
    "doc_export": "文档导出",
    "memory_write": "笔记写入",
}

# 断言模式：(正则, 事实类别)。刻意收紧以降低误报 —— 误报会多花一轮模型自纠。
_CLAIM_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"(?:客户)?(?:档案|信息|资料)(?:已经|已)?(?:保存|建档|录入|创建|新增|更新|修改)"), "crm_write"),
    (re.compile(r"已(?:为你|经|成功)?(?:保存|建档|录入|新增|创建|更新|修改)(?:了)?[^。；\n]{0,12}(?:客户|档案)"), "crm_write"),
    (re.compile(r"已(?:为你|经|成功)?(?:生成|导出)(?:了)?(?:一?份)?\s*(?:Word|PDF|PPTX?|pptx?|文档|方案书|文件)", re.IGNORECASE), "doc_export"),
    (re.compile(r"(?:Word|PDF|PPTX?|文档|方案书|文件)(?:已经|已)(?:生成|导出)完毕", re.IGNORECASE), "doc_export"),
    # L4 P2-4：记忆完成态断言（刻意收紧 —— 只匹配明确的「写入笔记/记忆」语义，
    # 避免把「已记录你的需求」这类对话性表述误判成落库断言）。把字句（把XX写入笔记）单独覆盖。
    (re.compile(r"(?:已经|已)(?:为你|把它)?(?:把[^，。\n]{0,12})?(?:写入|记入|存入)(?:了)?(?:长期)?(?:笔记|记忆)"), "memory_write"),
    (re.compile(r"已(?:经|为你)?(?:记住|记下)(?:了)?(?:这|该|此)[^。；\n]{0,12}(?:条|信息|口径|事实|偏好)"), "memory_write"),
    (re.compile(r"(?:笔记)(?:已经|已)(?:保存|写入|落库)"), "memory_write"),
    # crm_read（2026-09-16）：客户档案/历史方案的**数据性断言**——声称查到了具体数据，
    # 但工具记录里没有成功的 CRM 读调用＝编造客户数据（比写幻觉更隐蔽）。刻意收窄到
    # 第二人称占有/呈现句式，避免把"华为云客户案例显示…"这类公共资料表述误判。
    (re.compile(r"你的?客户(?:档案|列表|名单|名录|资料)[^。；\n]{0,16}(?:共有|一共|包括|显示)"), "crm_read"),
    (re.compile(r"(?:客户档案|客户列表|客户名单|历史方案|匹配记录|方案历史)[^。；\n]{0,6}(?:显示|如下)"), "crm_read"),
    (re.compile(r"你(?:曾|曾经)?(?:给|为|向)[^。；\n]{0,12}(?:做|生成|提供|输出)过方案"), "crm_read"),
]

_NEGATIVE_MARKERS = ("Error:", '"status": "error"', "你拒绝", "已跳过", "不允许", "参数不正确", "执行失败",
                     "错误：", "未保存", "未落库")


def _looks_success(observation: str) -> bool:
    text = observation or ""
    return not any(mark in text for mark in _NEGATIVE_MARKERS)


def collect_write_facts(tool_calls_log: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """从工具调用记录中提取**真实成功执行**的写操作，作为核验事实。"""
    facts: List[Dict[str, str]] = []
    for entry in (tool_calls_log or []):
        if not isinstance(entry, dict):
            continue
        tool = str(entry.get("tool") or "")
        kind = FACT_KIND_BY_TOOL.get(tool)
        if not kind:
            continue
        obs = str(entry.get("result") or "")
        if not _looks_success(obs):
            continue
        facts.append({"tool": tool, "kind": kind, "summary": obs[:200].replace("\n", " ")})
    return facts


def fact_kinds(facts: List[Dict[str, str]]) -> Set[str]:
    return {f.get("kind") for f in (facts or []) if isinstance(f, dict)}


def build_fact_block(facts: List[Dict[str, str]]) -> str:
    """注入 system 的「宿主核验事实」块。空清单也要注入 —— 明确告诉模型"什么都还没执行"。"""
    if not facts:
        return (
            "【宿主核验事实】本次运行**尚未**真实执行任何写操作或客户档案查询"
            "（客户档案写入/查询、文档导出、笔记写入均未发生）。\n"
            "因此你**不得**在正文中表述「已保存」「已建档」「已生成文件」「已写入笔记/记忆」等完成态；"
            "也**不得**虚构「你的客户档案/历史方案」的具体数据（如需引用客户数据，"
            "应调用 mcp__crm__client_list / mcp__crm__match_history 真实查询）；"
            "如需这些动作，应调用对应工具（写操作会请用户确认），或表述为「待你确认后执行」。"
        )
    lines = []
    for f in facts:
        lines.append(f"- {KIND_LABEL.get(f.get('kind'), f.get('kind'))}：{f.get('tool')}（成功）")
    return (
        "【宿主核验事实（本次真实执行成功的写操作，以此为准）】\n" + "\n".join(lines)
        + "\n除此之外的写操作**未执行**，不得声称完成。"
    )


def scan_false_write_claims(answer: str, facts: List[Dict[str, str]]) -> List[str]:
    """扫描终稿中与宿主事实不符的完成态断言，返回**缺失事实的类别**列表。"""
    if not answer:
        return []
    present = fact_kinds(facts)
    missing: List[str] = []
    for pattern, kind in _CLAIM_PATTERNS:
        if kind in present or kind in missing:
            continue
        if pattern.search(answer):
            missing.append(kind)
    return missing


def build_correction_instruction(missing: List[str], facts: List[Dict[str, str]]) -> str:
    """给模型的自纠指令（走一次模型回合，修正权归模型）。"""
    names = "、".join(KIND_LABEL.get(k, k) for k in missing)
    return (
        "【宿主完成态核验未通过】你在上一轮给出的正文中声称已完成：" + names
        + "，但宿主记录显示这些操作**并未真实执行**。\n"
        + ("本次真实执行成功的写操作：\n" + "\n".join(f"- {f.get('tool')}" for f in facts) + "\n" if facts else "本次没有任何写操作真实执行成功。\n")
        + "请立即修正正文：把不实的完成态表述改为如实描述"
          "（写操作如「我可以为你导出 / 建档，确认后执行」；"
          "客户数据如「我可以为你查询客户档案」，或改用真实工具结果），"
          "其余内容保持不变。只输出修正后的完整正文。"
    )
