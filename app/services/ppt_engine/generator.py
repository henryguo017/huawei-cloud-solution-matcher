# -*- coding: utf-8 -*-
"""华为红售前 PPT 引擎 — DeepSeek 两段式 deck 生成器（P2）

模板锁定设计：
- 12 个版式的**顺序与几何完全固定**（引擎 layouts），LLM 只做两件事：
  段1「大纲」：通读方案内容，为 10 个内容页产出 headline + 要点 + 关键数字；
  段2「填槽」：按 SLOT_SPEC 模板分批把大纲 + 原文素材填成每页 data JSON。
- 版式序列硬编码（cover→toc→background→pain_points→requirements→
  architecture→compare→cost→security→roadmap→service→end），
  LLM 无权增删页或改版式。
- 成本页数字纪律：前端传入 cost_reference（成本卡片编辑态）时，表格与
  合计**程序化生成**，LLM 不碰任何金额（防编造）。
- 质量门禁：每批生成即过 validate_deck 批校验，失败把问题回喂重试；
  整体仍失败抛 DeckGenerateError，由调用方降级 legacy 渲染。
"""
import asyncio
import json
import logging
import re
import concurrent.futures
from typing import Any, Dict, List, Optional

from app.models.llm import get_llm_response
from app.config import MATCH_LLM_MODEL

from .engine import validate_deck

logger = logging.getLogger(__name__)

# 模板锁定的 12 页版式序列（顺序即售前方案书叙事线，禁改）
FIXED_LAYOUTS = [
    'cover', 'toc', 'background', 'pain_points', 'requirements',
    'architecture', 'compare', 'cost', 'security', 'roadmap', 'service',
    'end',
]
_CONTENT_LAYOUTS = FIXED_LAYOUTS[2:-1]   # 10 个内容页
_LLM_BATCHES = [                          # 段2 分批（每批 3 页，控输出体量）
    ['background', 'pain_points', 'requirements'],
    ['architecture', 'compare', 'cost'],
    ['security', 'roadmap', 'service'],
]

_MAX_SOURCE_CHARS = 6000                  # 喂给 LLM 的方案原文截断
_MAX_REBATCH_ROUNDS = 2                   # 批级重试轮数


class DeckGenerateError(Exception):
    """两段式生成最终失败（重试耗尽），调用方应降级 legacy 渲染"""


