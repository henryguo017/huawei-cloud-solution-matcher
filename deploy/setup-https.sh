#!/bin/bash
# ============================================================
# 华为云解决方案匹配系统 - HTTPS 部署脚本
# 域名: cloudsol.cn
# 服务器: 101.37.28.206
# ============================================================

set -e  # 遇到错误立即退出

echo "=========================================="
echo "  华为云解决方案匹配系统 - HTTPS 部署"
echo "  域名: cloudsol.cn"
echo "=========================================="

# --------------------------------------------------
# 1. 安装必要依赖
# --------------------------------------------------
echo ""
echo "[1/6] 安装必要依赖..."

if ! command -v certbot &> /dev/null; then
    echo "  → 安装 certbot..."
    apt-get update -qq
    apt-get install -y -qq software-properties-common
    add-apt-repository -y ppa:certbot/certbot 2>/dev/null || true
    apt-get update -qq
    apt-get install -y -qq certbot python3-certbot-nginx
fi

echo "  ✓ 依赖安装完成"

# --------------------------------------------------
# 2. 创建 Webroot 目录（用于 ACME 验证）
# --------------------------------------------------
echo ""
echo "[2/6] 配置 ACME Webroot..."
mkdir -p /var/www/certbot
echo "  ✓ Webroot 目录已创建"

# --------------------------------------------------
# 3. 备份现有 Nginx 配置
# --------------------------------------------------
echo ""
echo "[3/6] 备份现有 Nginx 配置..."
BACKUP_DIR="/etc/nginx/backup-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

if [ -f /etc/nginx/sites-enabled/default ]; then
    cp /etc/nginx/sites-enabled/default "$BACKUP_DIR/" 2>/dev/null || true
fi

# 查找并备份所有现有 huawei-cloud 相关配置
find /etc/nginx/sites-available -name "*huawei*" -o -name "*cloud*" 2>/dev/null | while read f; do
    cp "$f" "$BACKUP_DIR/" 2>/dev/null || true
done

echo "  ✓ 配置已备份到 $BACKUP_DIR"

# --------------------------------------------------
# 4. 部署 Nginx 配置
# --------------------------------------------------
echo ""
echo "[4/6] 部署 Nginx 配置..."

# 复制新配置
cp /var/www/huawei-cloud-solution-matcher/deploy/cloudsol-nginx.conf \
   /etc/nginx/sites-available/huawei-cloud

# 移除默认站点
rm -f /etc/nginx/sites-enabled/default

# 确保软链接正确
rm -f /etc/nginx/sites-enabled/huawei-cloud
ln -s /etc/nginx/sites-available/huawei-cloud /etc/nginx/sites-enabled/huawei-cloud

# 测试 Nginx 配置
echo "  → 测试 Nginx 配置..."
nginx -t

echo "  ✓ Nginx 配置已部署并测试通过"

# --------------------------------------------------
# 5. 申请 SSL 证书
# --------------------------------------------------
echo ""
echo "[5/6] 申请 Let's Encrypt SSL 证书..."

certbot certonly --nginx -d cloudsol.cn -d www.cloudsol.cn \
    --non-interactive \
    --agree-tos \
    --email admin@cloudsol.cn \
    --redirect \
    2>&1 || {
    echo ""
    echo "  ⚠️  certbot --nginx 失败，尝试 webroot 方式..."
    certbot certonly --webroot \
        -w /var/www/certbot \
        -d cloudsol.cn \
        -d www.cloudsol.cn \
        --non-interactive \
        --agree-tos \
        --email admin@cloudsol.cn \
        2>&1
}

# 检查证书是否成功
if [ ! -f /etc/letsencrypt/live/cloudsol.cn/fullchain.pem ]; then
    echo "  ✗ SSL 证书申请失败！"
    exit 1
fi

echo "  ✓ SSL 证书申请成功！"

# --------------------------------------------------
# 6. 重启 Nginx
# --------------------------------------------------
echo ""
echo "[6/6] 重启 Nginx 服务..."
systemctl restart nginx
systemctl enable nginx

echo "  ✓ Nginx 已重启并设置为开机启动"

# --------------------------------------------------
# 7. 设置自动续期
# --------------------------------------------------
echo ""
echo "[额外] 配置 SSL 证书自动续期..."

# 确保 certbot 定时任务已启用
if [ -f /etc/cron.d/certbot ]; then
    echo "  → certbot 定时任务已存在"
else
    # 创建续期任务
    cat > /etc/cron.d/certbot-renew << 'EOF'
# 每天凌晨 2:30 检查并续期证书
30 2 * * * root certbot renew --quiet --nginx --post-hook "systemctl reload nginx"
EOF
    echo "  → 证书续期定时任务已创建"
fi

echo "  ✓ 自动续期已配置"

# --------------------------------------------------
# 部署完成
# --------------------------------------------------
echo ""
echo "=========================================="
echo "  ✅ 部署完成！"
echo "=========================================="
echo ""
echo "  域名:       https://cloudsol.cn"
echo "  域名(www):  https://www.cloudsol.cn"
echo "  API 地址:   https://cloudsol.cn/api"
echo "  文档:       https://cloudsol.cn/docs"
echo ""
echo "  SSL 证书路径:"
echo "    /etc/letsencrypt/live/cloudsol.cn/fullchain.pem"
echo "    /etc/letsencrypt/live/cloudsol.cn/privkey.pem"
echo ""
echo "  命令参考:"
echo "    nginx -t              # 测试配置"
echo "    systemctl status nginx # 查看 Nginx 状态"
echo "    certbot renew --dry-run # 测试证书续期"
echo "=========================================="
