#!/bin/bash
# ============================================================
# 华为云解决方案匹配系统 - 轻量更新部署脚本 (2026-07-25 第二轮)
# 覆盖提交: 652d62e (新增15篇产品档案KB文档) + 3d33bb3 (AI助手升级) + docstring改为四路
# 域名: cloudsol.cn | 服务器: 47.96.109.234 | 路径: /var/www/huawei-cloud-solution-matcher
# 用法 (在服务器 web 终端 / 已登录服务器的终端直接执行):
#   sudo bash /tmp/huawei-cloud-solution-matcher-main/deploy/deploy_20260725l.sh
# 或本机: scp deploy/deploy_20260725l.sh admin@47.96.109.234:/tmp/ && ssh admin@47.96.109.234 "sudo bash /tmp/deploy_20260725l.sh"
# ============================================================
set -e

PROJECT_DIR="/var/www/huawei-cloud-solution-matcher"
TMP_SRC="/tmp/huawei-cloud-solution-matcher-main"
ZIP="/tmp/hcsm_20260725l.zip"
VER="20260725l"

echo "=========================================="
echo "  轻量更新部署 (代码更新 + 重建向量库)"
echo "  目标: $PROJECT_DIR"
echo "  版本: $VER"
echo "=========================================="

# --------------------------------------------------
# 1. 拉取 GitHub main 最新代码 (含 652d62e + 3d33bb3)
# --------------------------------------------------
echo "[1/6] 下载 GitHub main 最新代码..."
cd /tmp
rm -rf "$TMP_SRC" "$ZIP"
wget -q "https://github.com/henryguo017/huawei-cloud-solution-matcher/archive/refs/heads/main.zip" -O "$ZIP"
python3 -c "import zipfile; zipfile.ZipFile('$ZIP').extractall('/tmp')"
echo "      已解压到 $TMP_SRC"

# --------------------------------------------------
# 2. 覆盖代码 (铁律①: 目录名必须 huawei, 仅覆盖代码不碰 DB)
#    data/ (users.db / vector_db / user_docs) 被 gitignore, 不在 zip 内, 不会被覆盖
# --------------------------------------------------
echo "[2/6] 覆盖代码 (保护 data/ 运行时数据)..."
cp -r "$TMP_SRC/"* "$PROJECT_DIR/"
echo "      代码已更新 (data/ 完好)"

# --------------------------------------------------
# 3. 停服 (铁律④: KB 重建前必须停服, 避免写冲突)
# --------------------------------------------------
echo "[3/6] 停止 huawei-cloud-api 服务..."
systemctl stop huawei-cloud-api
sleep 2

# --------------------------------------------------
# 4. 重建向量库 (铁律④: 652d62e 新增 15 篇产品档案, 须重建才能被 AI 检索)
#    默认知识库 user_id=0 覆盖匿名访问 + 新注册用户
# --------------------------------------------------
echo "[4/6] 重建默认向量库 (含15篇产品档案)..."
cd "$PROJECT_DIR"
venv/bin/python -c "from app.services.knowledge_base import KnowledgeBaseService; s=KnowledgeBaseService(user_id=0); print(s.build_from_directory(use_default_dirs=True))"

# ---- 可选: 已登录现有账号私有库是注册时快照, 不含新产品档案 ----
# 若你的账号也想检索这 15 篇, 对其各自 user_id 同样重建一次:
#   USER_ID=$(sqlite3 "$PROJECT_DIR/users.db" "SELECT id FROM users WHERE username='你的账号'")
#   venv/bin/python -c "from app.services.knowledge_base import KnowledgeBaseService; s=KnowledgeBaseService(user_id=$USER_ID); print(s.build_from_directory(use_default_dirs=True))"

# --------------------------------------------------
# 5. 起服
# --------------------------------------------------
echo "[5/6] 启动 huawei-cloud-api 服务..."
systemctl start huawei-cloud-api
sleep 3
systemctl status huawei-cloud-api --no-pager | head -6

# --------------------------------------------------
# 6. 部署后验证 (铁律⑤: 真 curl 确认生效, 勿信版本号/截图)
# --------------------------------------------------
echo "[6/6] 验证前端版本号生效 (应检测到 $VER)..."
curl -s "https://www.cloudsol.cn/index.html" | grep -o "style.css?v=$VER" || echo "⚠️ 未检测到版本号, 检查 CDN/缓存"
curl -s "https://www.cloudsol.cn/index.html" | grep -o "script.js?v=$VER" || echo "⚠️ 未检测到版本号, 检查 CDN/缓存"
echo "--- 验证后端健康 ---"
curl -s "https://www.cloudsol.cn/api/health" | head -c 200
echo ""

echo "=========================================="
echo "  ✅ 部署完成! 版本 $VER"
echo "  前端请 Ctrl+Shift+R 硬刷新 cloudsol.cn"
echo "=========================================="