# ----------------------------------------------------------------
# 版式填写模板（few-shot：与 layouts 的 data 结构严格一致，LLM 照抄结构）
# ----------------------------------------------------------------
_LAYOUT_EXAMPLES = {
    'background': {
        'header': {'sec': '01', 'sec_name': '项目背景与建设目标',
                   'headline': '≤22字的一句结论式标题', 'page_no': '03',
                   'stats': [['数字', '标签'], ['数字', '标签'], ['数字', '标签']],
                   'note': '数据来源说明，≤30字'},
        'paras': ['背景段落1，60-80字', '背景段落2，60-80字', '背景段落3，60-80字'],
        'kpis': [['45 万㎡', '园区建筑面积'], ['380+ 家', '入驻企业'],
                 ['8 套', '存量系统']],
        'chart': {'title': '图表标题（含单位）', 'cats': ['2024', '2025', '2026E'],
                  'vals': [32, 41, 55], 'name': '系列名', 'num_fmt': '0'},
        'path': {'title': '发展路径', 'nodes': [['2016', '事件'], ['2027', '事件']]},
        'goals': {'title': '建设目标（量化 · 可验收）',
                  'rows': [['G1 目标名', '量化指标', '效果对比', 'M1 达成',
                            '验收：方式']]},
    },
    'pain_points': {
        'header': {'sec': '02', 'sec_name': '现状与核心痛点',
                   'headline': '≤22字', 'page_no': '04',
                   'stats': [['数字', '标签'], ['数字', '标签'], ['数字', '标签']],
                   'note': '数据来源，≤30字'},
        'cards': [['P1 痛点名', '现状描述40-50字', '影响描述30字',
                   '关键数字', '数字标签']],
        'quant': {'title': '业务影响量化',
                  'headers': ['维度', '量化损失', '紧急度'],
                  'rows': [['维度', '损失', '高']]},
        'maps': {'title': '痛点 → 对策映射', 'pairs': [['P1', '对策描述']]},
    },
    'requirements': {
        'header': {'sec': '03', 'sec_name': '需求分析', 'headline': '≤22字',
                   'page_no': '05',
                   'stats': [['数字', '标签'], ['数字', '标签'], ['数字', '标签']],
                   'note': '需求来源，≤30字'},
        'cols': [['业务需求', ['需求1', '需求2', '需求3', '需求4', '需求5', '需求6']],
                 ['技术需求', ['需求1', '需求2', '需求3', '需求4', '需求5', '需求6']],
                 ['约束条件', ['约束1', '约束2', '约束3', '约束4', '约束5']]],
        'resp': {'title': '本期响应',
                 'cols': [[['标签', '响应1'], ['标签', '响应2']],
                          [['标签', '响应1'], ['标签', '响应2']],
                          [['标签', '响应1'], ['标签', '响应2']]]},
        'matrix': {'title': '需求优先级分组（P0 必做 → P2 可延期）',
                   'groups': [['P0 · 本期必做', 'grad', '内容'],
                              ['P1 · 本期尽量', 'outline_red', '内容'],
                              ['P2 · 二期迭代', 'outline_gray', '内容']]},
    },
    'architecture': {
        'header': {'sec': '04', 'sec_name': '总体方案架构', 'headline': '≤22字',
                   'page_no': '06',
                   'stats': [['数字', '标签'], ['数字', '标签'], ['数字', '标签']],
                   'note': '设计说明，≤30字'},
        'layers': [['接入层', '统一入口', [['组件名', 1.55], ['组件名', 1.55]]],
                   ['应用层', '弹性承载', [['组件名', 2.0], ['组件名', 1.8]]],
                   ['数据层', '数据底座', [['组件名', 2.25], ['组件名', 1.85]]]],
        'points': {'title': '五大设计要点',
                   'rows': [['要点名', '一句话说明'], ['要点名', '一句话说明'],
                            ['要点名', '一句话说明'], ['要点名', '一句话说明'],
                            ['要点名', '一句话说明']]},
        'specs': {'title': '资源规格速览',
                  'rows': [['计算', '规格'], ['存储', '规格'],
                           ['网络', '规格'], ['安全', '规格']]},
        'table': {'title': '关键组件选型依据',
                  'headers': ['组件', '备选方案', '选定理由', '替代预案（国产化）'],
                  'rows': [['计算', 'A vs B', '理由', '预案']]},
    },
    'compare': {
        'header': {'sec': '05', 'sec_name': '方案对比分析', 'headline': '≤22字',
                   'page_no': '07',
                   'stats': [['数字', '标签'], ['数字', '标签'], ['数字', '标签']],
                   'note': '测算口径，≤35字'},
        'table': {'headers': ['对比维度', '华为云方案', '自建/竞品', '结论'],
                  'rows': [['维度', '华为云做法', '对方做法', '华为云']]},
        'chart': {'title': '对比测算（万元）', 'cats': ['华为云路线', '自建路线'],
                  'vals': [18.3, 26.9], 'name': '对比值', 'num_fmt': '0.0',
                  'colors': ['red', 'gray']},
        'concls': {'title': '关键结论', 'rows': [['结论名', '一句话展开']]},
    },
    'cost': {
        'header': {'sec': '06', 'sec_name': '成本估算', 'headline': '≤22字',
                   'page_no': '08',
                   'stats': [['数字', '标签'], ['数字', '标签'], ['数字', '标签']],
                   'note': '单价来源与口径，≤35字'},
        'chart': {'title': '月费用结构（元/月）',
                  'cats': ['组件1', '组件2'], 'vals': [640, 400],
                  'name': '月小计（元）', 'num_fmt': '#,##0',
                  'colors': ['gray', 'red']},
        'cards': [['三年 TCO（直接成本）', '¥数字', '月均说明', 'red'],
                  ['付费结构', '包年 + 按量', '说明', 'ink'],
                  ['二期/扩容预留', '资源池预置', '说明', 'ink']],
        'strategies': {'title': '优化策略',
                       'rows': [['① 名称 ', '做法与降幅']]},
    },
    'security': {
        'header': {'sec': '07', 'sec_name': '安全合规设计', 'headline': '≤22字',
                   'page_no': '09',
                   'stats': [['数字', '标签'], ['数字', '标签'], ['数字', '标签']],
                   'note': '合规口径，≤30字'},
        'matrix': {'headers': ['等保三级要求', '平台能力', '本方案响应措施', '责任划分'],
                   'rows': [['要求', '能力', '措施', '平台+租户']]},
        'certs': [['认证名', '一句话说明']],
        'plan': {'title': '测评工作计划', 'headers': ['阶段', '时间', '工作项', '输出物', '责任方'],
                 'rows': [['定级备案', '2026-10', '工作项', '输出物', '责任方']]},
    },
    'roadmap': {
        'header': {'sec': '08', 'sec_name': '实施路线', 'headline': '≤22字',
                   'page_no': '10',
                   'stats': [['数字', '标签'], ['数字', '标签'], ['数字', '标签']],
                   'note': '割接窗口说明，≤30字'},
        'stages': [['W1-2', '阶段名', ['交付物1', '交付物2']]],
        'milestones': {'title': '里程碑与验收标准',
                       'headers': ['里程碑', '时间', '验收标准', '验收方式'],
                       'rows': [['M1 名称', 'W2', '验收标准', '方式']]},
        'risks': {'title': '关键风险与应对',
                  'rows': [['风险名', '高/中/低', '描述', '应对措施']]},
    },
    'service': {
        'header': {'sec': '08', 'sec_name': '服务保障体系', 'headline': '≤22字',
                   'page_no': '11',
                   'stats': [['数字', '标签'], ['数字', '标签'], ['数字', '标签']],
                   'note': '承诺口径说明，≤30字'},
        'sla': {'title': 'SLA 承诺', 'headers': ['承诺项', '标准', '赔付 / 兜底'],
                'rows': [['服务可用性', '99.95%', '赔付说明']]},
        'services': {'title': '包含服务项（6 项）',
                     'rows': [['服务名', '一句话说明']]},
        'team': {'title': '交付团队配置', 'headers': ['角色', '投入', '核心职责'],
                 'rows': [['项目经理', '1 名 · 全程', '职责']]},
        'boundary': {'title': '服务边界说明', 'rows': ['边界条款1', '边界条款2']},
    },
}

