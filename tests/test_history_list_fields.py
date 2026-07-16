"""
回归测试：验证 get_match_history_list / get_competitor_history_list 的 SELECT
已包含 downloaded / archived 列（v=20260715 修复点）。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.usage_logger import UsageLoggerService


def test_list_returns_downloaded_archived():
    tmp = tempfile.mktemp(suffix=".db")
    try:
        svc = UsageLoggerService(db_path=tmp)

        # 1) 保存一条 match 记录
        hid = svc.save_match_history(
            demand_text="某智慧园区人脸闸机需求",
            solution="# 方案\n华为云XXX",
            industry="智慧园区",
            user_id=1,
        )
        assert hid is not None, "save_match_history 应返回 id"

        # 2) 列表初始状态：两者均为 False
        lst = svc.get_match_history_list(user_id=1)
        assert len(lst) == 1
        item = lst[0]
        assert item["downloaded"] is False
        assert item["archived"] is False

        # 3) 置位 downloaded + archived
        ok = svc.set_history_flags(hid, user_id=1, downloaded=True, archived=True)
        assert ok is True

        # 4) 列表应反映置位后的状态（核心回归点）
        lst2 = svc.get_match_history_list(user_id=1)
        item2 = lst2[0]
        assert item2["downloaded"] is True, "列表 downloaded 应为 True（修复点）"
        assert item2["archived"] is True, "列表 archived 应为 True（修复点）"

        # 5) 竞品列表同样验证
        cid = svc.save_competitor_history(
            competitor="阿里云",
            industry="智慧城市",
            analysis="# 竞品分析\n...",
            user_id=1,
        )
        assert cid is not None
        clst = svc.get_competitor_history_list(user_id=1)
        assert clst[0]["downloaded"] is False
        assert clst[0]["archived"] is False
        svc.set_history_flags(cid, user_id=1, downloaded=True)
        clst2 = svc.get_competitor_history_list(user_id=1)
        assert clst2[0]["downloaded"] is True
        assert clst2[0]["archived"] is False

        print("PASS: get_*_history_list 正确返回 downloaded/archived")
    finally:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except PermissionError:
            pass  # 连接可能仍有短暂锁，忽略


if __name__ == "__main__":
    test_list_returns_downloaded_archived()
