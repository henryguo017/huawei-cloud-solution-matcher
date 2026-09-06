#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cloudsol DB 每日备份（2026-09-06）。

备份 data/users.db + data/share.db → data/backups/<name>_<时间戳>.db，保留最近 7 天。
- 用 Python sqlite3 .backup()：WAL 模式下安全的在线备份（服务不停机可跑）；
- 只读方式打开源库（mode=ro），备份过程不可能写坏生产库；
- ChromaDB（向量库）不在此列：可用 /knowledge/rebuild 重建，无不可再生数据。

cron 示例（每日 03:30）：
  30 3 * * * cd /var/www/huawei-cloud-solution-matcher && /usr/bin/python3 deploy/backup_db.py >> data/backups/backup.log 2>&1
"""
import sqlite3
import sys
import os
import time
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # deploy/ → 仓库根
DATA = os.path.join(ROOT, "data")
BK = os.path.join(DATA, "backups")
KEEP_DAYS = 7


def main() -> int:
    os.makedirs(BK, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    ok = True

    for name in ("users", "share"):
        src = os.path.join(DATA, f"{name}.db")
        if not os.path.exists(src):
            print(f"[backup] 跳过（不存在）: {src}")
            continue
        dst = os.path.join(BK, f"{name}_{ts}.db")
        try:
            s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
            d = sqlite3.connect(dst)
            with d:
                s.backup(d)
            s.close()
            d.close()
            print(f"[backup] OK {os.path.basename(dst)} ({os.path.getsize(dst) // 1024}KB)")
        except Exception as e:
            ok = False
            print(f"[backup] 失败 {name}: {e}")
            if os.path.exists(dst):
                try:
                    os.remove(dst)
                except OSError:
                    pass

    # 清理过期备份（按修改时间）
    cutoff = time.time() - KEEP_DAYS * 86400
    for f in glob.glob(os.path.join(BK, "*_*.db")):
        try:
            if os.path.getmtime(f) < cutoff:
                os.remove(f)
                print(f"[backup] 清理过期: {os.path.basename(f)}")
        except OSError:
            pass

    print(f"[backup] done {time.strftime('%F %T')} 保留{KEEP_DAYS}天")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
