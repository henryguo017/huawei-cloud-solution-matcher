# 华为云解决方案匹配系统 - 部署指南

## 目录
- [本地开发环境](#本地开发环境)
- [生产环境部署](#生产环境部署)
- [华为云部署](#华为云部署)
- [常见问题](#常见问题)

---

## 本地开发环境

### 1. 环境要求
- Python 3.8+
- Node.js 14+（可选，用于前端开发）

### 2. 安装依赖

**Windows:**
```bash
# 运行安装脚本
install.bat

# 或手动安装
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**Linux/Mac:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. 配置环境变量
```bash
# 复制配置模板
cp .env.example .env

# 编辑 .env 文件，填写 API 密钥
nano .env
```

必须配置的变量：
- `OPENAI_API_KEY`: OpenAI API 密钥
- 或 `DEEPSEEK_API_KEY`: DeepSeek API 密钥

### 4. 启动服务

**方式一：使用启动脚本（Windows）**
```bash
start_api.bat
```

**方式二：手动启动**
```bash
# 激活虚拟环境
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows

# 启动 API 服务
python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. 访问应用
- 前端界面: http://localhost:8000
- API 文档: http://localhost:8000/docs
- API 文档 (ReDoc): http://localhost:8000/redoc

---

## 生产环境部署

### 部署架构
```
用户请求
    ↓
Nginx (反向代理 + HTTPS)
    ↓
Uvicorn/Gunicorn (FastAPI应用)
    ↓
向量数据库 + LLM API
```

### 1. 服务器准备
- 操作系统: Ubuntu 20.04+ 或 CentOS 7+
- CPU: 4核+
- 内存: 8GB+
- 磁盘: 50GB+

### 2. 安装系统依赖
```bash
# Ubuntu
sudo apt update
sudo apt install -y python3-pip python3-venv nginx supervisor

# CentOS
sudo yum install -y python3-pip python3-devel nginx supervisor
```

### 3. 部署应用代码
```bash
# 创建应用目录
sudo mkdir -p /var/www/huawei-cloud-solution-matcher
sudo chown -R $USER:$USER /var/www/huawei-cloud-solution-matcher

# 克隆或上传代码
cd /var/www/huawei-cloud-solution-matcher
git clone <your-repo-url> .

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
nano .env  # 填写 API 密钥
```

### 4. 初始化知识库
```bash
# 确保知识库文档存在
ls -l data/sample_solutions/

# 通过 API 重建知识库
curl -X POST http://localhost:8000/api/knowledge/rebuild
```

### 5. 配置 Nginx
```bash
# 复制 Nginx 配置
sudo cp deploy/nginx.conf /etc/nginx/sites-available/huawei-cloud
sudo ln -s /etc/nginx/sites-available/huawei-cloud /etc/nginx/sites-enabled/

# 配置 SSL 证书（使用 Let's Encrypt）
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com

# 测试配置
sudo nginx -t

# 重启 Nginx
sudo systemctl restart nginx
```

### 6. 配置 Supervisor（进程管理）
```bash
# 复制 Supervisor 配置
sudo cp deploy/supervisor.conf /etc/supervisor/conf.d/huawei-cloud-api.conf

# 创建日志目录
sudo mkdir -p /var/log/supervisor
sudo chown -R www-data:www-data /var/log/supervisor

# 更新配置
sudo supervisorctl reread
sudo supervisorctl update

# 启动服务
sudo supervisorctl start huawei-cloud-api
```

### 7. 验证部署
```bash
# 检查服务状态
sudo supervisorctl status huawei-cloud-api

# 检查 API 健康状态
curl http://localhost:8000/api/health

# 检查 Nginx 状态
sudo systemctl status nginx
```

---

## 华为云部署

### 方案一：ECS 云服务器部署
1. 购买华为云 ECS 实例（推荐规格：4核8GB）
2. 按照上述生产环境部署步骤操作
3. 配置安全组开放 80/443 端口
4. 使用华为云域名解析服务绑定域名

### 方案二：使用华为云容器服务 CCE
1. 构建 Docker 镜像
2. 推送到华为云容器镜像服务 SWR
3. 在 CCE 创建容器工作负载
4. 配置负载均衡 ELB

### Docker 部署（可选）
```dockerfile
# Dockerfile 示例
FROM python:3.10-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## 常见问题

### 1. 端口被占用
```bash
# 查找占用端口的进程
lsof -i :8000

# 杀死进程
kill -9 <PID>
```

### 2. 权限问题
```bash
# 给予执行权限
chmod +x start_api.sh
chmod -R 755 /var/www/huawei-cloud-solution-matcher
```

### 3. 依赖安装失败
```bash
# 升级 pip
pip install --upgrade pip

# 清除缓存重新安装
pip cache purge
pip install --no-cache-dir -r requirements.txt
```

### 4. 知识库构建失败
- 检查 `data/sample_solutions/` 目录权限
- 确保文档格式正确（PDF/TXT）
- 查看日志文件 `api.log`

### 5. API 调用超时
- 检查 OpenAI/DeepSeek API 密钥是否有效
- 检查网络连接
- 查看日志定位具体错误

---

## 性能优化建议

1. **增加 worker 数量**: 修改 `--workers 4` 参数（建议设置为 CPU 核心数）
2. **启用缓存**: 考虑使用 Redis 缓存频繁查询的结果
3. **负载均衡**: 多实例部署 + Nginx 负载均衡
4. **数据库优化**: 迁移到华为云 GaussDB 替代 ChromaDB

---

## 监控与日志

### 查看日志
```bash
# API 日志
tail -f /var/log/supervisor/huawei-cloud-api.log

# Nginx 日志
tail -f /var/log/nginx/access.log
tail -f /var/log/nginx/error.log
```

### 健康检查
```bash
# API 健康状态
curl http://localhost:8000/api/health

# 检查系统资源
htop
df -h
```
