#!/bin/bash
# ============================================================
# 华为云解决方案匹配系统 - 轻量代码更新脚本
# 用途: 把 GitHub main 最新代码覆盖到生产服务器（不碰数据库）
# 服务器: 47.96.109.234 (阿里云轻量, Ubuntu 22.04)
# 部署路径: /var/www/huawei-cloud-solution-matcher
# 用法 (在本地终端执行, 需能 SSH 到服务器):
#   scp deploy/update.sh admin@47.96.109.234:/tmp/
#   ssh admin@47.96.109.234 "sudo bash /tmp/update.sh"
# 或直接 ssh 进去后手动运行。
# ============================================================
set -e

PROJECT_DIR="/var/www/huawei-cloud-solution-matcher"
TMP="/tmp/huawei-cloud-solution-matcher-main"
ZIP="/tmp/hcsm_main.zip"

echo "=========================================="
echo "  轻量代码更新 (覆盖代码, 保留数据)"
echo "  目标: $PROJECT_DIR"
echo "=========================================="

# --------------------------------------------------
# 1. 拉取 GitHub main 最新代码
# --------------------------------------------------
echo "[1/4] 下载 GitHub main 最新代码..."
cd /tmp
rm -rf huawei-cloud-solution-matcher "$TMP" "$ZIP"
wget -q "https://github.com/henryguo017/huawei-cloud-solution-matcher/archive/refs/heads/main.zip" -O "$ZIP"
python3 -c "import zipfile; zipfile.ZipFile('$ZIP').extractall('/tmp')"
echo "      已解压到 $TMP"

# --------------------------------------------------
# 2. 覆盖代码 (排除 data/ 数据库目录)
# --------------------------------------------------
echo "[2/4] 覆盖代码 (保护 data/ 数据库)..."
if [ ! -d "$PROJECT_DIR" ]; then
  echo "      项目目录不存在, 创建并整体复制"
  mkdir -p "$PROJECT_DIR"
  cp -r "$TMP/." "$PROJECT_DIR/"
else
  if command -v rsync >/dev/null 2>&1; then
    # 优先用 rsync, 显式排除 data 与 .git
    rsync -a --exclude='data' --exclude='.git' "$TMP/" "$PROJECT_DIR/"
  else
    # 回退: 备份 data -> 整体复制 -> 恢复 data
    echo "      rsync 不可用, 使用备份恢复方式"
    cp -a "$PROJECT_DIR/data" /tmp/_hcsm_data_bak_$$
    cp -r "$TMP/." "$PROJECT_DIR/"
    rm -rf "$PROJECT_DIR/data"
    cp -a /tmp/_hcsm_data_bak_$$/. "$PROJECT_DIR/data/"
    rm -rf /tmp/_hcsm_data_bak_$$
  fi
fi
echo "      代码已更新, data/ 完好保留"

# --------------------------------------------------
# 3. 重启 API 服务
# --------------------------------------------------
echo "[3/4] 重启 huawei-cloud-api 服务..."
systemctl restart huawei-cloud-api
sleep 2
systemctl status huawei-cloud-api --no-pager | head -6

# --------------------------------------------------
# 4. 查看最近日志
# --------------------------------------------------
echo "[4/4] 最近 10 行日志:"
journalctl -u huawei-cloud-api -n 10 --no-pager

echo ""
echo "=========================================="
echo "  ✅ 部署完成!"
echo "  前端请 Ctrl+Shift+R 硬刷新 cloudsol.cn"
echo "=========================================="
