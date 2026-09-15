# 下一步规划 v3（2026-09-06，PPT 引擎闭环后）

> 背景：PPT 引擎四阶段上线 + 生产全绿（a1ecb29），产品版本升 v3.0.0（47d1633）。
> 前置：docs/roadmap-next-2026-09-02.md 生态路线 P0/P1 基本关账（飞书通知 ✅、MCP 网关+cost_calc ✅、HTTP+SSE ✅）；
> 钉钉通知代码就绪未上线；docs/code-audit-2026-09-05.md 遗留小坑未清。
> 优先级：A（钉钉上线）→ C（监控）→ B（PDF 引擎化）；D 线 9 月内不动。

---

## A 线：钉钉机器人上线（1 天）⭐ 先做

目标：飞书 + 钉钉双平台 IM 闭环，09-02 路线图生态项全部关账。

| # | 任务 | 说明 | 预估 |
|---|------|------|------|
| A1 | 钉钉开放平台配置 | 建群机器人（Stream 模式免公网回调），拿 app_key/secret | 用户侧 30min |
| A2 | .env 配置钉钉段 | `DINGTALK_APP_KEY/SECRET/BOT_ENABLED=1`，限次对齐飞书 | 10min |
| A3 | 服务部署 | `deploy/cloudsol-im-bot.service` systemd 常驻，`systemctl enable --now` | 30min |
| A4 | 生产 E2E | @机器人问"帮我给XX客户出方案"走完整 Agent 链路；方案完成通知推送群卡片（share 链接免登录打开） | 1h |
| A5 | 验收文档 | docs/dingtalk-bot-setup.md 补生产实测记录；feature-inventory 同步 | 30min |

风险：钉钉 Stream SDK 长连接稳定性（飞书 ws 已跑通同模式，预期风险低）。

## C 线：质量与运维底座（1-2 天，可穿插）

| # | 任务 | 说明 | 预估 |
|---|------|------|------|
| C1 | 重启 502 窗口消除 | systemd 加 `ExecStartPost` 就绪探针（或 nginx `proxy_next_upstream` 兜底）；今天 21:19 的 502 就是这个坑 | 1h |
| C2 | MCP 远端工具限流 | 对标 web_search 3 次/会话（审计遗留） | 2h |
| C3 | 邮箱改绑加验证 | 改绑新邮箱须验证码确认（审计遗留，安全项） | 2h |
| C4 | GaussDB 占位决策 | 做实（真实价目+文档）或摘除，不留半成品 | 0.5h 决策 |
| C5 | 0 字节死库清理 | 审计确认 4 个空库文件删除 | 0.5h |
| C6 | E2E 脚本 pytest 化 | scripts/ 的引擎 E2E / 意图单测转正进 tests/，CI 可跑 | 0.5 天 |

## B 线：报告三件套一致性——PDF 引擎化（2-3 天）⭐ 复用 PPT 资产

现状：PPT=新引擎（tokens/layouts/门禁），Word=修复后管线，**PDF=reportlab 老管线**（仅字体兜底），三格式品质不齐。

| # | 任务 | 说明 | 预估 |
|---|------|------|------|
| B1 | 设计确认 | PDF 版面方案：矢量重排 12 页结构（reportlab 复用 tokens 色彩/字号令牌），或"Word 转 PDF"轻方案（libreoffice headless，品质依赖 Word 排版）——先定方向再写码 | 0.5 天 |
| B2 | 管线实现 | 复用 ppt_engine 的 tokens + 成本表程序化数据，走 validate 门禁后渲染 PDF | 1 天 |
| B3 | E2E | 单元格级断言（沿用 b14ecbc 教训：断言必须到单元格文本）+ 三格式视觉一致性核对 | 0.5 天 |
| B4 | 部署+知识库同步 | 生产验证；platform_knowledge 补 PDF 描述；feature-inventory 更新 | 0.5 天 |

面试故事：一套设计令牌驱动 Word / PPT / PDF 三种售前交付物。

## D 线：立项不实施（9 月内不动）

- 微信小程序：先看 IM 推送→点击转化数据再决策
- 移动端 Agent 解锁：工作量大，移动端暂锁经典模式
- 深色模式：暂缓