_COVER_TEMPLATE = {'title': '客户名+方案名（≤18字）', 'subtitle': '四个关键词用　·　连接',
                   'cols': [['方案范围', '一句话'], ['交付周期', '一句话'],
                            ['成本口径', '一句话（可含关键金额）']],
                   'meta': [['客户', '客户名'], ['日期', '2026 年 X 月'],
                            ['版本', 'V1.0（汇报版）'], ['密级', '商密（内部使用）']]}
_TOC_TEMPLATE = {
    'items': [['01', '项目背景与建设目标', '副题'], ['02', '现状与核心痛点', '副题'],
              ['03', '需求分析', '副题'], ['04', '总体方案架构', '副题'],
              ['05', '方案对比分析', '副题'], ['06', '成本估算', '副题'],
              ['07', '安全合规设计', '副题'], ['08', '实施路线与服务保障', '副题']],
    'summary': {'items': [['范围　', '一句话'], ['周期　', '一句话'],
                          ['投入　', '一句话'], ['合规　', '一句话']],
                'conclusion': '一句红字结论（≤40字）'}}
_END_ACTIONS = ['确认方案范围', '商务细节洽谈', '12 周排期启动']


def _extract_json(text: str) -> Any:
    """剥 Markdown 围栏后解析 JSON；容忍前后杂讯"""
    text = text.strip()
    m = re.search(r'```(?:json)?\s*(.*?)```', text, re.S)
    if m:
        text = m.group(1).strip()
    start = min([x for x in (text.find('{'), text.find('[')) if x >= 0],
                default=-1)
    if start > 0:
        text = text[start:]
    return json.loads(text)


async def _llm_json(prompt: str, batch_tag: str) -> Any:
    """调 DeepSeek（flash）并解析 JSON；解析失败重试一次"""
    last_err = None
    for attempt in range(2):
        try:
            resp = await get_llm_response(prompt, model=MATCH_LLM_MODEL)
            return _extract_json(resp)
        except Exception as e:  # noqa: BLE001
            last_err = e
            logger.warning('[PPT引擎][%s] 第%d次解析失败: %s',
                           batch_tag, attempt + 1, e)
    raise DeckGenerateError('%s: JSON 解析失败 %s' % (batch_tag, last_err))


