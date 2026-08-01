#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
行业展会 JSON 校验脚本 —— 「确认正确再上」的强制步骤

用法（每次修改 data/industry_events.json 后、提交前必跑）：
    python scripts/validate_events.py

检查三件事（对应 2026-08-02 用户确立的验证标准）：
  1. JSON 格式合法 + 字段完整（name/city/date_range/location/url/note）
  2. 每个 url 可访问（HTTP 200，跟随重定向）
  3. 页面内容是否含"当年年份"（如条目 date_range 含 2026 则页面应含 2026；
     不含则判定为"疑似往届页面"，需要人工复核）

退出码：
  0 = 全部通过（可提交）
  1 = 有不可访问的链接（禁止提交）
  2 = 有疑似往届的页面（需人工复核后提交）
"""
import json
import re
import sys
import time
from pathlib import Path

import httpx

BASE = Path(__file__).resolve().parent.parent
EVENTS_FILE = BASE / "data" / "industry_events.json"
TIMEOUT = 10

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
}

# 当前年份（用于年份校验）
CURRENT_YEAR = time.strftime("%Y")


def check_url(url: str) -> tuple:
    """返回 (ok, status, page_text)"""
    try:
        r = httpx.get(url, timeout=TIMEOUT, follow_redirects=True, headers=HEADERS, verify=False)
        return (r.status_code == 200, r.status_code, r.text)
    except Exception as e:
        return (False, 0, str(e))


def main() -> int:
    if not EVENTS_FILE.exists():
        print(f"[错误] 找不到展会文件: {EVENTS_FILE}")
        return 1

    try:
        events = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[错误] JSON 解析失败: {e}")
        return 1

    if not isinstance(events, list) or not events:
        print("[错误] 展会数据应为非空数组")
        return 1

    required = {"name", "city", "date_range", "location", "url", "note"}
    exit_code = 0
    print(f"=== 行业展会校验（共 {len(events)} 条）===\n")

    for i, ev in enumerate(events, 1):
        name = ev.get("name", "?")
        url = ev.get("url", "")
        missing = required - set(ev.keys())
        if missing:
            print(f"[{i}] ✗ 字段缺失: {name} 缺 {sorted(missing)}")
            exit_code = max(exit_code, 1)
            continue
        if not url.startswith("http"):
            print(f"[{i}] ✗ url 非 http(s): {name} -> {url}")
            exit_code = max(exit_code, 1)
            continue

        ok, status, text = check_url(url)
        if not ok:
            print(f"[{i}] ✗ 链接不可访问({status}): {name}\n      {url}\n      {text[:80]}")
            exit_code = max(exit_code, 1)
            continue

        # 年份检查：优先看 <title> 标题（最可靠——往届页面标题通常写明届数），
        # 正文年份只作辅助（页面 JS/JSON 里可能有"下一届"占位，正文匹配会误判）
        title_m = re.search(r"<title[^>]*>([^<]*)</title>", text[:20000], re.I)
        title_text = title_m.group(1) if title_m else ""
        years = set(re.findall(r"(20\d{2})", ev.get("date_range", "") + " " + name))
        title_years = set(re.findall(r"(20\d{2})", title_text))
        if years:
            # 标题包含当年年份 → 确认是本届页面
            if title_years & years:
                print(f"[{i}] ✓ 可访问({status}) + 标题年份命中: {name}")
                continue
            # 标题不含当年年份（且标题非空）→ 疑似往届
            if title_text.strip():
                print(f"[{i}] ⚠ 疑似往届页面（标题未含 {'/'.join(sorted(years))}）: {name}")
                print(f"      {url} | 标题: {title_text.strip()[:60]}")
                exit_code = max(exit_code, 2)
                continue
            # 标题为空（动态渲染页面）：退回正文年份检查
            page_sample = text[:8000] or ""
            found_years = set(re.findall(r"(20\d{2})", page_sample))
            missing_years = years - found_years
            if missing_years:
                print(f"[{i}] ⚠ 疑似往届页面（页面未含 {'/'.join(sorted(years))}）: {name}")
                print(f"      {url}")
                exit_code = max(exit_code, 2)
                continue
        print(f"[{i}] ✓ 可访问({status}): {name}")

    print("\n=== 校验完成 ===")
    if exit_code == 0:
        print("全部通过 ✓ 可提交部署")
    elif exit_code == 1:
        print("存在不可访问链接 ✗ 禁止提交，先修复")
    else:
        print("存在疑似往届页面 ⚠ 人工复核后再提交（确认年份确实未发布则更新 note 说明）")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
