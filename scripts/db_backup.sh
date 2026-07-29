#!/usr/bin/env bash
#
# DB 在线热备脚本 —— 华为云解决方案智能匹配系统
#
# 用法:
#   bash scripts/db_backup.sh                 # 默认 PROJECT_DIR=/var/www/huawei-cloud-solution-matcher
#   PROJECT_DIR=/path/to/app bash scripts/db_backup.sh
#   PYTHON=/path/to/python PROJECT_DIR=/path/to/app bash scripts/db_backup.sh   # 自定义 python（本地验证用）
#
# 建议挂 crontab（每天 04:00）:
#   0 4 * * * PROJECT_DIR=/var/www/huawei-cloud-solution-matcher bash /var/www/huawei-cloud-solution-matcher/scripts/db_backup.sh >> /var/www/huawei-cloud-solution-matcher/backups/cron.log 2>&1
#
set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/var/www/huawei-cloud-solution-matcher}"
PYTHON="${PYTHON:-$PROJECT_DIR/venv/bin/python}"
DB_FILE="$PROJECT_DIR/data/users.db"
BACKUP_DIR="$PROJECT_DIR/backups"
KEEP="${KEEP:-7}"   # 保留最近 7 份（可用环境变量 KEEP=3 覆盖）

if [ ! -f "$DB_FILE" ]; then
    echo "[db_backup] ERROR: 数据库文件不存在: $DB_FILE" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"
TS="$(date +%Y%m%d_%H%M%S)"
DST="$BACKUP_DIR/users_${TS}.db"

# 在线热备：用 venv 里的 python 调 sqlite3.backup()，不中断服务、避免直接 cp 在线库导致损坏
# 用普通 connect（跨平台）；backup() 会获取源库读锁并复制，与线上写入并发安全
"$PYTHON" - "$DB_FILE" "$DST" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
con = sqlite3.connect(src)
try:
    bck = sqlite3.connect(dst)
    try:
        con.backup(bck)
    finally:
        bck.close()
finally:
    con.close()
print(f"[db_backup] 已备份到 {dst}")
PY

# 仅保留最近 KEEP 份：ls -1t 按修改时间倒序，tail 跳过最新 KEEP 份后删除其余
# 用 while 循环代替 xargs，避免某些环境下 xargs 传递大环境导致 exec 失败
ls -1t "$BACKUP_DIR"/users_*.db | tail -n +$((KEEP + 1)) | while IFS= read -r f; do
    rm -f "$f" || true
done

echo "[db_backup] 完成: 保留最近 $KEEP 份"
