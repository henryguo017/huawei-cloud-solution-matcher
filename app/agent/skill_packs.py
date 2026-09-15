# -*- coding: utf-8 -*-
"""P2 Skills：行业技能包加载器（纯标准库，零新依赖）。

职责：
  - 从 data/skill_packs/<slug>.json 加载行业技能包（模块级缓存，进程内只读一次磁盘）；
  - match_pack(industries)：按意图分类产出的行业词列表匹配首个可用包；
  - 任何 IO / 格式 / 校验异常 → 返回 None（调用方静默降级，绝不阻断主链路）。

包格式（v1，只注入提示词、不改工具集）：
{
  "slug": "manufacturing",
  "industry": "制造",                    # 规范行业名（与 intent._INDUSTRY_KEYWORDS 对齐）
  "aliases": ["工业", "工厂", "装备"],    # 意图行业词别名（命中任一即匹配）
  "version": "2026-09-06",
  "prompt_template": {
    "demand_analyst":    "...",          # 需求分析师角色追加块
    "solution_architect": "...",         # 方案架构师角色追加块
    "quality_reviewer":  "...",          # 质量校验官角色追加块
    "synthesize":        "..."           # 终稿汇总口径追加块
  },
  "playbook": ["要点1", "要点2", ...]    # 终稿必备行业要点（随 synthesize 注入）
}

能力包格式（v2，P1-B：按"动作"维度挂载，与行业包正交、可同时生效）：
{
  "slug": "capability_ppt",
  "kind": "capability",                 # 关键：标明是能力包（缺省即行业包，向后兼容 11 个行业包）
  "industry": "PPT生成",                 # 展示名（行业包这里是规范行业名）
  "triggers": {                          # 声明式触发条件，纯数据驱动，新增能力包无需改代码
    "intents": ["export"],               # 可选：意图名命中其一（空=不限意图）
    "keywords": ["PPT", "幻灯片"]         # 可选：原文出现其一（空=不限关键词，大小写不敏感）
  },                                     # 语义 = AND（声明了的维度必须命中）；两者都空则该包永不生效
  "version": "2026-09-06",
  "prompt_template": { ... 同上四段 ... },
  "playbook": ["要点1", ...]
}

设计铁律：
  - 默认关：AGENT_SKILL_PACKS=0 时 harness 根本不调用本模块；
  - 失败吞掉：读文件/解析/校验失败仅记 warning 并返回 None；
  - 不碰工具集：本模块只产出提示词文本，工具集决策仍归 harness 角色/映射表。
"""

import os
import json
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# data/skill_packs 目录（仓库内；本文件位于 app/agent/ 下，需回退三级到仓库根）
_PACK_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "skill_packs",
)

# 进程内缓存：slug → pack dict（含加载失败标记，避免反复读坏文件）
_cache: Dict[str, Optional[dict]] = {}

# 包类型标记：值为 capability 表示「能力包」（按动作维度挂载）；缺省/其他值均视为行业包。
# 行业包 11 个无此字段 → 天然向后兼容。
CAPABILITY_KIND = "capability"


def list_packs() -> List[str]:
    """枚举可用包 slug（按文件名排序）。目录不存在/IO 异常返回空表。"""
    try:
        if not os.path.isdir(_PACK_DIR):
            return []
        return sorted(
            f[:-5] for f in os.listdir(_PACK_DIR)
            if f.endswith(".json") and not f.startswith(".")
        )
    except Exception as e:  # pragma: no cover - 防御性
        logger.warning("[skill_packs] 枚举失败: %s", e)
        return []


