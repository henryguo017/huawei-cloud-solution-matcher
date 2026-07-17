# 密码重置功能部署指南

## 新增功能
1. ✅ 忘记密码（邮件重置）
2. ✅ 新用户注册强制填邮箱
3. ✅ 老用户登录后弹窗引导绑定邮箱

## 部署步骤

### 1. 上传部署包到服务器
```bash
# 在本地执行（密码：你的服务器密码）
scp password_reset_v1.3.1.tar.gz root@47.96.109.234:/root/
```

### 2. 服务器解压
```bash
# SSH 登录服务器
ssh root@47.96.109.234

# 解压部署包
cd /var/www/huawei-cloud-solution-matcher
tar -xzf /root/password_reset_v1.3.1.tar.gz

# 更新版本号（强制浏览器刷新）
# 检查 index.html 版本号是否已更新为 v=20260702a
```

### 3. 配置 163 邮箱 SMTP
```bash
# 编辑配置文件
nano app/config.py

# 确认以下配置正确：
SMTP_HOST = "smtp.163.com"
SMTP_PORT = 465
SMTP_USER = "henryguo0523@163.com"  # 你的163邮箱
SMTP_PASS = "SMyjF34BjgCFMGud"  # 163授权码
```

### 4. 更新数据库
```bash
# 执行 SQL（添加 reset_token 字段）
sqlite3 data/users.db "ALTER TABLE users ADD COLUMN reset_token TEXT;"
sqlite3 data/users.db "ALTER TABLE users ADD COLUMN reset_token_expiry TIMESTAMP;"
```

### 5. 重启服务
```bash
systemctl restart huawei-cloud-api
systemctl status huawei-cloud-api
```

### 6. 验证部署
```bash
# 检查服务状态
curl https://cloudsol.cn/api/health

# 测试 forgot-password 接口
curl -X POST https://cloudsol.cn/api/auth/forgot-password \
  -H "Content-Type: application/json" \
  -d '{"email": "3324507839@qq.com"}'
# 应该返回：{"message": "如果该邮箱已注册，重置链接已发送"}
```

## 测试清单

| 测试项 | 操作步骤 | 预期结果 |
|--------|----------|----------|
| **注册新用户（不填邮箱）** | 注册页提交空邮箱 | 提示"邮箱不能为空" |
| **注册新用户（填邮箱）** | 注册页填有效邮箱 | 注册成功 |
| **忘记密码（输入存在的邮箱）** | 点击"忘记密码？" → 输入邮箱 | 收到重置邮件 |
| **忘记密码（输入不存在的邮箱）** | 点击"忘记密码？" → 输入假邮箱 | 提示"如果该邮箱已注册..."（静默） |
| **点击重置链接** | 打开邮件里的链接 | 打开重置密码页面 |
| **重置密码** | 输入新密码 → 提交 | 密码重置成功 |
| **老用户登录（无邮箱）** | 用 admin 登录 | 弹窗提示绑定邮箱 |
| **老用户登录（有邮箱）** | 用 henryguo 登录 | 不弹窗 |

## 回滚方案

如果部署失败，恢复备份：
```bash
cd /var/www/huawei-cloud-solution-matcher
tar -xzf backup_20260701.tar.gz
systemctl restart huawei-cloud-api
```

---
生成时间：2026-07-02 00:15
