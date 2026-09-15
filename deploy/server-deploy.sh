#!/bin/bash
# ============================================================
# 华为云解决方案匹配系统 - 服务器一键部署脚本
# 域名: cloudsol.cn
# 服务器: 47.96.109.234 (阿里云轻量应用服务器，新)
# 用途: 在阿里云轻量服务器上一键完成全部部署
# ============================================================

set -e  # 遇到错误立即退出

PROJECT_DIR="/var/www/huawei-cloud-solution-matcher"
DOMAIN="cloudsol.cn"
SERVER_IP="47.96.109.234"

echo "=========================================="
echo "  华为云解决方案匹配系统"
echo "  服务器一键部署"
echo "=========================================="
echo "  域名: $DOMAIN"
echo "  路径: $PROJECT_DIR"
echo "=========================================="

# --------------------------------------------------
# 0. 检查是否在 root 权限下运行
# --------------------------------------------------
if [ "$EUID" -ne 0 ]; then
    echo ""
    echo "  ⚠️  请使用 sudo 或 root 用户运行此脚本"
    exit 1
fi

# --------------------------------------------------
# 1. 更新系统并安装依赖
# --------------------------------------------------
echo ""
echo "[1/9] 安装系统依赖..."

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

# 安装 Python、Nginx、Certbot 等
apt-get install -y -qq \
    python3 python3-pip python3-venv \
    nginx curl wget \
    certbot python3-certbot-nginx \
    software-properties-common \
    2>&1 | grep -v "^Selecting\|^Preparing\|^Unpacking\|^Setting up\|^Processing\|^Scanning\|^Building" || true

echo "  ✓ 系统依赖安装完成"

# --------------------------------------------------
# 2. 创建项目目录
# --------------------------------------------------
echo ""
echo "[2/9] 创建项目目录..."

mkdir -p "$PROJECT_DIR"
chown -R $SUDO_USER:$SUDO_USER "$PROJECT_DIR" 2>/dev/null || chown -R root:root "$PROJECT_DIR"

echo "  ✓ 项目目录已创建: $PROJECT_DIR"

# --------------------------------------------------
# 3. 检查代码是否已上传
# --------------------------------------------------
echo ""
echo "[3/9] 检查项目代码..."

if [ ! -f "$PROJECT_DIR/requirements.txt" ]; then
    echo ""
    echo "  ⚠️  未在 $PROJECT_DIR 找到项目代码！"
    echo ""
    echo "  请先上传代码到服务器："
    echo "  1. 在本地打包: tar --exclude='venv' --exclude='.git' -czf deploy.tar.gz ."
    echo "  2. 上传到服务器: scp deploy.tar.gz root@$SERVER_IP:/tmp/"
    echo "  3. 解压: tar -xzf /tmp/deploy.tar.gz -C $PROJECT_DIR"
    echo ""
    exit 1
fi

echo "  ✓ 项目代码已存在"

# --------------------------------------------------
# 4. 创建 Python 虚拟环境
# --------------------------------------------------
echo ""
echo "[4/9] 创建 Python 虚拟环境..."

cd "$PROJECT_DIR"

if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "  → 虚拟环境已创建"
else
    echo "  → 虚拟环境已存在，跳过创建"
fi

# 安装/更新依赖
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q 2>&1 | tail -5

echo "  ✓ Python 依赖安装完成"

# --------------------------------------------------
# 5. 检查并提示配置 .env 文件
# --------------------------------------------------
echo ""
echo "[5/9] 检查环境变量配置..."

if [ ! -f "$PROJECT_DIR/.env" ]; then
    if [ -f "$PROJECT_DIR/.env.example" ]; then
        cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    fi
fi

# 检查关键配置
if grep -q "your-key\|sk-xxxxxxxx\|change-in-production" "$PROJECT_DIR/.env" 2>/dev/null; then
    echo ""
    echo "  ⚠️  检测到 .env 文件中存在未修改的默认配置！"
    echo ""
    echo "  请手动编辑 $PROJECT_DIR/.env 文件，配置以下关键变量："
    echo ""
    echo "    # LLM API 密钥（至少配置一个）"
    echo "    DEEPSEEK_API_KEY=你的DeepSeek密钥"
    echo "    # 或 OPENAI_API_KEY=你的OpenAI密钥"
    echo ""
    echo "    # JWT 密钥（生产环境必须修改！）"
    echo "    JWT_SECRET_KEY=随机生成的强密码"
    echo ""
    echo "  编辑命令: nano $PROJECT_DIR/.env"
    echo ""
    read -p "  按回车键继续（已配置好 .env 请忽略此提示）..."