def _source_text(solution_markdown: str,
                 solution_chapters: Optional[List[Dict[str, Any]]]) -> str:
    """优先用结构化章节，回退 Markdown；统一截断"""
    parts: List[str] = []
    if solution_chapters:
        for ch in solution_chapters:
            parts.append('## %s' % ch.get('title', ''))
            parts.append(ch.get('content', '') or '')
            for sec in ch.get('sections', []) or []:
                parts.append('### %s' % sec.get('title', ''))
                parts.append(sec.get('content', '') or '')
    if not parts and solution_markdown:
        parts = [solution_markdown]
    text = '\n'.join(parts).strip()
    return text[:_MAX_SOURCE_CHARS]


def _program_cost_table(cost_reference: Dict[str, Any]) -> List[List[str]]:
    """由成本参考（前端成本卡片编辑态）程序化生成 SKU 表行——LLM 不碰金额"""
    rows = cost_reference.get('rows') or []
    view_mode = cost_reference.get('view_mode') or 'month'
    try:
        disc = float(cost_reference.get('annual_discount', 0.85) or 0.85)
    except (TypeError, ValueError):
        disc = 0.85
    factor = (12 * disc) if view_mode == 'year' else 1

    def fmt(v) -> str:
        fv = float(v)
        return f'{fv:,.2f}' if fv != int(fv) else f'{int(fv):,}'

    table_rows, total = [], 0.0
    for r in rows:
        product = r.get('product', '') or ''
        spec = r.get('spec', '') or ''
        if r.get('business_only'):
            table_rows.append([product, spec, '商务报价', '—', '—', '—', '—', '—'])
            continue
        if r.get('no_price'):
            table_rows.append([product, spec, '参考价', '—', '—', '—', '—', '—'])
            continue
        try:
            qty = float(r.get('qty') or 0)
            price = float(r.get('unit_price') or 0)
        except (TypeError, ValueError):
            continue
        sub = qty * price
        total += sub
        # 数量列：数量 + 单位（修复：原 or 链导致有单位时数量丢失，只显示'台'）
        qty_txt = fmt(qty) + (r.get('unit_label') or '')
        table_rows.append([
            product, spec, r.get('billing', '') or '包年包月',
            qty_txt,
            fmt(price), fmt(sub), fmt(sub * disc if view_mode != 'year'
                                      else sub * factor), ''])
    if not table_rows:
        return []
    n = len(table_rows)
    for i, row in enumerate(table_rows):
        if row[-1] == '':
            row[-1] = '%.1f%%' % ((float(row[5].replace(',', '')) / total * 100)
                                  if total else 0)
    month_total = total
    year_total = total * disc if view_mode != 'year' else total
    table_rows.append(['合计', '—', '—', '—', '—', fmt(month_total),
                       fmt(year_total), '100%'])
    # 行数对齐样张容量（7 行 = 6 明细 + 合计）：超出时保留前 6 行 + 合计行
    if n > 6:
        return table_rows[:6] + [table_rows[-1]]
    return table_rows


def _synth_cost_table(cost_page: Dict[str, Any]):
    """无成本卡片时的成本页明细表合成（保住满版几何）。

    数据源：LLM 成本页 chart 的费用结构（cats=费用项, vals=月费用概算）——
    金额来自方案素材口径而非凭空编造，此处仅做格式化与占比计算。
    返回 (rows, headers, widths, accent_cols)；无可用数据时返回单行占位表。
    行数上限 7（6 明细 + 合计），对齐 SLOT_SPEC cost.table _t(7)。
    """
    headers = ['产品', '规格', '计费方式', '数量',
               '单价(元/月)', '月小计(元)', '年付(85折)', '占比']
    widths = [1.5, 2.0, 1.1, 0.95, 1.45, 1.45, 1.45, 0.853]
    accent = [5]

    def fmt(v) -> str:
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return ''
        return f'{fv:,.2f}' if fv != int(fv) else f'{int(fv):,}'

    chart = cost_page.get('chart') or {}
    cats = chart.get('cats') or []
    vals = chart.get('vals') or []
    items = []
    for cat, val in zip(cats, vals):
        try:
            fv = float(val)
        except (TypeError, ValueError):
            continue
        if str(cat or '').strip():
            items.append((str(cat).strip(), fv))
    items = items[:6]

    if not items:
        # 极端兜底：LLM 未给出费用结构 → 单行占位（不编造数字）
        return ([['成本明细', '按最终配置与商务报价为准', '—', '—',
                  '—', '—', '—', '100%']],
                headers, widths, accent)

    total = sum(v for _, v in items)
    rows = [[cat, '按方案口径', '概算', '—', '—', fmt(v), '—',
             ('%.1f%%' % (v / total * 100)) if total else '—']
            for cat, v in items]
    rows.append(['合计', '—', '—', '—', '—', fmt(total), '—', '100%'])
    return rows, headers, widths, accent


