# 阿里云服务器部署指南 - cloudsol.cn

## 概述

本指南将指导你把华为云解决方案匹配系统完整部署到阿里云 ECS 服务器，并启用 HTTPS。

- **域名**: cloudsol.cn / www.cloudsol.cn
- **服务器 IP**: 101.37.28.206
- **部署路径**: /var/www/huawei-cloud-solution-matcher

---

## 前置条件

1. 已购买域名 `cloudsol.cn` ✅
2. 已完成 DNS 解析（A 记录指向 101.37.28.206） ✅
3. 阿里云 ECS 服务器已开通（推荐 Ubuntu 20.04+）
4. 服务器安全组已开放 **80、443、22** 端口

---

## 方法一：一键部署脚本（推荐）

### 步骤1：上传代码到服务器

**方式A - 使用 SCP（推荐）:**

在你的本地电脑（Windows PowerShell / Git Bash）执行：

```bash
# 进入项目目录
cd E:/newai/huawei-cloud-solution-matcher

# 打包项目（排除 venv、.git 等大文件）
tar --exclude='venv' --exclude='.git' --exclude='.workbuddy' \
    --exclude='node_modules' --exclude='__pycache__' \
    -czf deploy.tar.gz .

# 上传到服务器（替换 root 为你的服务器用户名）
scp deploy.tar.gz root@101.37.28.206:/tmp/
```

**方式B - 使用 Git 拉取:**

如果代码已推送到 Git 仓库：

```bash
ssh root@101.37.28.206
cd /var/www
git clone <你的仓库地址> huawei-cloud-solution-matcher
```

### 步骤2：在服务器上执行一键部署

SSH 登录服务器后执行：

```bash
ssh root@101.37.28.206

# 进入 /tmp 目录解压
cd /tmp
tar -xzf deploy.tar.gz

# 移动到部署目录
mkdir -p /var/www
mv /tmp /var/www/huawei-cloud-solution-matcher 2>/dev/null || true
rsync -av --delete /tmp/ /var/www/huawei-cloud-solution-matcher/ 2>/dev/null || true

# 进入项目目录
cd /var/www/huawei-cloud-solution-matcher

# 执行一键部署脚本
chmod +x deploy/server-deploy.sh
bash deploy/server-deploy.sh
```

---

## 方法二：手动逐步部署

### 步骤1：连接服务器

```bash
ssh root@101.37.28.206
```

### 步骤2：安装系统依赖

```bash
apt-get update
apt-get install -y python3-pip python3-venv nginx curl
```

### 步骤3：上传并解压项目代码

```bash
mkdir -p /var/www/huawei-cloud-solution-matcher
cd /var/www/huawei-cloud-solution-matcher

# 如果你已用 scp 上传了 deploy.tar.gz
tar -xzf /tmp/deploy.tar.gz -C /var/www/huawei-cloud-solution-matcher/
```

### 步骤4：创建 Python 虚拟环境

```bash
cd /var/www/huawei-cloud-solution-matcher
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 步骤5：配置环境变量

```bash
cp .env.example .env
nano .env
```

**必须配置以下变量：**

```
# LLM API 密钥（至少配置一个）
DEEPSEEK_API_KEY=你的DeepSeek密钥
# 或
OPENAI_API_KEY=你的OpenAI密钥

# JWT 密钥（生产环境必须修改！）
JWT_SECRET_KEY=随机生成的强密码字符串

# 其他配置保持默认即可
```

保存并退出（Ctrl+O, Enter, Ctrl+X）

### 步骤6：初始化知识库（如需要）

```bash
# 确保数据目录存在
mkdir -p data/vector_db

# 启动后端临时服务，重建知识库
source venv/bin/activate
python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 &

# 等待几秒后执行重建
curl -X POST http://127.0.0.1:8000/api/knowledge/rebuild

# 停止临时服务
kill %1
```

### 步骤7：配置 Nginx + HTTPS

```bash
cd /var/www/huawei-cloud-solution-matcher
chmod +x deploy/setup-https.sh
bash deploy/setup-https.sh
```

### 步骤8：配置后端服务自启动

**使用 systemd（推荐）：**

```bash
cp deploy/huawei-cloud-api.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable huawei-cloud-api
systemctl start huawei-cloud-api
```

**或使用 Supervisor：**

```bash
apt-get install -y supervisor
cp deploy/supervisor.conf /etc/supervisor/conf.d/huawei-cloud-api.conf
supervisorctl reread
supervisorctl update
supervisorctl start huawei-cloud-api
```

### 步骤9：验证部署

```bash
# 检查后端服务状态
systemctl status huawei-cloud-api

# 检查 Nginx 状态
systemctl status nginx

# 测试 API
curl http://localhost:8000/api/health

# 测试域名访问（在服务器上）
curl -I https://cloudsol.cn
```

---

## 验证清单

部署完成后，通过以下方式验证：

| 检查项 | 预期结果 | 验证命令/URL |
|--------|---------|-------------|
| DNS 解析 | 域名指向服务器 IP | `nslookup cloudsol.cn` |
| HTTP 访问 | 自动跳转到 HTTPS | `curl -I http://cloudsol.cn` |
| HTTPS 访问 | 200 OK，SSL 证书有效 | `curl -I https://cloudsol.cn` |
| API 健康 | 返回 healthy | `https://cloudsol.cn/api/health` |
| 前端加载 | 页面正常显示 | 浏览器访问 `https://cloudsol.cn` |
| 方案匹配 | 能正常提交需求 | 在页面上测试 |

---

## 常见问题

### 1. 证书申请失败

```bash
# 检查域名解析是否生效
nslookup cloudsol.cn

# 手动测试 certbot
certbot certonly --webroot -w /var/www/certbot -d cloudsol.cn --dry-run
```

### 2. 端口未开放

在阿里云控制台 > 安全组中，确保已放行：
- TCP 80（HTTP）
- TCP 443（HTTPS）
- TCP 22（SSH）

### 3. Nginx 配置错误

```bash
# 测试配置语法
nginx -t

# 查看错误日志
tail -f /var/log/nginx/error.log
```

### 4. 后端服务无法启动

```bash
# 查看服务日志
journalctl -u huawei-cloud-api -f

# 或 supervisor 日志
tail -f /var/log/supervisor/huawei-cloud-api.log
```

---

## 维护命令

```bash
# 重启后端服务
systemctl restart huawei-cloud-api

# 重启 Nginx
systemctl restart nginx

# 查看服务状态
systemctl status huawei-cloud-api nginx

# 手动续期 SSL 证书
certbot renew --dry-run        # 测试续期
certbot renew                  # 实际续期

# 查看访问日志
tail -f /var/log/nginx/access.log

# 查看错误日志
tail -f /var/log/nginx/error.log
```

---

## ICP 备案提醒

⚠️ **根据中国大陆法规，域名 + 大陆服务器对外提供服务必须进行 ICP 备案。**

备案流程：
1. 登录阿里云备案系统：https://beian.aliyun.com
2. 填写网站信息、负责人信息
3. 提交初审（通常 1-2 个工作日）
4. 拍照核验
5. 管局审核（通常 7-20 个工作日）
6. 获取备案号，在网站底部展示

**备案期间**，域名可以访问，但建议先关闭公网访问或添加访问限制，避免被管局拦截。
