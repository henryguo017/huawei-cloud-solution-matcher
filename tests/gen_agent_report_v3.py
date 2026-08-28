# -*- coding: utf-8 -*-
"""读取结果 jsonl（支持 AGENT_OUT 环境变量），生成全量测试报告 HTML（支持 AGENT_OUT_REPORT 指定输出）。
回答内容中的 Markdown（### / *** / 表格 / 列表 / 加粗 / 引用 / 代码）会被渲染为 HTML。
"""
import json
import os
import re
from collections import OrderedDict

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("AGENT_OUT") or os.path.join(BASE, "agent_50q_results.jsonl")
OUT = os.environ.get("AGENT_OUT_REPORT") or os.path.join(BASE, "agent_50q_report.html")

CAT_ORDER = [
    "日常对话", "平台使用", "账户个人", "方案-制造", "方案-医疗", "方案-政务",
    "方案-教育", "方案-金融", "方案-农业", "方案-园区", "方案-交通", "方案-零售",
    "方案-能源", "方案-文旅", "方案-汽车", "方案-矿山", "方案-钢铁", "方案-化工",
    "方案-物流", "方案-生物医药", "方案-游戏", "竞品对比", "边缘异常",
]


def cat_of(r):
    c = r.get("category", "")
    if c.startswith("方案-"):
        return "方案生成"
    if c in ("竞品对比",):
        return "竞品对比"
    if c in ("日常对话",):
        return "日常对话"
    if c in ("平台使用",):
        return "平台使用"
    if c in ("账户个人",):
        return "账户个人"
    if c in ("边缘异常",):
        return "边缘异常"
    return c


def verdict(r):
    """质量判定：路由一致 + 有实质回答/合理行为 = 通过；否则标注问题。"""
    exp = r.get("expected")
    got = r.get("intent")
    err = r.get("error", "")
    if err:
        return ("异常", "error")
    if got != exp:
        return ("路由偏差", "warn")
    ans = r.get("answer", "")
    if r.get("paused"):
        return ("通过(澄清)", "ok")
    if got in ("solution", "competitor"):
        if len(ans) >= 800 and ("资料" in ans or "##" in ans or "华为云" in ans):
            return ("通过", "ok")
        return ("偏弱", "warn")
    if got == "general":
        if len(ans) >= 20:
            return ("通过", "ok")
        return ("偏弱", "warn")
    if got == "greeting":
        return ("通过", "ok")
    if got == "account":
        if "我的" in ans or "成就" in ans or "方案" in ans or "收藏" in ans or "账号" in ans:
            return ("通过", "ok")
        return ("偏弱", "warn")
    return ("通过", "ok")


# ───────────────────────── Markdown → HTML ─────────────────────────
def _inline(s: str) -> str:
    """行内格式：转义 HTML + 加粗/斜体/行内代码/链接。"""
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"__(.+?)__", r"<b>\1</b>", s)
    s = re.sub(r"(?<!\*)\*(?!\*)(.+?)\*(?!\*)", r"<i>\1</i>", s)
    s = re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    s = re.sub(r"\[(.+?)\]\((https?://[^)]+)\)", r'<a href="\2" target="_blank">\1</a>', s)
    return s


def md2html(text: str) -> str:
    """轻量 Markdown → HTML：标题 / 分隔线 / 表格 / 列表 / 引用 / 段落。"""
    if not text:
        return ""
    lines = text.split("\n")
    n = len(lines)
    out = []
    i = 0
    para = []

    def flush_para():
        if para:
            joined = " ".join(x.strip() for x in para if x.strip())
            if joined:
                out.append("<p>" + _inline(joined) + "</p>")
            para.clear()

    while i < n:
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.strip()

        # 空行 → 段落分隔
        if not stripped:
            flush_para()
            i += 1
            continue

        # 分隔线
        if re.match(r"^(\*\s*){3,}$", stripped) or re.match(r"^(-\s*){3,}$", stripped) or re.match(r"^(=\s*){3,}$", stripped):
            flush_para()
            out.append("<hr>")
            i += 1
            continue

        # 标题
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_para()
            level = len(m.group(1))
            out.append(f"<h{level}>" + _inline(m.group(2).strip()) + f"</h{level}>")
            i += 1
            continue

        # 引用
        if stripped.startswith(">"):
            flush_para()
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i].strip()))
                i += 1
            out.append("<blockquote>" + _inline(" ".join(quote)) + "</blockquote>")
            continue

        # 表格：当前行以 | 开头，且下一行是分隔行（含 - 和 |）
        if stripped.startswith("|") and i + 1 < n and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]) and "-" in lines[i + 1]:
            flush_para()
            header_cells = [c.strip() for c in stripped.strip().strip("|").split("|")]
            i += 2  # 跳过表头分隔行
            body_rows = []
            while i < n and lines[i].strip().startswith("|"):
                body_rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            th = "".join(f"<th>{_inline(c)}</th>" for c in header_cells)
            trs = ""
            for row in body_rows:
                tds = "".join(f"<td>{_inline(c)}</td>" for c in row)
                trs += f"<tr>{tds}</tr>"
            out.append(f'<table class="md"><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>')
            continue

        # 无序列表
        if re.match(r"^[-*]\s+", stripped):
            flush_para()
            items = []
            while i < n and re.match(r"^[-*]\s+", lines[i].strip()):
                items.append(re.sub(r"^[-*]\s+", "", lines[i].strip()))
                i += 1
            out.append("<ul>" + "".join(f"<li>{_inline(it)}</li>" for it in items) + "</ul>")
            continue

        # 有序列表
        if re.match(r"^\d+[.、]\s+", stripped):
            flush_para()
            items = []
            while i < n and re.match(r"^\d+[.、]\s+", lines[i].strip()):
                items.append(re.sub(r"^\d+[.、]\s+", "", lines[i].strip()))
                i += 1
            out.append("<ol>" + "".join(f"<li>{_inline(it)}</li>" for it in items) + "</ol>")
            continue

        # 普通段落行
        para.append(raw)
        i += 1

    flush_para()
    return "\n".join(out)


