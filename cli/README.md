# cloudsol CLI

cloudsol.cn 售前 AI Agent 的命令行客户端（v1 薄客户端：所有智能在服务端，本地只做 HTTP）。

## 安装

零构建，单文件。用项目 venv 直接跑：

```
venv\Scripts\pip install -r cli\requirements-cli.txt   # 可选，装 rich 有更好的体验
venv\Scripts\python.exe cli\cloudsol.py --help
```

可选：把 `cli` 加进 PATH 或做个 `cloudsol.cmd`（内容 `@"%~dp0..\venv\Scripts\python.exe" "%~dp0cloudsol.py" %*`）。

## 登录（两种方式）

**方式一：API Key（推荐，公开分发标准通道）**

1. 网页登录 cloudsol.cn → 调用 `POST /api/auth/api-key`（或等价的「API 密钥」管理页）签发；
2. 明文 Key（`ck_` 开头）仅签发时返回一次，立即保存：
   ```
   python cli/cloudsol.py login --token ck_xxxxxxxx...
   ```
3. Key 遵守每日免费配额（默认 20 次 Agent 调用/天，`API_KEY_DAILY_LIMIT` 可调），超限 429 次日重置；吊销后立即失效。

**方式二：账号密码（个人使用）**

```
python cli/cloudsol.py login
```

会拉验证码图片并自动打开，人眼输入即可。JWT 存 `~/.cloudsol/config.json`（6 小时有效，401 自动续期）。

## 六个命令

```
cloudsol ask "IoTDA 和 IoTDA 专业版有什么区别"        # 单轮问答，流式输出
cloudsol solve "门锁厂 500人 10万把锁 200万预算"      # Agent 出方案，落盘 cloudsol_out/
cloudsol ppt "把方案整理成 PPT" --session <会话ID>     # 续会话导 PPT（空会话没有方案可整理）
cloudsol client list                                  # 客户档案列表
cloudsol client add --name "XX客户" --industry "制造"  # 建档（强制终端确认）
cloudsol status                                       # 生产体检：灰度观测+知识库统计
```

通用参数：`--session` 续聊 · `--legacy` 切旧引擎 · `--no-web` 禁联网 · `--yes` 自动放行非 CRM 写操作 · `--out DIR` 输出目录 · `--base-url`（本地调试用 `http://127.0.0.1:8800`）。

## 安全设计

- CRM 写操作（client_add/update）：**--yes 不生效**，永远终端展示完整 payload 后人工确认；
- 工具权限走与网页一致的闸门：SSE `permission_request` → 终端 `[y/N]` → 决议回传；
- token 文件 best-effort 0600；过期自动续期一次，绝不自动重试密码登录（防锁定）。

## 退出码

`0` 成功 · `1` 用法错误 · `2` 认证失败 · `3` 超时 · `4` HTTP 错误 · `5` 网络错误 · `130` Ctrl+C
