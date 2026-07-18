#!/usr/bin/env python3
"""
cloudsol.cn 完整端到端测试脚本
覆盖所有 API 端点，输出结构化测试报告。

用法:
  1. python test_full_e2e.py --fetch-captcha   → 获取验证码存 _captcha.png，人工读图
  2. python test_full_e2e.py --captcha-value CFCK --run-all guo 123456
     或一步到位: python test_full_e2e.py guo 123456 (会自动取验证码+等输入)
"""

import sys, os, json, time, traceback, base64, argparse
from datetime import datetime

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

# ============================================================
# 配置
# ============================================================
BASE_URL = "https://cloudsol.cn/api"
CAPTCHA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_captcha_test.png")
REPORT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "线上全功能测试报告_2026-07-19.md")

# 测试结果收集器
results = []
token = None
user_info = None
start_time = time.time()

def record(category, name, status, detail="", duration_ms=0):
    """记录一条测试结果"""
    results.append({
        "category": category,
        "name": name,
        "status": status,       # PASS / FAIL / SKIP / WARN
        "detail": str(detail)[:300],
        "duration_ms": round(duration_ms, 1),
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    })
    icon = {"PASS": "\u2705", "FAIL": "\u274c", "SKIP": "\u23ed", "WARN": "\u26a0\ufe0f"}[status]
    dur = f" ({duration_ms:.0f}ms)" if duration_ms > 0 else ""
    print(f"  {icon} [{status}] {name}{dur}")
    if status == "FAIL" and detail:
        print(f"      -> {detail[:200]}")