async def _plan_outline(source: str, cost_ref: Optional[Dict[str, Any]],
                        title: str, customer: str) -> Dict[str, Any]:
    """段1：大纲。输出 {layout: {headline, points[], numbers[]}}"""
    cost_hint = ''
    if cost_ref and cost_ref.get('rows'):
        names = [r.get('product', '') for r in cost_ref['rows'][:8]]
        cost_hint = ('\n已有经核实的成本明细（成本页直接采用，不要另行编造）：'
                     + '、'.join(n for n in names if n))
    prompt = f"""你是华为云售前解决方案专家。基于下面的方案素材，为一份 12 页售前 PPT 做内容大纲。

素材：
{source}
{cost_hint}

12 页结构固定为：封面/目录/项目背景与建设目标/现状与核心痛点/需求分析/总体方案架构/方案对比分析/成本估算/安全合规设计/实施路线/服务保障体系/结尾。
你只需为其中 10 个内容页（background、pain_points、requirements、architecture、compare、cost、security、roadmap、service，以及 toc 的 headline 摘要）各输出：
- headline: 一句结论式页标题（≤22字，含关键数字优先）
- points: 该页要点清单（4-8 条，尽量带量化数字）
- numbers: 该页最关键的 3 个数字及标签

严格输出 JSON（不要多余文字）：
{{"toc_summary": {{"headline_summary": "一句话全文摘要"}} ,
 "pages": {{"background": {{"headline": "...", "points": ["..."], "numbers": [["数字","标签"]]}}, "pain_points": {{...}}, "requirements": {{...}}, "architecture": {{...}}, "compare": {{...}}, "cost": {{...}}, "security": {{...}}, "roadmap": {{...}}, "service": {{...}}}}}}

规则：数字必须来自素材，禁止编造；无素材支撑的数字用定性表述；金额只在 cost/compare 出现。方案主题：{title or '华为云解决方案'}；客户：{customer or '未提供'}。"""
    return await _llm_json(prompt, 'plan')


def _batch_prompt(layouts: List[str], outline: Dict[str, Any], source: str,
                  cost_ref: Optional[Dict[str, Any]], title: str,
                  customer: str, date_str: str,
                  problems: Optional[Dict[str, list]] = None) -> str:
    templates = {}
    cost_note = ''
    for ly in layouts:
        templates[ly] = _LAYOUT_EXAMPLES[ly]
        if ly == 'cost' and cost_ref and cost_ref.get('rows'):
            # 注意：指令必须放在模板 JSON 之外 —— 放进模板会被 LLM 原样抄回
            # data 形成幻觉槽位（实测门禁三轮拦截，批重试耗尽）。
            cost_note = ('\n特别说明（cost 页）：table 槽将由系统按已核实成本明细'
                         '程序化生成，你【不要】输出 table 槽，只输出 '
                         'header/chart/cards/strategies。')
    prob_txt = ''
    if problems:
        prob_txt = ('\n上一轮以下页面未过校验，必须修正：\n'
                    + json.dumps(problems, ensure_ascii=False))
    return f"""你是华为云售前解决方案专家。按给定 JSON 模板，为 PPT 的 {layouts} 页填写内容。

素材：
{source}

内容大纲（必须遵循其 headline 与要点方向）：
{json.dumps(outline, ensure_ascii=False)}
{prob_txt}
{cost_note}
每页输出一个 data 对象，结构与下列模板完全一致（键名不得增删改，字符串槽不要超长）：
{json.dumps(templates, ensure_ascii=False)}

硬性规则：
1. 只输出 JSON：{{"pages": {{"{layouts[0]}": {{...}}, "{layouts[1]}": {{...}}, "{layouts[2]}": {{...}}}}}}，无多余文字。
2. 数字必须来自素材或大纲，禁止编造金额；无数据用定性表述。
3. rows/条目数量（满版硬性要求，宁多勿少，不得超过上述上限——表会被版式裁切）：
   compare.table 6-8 条、security.matrix 5-6 条、architecture.table 3-4 条、
   pain_points.quant 3-4 条、roadmap.milestones 3-4 条、roadmap.risks 3 条、
   service.sla 3-4 条、service.team 3-4 条、service.services 6 条；
   卡片/列表明细不少于 3 条；stages 固定 4 条、matrix groups 固定 3 条。
4. headline ≤22 字；note ≤35 字；stats 恰好 3 组且数字 ≤6 字符。
5. 方案主题：{title or '华为云解决方案'}；客户：{customer or '未提供'}；日期：{date_str}。"""


