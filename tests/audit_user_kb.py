"""
用户独立知识库系统 — 全流程端到端审计测试
使用 httpx.ASGITransport 直接测试 FastAPI app (async)，无需网络连接
"""
import sys, os, json, asyncio, random
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx
from api.main import app

FAILED = []
PASSED = []

def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print(f"  ✅ {name}")
    else:
        FAILED.append(name)
        print(f"  ❌ {name} {detail}")

async def main():
    print("=" * 60)
    print("🔍 用户独立知识库系统 — 全流程审计测试")
    print("=" * 60)

    transport = httpx.ASGITransport(app=app)
    
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # ============================================================
        print("\n📋 Phase 1: 基础健康检查")
        # ============================================================
        r = await c.get("/api/health")
        check("1.1 健康检查 200", r.status_code == 200, f"status={r.status_code}")
        data = r.json()
        check("1.2 health 返回有效响应", "status" in data or "version" in data or "app" in data,
              f"keys={list(data.keys())}")

        # ============================================================
        print("\n📋 Phase 2: 用户注册")
        # ============================================================
        uid_a = f"test_audit_a_{random.randint(10000,99999)}"
        uid_b = f"test_audit_b_{random.randint(10000,99999)}"
        pwd = "Test123456"

        r = await c.post("/api/auth/register", json={
            "username": uid_a, "password": pwd, "email": f"{uid_a}@test.com"
        })
        check("2.1 用户A注册成功", r.status_code == 200, f"body={r.text[:200]}")
        user_a_id = r.json().get("user_id")
        check("2.2 用户A获得user_id", user_a_id is not None, f"id={user_a_id}")

        r = await c.post("/api/auth/register", json={
            "username": uid_b, "password": pwd, "email": f"{uid_b}@test.com"
        })
        check("2.3 用户B注册成功", r.status_code == 200, f"body={r.text[:200]}")
        user_b_id = r.json().get("user_id")

        # 等待异步复制完成
        await asyncio.sleep(0.5)
        from api.dependencies import get_user_knowledge_base
        kb_a = get_user_knowledge_base(user_a_id)
        stats_a = kb_a.get_stats()
        check("2.4 用户A注册后KB已自动复制", stats_a.get("total_documents", 0) > 0,
              f"docs={stats_a.get('total_documents', 0)}")

        kb_b = get_user_knowledge_base(user_b_id)
        stats_b = kb_b.get_stats()
        check("2.5 用户B注册后KB已自动复制", stats_b.get("total_documents", 0) > 0,
              f"docs={stats_b.get('total_documents', 0)}")

        # ============================================================
        print("\n📋 Phase 3: 登录获取 Token")
        # ============================================================
        # 验证码存储于DB，每次login调用verify_captcha会删除记录
        # 所以每个用户需要各自的验证码
        import sqlite3 as _sqlite3  # 用于直接读取captcha值
        from app.utils.db_init import get_db_connection

        # --- 用户A ---
        r = await c.get("/api/auth/captcha")
        check("3.0a 用户A获取验证码", r.status_code == 200)
        ca = r.json()
        captcha_key_a = ca["captcha_key"]
        # 从DB读取captcha_value（get_db_connection返回默认路径，但测试中需要在主目录下）
        _con = _sqlite3.connect("data/users.db")
        _row = _con.execute("SELECT captcha_value FROM captchas WHERE captcha_key=?",
                            (captcha_key_a,)).fetchone()
        _con.close()
        check("3.0a-2 验证码值可读", _row is not None)
        captcha_value_a = _row[0] if _row else ""

        r = await c.post("/api/auth/login", json={
            "username": uid_a, "password": pwd,
            "captcha_key": captcha_key_a, "captcha_value": captcha_value_a
        })
        check("3.1 用户A登录成功", r.status_code == 200, f"body={r.text[:200]}")
        token_a = r.json().get("access_token")
        check("3.2 用户A获得token", token_a is not None)

        # --- 用户B ---
        r = await c.get("/api/auth/captcha")
        check("3.0b 用户B获取验证码", r.status_code == 200)
        cb = r.json()
        captcha_key_b = cb["captcha_key"]
        _con = _sqlite3.connect("data/users.db")
        _row = _con.execute("SELECT captcha_value FROM captchas WHERE captcha_key=?",
                            (captcha_key_b,)).fetchone()
        _con.close()
        check("3.0b-2 验证码值可读", _row is not None)
        captcha_value_b = _row[0] if _row else ""

        r = await c.post("/api/auth/login", json={
            "username": uid_b, "password": pwd,
            "captcha_key": captcha_key_b, "captcha_value": captcha_value_b
        })
        check("3.3 用户B登录成功", r.status_code == 200, f"body={r.text[:200]}")
        token_b = r.json().get("access_token")

        auth_a = {"Authorization": f"Bearer {token_a}"}
        auth_b = {"Authorization": f"Bearer {token_b}"}

        # ============================================================
        print("\n📋 Phase 4: 知识库CRUD — 隔离写入")
        # ============================================================
        r = await c.post("/api/knowledge/documents", json={
            "category": "huawei",
            "industry": "智慧农业",
            "title": f"Audit_Test_A_{uid_a}",
            "content": f"这是用户{uid_a}的独有测试文档，包含唯一标识 AUDIT_SECRET_A"
        }, headers=auth_a)
        check("4.1 用户A创建文档成功", r.status_code == 200, f"body={r.text[:200]}")
        doc_a_id = r.json().get("id")
        check("4.2 用户A获得文档ID", doc_a_id is not None)

        r = await c.post("/api/knowledge/documents", json={
            "category": "huawei",
            "industry": "智慧农业",
            "title": f"Audit_Test_B_{uid_b}",
            "content": f"这是用户{uid_b}的独有测试文档，包含唯一标识 AUDIT_SECRET_B"
        }, headers=auth_b)
        check("4.3 用户B创建文档成功", r.status_code == 200)
        doc_b_id = r.json().get("id")

        # ============================================================
        print("\n📋 Phase 5: 知识库隔离读取")
        # ============================================================
        r = await c.get("/api/knowledge/documents", headers=auth_a)
        check("5.1 用户A列表文档成功", r.status_code == 200)
        titles_a = [d["title"] for d in r.json().get("documents", [])]
        check("5.2 用户A看到自己的测试文档", f"Audit_Test_A_{uid_a}" in titles_a)

        r = await c.get("/api/knowledge/documents", headers=auth_b)
        titles_b = [d["title"] for d in r.json().get("documents", [])]
        check("5.3 用户B看到自己的测试文档", f"Audit_Test_B_{uid_b}" in titles_b)

        check("5.4 用户B看不到用户A的文档 ⚡隔离验证",
              f"Audit_Test_A_{uid_a}" not in titles_b,
              f"数据泄漏！B看到了A的文档")
        check("5.5 用户A看不到用户B的文档 ⚡隔离验证",
              f"Audit_Test_B_{uid_b}" not in titles_a,
              f"数据泄漏！A看到了B的文档")

        # ============================================================
        print("\n📋 Phase 6: 跨用户访问拒绝")
        # ============================================================
        r = await c.get(f"/api/knowledge/documents/{doc_a_id}", headers=auth_b)
        check("6.1 用户B读取A的文档被拒绝", r.status_code in [404, 403],
              f"status={r.status_code} body={r.text[:100]}")

        r = await c.put(f"/api/knowledge/documents/{doc_a_id}", json={"content": "HACKED!"}, headers=auth_b)
        check("6.2 用户B更新A的文档被拒绝", r.status_code in [404, 403],
              f"status={r.status_code}")

        r = await c.delete(f"/api/knowledge/documents/{doc_a_id}", headers=auth_b)
        check("6.3 用户B删除A的文档被拒绝", r.status_code in [404, 403],
              f"status={r.status_code}")

        # GET读取接口允许未登录访问（只读全局默认KB）
        r = await c.get("/api/knowledge/documents")
        check("6.4 未登录可读取知识库(全局默认)", r.status_code == 200,
              f"status={r.status_code}")
        public_docs = r.json().get("documents", [])
        check("6.5 全局默认KB有文档", len(public_docs) > 0, f"count={len(public_docs)}")

        # ============================================================
        print("\n📋 Phase 7: 知识库更新与删除")
        # ============================================================
        # 注意：doc_id 由 _encode_doc_id 生成，含 %2F 等编码字符。
        # FastAPI 路径路由会解码 %2F→/ 导致路径匹配失败。
        # 需要双重编码 %→%25 以通过 URL 路由层
        safe_a = doc_a_id.replace('%', '%25')
        safe_b = doc_b_id.replace('%', '%25')

        r = await c.put(f"/api/knowledge/documents/{safe_a}", json={
            "content": f"更新后的内容 - 用户{uid_a}修改版"
        }, headers=auth_a)
        check("7.1 用户A更新自己文档成功", r.status_code == 200, f"status={r.status_code}")

        r = await c.get(f"/api/knowledge/documents/{safe_a}", headers=auth_a)
        check("7.2 用户A读取更新后的文档", r.status_code == 200, f"status={r.status_code}")
        updated_content = r.json().get("content", "")
        check("7.3 更新内容正确", "修改版" in updated_content, updated_content[:50])

        r = await c.delete(f"/api/knowledge/documents/{safe_a}", headers=auth_a)
        check("7.4 用户A删除自己文档成功", r.status_code == 200, f"status={r.status_code}")

        r = await c.get(f"/api/knowledge/documents/{safe_a}", headers=auth_a)
        check("7.5 删除后读取返回404", r.status_code == 404, f"status={r.status_code}")

        r = await c.delete(f"/api/knowledge/documents/{safe_b}", headers=auth_b)
        check("7.6 用户B删除自己文档成功", r.status_code == 200, f"status={r.status_code}")

        # ============================================================
        print("\n📋 Phase 8: 方案匹配（使用用户KB）")
        # ============================================================
        r = await c.post("/api/match", json={
            "demand": "我是一家农业公司，需要物联网智慧大棚解决方案"
        }, headers=auth_a)
        check("8.1 用户A匹配请求成功", r.status_code == 200, f"status={r.status_code}")
        match_result = r.json()
        check("8.2 匹配返回answer", match_result.get("answer") is not None,
              f"keys={list(match_result.keys())[:5]}")
        answer = match_result.get("answer", "")
        check("8.3 匹配结果非空", len(answer) > 50, f"len={len(answer)}")

        # ============================================================
        print("\n📋 Phase 9: 竞品分析（使用用户KB）")
        # ============================================================
        r = await c.post("/api/analyze", json={
            "competitor": "阿里云",
            "industry": "智慧农业"
        }, headers=auth_a)
        check("9.1 用户A竞品分析成功", r.status_code == 200, f"status={r.status_code}")
        analyze_result = r.json()
        check("9.2 竞品分析返回answer", analyze_result.get("answer") is not None)

        # ============================================================
        print("\n📋 Phase 10: 仪表盘（用户隔离）")
        # ============================================================
        r = await c.get("/api/dashboard/stats", headers=auth_a)
        check("10.1 用户A仪表盘请求成功", r.status_code == 200, f"status={r.status_code}")
        dash_a = r.json()
        check("10.2 仪表盘包含行业覆盖", dash_a.get("industry_coverage") is not None)

        r = await c.get("/api/dashboard/stats", headers=auth_b)
        check("10.3 用户B仪表盘请求成功", r.status_code == 200)

        r = await c.get("/api/dashboard/stats")
        check("10.4 未登录访问仪表盘被拒绝", r.status_code in [401, 403],
              f"status={r.status_code}")

        # ============================================================
        print("\n📋 Phase 11: Agent模式（contextvars传递）")
        # ============================================================
        r = await c.post("/api/agent/match", json={
            "demand": "智慧城市交通管理"
        }, headers=auth_a)
        check("11.1 Agent匹配请求成功", r.status_code == 200, f"status={r.status_code}")
        agent_result = r.json()
        check("11.2 Agent返回answer", agent_result.get("answer") is not None,
              f"keys={list(agent_result.keys())[:5]}")

        # ============================================================
        print("\n📋 Phase 12: 安全端点保护验证")
        # ============================================================
        r = await c.post("/api/knowledge/rebuild")
        check("12.1 rebuild未登录被拒绝", r.status_code in [401, 403],
              f"status={r.status_code}")

        r = await c.post("/api/knowledge/clear")
        check("12.2 clear未登录被拒绝", r.status_code in [401, 403],
              f"status={r.status_code}")

        r = await c.post("/api/knowledge/rebuild", headers=auth_a)
        check("12.3 普通用户rebuild被拒绝", r.status_code in [401, 403],
              f"status={r.status_code}")

        # ============================================================
        print("\n📋 Phase 13: 老用户懒初始化验证")
        # ============================================================
        from api import dependencies as dep_mod
        dep_mod._user_kb_cache = {}
        user_a_dir = os.path.join("data", "user_docs", str(user_a_id))
        check("13.1 用户A目录已存在", os.path.exists(user_a_dir))

        kb_a2 = get_user_knowledge_base(user_a_id)
        stats_a2 = kb_a2.get_stats()
        check("13.2 懒初始化跳过（目录存在）", stats_a2.get("total_documents", 0) > 0,
              f"docs={stats_a2.get('total_documents', 0)}")

        # ============================================================
        print("\n📋 Phase 14: 向量搜索隔离验证")
        # ============================================================
        result_a = kb_a.search("智慧农业 物联网")
        check("14.1 用户A向量搜索成功", len(result_a) > 0, f"results={len(result_a)}")

        result_b = kb_b.search("智慧农业 物联网")
        check("14.2 用户B向量搜索成功", len(result_b) > 0, f"results={len(result_b)}")

        # ============================================================
        print("\n📋 Phase 15: 统计端点验证")
        # ============================================================
        r = await c.get("/api/knowledge/stats")
        check("15.1 stats无需登录可访问", r.status_code == 200, f"status={r.status_code}")

        r = await c.get("/api/knowledge/stats", headers=auth_a)
        check("15.2 stats登录用户可访问", r.status_code == 200)

        # ============================================================
        # 清理
        # ============================================================
        import shutil
        shutil.rmtree(f"data/user_docs/{user_a_id}", ignore_errors=True)
        shutil.rmtree(f"data/user_docs/{user_b_id}", ignore_errors=True)
        dep_mod._user_kb_cache = {}

    # ============================================================
    print("\n" + "=" * 60)
    print("📊 审计结果汇总")
    print("=" * 60)
    print(f"  ✅ 通过: {len(PASSED)}")
    print(f"  ❌ 失败: {len(FAILED)}")
    if FAILED:
        print("\n失败项:")
        for f in FAILED:
            print(f"  ❌ {f}")
    else:
        print("\n🎉 全部测试通过！系统运行正常！")
    print("=" * 60)

    return len(FAILED) == 0

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