else
    echo "  ✓ .env 配置看起来已设置"
fi

# --------------------------------------------------
# 6. 配置 Nginx + HTTPS
# --------------------------------------------------
echo ""
echo "[6/9] 配置 Nginx + HTTPS..."

cd "$PROJECT_DIR"

# 执行 HTTPS 部署脚本
if [ -f "deploy/setup-https.sh" ]; then
    chmod +x deploy/setup-https.sh
    bash deploy/setup-https.sh
else
    echo "  ⚠️  未找到 deploy/setup-https.sh，跳过 HTTPS 配置"
fi

# --------------------------------------------------
# 7. 初始化数据目录
# --------------------------------------------------
echo ""
echo "[7/9] 初始化数据目录..."

mkdir -p "$PROJECT_DIR/data/vector_db"
mkdir -p "$PROJECT_DIR/data/sample_solutions"

echo "  ✓ 数据目录已就绪"

# --------------------------------------------------
# 8. 配置后端服务自启动
# --------------------------------------------------
echo ""
echo "[8/9] 配置后端服务自启动..."

# 优先使用 systemd
if command -v systemctl &> /dev/null; then
    cp "$PROJECT_DIR/deploy/huawei-cloud-api.service" /etc/systemd/system/

    # 修正 service 文件中的用户（如果不是 www-data）
    CURRENT_USER=${SUDO_USER:-root}
    if [ "$CURRENT_USER" != "www-data" ]; then
        sed -i "s/User=www-data/User=$CURRENT_USER/g" /etc/systemd/system/huawei-cloud-api.service
        sed -i "s/Group=www-data/Group=$CURRENT_USER/g" /etc/systemd/system/huawei-cloud-api.service
    fi

    systemctl daemon-reload
    systemctl enable huawei-cloud-api

    # 停止可能存在的旧实例
    systemctl stop huawei-cloud-api 2>/dev/null || true

    # 启动服务
    systemctl start huawei-cloud-api

    # 等待服务启动
    sleep 3

    # 检查服务状态
    if systemctl is-active --quiet huawei-cloud-api; then
        echo "  ✓ 后端服务已通过 systemd 启动并设为开机自启"
    else
        echo "  ⚠️  后端服务启动失败，请检查日志: journalctl -u huawei-cloud-api -n 20"
    fi
else
    # 回退到 supervisor
    apt-get install -y -qq supervisor
    cp "$PROJECT_DIR/deploy/supervisor.conf" /etc/supervisor/conf.d/huawei-cloud-api.conf
    supervisorctl reread
    supervisorctl update
    supervisorctl start huawei-cloud-api 2>/dev/null || true
    echo "  ✓ 后端服务已通过 Supervisor 启动"
fi

# --------------------------------------------------
# 9. 最终验证
# --------------------------------------------------
echo ""
echo "[9/9] 部署验证..."

# 等待服务完全启动
sleep 2

# 测试本地 API
echo ""
echo "  → 测试后端 API 健康状态..."
if curl -s http://127.0.0.1:8000/api/health | grep -q "healthy"; then
    echo "  ✓ 后端 API 运行正常"
else
    echo "  ⚠️  后端 API 暂时未响应（可能还在启动中）"
fi

# 测试 Nginx
echo ""
echo "  → 测试 Nginx 配置..."
if nginx -t 2>&1 | grep -q "successful"; then
    echo "  ✓ Nginx 配置正确"
else
    echo "  ⚠️  Nginx 配置测试未通过"
fi

# --------------------------------------------------
# 部署完成
# --------------------------------------------------
echo ""
echo "=========================================="
echo "  ✅ 部署完成！"
echo "=========================================="
echo ""
echo "  🌐 访问地址:"
echo "     https://$DOMAIN"
echo "     https://www.$DOMAIN"
echo ""
echo "  📚 API 文档:"
echo "     https://$DOMAIN/docs"
echo ""
echo "  🔧 常用命令:"
echo "     systemctl status huawei-cloud-api  # 查看后端状态"
echo "     systemctl status nginx             # 查看 Nginx 状态"
echo "     journalctl -u huawei-cloud-api -f  # 查看后端日志"
echo "     nginx -t                           # 测试 Nginx 配置"
echo "     certbot renew --dry-run            # 测试证书续期"
echo ""
echo "  ⚠️  提醒:"
echo "     1. 请确保阿里云安全组已开放 80/443 端口"
echo "     2. 如需 ICP 备案，请访问: https://beian.aliyun.com"
echo "     3. DNS 解析完全生效可能需要 10-30 分钟"
echo "=========================================="
