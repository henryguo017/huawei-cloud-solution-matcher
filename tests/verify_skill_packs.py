# -*- coding: utf-8 -*-
"""P2-Skills 行业技能包验证（零外部依赖，纯本地）。

覆盖：
  1. 5 个包 JSON 结构与内容合规（四段模板非空、playbook 非空、aliases 列表）
  2. 加载器：list_packs / load_pack / 缓存 / 坏包容错
  3. match_pack：规范名、别名、优先级、无命中
  4. 注入文本块：pack_prompt_block / pack_synthesize_block / 空安全

运行：python tests/verify_skill_packs.py   （项目根目录；venv 或 managed python 均可）
"""
import os
import sys
import json
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# venv 缺 numpy、managed python 缺 httpx：stub 掉 app/app.agent 包链后经 importlib 直载 skill_packs
import importlib.util
import types

_app = types.ModuleType("app")
_app.__path__ = [os.path.join(ROOT, "app")]
_agent = types.ModuleType("app.agent")
_agent.__path__ = [os.path.join(ROOT, "app", "agent")]
sys.modules.setdefault("app", _app)
sys.modules.setdefault("app.agent", _agent)

_spec = importlib.util.spec_from_file_location(
    "skill_packs", os.path.join(ROOT, "app", "agent", "skill_packs.py")
)
sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sp)

PASS = 0
FAIL = 0


def check(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[OK ] {label}")
    else:
        FAIL += 1
        print(f"[XX ] {label}" + (f"  -> {detail}" if detail else ""))


def main():
    # ── 1. 包内容合规 ──
    slugs = sp.list_packs()
    check("list_packs 枚举 5 包", len(slugs) == 5, f"got {slugs}")
    tpl_keys = {"demand_analyst", "solution_architect", "quality_reviewer", "synthesize"}
    for s in slugs:
        p = sp.load_pack(s)
        ok = (
            p and p.get("industry") and set((p.get("prompt_template") or {}).keys()) == tpl_keys
            and all(isinstance(v, str) and len(v) > 50 for v in p["prompt_template"].values())
            and isinstance(p.get("playbook"), list) and len(p["playbook"]) >= 5
            and isinstance(p.get("aliases"), list)
        )
        check(f"包 {s}（{p.get('industry') if p else '?'}）结构+内容量合规", bool(ok))
        # playbook 不得有空话（每条 ≥8 字）
        if p:
            check(f"包 {s} playbook 条目均为实质要点", all(len(x) >= 8 for x in p["playbook"]))

    # ── 2. 加载器容错 ──
    check("load_pack(None) → None", sp.load_pack(None) is None)
    check("load_pack('nonexistent') → None", sp.load_pack("nonexistent") is None)
    check("load_pack 缓存生效", sp.load_pack("manufacturing") is sp.load_pack("manufacturing"))

    # 坏包容错：临时目录放一个坏 JSON，隔离 _PACK_DIR
    with tempfile.TemporaryDirectory() as td:
        orig_dir = sp._PACK_DIR
        try:
            sp._PACK_DIR = td
            with open(os.path.join(td, "broken.json"), "w", encoding="utf-8") as f:
                f.write("{not-json")
            with open(os.path.join(td, "empty_tpl.json"), "w", encoding="utf-8") as f:
                json.dump({"industry": "坏包", "prompt_template": {}}, f)
            sp._cache.clear()
            check("坏 JSON 包被跳过", sp.load_pack("broken") is None)
            check("空模板包被判不合规", sp.load_pack("empty_tpl") is None)
            check("坏包目录下 list/match 不崩", sp.match_pack(["制造"]) is None)
        finally:
            sp._PACK_DIR = orig_dir
            sp._cache.clear()

    # ── 3. match_pack 匹配 ──
    m = sp.match_pack(["制造"])
    check("规范名命中：制造→manufacturing", m and m["slug"] == "manufacturing")
    m = sp.match_pack(["某行业", "医院", "其他"])
    check("别名命中：医院→healthcare", m and m["slug"] == "healthcare")
    m = sp.match_pack(["XX", "农商行"])
    check("别名命中：农商行→finance", m and m["slug"] == "finance")
    m = sp.match_pack(["教育"])
    check("无包行业 → None（不误挂）", m is None)
    m = sp.match_pack([])
    check("空行业列表 → None", m is None)
    m = sp.match_pack(["医疗", "制造"])
    check("多行业按意图顺序优先", m and m["slug"] == "healthcare")

    # ── 4. 注入文本块 ──
    pack = sp.load_pack("manufacturing")
    blk = sp.pack_prompt_block(pack, "solution_architect")
    check("角色块含包头+内容", blk.startswith("\n\n【行业技能包 · 制造】") and "IoT" in blk)
    check("角色块缺段 → 空串", sp.pack_prompt_block(pack, "nonexistent_key") == "")
    syn = sp.pack_synthesize_block(pack)
    check("终稿块含 synthesize+playbook", "终稿必备行业要点" in syn and syn.count("\n- ") >= 5)
    check("None 包 → 全空串", sp.pack_prompt_block(None, "synthesize") == "" and sp.pack_synthesize_block(None) == "")

    print(f"\n{PASS}/{PASS + FAIL} passed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
