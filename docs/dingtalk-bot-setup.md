# 钉钉交互机器人配置指南（Stream 模式）

> 目标：钉钉群里 @机器人 发需求 → cloudsol Agent 生成方案 → 群里回一张带临时分享页链接的卡片（匿名可读、30 天有效）。  
> 架构：独立 systemd 服务 `cloudsol-im-bot`，出站长连接（Stream 模式，免公网回调/免开端口），经 `127.0.0.1:8000` 环回调用 API 内部端点跑 Agent。

## 一、钉钉开放平台创建应用（手动，约 10 分钟）

1. 打开 [钉钉开放平台](https://open-dev.dingtalk.com/)，用钉钉账号登录（没有组织的可免费创建一个）。
2. **应用开发 → 创建应用**：应用名建议「云方案助手」，描述随意。
3. 进入应用 → **应用能力 → 添加应用能力 → 机器人**（机器人配置里"消息接收模式"选 **Stream 模式**——这是免公网回调的关键）。
4. **凭证与基础信息**：复制 `Client ID`（即 AppKey）和 `Client Secret`（即 AppSecret）。
5. **版本管理与发布 → 发布应用**（不发布群里搜不到机器人）。
6. 群里添加机器人：群设置 → 机器人 → 添加机器人 → 选「云方案助手」。

## 二、服务器配置 .env

在 `/var/www/huawei-cloud-solution-matcher/.env` 追加：

```bash
# ── IM 机器人（钉钉 Stream 模式）──
INTERNAL_API_TOKEN=<随机长串，如 openssl rand -hex 24 生成>
DINGTALK_BOT_CLIENT_ID=<第一步的 Client ID>
DINGTALK_BOT_CLIENT_SECRET=<第一步的 Client Secret>
IM_BOT_USER_ID=3                      # 群里请求以此账号身份执行（KB上下文/成就归属）
IM_BOT_WHITELIST=                     # senderStaffId 白名单，逗号分隔；空=群里所有人可用
IM_BOT_DAILY_LIMIT=50                 # 每人每天最多触发 50 次 Agent 生成
```

> `IM_BOT_USER_ID` 填运营者账号 id（可查 users 表或登录后看接口返回）。  
> 白名单先留空调试，跑通后再把群成员的 senderStaffId 填进来（bot 日志会打印每个发送者的 staffId）。

## 三、安装与启动

```bash
cd /var/www/huawei-cloud-solution-matcher
venv/bin/pip install -r requirements.txt          # 新增 dingtalk-stream（仅 bot 服务使用）
cp deploy/cloudsol-im-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl restart huawei-cloud-api                 # .env 新增了 INTERNAL_API_TOKEN，主服务需重启加载
systemctl enable --now cloudsol-im-bot
journalctl -u cloudsol-im-bot -f                   # 看日志：应出现「钉钉 Stream 机器人启动」
```

## 四、验收

群里发：`@云方案助手 给一家500人的制造企业做个上云方案`

预期时序：

1. 立即回复「已收到需求，正在生成方案（约 2-4 分钟）…」
2. 2-5 分钟后回复「✅ 方案已生成」卡片：400 字导读 + 「点此查看完整方案」链接（`https://cloudsol.cn/share.html?id=...`，匿名可读）
3. 日志可见 `staff=xxx text=...` 与 `[agent/chat]` 执行轨迹

## 五、故障排查

| 现象                 | 排查                                                                                          |
| ------------------ | ------------------------------------------------------------------------------------------- |
| 服务启动即退出，日志「凭证未配置」  | .env 没配 DINGTALK_BOT_CLIENT_ID/SECRET，或没重启服务                                                |
| 群里 @ 无反应           | 确认应用已发布、机器人已在群里、消息接收模式=Stream；`journalctl -u cloudsol-im-bot` 有无收到消息日志                      |
| 回复「生成失败（服务返回 403）」 | .env 的 INTERNAL_API_TOKEN 与主服务加载的不一致 → `systemctl restart huawei-cloud-api cloudsol-im-bot` |
| 回复「生成失败：后端服务暂不可用」  | 主 API 没起来：`systemctl status huawei-cloud-api`                                               |
| 回复「今日生成次数已达上限」     | IM_BOT_DAILY_LIMIT 限次生效（进程重启后计数清零）                                                          |

## 六、安全边界

- 内部端点双重防线：uvicorn 仅监听 `127.0.0.1`（公网不可达）+ `X-Internal-Token` 精确匹配（未配置=端点整体 403）。
- bot 无头放行的工具权限仅在内部端点内显式 allow（generate_doc/read_customer_file/mcp 成本工具），不影响网页端权限闸门。
- 滥用防护：白名单 + 每人每日限次；计数在进程内存（重启清零，可接受）。

