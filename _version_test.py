import sys, tempfile, os
sys.path.insert(0, "E:/newai/huawei-cloud-solution-matcher")
from app.services.usage_logger import UsageLoggerService

db = os.path.join(tempfile.gettempdir(), "ver_test.db")
if os.path.exists(db): os.remove(db)
svc = UsageLoggerService(db_path=db)

# 三次独立匹配 -> 三个分组各 v1
id1 = svc.save_match_history("需求A", "方案A1", "制造", user_id=1)
id2 = svc.save_match_history("需求B", "方案B1", "零售", user_id=1)
id3 = svc.save_match_history("需求C", "方案C1", "制造", user_id=1)
m1 = svc.get_match_history_meta(id1, user_id=1)
assert m1["version"] == 1 and m1["group_id"] is not None, m1
g1 = m1["group_id"]
print("[OK] 新建分组 group_id=", g1, "version=", m1["version"])

# 在 group1 下追加新版本（重新生成）
id1v2 = svc.save_match_history("需求A", "方案A2-优化", "制造", user_id=1, group_id=g1)
m1v2 = svc.get_match_history_meta(id1v2, user_id=1)
assert m1v2["version"] == 2 and m1v2["group_id"] == g1, m1v2
print("[OK] 同组追加版本 v2")

# 分组查询
grp = svc.get_match_history_group(g1, user_id=1)
assert grp["total_versions"] == 2, grp
assert [v["version"] for v in grp["versions"]] == [1, 2], grp
print("[OK] 分组查询返回 2 个版本按升序")

# 定稿 v2
res = svc.finalize_match_history(id1v2, user_id=1)
assert res["version"] == 2, res
grp2 = svc.get_match_history_group(g1, user_id=1)
assert grp2["final_version"] == 2, grp2
m1 = svc.get_match_history_meta(id1, user_id=1)
m2 = svc.get_match_history_meta(id1v2, user_id=1)
assert m1["is_final"] is False and m2["is_final"] is True, (m1, m2)
print("[OK] 定稿 v2，同组仅一个定稿")

# 回滚（非破坏性）：把 v1 复制为新版本 v3
rb = svc.rollback_match_history(id1, user_id=1)
assert rb["version"] == 3 and rb["group_id"] == g1, rb
grp3 = svc.get_match_history_group(g1, user_id=1)
assert grp3["total_versions"] == 3, grp3
# 原 v1 内容不变
v1 = svc.get_match_history_by_id(id1, user_id=1)
assert "方案A1" in v1["solution"], v1
print("[OK] 回滚生成 v3（基于 v1），原版本未被修改")

# 权限隔离：其他用户看不到
assert svc.get_match_history_group(g1, user_id=999) is None, "应隔离"
assert svc.rollback_match_history(id1, user_id=999) is None, "应无权限"
print("[OK] 用户数据隔离生效")

# 列表返回版本字段
lst = svc.get_match_history_list(limit=50, user_id=1)
for it in lst:
    assert "group_id" in it and "version" in it and "is_final" in it, it
print("[OK] 列表返回 version/is_final/group_id/title 字段")

print("\nALL VERSIONING TESTS PASSED")