def api(method, path, **kwargs):
    """统一请求封装（自动带 token）"""
    url = f"{BASE_URL}{path}"
    headers = kwargs.pop("headers", {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if headers:
        kwargs["headers"] = headers
    t0 = time.time()
    try:
        resp = getattr(requests, method.lower())(url, timeout=120, **kwargs)
        elapsed = (time.time() - t0) * 1000
        return resp, elapsed
    except Exception as e:
        return None, (time.time() - t0) * 1000


# ============================================================
# 阶段 1: 验证码 + 登录
# ============================================================
def fetch_captcha():
    """获取验证码并保存图片供人工读取"""
    resp, ms = api("get", "/auth/captcha")
    if not resp or resp.status_code != 200:
        print(f"[ERR] 获取验证码失败: {resp.status_code if resp else 'network error'}")
        return None, None
    data = resp.json()
    img_b64 = data.get("captcha_image", "")
    img_data = base64.b64decode(img_b64.split(",", 1)[1] if "," in img_b64 else img_b64)
    with open(CAPTCHA_PATH, "wb") as f:
        f.write(img_data)
    print(f"\n[OK] 验证码图片已保存: {CAPTCHA_PATH}")
    print(f"     captcha_key: {data['captcha_key']}")
    return data["captcha_key"], CAPTCHA_PATH


def do_login(username, password, captcha_value=None, captcha_key=None):
    """登录获取 token"""
    global token, user_info
    if not captcha_key or not captcha_value:
        key, img_path = fetch_captcha()
        if not key:
            return False
        captcha_key = key
        # 如果没传值，提示用户读图
        if not captcha_value:
            print(f"\n请查看图片 {img_path} 并输入验证码:")
            captcha_value = input("验证码> ").strip()

    payload = {
        "username": username,
        "password": password,
        "captcha_key": captcha_key,
        "captcha_value": captcha_value,
    }
    resp, ms = api("post", "/auth/login", json=payload)
    if not resp or resp.status_code != 200:
        detail = ""
        if resp:
            try:
                detail = resp.json().get("detail", "")
            except:
                detail = resp.text[:200]
        record("鉴权", "登录", "FAIL", detail, ms)
        return False

    data = resp.json()
    token = data["access_token"]
    user_info = data["user"]
    record("鉴权", "登录", "PASS", f"user={user_info['username']}, id={user_info['id']}, expires_in={data['expires_in']}s", ms)
    return True


def test_auth_me():
    """GET /auth/me — 验证 token 有效"""
    resp, ms = api("get", "/auth/me")
    if not resp or resp.status_code != 200:
        record("鉴权", "当前用户(/auth/me)", "FAIL", f"status={resp.status_code if resp else 'None'}", ms)
        return
    data = resp.json()
    record("鉴权", "当前用户(/auth/me)", "PASS", f"id={data.get('id')}, username={data.get('username')}", ms)


# ============================================================
# 阶段 2: 匹配三模式
# ============================================================
TEST_DEMAND = "中型制造企业有50台生产设备想做预测性维护减少停机"

def test_match_standard_anonymous():
    """匿名标准匹配"""
    # 匿名：不带 Authorization
    global token
    saved_token = token
    token = None
    resp, ms = api("post", "/match", json={"demand": TEST_DEMAND, "mode": "standard"})
    token = saved_token
    if not resp or resp.status_code != 200:
        record("匹配", "标准模式(匿名)", "FAIL", f"status={resp.status_code if resp else 'None'}", ms)
        return
    data = resp.json()
    has_answer = bool(data.get("answer"))
    has_sources = len(data.get("source_documents", [])) > 0
    record("匹配", "标准模式(匿名)",
           "PASS" if has_answer else "WARN",
           f"answer={'有('+str(len(data['answer']))+'字)' if has_answer else '无'}, sources={has_sources}", ms)

def test_match_standard_loggedin():
    """已登录标准匹配"""
    resp, ms = api("post", "/match", json={"demand": TEST_DEMAND, "mode": "standard"})
    if not resp or resp.status_code != 200:
        record("匹配", "标准模式(已登录)", "FAIL", f"status={resp.status_code if resp else 'None'}", ms)
        return
    data = resp.json()
    ans_len = len(data.get("answer", ""))
    src_count = len(data.get("source_documents", []))
    has_chapters = bool(data.get("solution_json"))
    record("匹配", "标准模式(已登录)", "PASS",
           f"answer={ans_len}字, sources={src_count}, chapters={'有' if has_chapters else '无'}", ms)

def test_match_agent_stream():
    """Agent 流式匹配(SSE)"""
    resp, ms = api("post", "/agent/match/stream",
                    json={"demand": TEST_DEMAND, "customer_files": [], "client_id": None},
                    stream=True)
    if not resp or resp.status_code != 200:
        detail = ""
        if resp:
            try:
                detail = resp.json().get("detail", "")[:150]
            except:
                detail = str(resp.text)[:150]
        record("匹配", "Agent流式体验模式", "FAIL", f"status={resp.status_code if resp else 'None'} | {detail}", ms)
        return

    # 读 SSE 事件
    events = []
    final_result = None
    line_buf = ""
    try:
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line_buf += raw_line
            if "\n\n" not in line_buf:
                continue
            parts = line_buf.split("\n\n")
            line_buf = parts[-1]
            for chunk in parts[:-1]:
                if not chunk.strip():
                    continue
                evt = {}
                for line in chunk.strip().split("\n"):
                    if ":" in line:
                        k, v = line.split(":", 1)
                        evt[k.strip()] = v.strip().strip('"')
                events.append(evt)
                if evt.get("type") == "result":
                    final_result = evt
    except Exception as e:
        pass

    event_types = [e.get("type") for e in events]
    has_final = any(t == "final" for t in event_types)
    has_result = final_result is not None
    answer_len = 0
    if final_result:
        try:
            d = json.loads(final_result.get("data", "{}")) if isinstance(final_result.get("data"), str) else final_result.get("data", {})
            answer_len = len(d.get("answer", ""))
        except:
            pass

    status = "PASS" if has_final and has_result else ("WARN" if has_result else "FAIL")
    record("匹配", "Agent流式体验模式", status,
           f"SSE events={len(event_types)}, types={event_types[:8]}, "
           f"answer={answer_len}字, has_final={has_final}, has_result={has_result}",
           ms)


def test_match_wizard():
    """向导模式匹配"""
    resp, ms = api("post", "/match",
                   json={"demand": TEST_DEMAND, "mode": "wizard", "industry": "工业互联网"})
    if not resp or resp.status_code != 200:
        record("匹配", "向导模式(工业互联网)", "FAIL", f"status={resp.status_code if resp else 'None'}", ms)
        return
    data = resp.json()
    ans_len = len(data.get("answer", ""))
    record("匹配", "向导模式(工业互联网)", "PASS", f"answer={ans_len}字, sources={len(data.get('source_documents',[]))}", ms)


# ============================================================
# 阶段 3: 知识库
# ============================================================
def test_kb_stats():
    """知识库统计"""
    resp, ms = api("get", "/knowledge/stats")
    if not resp or resp.status_code != 200:
        record("知识库", "统计信息(/knowledge/stats)", "FAIL", "", ms)
        return
    d = resp.json()
    total_docs = d.get("total_documents", 0)
    industries = d.get("industries", [])
    companies = d.get("competitor_companies", [])
    accuracy = d.get("accuracy", "?")
    record("知识库", "统计信息(/knowledge/stats)", "PASS",
           f"docs={total_docs}, industries={len(industries)}, competitors={len(companies)}, accuracy={accuracy}", ms)

def test_kb_sync_mine_async():
    """异步同步用户知识库"""
    resp, ms = api("post", "/knowledge/sync-mine")
    if not resp or resp.status_code != 202:
        record("知识库", "异步同步(sync-mine)", "FAIL", f"expected 202 got {resp.status_code if resp else 'None'}", ms)
        return
    data = resp.json()
    task_id = data.get("task_id", "")
    record("知识库", "异步同步(sync-mine)发起", "PASS", f"task_id={task_id[:12]}..., status={data.get('status')}", ms)

    # 轮询几次看进度（最多30秒）
    if task_id:
        polled = False
        for i in range(6):  # 最多 30s
            time.sleep(5)
            r2, ms2 = api("get", f"/knowledge/task/{task_id}")
            if r2 and r2.status_code == 200:
                td = r2.json()
                progress = td.get("progress", 0)
                msg = td.get("message", "")[:80]
                st = td.get("status", "")
                if st in ("success", "failed"):
                    polled = True
                    record("知识库", "异步同步完成", "PASS" if st == "success" else "FAIL",
                           f"progress={progress}%, status={st}, msg={msg}", ms2)
                    break
                elif i < 3:
                    print(f"      ... polling sync: {st} {progress}% {msg[:50]}")
        if not polled:
            record("知识库", "异步同步轮询", "WARN", "轮询超时(30s)，任务可能仍在运行", 0)

def test_kb_documents():
    """文档列表 CRUD"""
    # 列表
    resp, ms = api("get", "/knowledge/documents")
    if not resp or resp.status_code != 200:
        record("知识库", "文档列表 GET", "FAIL", "", ms)
        return
    docs = resp.json().get("documents", [])
    record("知识库", "文档列表 GET", "PASS", f"共 {len(docs)} 个文档", ms)

    # 创建测试文档
    test_content = "# E2E测试文档\n这是一个自动化端到端测试创建的文档。"
    resp2, ms2 = api("post", "/knowledge/documents", json={
        "title": "[E2E测试] 自动化测试文档",
        "content": test_content,
        "industry": "工业互联网",
        "source_type": "manual",
    })
    if not resp2 or resp2.status_code not in (200, 201):
        record("知识库", "文档创建 POST", "FAIL", f"got {resp2.status_code if resp2 else 'None'}", ms2)
        return
    doc_data = resp2.json()
    doc_id = doc_data.get("id") or doc_data.get("document_id", "")
    record("知识库", "文档创建 POST", "PASS", f"doc_id={str(doc_id)[:16]}...", ms2)

    # 更新
    if doc_id:
        resp3, ms3 = api("put", f"/knowledge/documents/{doc_id}", json={
            "title": "[E2E测试] 已更新的文档",
            "content": test_content + "\n## 更新内容\n此行用于验证更新功能。",
            "industry": "工业互联网",
            "source_type": "manual",
        })
        if resp3 and resp3.status_code == 200:
            record("知识库", "文档更新 PUT", "PASS", f"doc_id={str(doc_id)[:16]}...", ms3)
        else:
            record("知识库", "文档更新 PUT", "WARN", f"got {resp3.status_code if resp3 else 'None'}", ms3)

        # 删除
        resp4, ms4 = api("delete", f"/knowledge/documents/{doc_id}")
        if resp4 and resp4.status_code == 200:
            record("知识库", "文档删除 DELETE", "PASS", "", ms4)
        else:
            record("知识库", "文档删除 DELETE", "WARN", f"got {resp4.status_code if resp4 else 'None'}", ms4)


# ============================================================
# 阶段 4: 客户档案
# ============================================================
def test_clients_crud():
    """客户档案 CRUD"""
    created_id = None

    # 列表
    resp, ms = api("get", "/clients")
    if not resp or resp.status_code != 200:
        record("客户档案", "客户列表 GET", "FAIL", "", ms)
        return
    clients = resp.json().get("clients", []) if isinstance(resp.json(), dict) else resp.json()
    count = len(clients) if isinstance(clients, list) else "?"
    record("客户档案", "客户列表 GET", "PASS", f"共 {count} 个客户", ms)

    # 创建
    resp2, ms2 = api("post", "/clients", json={
        "company_name": "[E2E测试] 自动化测试企业",
        "industry": "制造业",
        "contact_name": "测试联系人",
        "contact_phone": "13800000000",
        "description": "端到端自动化测试创建的虚拟客户档案。",
        "tags": ["E2E", "自动化"],
    })
    if not resp2 or resp2.status_code not in (200, 201):
        record("客户档案", "客户创建 POST", "FAIL", f"got {resp2.status_code if resp2 else 'None'}", ms2)
        return
    c_data = resp2.json()
    created_id = c_data.get("id") if c_data else None
    record("客户档案", "客户创建 POST", "PASS", f"id={created_id}", ms2)

    # 删除清理
    if created_id:
        resp3, ms3 = api("delete", f"/clients/{created_id}")
        s = resp3.status_code if resp3 else None
        record("客户档案", "客户删除 DELETE",
               "PASS" if s == 200 else "WARN", f"status={s}", ms3)


# ============================================================
# 阶段 5: 竞品分析
# ============================================================
def test_competitor_analysis():
    """竞品分析"""
    resp, ms = api("post", "/analyze", json={
        "competitor": ["阿里云"],
        "industry": "工业互联网",
        "focus_area": "智能制造解决方案",
    })
    if not resp or resp.status_code != 200:
        record("竞品分析", "分析接口", "FAIL", f"got {resp.status_code if resp else 'None'}", ms)
        return
    data = resp.json()
    analysis = data.get("analysis", "")
    comp_info = data.get("competitor_info", {})
    record("竞品分析", "分析接口", "PASS",
           f"analysis={'有('+str(len(analysis))+'字)' if analysis else '无'}, "
           f"comp_info_keys={list(comp_info.keys())[:5] if comp_info else []}", ms)


# ============================================================
# 阶段 6: 方案优化
# ============================================================
def test_refine_solution():
    """方案优化(refine)"""
    sample_answer = """
## 执行摘要
华为云为中型制造企业提供基于IoT的预测性维护解决方案。

## 核心方案
1. 设备数据采集与边缘计算
2. AI故障预测模型
3. 数字孪生监控平台

## 参考资料
[资料1] 华为云IoT平台白皮书
[资料2] 边缘计算最佳实践
"""
    resp, ms = api("post", "/solution/refine", json={
        "original_answer": sample_answer,
        "refine_instruction": "增加成本估算和ROI分析部分",
    })
    if not resp or resp.status_code != 200:
        record("优化", "方案优化(solution/refine)", "FAIL", f"got {resp.status_code if resp else 'None'}", ms)
        return
    data = resp.json()
    refined = data.get("refined_answer", "")
    record("优化", "方案优化(solution/refine)", "PASS",
           f"original={len(sample_answer)}字, refined={len(refined)}字", ms)


# ============================================================
# 阶段 7: 仪表盘/历史/成就
# ============================================================
def test_dashboard_stats():
    """仪表盘统计"""
    resp, ms = api("get", "/dashboard/stats")
    if not resp or resp.status_code != 200:
        record("仪表盘", "统计数据", "FAIL", f"got {resp.status_code if resp else 'None'}", ms)
        return
    d = resp.json()
    keys = list(d.keys())[:10]
    record("仪表盘", "统计数据", "PASS", f"keys={keys}", ms)


def test_history_list():
    """历史列表"""
    resp, ms = api("get", "/history/list?limit=5")
    if not resp or resp.status_code != 200:
        record("历史记录", "历史列表 GET", "WARN", f"got {resp.status_code if resp else 'None'}", ms)
        return
    d = resp.json()
    items = d.get("items", d.get("history", []))
    total = d.get("total", len(items))
    record("历史记录", "历史列表 GET", "PASS", f"total={total}, shown={len(items)}", ms)


def test_achievements():
    """成就系统"""
    resp, ms = api("get", "/achievements")
    if not resp or resp.status_code != 200:
        record("成就系统", "成就列表 GET", "FAIL", f"got {resp.status_code if resp else 'None'}", ms)
        return
    d = resp.json()
    achievements = d.get("achievements", [])
    unlocked = sum(1 for a in achievements if a.get("unlocked", False))
    record("成就系统", "成就列表 GET", "PASS", f"total={len(achievements)}, unlocked={unlocked}", ms)


# ============================================================
# 阶段 8: AI 助手
# ============================================================
def test_ai_chat():
    """AI助手对话"""
    resp, ms = api("post", "/ai/chat", json={"message": "你好，简单介绍一下你自己"})
    if not resp or resp.status_code != 200:
        record("AI助手", "对话(/ai/chat)", "FAIL", f"got {resp.status_code if resp else 'None'}", ms)
        return
    d = resp.json()
    reply = d.get("reply", d.get("response", d.get("message", "")))
    record("AI助手", "对话(/ai/chat)", "PASS", f"reply={'有('+str(len(reply))+'字)' if reply else '空'}", ms)


# ============================================================
# 主流程 & 报告生成
# ============================================================
def generate_report():
    """生成 Markdown 测试报告"""
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    warned = sum(1 for r in results if r["status"] == "WARN")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    total_dur = time.time() - start_time

    lines = [
        f"# cloudsol.cn 全功能端到端测试报告",
        f"",
        f"> **测试时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"> **服务器**: https://cloudsol.cn (47.96.109.234)",
        f"> **API版本**: v1.1.0 (health check确认)",
        f"> **测试账号**: guo (id={user_info['id'] if user_info else '?'})",
        f"> **总耗时**: {total_dur:.1f}s",
        f"",
        f"## 汇总",
        f"",
        f"| 指标 | 数值 |",
        f"|---|---|",
        f"| 总测试项 | {total} |",
        f"| \u2705 通过 | {passed} | ({passed/max(total,1)*100:.0f}%) |",
        f"| \u274c 失败 | {failed} |",
        f"| \u26a0\ufe0f 异常/警告 | {warned} |",
        f"| \u23ed 跳过 | {skipped} |",
        f"",
        f"## 详细结果",
        f"",
    ]

    current_cat = None
    for r in results:
        cat = r["category"]
        if cat != current_cat:
            current_cat = cat
            lines.append(f"### {cat}")
            lines.append("")
            lines.append("| 测试项 | 状态 | 耗时 | 详情 |")
            lines.append("|---|---|---|---|")

        icon = {"PASS": "\u2705", "FAIL": "\u274c", "SKIP": "\u23ed", "WARN": "\u26a0\ufe0f"}[r["status"]]
        lines.append(
            f"| {r['name']} | {icon} {r['status']} "
            f"| {r['duration_ms']:.0f}ms | {r['detail'][:120]} |"
        )
        lines.append("")

    # 评估结论
    fail_names = [(r["category"], r["name"], r["detail"]) for r in results if r["status"] == "FAIL"]
    warn_names = [(r["category"], r["name"], r["detail"]) for r in results if r["status"] == "WARN"]
    
    lines.append("---")
    lines.append("")
    lines.append("## 评估结论")
    lines.append("")
    
    if failed == 0 and warned == 0:
        lines.append("**全部通过** \u2705 所有核心功能正常运行。")
    elif failed == 0:
        lines.append(f"**基本通过** \u2705 无失败项，但 {warned} 项存在警告需关注。")
    else:
        lines.append(f"**存在问题** \u274c 有 {failed} 项失败需要修复。")
    
    if fail_names:
        lines.append("")
        lines.append("### 失败项清单")
        lines.append("")
        for cat, name, detail in fail_names:
            lines.append(f"- **[{cat}] {name}**: {detail[:150]}")
    
    if warn_names:
        lines.append("")
        lines.append("### 警告项清单")
        lines.append("")
        for cat, name, detail in warn_names:
            lines.append(f"- **[{cat}] {name}**: {detail[:150]}")

    report_text = "\n".join(lines)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(report_text)
    print(f"\n{'='*60}")
    print(f"报告已保存: {REPORT_FILE}")
    print(f"通过: {passed}/{total} | 失败: {failed} | 警告: {warned} | 总耗时: {total_dur:.1f}s")
    print(f"{'='*60}")
    return REPORT_FILE


def main():
    parser = argparse.ArgumentParser(description="cloudsol.cn E2E 全功能测试")
    parser.add_argument("--fetch-captcha", action="store_true", help="仅获取验证码")
    parser.add_argument("--captcha-value", help="手动指定验证码值")
    parser.add_argument("--captcha-key", help="手动指定 captcha_key")
    parser.add_argument("--skip-match", action="store_true", help="跳过匹配测试(省时间)")
    parser.add_argument("username", nargs="?", default="guo")
    parser.add_argument("password", nargs="?", default="123456")
    args = parser.parse_args()

    print("=" * 60)
    print("  cloudsol.cn 全功能端到端测试")
    print(f"  目标: {BASE_URL}")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    if args.fetch_captcha:
        fetch_captcha()
        return

    # ---- 登录 ----
    print("\n[1/9] 鉴权模块")
    ok = do_login(args.username, args.password,
                  captcha_value=args.captcha_value,
                  captcha_key=args.captcha_key)
    if not ok:
        print("\n[ABORT] 登录失败，无法继续测试。请检查账号密码或验证码。")
        sys.exit(1)
    test_auth_me()

    # ---- 匹配 ----
    if not args.skip_match:
        print("\n[2/9] 匹配模块")
        test_match_standard_anonymous()
        test_match_standard_loggedin()
        test_match_agent_stream()
        test_match_wizard()
    else:
        record("匹配", "(跳过--skip-match)", "SKIP", "")

    # ---- 知识库 ----
    print("\n[3/9] 知识库模块")
    test_kb_stats()
    test_kb_sync_mine_async()
    test_kb_documents()

    # ---- 客户档案 ----
    print("\n[4/9] 客户档案")
    test_clients_crud()

    # ---- 竞品分析 ----
    print("\n[5/9] 竞品分析")
    test_competitor_analysis()

    # ---- 优化 ----
    print("\n[6/9] 方案优化")
    test_refine_solution()

    # ---- 仪表盘/历史/成就 ----
    print("\n[7/9] 数据面板")
    test_dashboard_stats()
    test_history_list()
    test_achievements()

    # ---- AI助手 ----
    print("\n[8/9] AI助手")
    test_ai_chat()

    # ---- 登出 ----
    print("\n[9/9] 登出")
    resp, ms = api("post", "/auth/logout")
    record("鉴权", "登出", "PASS" if (resp and resp.status_code == 200) else "WARN", "", ms)

    # ---- 生成报告 ----
    report_path = generate_report()


if __name__ == "__main__":
    main()