async def _fill_batch(layouts: List[str], outline: Dict[str, Any], source: str,
                      cost_ref: Optional[Dict[str, Any]], title: str,
                      customer: str, date_str: str) -> Dict[str, Dict[str, Any]]:
    """段2 单批：生成 → 校验 → 问题回喂重试"""
    problems: Dict[str, list] = {}
    for round_no in range(_MAX_REBATCH_ROUNDS + 1):
        prompt = _batch_prompt(layouts, outline, source, cost_ref, title,
                               customer, date_str,
                               problems=problems or None)
        result = await _llm_json(prompt, '+'.join(layouts))
        pages = (result or {}).get('pages', result or {})
        # 防御：剥离 LLM 可能抄回的非白名单提示键（如 table_note）
        for ly in layouts:
            if isinstance(pages.get(ly), dict):
                pages[ly].pop('table_note', None)
        # 组装完整页 data（补 cover 级 header 槽校验所需的固定项）
        problems = {}
        for ly in layouts:
            data = pages.get(ly) or {}
            deck_page = {'pages': [{'layout': ly, 'data': data}]}
            probs = validate_deck(deck_page)
            if probs:
                problems[ly] = probs
        if not problems:
            return pages
        logger.warning('[PPT引擎] 批 %s 第%d轮未过门禁: %s',
                       layouts, round_no + 1, problems)
    raise DeckGenerateError('批 %s 重试耗尽' % layouts)


def generate_deck(solution_markdown: str = '',
                  solution_chapters: Optional[List[Dict[str, Any]]] = None,
                  cost_reference: Optional[Dict[str, Any]] = None,
                  title: str = '', customer: str = '',
                  date_str: str = '') -> Dict[str, Any]:
    """同步入口（内部处理事件循环），返回过门禁的 deck dict

    韧性（2026-09-06 生产实测）：单批 LLM 偶发抖动可在 3 轮批内重试后仍耗尽
    → DeckGenerateError → 调用方降级 legacy 毛坯（破坏模板承诺）。
    这里整单重试一次，把降级概率从 p 压到 p²（重试只发生在失败路径，无常态开销）。
    """
    kwargs = dict(solution_markdown=solution_markdown,
                  solution_chapters=solution_chapters,
                  cost_reference=cost_reference,
                  title=title, customer=customer, date_str=date_str)
    try:
        return _run_async(generate_deck_async(**kwargs))
    except DeckGenerateError as e:
        logger.warning('[PPT引擎] 生成失败（%s），整单重试一次', str(e)[:120])
        return _run_async(generate_deck_async(**kwargs))


