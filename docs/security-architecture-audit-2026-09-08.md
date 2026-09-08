# 架构与安全审计报告（2026-09-08）

> 范围：全仓库文件结构 + 代码结构 + 入侵面。方法：全量 grep 模式扫描 + 关键文件精读（auth/nginx/upload/export/share/MCP/限流）。
> 结论先行：**整体安全基础扎实**（bcrypt/JWT/参数化 SQL/路径穿越防护/无硬编码密钥/nginx 加固都在位），无"可被直接入侵"级漏洞；有 3 个需尽快处理的红线项 + 若干纵深加固建议。

---

## 一、做对了的（安全基线盘点）

| 项 | 实现位置 | 状态 |
|---|---|---|
| 密码存储 | bcrypt + 72 字节截断（`app/utils/auth_utils.py`） | ✅ |
| 会话 | JWT（env 密钥）+ `token_version` 登出即全端失效 | ✅ |
| 验证码 | 一次性（验证后即删）+ 过期时间，存 DB | ✅ |
| SQL | 全参数化 `?` 占位；f-string 仅插内部 int 常量（`-{days-1} days`） | ✅ |
| 危险函数 | 无 eval/exec/pickle/os.system/shell=True；MCP 子进程用 `create_subprocess_exec`（无 shell） | ✅ |
| 密钥管理 | 全部走 .env；.env 不入库；.env.example 无真实密钥；无硬编码扫描命中 | ✅ |
| 文件安全 | `app/agent/file_security.py`：绝对路径/`../`穿越/符号链接逃逸三防 + 扩展名白名单 + 100MB 上限 + uuid 前缀防覆盖 | ✅ |
| 越权 | KB 上传/任务/文档全部强制登录 + 任务仅发起者或管理员可查；Agent 端点强制登录 | ✅ |
| 分享链接 | `secrets.token_urlsafe(8)`（11 字符不可枚举），匿名只读、30 天 TTL | ✅ |
| 内部接口 | IM bot → API 走 `X-Internal-Token` 精确匹配，未配置则拒绝 | ✅ |
| Nginx | HSTS/CSP/XFO/nosniff、HTTP→HTTPS 301、`.env/.py/.sql/.bak` 探测直接 404、ACME 分离 | ✅ |
| 限流 | 内存版 IP/用户桶（`api/dependencies.py`），导出 30/min、匹配 120/min | ✅ |

## 二、红线项（建议本周处理）

### R1. `/docs` `/redoc` 公网暴露（信息泄露）
nginx 把 FastAPI Swagger UI 直接代理到公网，攻击者可枚举全部 API 结构、参数模型。个人项目尚可接受，但这是简历项目，面试官随手一试就看到。
**修法**（10 分钟）：nginx 删除 `/docs` `/redoc` 两个 location（或加 IP 白名单）；或 main.py 里按 env 关闭 `docs_url=None, redoc_url=None`。

### R2. JWT 密钥占位值仅 warning 不拒启
`JWT_SECRET_KEY` 若生产 .env 没配真实值，代码只 `warnings.warn` 后继续用占位 key 运行——占位 key 是公开在 GitHub 里的，**等于任何人可伪造任意用户 JWT（含 admin）**。
**动作**：① 立即上服务器确认 `grep JWT_SECRET_KEY /var/www/huawei-cloud-solution-matcher/.env` 是强随机值；② 代码改为占位值直接 `raise SystemExit` 拒绝启动（5 分钟）。

### R3. 登录无失败锁定、无 IP 限流
验证码一次性但无扭曲（本次测试中 AI 一次识别成功），login 端点无 rate_limit、无连续失败锁定 → 可脚本化撞库弱口令。
**修法**（1 小时）：`/auth/login` 加 `rate_limit(10, 300)`；`users` 表加 `failed_attempts/locked_until`，连续 5 次失败锁 15 分钟。

## 三、中风险（建议排期）

- **M1 匿名算力滥用**：`/match`、`/match/stream`、`/export/report` 匿名可用 = 免费烧 DeepSeek token 和 CPU。限流 120/min 偏宽且是单进程内存桶（重启清零、不限总量）。建议：匿名档降到 10/min + 每日全局总量闸门。
- **M2 XSS 纵深不足**：CSP 允许 `unsafe-inline` + 前端大量 innerHTML。markdown 已源头转义，但 KB 上传文档、竞品资料、web_extract 抓回的网页内容最终进 DOM，转义依赖单一环节。建议前端统一过一遍 DOMPurify 类清理。
- **M3 出网请求 SSRF 面**：`web_extract` 接受任意 URL，可被用来探测内网/云 metadata（阿里云 100.100.100.200）。当前内网无敏感服务，但建议加私网/链路本地地址黑名单（127.0.0.0/8、10/8、172.16/12、192.168/16、169.254/16、100.64/10）。
- **M4 nginx 配置漂移**：仓库 `deploy/cloudsol-nginx.conf` 已加固，但线上 `sites-available/huaiwei-cloud` 无法远程确认一致（本机无 SSH 密钥）。上服务器 `diff` 核验一次。另：敏感扩展名拦截未含 `.db/.pem/.json`；`/static` location 指向项目根 `static/` 子目录（当前不存在），将来建目录勿放敏感文件。

## 四、架构问题（非安全，维护性/扩展性）

1. **单进程单 worker + 全内存态**：限流桶、导出任务表、KB 用户缓存都在进程内存——重启丢失、多副本不可用（代码注释已自知）。作品集阶段合理；上量需 Redis。
2. **巨型模块**：`api/routes.py` 3400+ 行、`app/agent/harness.py` 2900+ 行。路由建议按域拆分（match/knowledge/clients/admin），harness 拆 plan/execute/critic。
3. **每新用户全量复制 KB**（902 片段 + 向量库目录拷贝）：磁盘随用户数线性膨胀。可改"共享全局库 + 用户增量层"检索时合并，省一个数量级磁盘。
4. **tests/ 全是一次性 verify_* 脚本**，未 pytest 化（v3 路线图 C6 已排期）。
5. **data/ 318 个 KB 文档入 git**：仓库大，但属有意为之（KB 版本化 + 部署铁律），保留。

## 五、修复优先级

| 级别 | 项 | 工作量 |
|---|---|---|
| 本周 | R2 确认生产 JWT 密钥 + 占位拒启 | 15min |
| 本周 | R1 关闭公网 /docs /redoc | 10min |
| 本周 | R3 登录限流 + 失败锁定 | 1h |
| 下次迭代 | M1 匿名配额收紧 | 1h |
| 下次迭代 | M3 SSRF 黑名单 | 1h |
| 排期 | M2 前端 DOMPurify、M4 nginx diff 核验 | 2h |