def main():
    rows = []
    with open(SRC, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    rows.sort(key=lambda r: r.get("idx", 0))

    groups = OrderedDict()
    for r in rows:
        g = cat_of(r)
        groups.setdefault(g, []).append(r)

    ok_cnt = 0
    warn_cnt = 0
    err_cnt = 0
    route_ok = 0
    for r in rows:
        v, cls = verdict(r)
        if cls == "ok":
            ok_cnt += 1
        elif cls == "warn":
            warn_cnt += 1
        else:
            err_cnt += 1
        if r.get("intent") == r.get("expected"):
            route_ok += 1

    cards = []
    for g in CAT_ORDER:
        items = groups.get(g, [])
        if not items:
            continue
        g_ok = sum(1 for r in items if verdict(r)[1] == "ok")
        cards.append(f'<h2 class="grp">{esc(g)} <span class="gcnt">({len(items)} 题，通过 {g_ok})</span></h2>')
        for r in items:
            v, cls = verdict(r)
            exp = r.get("expected")
            got = r.get("intent")
            badge = ("<span class='b-ok'>通过</span>" if cls == "ok"
                     else "<span class='b-warn'>观察</span>" if cls == "warn"
                     else "<span class='b-err'>异常</span>")
            route_tag = ("<span class='rt-ok'>路由一致</span>" if got == exp
                         else "<span class='rt-bad'>路由偏差</span>")
            clarify = ""
            if r.get("paused") and r.get("clarify_questions"):
                raw_qs = r.get("clarify_questions", [])
                qs_parts = []
                for q in raw_qs:
                    if isinstance(q, dict):
                        qs_parts.append(q.get("question", "") or q.get("text", "") or str(q))
                    else:
                        qs_parts.append(str(q))
                qs = " / ".join(p for p in qs_parts if p)
                clarify = f'<div class="clarify">澄清追问：{esc(qs)}</div>'
            err_html = ""
            if r.get("error"):
                err_html = f'<div class="err">ERROR: {esc(r.get("error"))}</div>'
            ans = r.get("answer", "")
            ans_html = md2html(ans)  # Markdown 渲染为 HTML
            cards.append(f"""
<div class="card {cls}">
  <div class="chead">
    <span class="idx">#{r.get('idx')}</span>
    <span class="q">{esc(r.get('question'))}</span>
    {badge} {route_tag}
  </div>
  <div class="meta">期望 {esc(exp)} → 实际 <b>{esc(got)}</b> · {esc(r.get('behavior'))} · 步数 {r.get('steps')} · {r.get('wall')}s</div>
  {clarify}
  {err_html}
  <div class="answer"><b>Agent 回答：</b>{ans_html}</div>
</div>""")

    summary = f"""
<div class="summary">
  <div class="stat"><div class="num">{len(rows)}</div><div class="lbl">总题数</div></div>
  <div class="stat ok"><div class="num">{ok_cnt}</div><div class="lbl">通过</div></div>
  <div class="stat warn"><div class="num">{warn_cnt}</div><div class="lbl">观察/偏弱</div></div>
  <div class="stat err"><div class="num">{err_cnt}</div><div class="lbl">异常</div></div>
  <div class="stat"><div class="num">{route_ok}/{len(rows)}</div><div class="lbl">路由准确率</div></div>
</div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent 模式 50 题全量测试报告</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;margin:0;background:#f5f6f8;color:#1f2329}}
.wrap{{max-width:1100px;margin:0 auto;padding:24px 18px 80px}}
h1{{color:#C7000B;font-size:24px;margin:0 0 4px}}
.sub{{color:#6b7280;margin:0 0 18px;font-size:13px}}
.summary{{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0 26px}}
.stat{{flex:1;min-width:120px;background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:16px;text-align:center}}
.stat .num{{font-size:26px;font-weight:700}}
.stat.ok .num{{color:#16a34a}}
.stat.warn .num{{color:#d97706}}
.stat.err .num{{color:#dc2626}}
.stat .lbl{{font-size:13px;color:#6b7280;margin-top:4px}}
.grp{{margin:26px 0 10px;font-size:18px;color:#111827;border-left:4px solid #C7000B;padding-left:10px}}
.gcnt{{font-size:13px;color:#6b7280;font-weight:400}}
.card{{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:14px 16px;margin:10px 0}}
.card.warn{{border-left:4px solid #d97706}}
.card.err{{border-left:4px solid #dc2626}}
.card.ok{{border-left:4px solid #16a34a}}
.chead{{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:15px}}
.idx{{background:#C7000B;color:#fff;border-radius:6px;padding:1px 8px;font-size:12px;font-weight:700}}
.q{{font-weight:600;flex:1}}
.b-ok{{background:#dcfce7;color:#16a34a;padding:1px 8px;border-radius:6px;font-size:12px}}
.b-warn{{background:#fef3c7;color:#d97706;padding:1px 8px;border-radius:6px;font-size:12px}}
.b-err{{background:#fee2e2;color:#dc2626;padding:1px 8px;border-radius:6px;font-size:12px}}
.rt-ok{{background:#e0f2fe;color:#0369a1;padding:1px 8px;border-radius:6px;font-size:12px}}
.rt-bad{{background:#fce7f3;color:#be185d;padding:1px 8px;border-radius:6px;font-size:12px}}
.meta{{color:#6b7280;font-size:12.5px;margin:6px 0 8px}}
.clarify{{background:#fff7ed;border:1px solid #fed7aa;color:#9a3412;border-radius:8px;padding:8px 10px;font-size:13px;margin-bottom:8px}}
.err{{background:#fee2e2;color:#dc2626;border-radius:8px;padding:8px 10px;font-size:13px;margin-bottom:8px}}
.answer{{background:#f8fafc;border:1px solid #eef2f7;border-radius:8px;padding:10px 12px;font-size:13.5px;line-height:1.7;word-break:break-word;margin-top:6px}}
.answer b{{color:#374151}}
.answer h1,.answer h2,.answer h3,.answer h4{{margin:12px 0 6px;color:#111827;line-height:1.3}}
.answer h2{{font-size:17px;border-bottom:2px solid #C7000B;padding-bottom:4px}}
.answer h3{{font-size:15px;color:#C7000B}}
.answer h4{{font-size:14px;color:#374151}}
.answer p{{margin:8px 0}}
.answer ul,.answer ol{{margin:8px 0;padding-left:22px}}
.answer li{{margin:3px 0}}
.answer hr{{border:none;border-top:1px solid #e5e7eb;margin:12px 0}}
.answer blockquote{{margin:8px 0;padding:6px 12px;background:#f1f5f9;border-left:3px solid #94a3b8;color:#475569}}
.answer code{{background:#eef2f7;padding:1px 5px;border-radius:4px;font-family:Consolas,Menlo,monospace;font-size:12.5px;color:#be185d}}
.answer a{{color:#C7000B}}
.answer table.md{{border-collapse:collapse;width:100%;margin:10px 0;font-size:13px}}
.answer table.md th,.answer table.md td{{border:1px solid #e5e7eb;padding:6px 9px;text-align:left;vertical-align:top}}
.answer table.md th{{background:#f1f5f9;font-weight:600;color:#374151}}
.answer table.md tr:nth-child(even) td{{background:#fafafa}}
</style></head>
<body><div class="wrap">
<h1>Agent 模式 · 50 题全量测试报告</h1>
<p class="sub">本地 in-process 驱动，绕过登录。覆盖：日常对话 / 平台使用 / 账户个人 / 各行业方案 / 竞品对比 / 边缘异常。修复范围：A 检索 300→1000字&3→6篇&加行业过滤；B client_context 透传&保底检索；C 路由不再误杀/误套；D 解析收紧&prompt封顶；E 账户意图后端真实取数（成就/我的方案/收藏/账户信息）；G 知识查询硬规则兜底（介绍/查询/什么是/有哪些 强制走 general 不套方案模板）。</p>
{summary}
{''.join(cards)}
</div></body></html>"""

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"REPORT_WRITTEN: {OUT} | total={len(rows)} ok={ok_cnt} warn={warn_cnt} err={err_cnt} route_ok={route_ok}")


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


if __name__ == "__main__":
    main()
