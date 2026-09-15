# -*- coding: utf-8 -*-
"""华为红售前 PPT 引擎 — 分发器 + 出稿门禁

deck 结构：
    {"pages": [{"layout": "cover", "data": {...}}, ...]}

门禁（validate_deck，违规直接拒绝出稿，引擎绝不静默降级）：
- layout 必须在 12 版式白名单内；
- data 的槽名必须在 SLOT_SPEC 白名单内（防 LLM 幻觉槽位）；
- 字符串槽超 max_chars、列表槽超 max_items / item_chars 即拒绝；
- header 槽必含 sec/sec_name/headline/page_no。
"""
from .layouts import LAYOUTS, SLOT_SPEC
from . import tokens as T


class DeckValidationError(ValueError):
    """deck 未过门禁（版式未知 / 槽位幻觉 / 容量超限）"""


def _check_header(layout, data, problems):
    h = data.get('header')
    if not isinstance(h, dict):
        problems.append('%s: header 槽缺失' % layout)
        return
    for k in ('sec', 'sec_name', 'headline', 'page_no'):
        if not h.get(k):
            problems.append('%s: header.%s 必填' % (layout, k))
    if h.get('stats') and len(h['stats']) > 3:
        problems.append('%s: header.stats 最多 3 组' % layout)


def _check_str(layout, slot, rule, val, problems, where=''):
    if len(val) > rule['max_chars']:
        problems.append('%s%s: 超容量 %d/%d 字'
                        % (layout, where or ('.' + slot), len(val),
                           rule['max_chars']))


def _check_list(layout, slot, rule, val, problems):
    if len(val) > rule['max_items']:
        problems.append('%s.%s: %d 项超上限 %d'
                        % (layout, slot, len(val), rule['max_items']))
    ic = rule.get('item_chars')
    if not ic:
        return
    for i, item in enumerate(val):
        parts = item if isinstance(item, (list, tuple)) else [item]
        for part in parts:
            if isinstance(part, str) and len(part) > ic:
                problems.append('%s.%s[%d]: 元素超 %d 字'
                                % (layout, slot, i, ic))


def validate_deck(deck):
    """返回 problems 列表；空列表 = 通过门禁"""
    problems = []
    pages = deck.get('pages')
    if not isinstance(pages, list) or not pages:
        return ['deck.pages 必须为非空列表']
    for i, page in enumerate(pages, 1):
        layout = page.get('layout')
        if layout not in LAYOUTS:
            problems.append('page%d: 未知版式 %r（白名单 %s）'
                            % (i, layout, sorted(LAYOUTS)))
            continue
        data = page.get('data') or {}
        spec = SLOT_SPEC[layout]
        for slot, val in data.items():
            if slot not in spec:
                problems.append('page%d(%s): 幻觉槽位 %r' % (i, layout, slot))
                continue
            rule = spec[slot]
            if rule['type'] == 'header':
                _check_header(layout, data, problems)
            elif rule['type'] == 'str':
                _check_str(layout, slot, rule, val, problems,
                           where='(page%d)' % i)
            elif rule['type'] == 'list':
                _check_list(layout, slot, rule, val, problems)
            elif rule['type'] == 'dict':
                _check_dict(layout, slot, rule, val, problems,
                            where='(page%d)' % i)
    return problems


def _check_dict(layout, slot, rule, val, problems, where=''):
    """dict 槽（表格等）行数上限：超出会被版式固定几何裁切/重叠"""
    mr = rule.get('max_rows')
    if mr and isinstance(val, dict) and isinstance(val.get('rows'), list):
        if len(val['rows']) > mr:
            problems.append('%s%s: 表格 %d 行超上限 %d'
                            % (layout, where or ('.' + slot),
                               len(val['rows']), mr))


def render_deck(prs, deck):
    """deck → 逐页渲染；先过 validate_deck 门禁，不通过抛 DeckValidationError"""
    problems = validate_deck(deck)
    if problems:
        raise DeckValidationError(
            'deck 未过出稿门禁（%d 项）:\n- %s'
            % (len(problems), '\n- '.join(problems)))
    n = len(deck['pages'])
    if n != T.TOTAL_PAGES:
        raise DeckValidationError(
            '页数 %d ≠ 模板 %d 页（样张模板固定 12 页结构）' % (n, T.TOTAL_PAGES))
    for page in deck['pages']:
        LAYOUTS[page['layout']](prs, page.get('data') or {})
    return len(deck['pages'])
