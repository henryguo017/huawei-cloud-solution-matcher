# -*- coding: utf-8 -*-
"""PPT 引擎客户数字提取回归（P2-9，2026-09-15）。

背景：用户实测反馈对话里收来的客户数字（240 台设备 / OEE 60% / 300 万预算）
没进生成的 PPT。修复 = generator._extract_client_facts 按句提取事实清单 +
硬性注入两段式提示词（段1大纲/段2填槽）。本文件锁住提取器行为，防止回退。

全部为纯函数测试（无 LLM / 无服务器），可进 CI smoke 层。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.ppt_engine.generator import (  # noqa: E402
    _extract_client_facts,
    _facts_hint,
)


def _nums(facts):
    return [f[0] for f in facts]


def _labels(facts):
    return [f[1] for f in facts]


def test_core_client_numbers():
    """240台设备 / OEE 60% / 停机率8% 三大核心数字必须原样提取"""
    facts = _extract_client_facts(
        "现场共有240台设备，综合效率OEE仅60%，非计划停机率高达8%。")
    assert "240台" in _nums(facts), facts
    assert "60%" in _nums(facts), facts
    assert "8%" in _nums(facts), facts
    assert any("OEE" in l for l in _labels(facts)), facts


def test_wan_yuan_unit_not_truncated():
    """「300万元」必须完整提取（2026-09-15 修复：万 先行吞量级截成 300万）"""
    facts = _extract_client_facts("项目预算300万元，希望当年收回投资。")
    assert "300万元" in _nums(facts), facts
    facts2 = _extract_client_facts("每月因停机损失约50万元产值。")
    assert "50万元" in _nums(facts2), facts2


def test_label_connective_trim():
    """标签尾部连接词（和/与/及/或）剥除，不产出「工厂和」脏标签"""
    facts = _extract_client_facts("我们有两座工厂和1200名员工。")
    for label in _labels(facts):
        assert label[-1] not in "和与及或", facts


def test_dedup_and_cap():
    """同一数值只保留第一条；条数不超过上限"""
    facts = _extract_client_facts("OEE从60%，到综合效率OEE 60%为止。")
    assert _nums(facts).count("60%") == 1, facts
    blob = "。".join(f"指标{i}为{i}0个点" for i in range(20))
    assert len(_extract_client_facts(blob, max_facts=5)) == 5


def test_no_facts_returns_empty():
    """无数字典料返回空清单（提示词块为空串，不影响原管线）"""
    assert _extract_client_facts("该方案聚焦降本增效与合规运营。") == []
    assert _facts_hint([]) == ""


def test_facts_hint_renders_guardrail():
    """提示词块必须带「禁止改动数值与单位」护栏文案"""
    hint = _facts_hint([["240台", "现场设备"], ["60%", "OEE"]])
    assert "240台" in hint and "OEE" in hint
    assert "禁止改动" in hint


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"[FAIL] {fn.__name__}: {e}")
    print(f"\n{len(fns) - failed}/{len(fns)} PASS")
    sys.exit(1 if failed else 0)