async def generate_deck_async(solution_markdown: str = '',
                              solution_chapters: Optional[List[Dict[str, Any]]] = None,
                              cost_reference: Optional[Dict[str, Any]] = None,
                              title: str = '', customer: str = '',
                              date_str: str = '') -> Dict[str, Any]:
    """两段式生成 deck：段1 大纲 → 段2 分批填槽 → 组装 → 整体门禁"""
    source = _source_text(solution_markdown, solution_chapters)
    if len(source) < 50:
        raise DeckGenerateError('方案素材过短（<50 字），无法生成 PPT')
    outline = await _plan_outline(source, cost_reference, title, customer)

    pages: Dict[str, Dict[str, Any]] = {}
    # cover / toc / end 由大纲 + 模板程序化组装（结构固定项不依赖 LLM）
    pages['cover'] = {
        'title': (title or '华为云解决方案建议书')[:18],
        'subtitle': '弹性算力　·　数据融合　·　安全合规　·　智能运维',
        'cols': [
            ['方案范围', _first_point(outline, 'background', 0,
                                      '存量系统迁移 + 二期资源预置')],
            ['交付周期', _first_point(outline, 'roadmap', 0,
                                      '12 周分四阶段交付')],
            ['成本口径', _first_point(outline, 'cost', 0,
                                      '全 SKU 透明计价，持续压降综合成本')],
        ],
        'meta': [['客户', customer or '未提供'], ['日期', date_str or '2026 年 9 月'],
                 ['版本', 'V1.0（汇报版）'], ['密级', '商密（内部使用）']],
    }
    toc_items = [
        ['01', '项目背景与建设目标', _headline_of(outline, 'background')],
        ['02', '现状与核心痛点', _headline_of(outline, 'pain_points')],
        ['03', '需求分析', _headline_of(outline, 'requirements')],
        ['04', '总体方案架构', _headline_of(outline, 'architecture')],
        ['05', '方案对比分析', _headline_of(outline, 'compare')],
        ['06', '成本估算', _headline_of(outline, 'cost')],
        ['07', '安全合规设计', _headline_of(outline, 'security')],
        ['08', '实施路线与服务保障', _headline_of(outline, 'roadmap')],
    ]
    pages['toc'] = {'items': toc_items, 'summary': {
        'items': [
            ['范围　', _first_point(outline, 'background', 0, '整体上云')],
            ['周期　', _first_point(outline, 'roadmap', 1, '分阶段交付')],
            ['投入　', _first_point(outline, 'cost', 0, '透明计价')],
            ['合规　', _first_point(outline, 'security', 0, '等保合规')],
        ],
        'conclusion': (outline.get('toc_summary', {}) or {}).get(
            'headline_summary', '华为云路线全面占优，建议尽快启动。')[:60],
    }}
    pages['end'] = {'actions': list(_END_ACTIONS)}

    # 段2 分批
    for batch in _LLM_BATCHES:
        got = await _fill_batch(batch, outline, source, cost_reference,
                                title, customer, date_str)
        for ly in batch:
            pages[ly] = got.get(ly) or {}

    # 成本页明细表：有成本卡片→程序化生成（LLM 不碰金额）；
    # 无成本卡片（Agent/未编辑成本卡场景）→用 LLM 成本页 chart 的费用结构
    # 程序化合成（名称+月小计+占比，金额来自素材口径非编造），保住满版几何。
    cost_table_rows = None
    if cost_reference and cost_reference.get('rows'):
        cost_table_rows = _program_cost_table(cost_reference)
        cost_headers = ['产品', '规格', '计费方式', '数量',
                        '单价(元/月)', '月小计(元)', '年付(85折)', '占比']
        cost_widths = [1.5, 2.0, 1.1, 0.95, 1.45, 1.45, 1.45, 0.853]
        cost_accent = [5, 6]
    if not cost_table_rows:
        cost_table_rows, cost_headers, cost_widths, cost_accent = \
            _synth_cost_table(pages.get('cost') or {})
    if cost_table_rows:
        pages['cost']['table'] = {
            'headers': cost_headers,
            'rows': cost_table_rows,
            'widths': cost_widths,
            'total_row_idx': len(cost_table_rows) - 1,
            'accent_cols': cost_accent,
        }

    deck = {'pages': [{'layout': ly, 'data': pages.get(ly) or {}}
                      for ly in FIXED_LAYOUTS]}
    problems = validate_deck(deck)
    if problems:
        raise DeckGenerateError('deck 未过整体门禁:\n- ' + '\n- '.join(problems))
    return deck


def _headline_of(outline: Dict[str, Any], layout: str, default: str = '') -> str:
    p = (outline.get('pages', {}) or {}).get(layout, {}) or {}
    return (p.get('headline') or default)[:24]


def _first_point(outline: Dict[str, Any], layout: str, idx: int,
                 default: str) -> str:
    p = (outline.get('pages', {}) or {}).get(layout, {}) or {}
    pts = p.get('points') or []
    if idx < len(pts):
        return str(pts[idx])[:36]
    return default


def _run_async(coro):
    """同步调用链里安全执行协程：无 loop 直接 run；有 loop 丢线程池"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(lambda: asyncio.run(coro)).result()
