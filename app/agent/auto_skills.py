# -*- coding: utf-8 -*-
"""L4-P3-2 自建技能（auto_skills）：模型把一次成功的工作流**固化成能力包**，后续任务自动挂载。

与 skill_packs（预置 15 包）的关系：
  预置包由人手写；本模块让模型在任务成功后自我沉淀——产出结构对齐能力包
  （kind=capability + triggers），走 match_capability 挂载，**零代码改动**（地基已有）。

质量控制与安全：
1. slug 强制 `user_` 前缀（永不覆盖 15 个预置包）；同名 = 更新（去重收敛）；
2. triggers 至少声明一个维度（intents/keywords），否则该包永不生效，拒绝入库；
3. prompt_template 四段至少两段非空、playbook ≥2 条——防"垃圾技能"污染后续任务；
4. 写入是 ask 闸门动作（用户确认后才落盘）；
5. 热加载：写盘后失效 skill_packs._cache 对应条目，下一任务即刻可挂载；
6. 总开关 AGENT_AUTO_SKILLS（默认 0=关），回退 = 置 0 重启 / 删 data/skill_packs/user_*.json。
"""
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_SLUG_RE = re.compile(r"^user_[a-z][a-z0-9_]{2,39}$")
TEMPLATE_KEYS = ("demand_analyst", "solution_architect", "quality_reviewer", "synthesize")
PLAYBOOK_MAX = 20
MAX_USER_PACKS = 15          # 自建包数量上限（防持久化膨胀）

VALID_INTENTS = {"solution", "competitor", "knowledge_q", "general", "file_ops",
                 "export", "greeting", "account"}


def _pack_dir() -> str:
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "skill_packs",
    )


def list_user_packs() -> List[str]:
    try:
        return sorted(
            f[:-5] for f in os.listdir(_pack_dir())
            if f.startswith("user_") and f.endswith(".json")
        )
    except Exception:  # noqa: BLE001
        return []


def validate_pack(slug: str, display_name: str, trigger_intents: List[str],
                  trigger_keywords: List[str], role_blocks: Dict[str, str],
                  playbook: List[str]) -> Tuple[bool, str]:
    """静态校验自建能力包定义。错误信息面向 LLM，可直接回喂修正。"""
    slug = str(slug or "").strip().lower()
    if not _SLUG_RE.match(slug):
        return False, (f"slug '{slug}' 不合法：必须以 user_ 开头，全小写字母/数字/下划线，"
                       "总长 5-43，如 user_bidding_checklist")
    if not (2 <= len(str(display_name or "").strip()) <= 40):
        return False, "display_name 必须为 2-40 字（用于挂载提示里的展示名）"
    intents = [str(i).strip() for i in (trigger_intents or []) if str(i).strip()]
    keywords = [str(k).strip() for k in (trigger_keywords or []) if str(k).strip()]
    bad_intents = [i for i in intents if i not in VALID_INTENTS]
    if bad_intents:
        return False, f"触发意图不合法：{bad_intents}（可选值：{sorted(VALID_INTENTS)}）"
    if not intents and not keywords:
        return False, "triggers 至少要声明一个维度（trigger_intents 或 trigger_keywords），否则该包永远不会被挂载"
    if len(intents) > 4 or len(keywords) > 12:
        return False, "触发条件过多（intents ≤4 个、keywords ≤12 个）——技能包应聚焦单一动作"
    role_blocks = role_blocks or {}
    if not isinstance(role_blocks, dict):
        return False, "role_blocks 必须是对象，键为四段：demand_analyst / solution_architect / quality_reviewer / synthesize"
    nonempty = [k for k in TEMPLATE_KEYS if str(role_blocks.get(k) or "").strip()]
    if len(nonempty) < 2:
        return False, (f"role_blocks 至少要有两段非空内容（当前非空段：{nonempty}）。"
                       "至少应包含 synthesize（终稿口径）——这是挂载后真正影响交付质量的段落")
    for k in nonempty:
        if len(str(role_blocks[k])) > 2000:
            return False, f"role_blocks.{k} 超长（>2000 字符）——技能包是口径与要点，不是全文"
    playbook = [str(p).strip() for p in (playbook or []) if str(p).strip()]
    if len(playbook) < 2:
        return False, "playbook 至少要有 2 条终稿必备要点"
    if len(playbook) > PLAYBOOK_MAX:
        return False, f"playbook 最多 {PLAYBOOK_MAX} 条"
    return True, ""


def save_pack(slug: str, display_name: str, trigger_intents: List[str],
              trigger_keywords: List[str], role_blocks: Dict[str, str],
              playbook: List[str], source_summary: str = "") -> Tuple[bool, str]:
    """校验并落盘一个自建能力包（同名 = 更新），并失效内存缓存（热加载）。"""
    ok, err = validate_pack(slug, display_name, trigger_intents, trigger_keywords, role_blocks, playbook)
    if not ok:
        return False, err
    slug = slug.strip().lower()
    pack = {
        "slug": slug,
        "kind": "capability",
        "industry": str(display_name).strip(),
        "origin": "model_created",
        "source_summary": str(source_summary or "").strip()[:300],
        "triggers": {
            "intents": [str(i).strip() for i in (trigger_intents or []) if str(i).strip()],
            "keywords": [str(k).strip() for k in (trigger_keywords or []) if str(k).strip()],
        },
        "version": time.strftime("%Y-%m-%d"),
        "prompt_template": {k: str(role_blocks.get(k) or "").strip() for k in TEMPLATE_KEYS},
        "playbook": [str(p).strip() for p in (playbook or []) if str(p).strip()],
    }
    try:
        os.makedirs(_pack_dir(), exist_ok=True)
        path = os.path.join(_pack_dir(), f"{slug}.json")
        existed = os.path.exists(path)
        if not existed and len(list_user_packs()) >= MAX_USER_PACKS:
            return False, f"自建技能包数已达上限（{MAX_USER_PACKS}），请先更新/清理已有 user_ 包"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(pack, f, ensure_ascii=False, indent=1)
        # 热加载：失效缓存，下一任务 match_capability 即刻可见
        from app.agent import skill_packs as sp
        sp._cache.pop(slug, None)
        logger.info("[auto_skill] 已保存自建能力包 %s（%s）", slug, "更新" if existed else "新建")
        return True, (f"能力包 {slug} 已{'更新' if existed else '创建'}。"
                      "后续命中触发条件的任务会自动挂载该包（无需重启）。")
    except Exception as e:  # noqa: BLE001
        logger.warning("[auto_skill] 保存失败: %s", e)
        return False, f"保存失败：{e}"


def delete_pack(slug: str) -> Tuple[bool, str]:
    """删除一个自建包（只允许删 user_ 前缀——预置包受保护）。"""
    slug = str(slug or "").strip().lower()
    if not _SLUG_RE.match(slug):
        return False, f"slug '{slug}' 不合法（且预置包受保护，只允许删除 user_ 前缀的自建包）"
    path = os.path.join(_pack_dir(), f"{slug}.json")
    if not os.path.exists(path):
        return False, f"包 {slug} 不存在"
    try:
        os.remove(path)
        from app.agent import skill_packs as sp
        sp._cache.pop(slug, None)
        return True, f"已删除自建包 {slug}"
    except Exception as e:  # noqa: BLE001
        return False, f"删除失败：{e}"
