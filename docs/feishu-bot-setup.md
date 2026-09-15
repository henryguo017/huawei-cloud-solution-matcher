# 飞书交互机器人配置指南（长连接模式）

> 背景：用户钉钉账号被学校组织管控无法建应用，飞书个人可自建团队+自助建应用，故飞书先行。
> 目标：飞书群里 @机器人 发需求 → cloudsol Agent 生成 → 群里回富文本卡片（临时分享页链接，匿名可读 30 天）。
> 架构：独立 systemd 服务 `cloudsol-im-feishu`，官方 SDK `lark-oapi` 长连接（免公网回调），经 `127.0.0.1:8000` 环回调用 `/api/agent/chat-internal`。与钉钉 bot（`cloudsol-im-bot`）完全同构，可共存。

## 一、飞书开发者后台建应用（手动，约 10 分钟）

1. 打开 [open.feishu.cn](https://open.feishu.cn) → 飞书账号登录 → **开发者后台**
   - 若提示无权限/无法创建：先在飞书 App 里**创建自己的团队**（侧栏 → 创建团队，个人手机号即可），再用该团队身份进开发者后台
2. **创建企业自建应用**：名字 `云方案助手`
3. **添加应用能力 → 机器人**
4. **权限管理**：搜索 `im:message`，开通 **「获取与发送单聊、群组消息」**
5. **事件与回调**：
   - 订阅方式选 **「使用长连接接收事件」**（关键，免公网回调/免开端口）
   - 添加事件：**接收消息 `im.message.receive_v1`**
6. **凭证与基础信息**：复制 `App ID` / `App Secret`
7. **版本管理与发布 → 创建版本 → 发布**（不发布加不了机器人）
8. 飞书群 → 设置 → 群机器人 → 添加 → 选「云方案助手」

## 二、服务器配置 .env

`/var/www/huawei-cloud-solution-matcher/.env` 追加（若之前已为钉钉 bot 配过 `INTERNAL_API_TOKEN` 等，不要重复配）：

```bash
FEISHU_BOT_APP_ID=<cli_ 开头的 App ID>
FEISHU_BOT_APP_SECRET=<App Secret>
# 以下若钉钉 bot 已配过则复用，无需再写：
# INTERNAL_API_TOKEN=<openssl rand -hex 24>
# IM_BOT_USER_ID=2
# IM_BOT_WHITELIST=          # 飞书按 sender open_id 过滤（与钉钉 staffId 共用此 env，逗号分隔）
# IM_BOT_DAILY_LIMIT=50
```

## 三、安装与启动

```bash
cd /var/www/huawei-cloud-solution-matcher
venv/bin/pip install -r requirements.txt          # 含 lark-oapi（仅飞书 bot 使用）
cp deploy/cloudsol-im-feishu.service /etc/systemd/system/
systemctl daemon-reload
systemctl restart huawei-cloud-api
systemctl enable --now cloudsol-im-feishu
journalctl -u cloudsol-im-feishu -f               # 应出现「飞书长连接机器人启动」
```

## 四、验收

群里发：`@云方案助手 给一家500人的制造企业做个上云方案`

预期：秒回「已收到需求…」→ 2-5 分钟后回「✅ 方案已生成」富文本（导读 + 「👉 点此查看完整方案」链接）。

## 五、故障排查

| 现象 | 排查 |
|---|---|
| 服务退出「凭证未配置」 | .env 没配 FEISHU_BOT_APP_ID/SECRET 或没重启服务 |
| 群里 @ 无反应 | 应用未发布；事件订阅方式不是「长连接」；没加 `im.message.receive_v1` 事件；机器人没加进群 |
| 回复「服务返回 403」 | INTERNAL_API_TOKEN 与主服务不一致 → `systemctl restart huawei-cloud-api cloudsol-im-feishu` |
| 发送被拒 code=99991672/230001 等 | 权限不足：确认 `im:message`（获取与发送单聊、群组消息）已开通且**已发布新版本**（改权限必须重新发布才生效） |
| 回复「次数已达上限」 | IM_BOT_DAILY_LIMIT 生效（进程重启清零） |

## 六、安全边界（与钉钉 bot 相同）

- 内部端点双防线：uvicorn 仅 127.0.0.1 + X-Internal-Token 精确匹配（未配置=403）
- 无头工具权限仅在内部端点内显式 allow，不影响网页端
- 白名单 + 每日限次；计数进程内存（重启清零）