def load_pack(slug: str) -> Optional[dict]:
    """加载单个行业包（带缓存与最小校验）。非法/缺失返回 None。"""
    if not slug or not isinstance(slug, str):
        return None
    if slug in _cache:
        return _cache[slug]
    pack = None
    path = os.path.join(_PACK_DIR, f"{slug}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 最小校验：industry 必填非空；prompt_template 至少有一段可用内容
        tpl = data.get("prompt_template") or {}
        if isinstance(data, dict) and data.get("industry") and any(
            isinstance(v, str) and v.strip() for v in tpl.values()
        ):
            data.setdefault("aliases", [])
            data.setdefault("playbook", [])
            data.setdefault("version", "")
            pack = data
        else:
            logger.warning("[skill_packs] 包结构不合规（缺 industry 或 prompt_template 为空）: %s", slug)
    except FileNotFoundError:
        logger.warning("[skill_packs] 包不存在: %s", slug)
    except Exception as e:
        logger.warning("[skill_packs] 加载失败（跳过）: %s (%s)", slug, e)
    _cache[slug] = pack
    return pack


def match_pack(industries: List[str]) -> Optional[dict]:
    """按意图行业词列表匹配首个可用包。

    匹配规则：行业词 == pack.industry 或行业词 ∈ pack.aliases。
    顺序跟随意图分类器的 industries 列表（靠前的行业优先）。

    注意：只匹配「行业包」——kind=capability 的能力包由 match_capability 挂载，
    两者维度正交（可同时生效），此处必须跳过，否则能力包会被当行业包误挂。
    """
    if not industries:
        return None
    for slug in list_packs():
        pack = load_pack(slug)
        if not pack:
            continue
        if (pack.get("kind") or "").strip() == CAPABILITY_KIND:
            continue
        names = {pack.get("industry")} | set(pack.get("aliases") or [])
        for ind in industries:
            if ind in names:
                return pack
    return None


def match_capability(intent_name: str, text: str = "") -> Optional[dict]:
    """按「动作」维度匹配能力包（P1-B）。

    与 match_pack（行业维度）正交：能力包按"用户想做什么"挂载，触发条件写在包内
    `triggers` 字段，纯数据驱动——新增能力包只需加 JSON，无需改本文件：

        "triggers": {"intents": ["export"], "keywords": ["PPT", "幻灯片"]}

    匹配语义（AND）：
      - intents 非空 → intent_name 必须命中其一；为空则不限意图；
      - keywords 非空 → text（大小写不敏感）中必须出现其一；为空则不限关键词；
      - 两者都为空 → 该包永不生效（防止空 triggers 误挂全部会话），直接跳过。

    首个命中即返回（按 slug 排序），无命中返回 None。任何异常静默降级。
    """
    if not intent_name and not text:
        return None
    low = (text or "").lower()
    for slug in list_packs():
        pack = load_pack(slug)
        if not pack or (pack.get("kind") or "").strip() != CAPABILITY_KIND:
            continue
        trig = pack.get("triggers") or {}
        intents = [x for x in (trig.get("intents") or []) if isinstance(x, str) and x.strip()]
        keywords = [x for x in (trig.get("keywords") or []) if isinstance(x, str) and x.strip()]
        # 两个维度都未声明 → 不生效，避免误挂
        if not intents and not keywords:
            continue
        # AND 语义：声明了的维度必须命中，未声明的维度不限制
        if intents and (intent_name or "") not in intents:
            continue
        if keywords and not any(k.lower() in low for k in keywords):
            continue
        return pack
    return None


def pack_prompt_block(pack: Optional[dict], key: str) -> str:
    """取包内指定段落的注入文本块；无包/无该段返回空串（调用方直接拼接即可）。"""
    if not pack:
        return ""
    tpl = pack.get("prompt_template") or {}
    text = (tpl.get(key) or "").strip()
    if not text:
        return ""
    industry = pack.get("industry") or ""
    # 行业包 vs 能力包：提示词头区分，便于日志/排障时一眼看出挂的是哪一类
    label = "能力技能包" if (pack.get("kind") or "").strip() == CAPABILITY_KIND else "行业技能包"
    header = f"\n\n【{label} · {industry}】（挂载版本 {pack.get('version') or 'n/a'}）"
    return header + "\n" + text


def pack_synthesize_block(pack: Optional[dict]) -> str:
    """终稿口径块 = synthesize 段 + playbook 要点清单。"""
    if not pack:
        return ""
    block = pack_prompt_block(pack, "synthesize")
    playbook = [p for p in (pack.get("playbook") or []) if isinstance(p, str) and p.strip()]
    if playbook:
        block += "\n终稿必备行业要点（逐条对照，缺失需补齐）：\n" + "\n".join(
            f"- {p}" for p in playbook
        )
    return block
