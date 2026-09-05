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
    """
    if not industries:
        return None
    for slug in list_packs():
        pack = load_pack(slug)
        if not pack:
            continue
        names = {pack.get("industry")} | set(pack.get("aliases") or [])
        for ind in industries:
            if ind in names:
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
    header = f"\n\n【行业技能包 · {industry}】（挂载版本 {pack.get('version') or 'n/a'}）"
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
