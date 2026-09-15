"""
E2E 测试：历史方案增强四块功能（下载标记 / 归档锁定 / 追问优化 / 列表字段回填）
通过真实 HTTP 命中 port 8011 的本地服务。
"""
import os
import sys
import sqlite3
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import requests
from app.utils.auth_utils import create_access_token

BASE = "http://127.0.0.1:8011"
PROJECT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
USAGE_DB = os.path.join(PROJECT, "data", "usage_logs.db")
USERS_DB = os.path.join(PROJECT, "data", "users.db")

created_ids = []


def get_admin():
    conn = sqlite3.connect(USERS_DB)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT id, username, role, token_version FROM users WHERE role='admin' LIMIT 1").fetchone()
    conn.close()
    return dict(row)


def mint_token(admin):
    token, _ = create_access_token(admin["id"], admin["username"], admin["role"], admin["token_version"])
    return token


def insert_test_records(user_id):
    conn = sqlite3.connect(USAGE_DB)
    cur = conn.execute(
        "INSERT INTO match_history (demand_text, solution, industry, sources, type, competitor, user_id) "
        "VALUES (?,?,?,?, 'match', '', ?)",
        ("E2E测试-智慧园区人脸闸机", "# 方案\n华为云XXX", "智慧园区", json.dumps([]), user_id),
    )
    mid = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO match_history (demand_text, solution, industry, sources, type, competitor, user_id) "
        "VALUES (?,?,?,?, 'analyze', ?, ?)",
        ("阿里云", "# 竞品分析\n...", "智慧城市", json.dumps([]), "阿里云", user_id),
    )
    cid = cur.lastrowid
    conn.commit()
    conn.close()
    created_ids.extend([mid, cid])
    return mid, cid


def cleanup():
    if not created_ids:
        return
    conn = sqlite3.connect(USAGE_DB)
    conn.execute("DELETE FROM match_history WHERE id IN (%s)" % ",".join("?" * len(created_ids)), created_ids)
    conn.commit()
    conn.close()
    print(f"[cleanup] 已删除测试记录 {created_ids}")


def main():
    admin = get_admin()
    print(f"[admin] id={admin['id']} user={admin['username']} role={admin['role']} tv={admin['token_version']}")
    token = mint_token(admin)
    headers = {"Authorization": f"Bearer {token}"}

    mid, cid = insert_test_records(admin["id"])

    # 1) 列表初始状态
    r = requests.get(f"{BASE}/api/history/list", headers=headers, timeout=20)
    assert r.status_code == 200, f"list 200, got {r.status_code}"
    match_list = r.json()["items"]
    m_item = next(x for x in match_list if x["id"] == mid)
    assert m_item["downloaded"] is False and m_item["archived"] is False, f"初始应为 False: {m_item}"
    print("[1] 列表初始 downloaded/archived=False OK")

    # 2) 下载 → 标记 downloaded
    r = requests.post(f"{BASE}/api/history/{mid}/download", headers=headers, timeout=60)
    assert r.status_code == 200, f"download 200, got {r.status_code} {r.text[:200]}"
    assert r.headers.get("content-type", "").startswith("application"), f"应返回文件: {r.headers.get('content-type')}"
    assert len(r.content) > 1000, f"下载文件过小: {len(r.content)}"
    print(f"[2] download 返回 {len(r.content)} 字节 OK")

    r = requests.get(f"{BASE}/api/history/list", headers=headers, timeout=20)
    m_item = next(x for x in r.json()["items"] if x["id"] == mid)
    assert m_item["downloaded"] is True, f"下载后列表 downloaded 应为 True: {m_item}"
    print("[2] 列表 downloaded=True 回填 OK")

    # 3) 追问优化（归档前，因为归档后禁止修改）→ conversation
    r = requests.post(f"{BASE}/api/history/{mid}/followup",
                      headers=headers,
                      json={"follow_up": "补充预算约束", "refined_solution": "# 优化方案\n控制预算50万"},
                      timeout=30)
    assert r.status_code == 200, f"followup 200, got {r.status_code} {r.text[:200]}"
    conv = r.json().get("conversation", [])
    assert len(conv) >= 2, f"应至少有 user+assistant 两条: {conv}"
    print(f"[3] followup 返回 {len(conv)} 轮对话 OK")

    r = requests.get(f"{BASE}/api/history/{mid}", headers=headers, timeout=20)
    assert r.status_code == 200
    detail = r.json()
    assert detail.get("conversation") and len(detail["conversation"]) >= 2, "详情应含 conversation"
    print("[3] 详情接口含 conversation OK")

    # 4) 归档 → archived=True，且 PATCH 改方案被拒、归档后追问也被拒
    r = requests.post(f"{BASE}/api/history/{mid}/archive", headers=headers, timeout=20)
    assert r.status_code == 200, f"archive 200, got {r.status_code}"
    r = requests.get(f"{BASE}/api/history/list", headers=headers, timeout=20)
    m_item = next(x for x in r.json()["items"] if x["id"] == mid)
    assert m_item["archived"] is True, f"归档后列表 archived 应为 True: {m_item}"
    print("[4] 列表 archived=True 回填 OK")

    r = requests.patch(f"{BASE}/api/history/{mid}/solution",
                       headers=headers, json={"solution": "篡改"}, timeout=20)
    assert r.status_code == 403, f"归档记录 PATCH 应 403，got {r.status_code}"
    print("[4] 归档守卫 PATCH 403 OK")

    r = requests.post(f"{BASE}/api/history/{mid}/followup",
                      headers=headers,
                      json={"follow_up": "归档后追问", "refined_solution": "x"}, timeout=20)
    assert r.status_code == 403, f"归档记录 followup 应 403，got {r.status_code}"
    print("[4] 归档守卫 followup 403 OK")

    # 5) 竞品列表归档回填
    r = requests.get(f"{BASE}/api/competitor/history/list", headers=headers, timeout=20)
    c_item = next(x for x in r.json()["items"] if x["id"] == cid)
    assert c_item["archived"] is False
    r = requests.post(f"{BASE}/api/history/{cid}/archive", headers=headers, timeout=20)
    assert r.status_code == 200
    r = requests.get(f"{BASE}/api/competitor/history/list", headers=headers, timeout=20)
    c_item = next(x for x in r.json()["items"] if x["id"] == cid)
    assert c_item["archived"] is True, f"竞品归档列表回填失败: {c_item}"
    print("[5] 竞品列表 archived=True 回填 OK")

    cleanup()
    print("\nALL_E2E_PASS")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        cleanup()
        print(f"E2E_FAIL: {e}")
        raise
