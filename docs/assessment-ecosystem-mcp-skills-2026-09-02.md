# 生态接入与能力扩展评估（微信 / 飞书 / 钉钉 + MCP / Skills）

> 评估时间：2026-09-02
> 背景：cloudsol.cn 已完成 Agent P1/P2/P3，本轮又补齐了三项缺口——
> ① Agent 结果页客户上下文提示；② MCP 远程工具真实 stdio 客户端；③ vector_db 可插拔抽象（Chroma 默认 + GaussDB 扩展点）。
> 本文评估「后续还能接入微信/飞书/钉钉等生态吗」「MCP 与 skills 还能再丰富吗」，并给出落地优先级。

---

## 〇、评估前提（与既有铁律对齐）

| 约束 | 含义 | 对扩展的影响 |
|------|------|--------------|
| 经典/Agent 物理隔离 | 经典 `script.js/style.css/users.db` 字节级不动；Agent 只动 `agent_workspace.*` + `index.html` 版本号 | 任何生态接入都不能改经典代码，新增能力走独立 adapter/route |
| 稳定性 > 新功能 | 任一新开关默认关闭、异常自动降级 | 微信/飞书/钉钉、MCP、新 skill 全部「默认关、可降级」 |
| 单一认证 | 一个 `users` 表 + 一个 JWT，经典/Agent 共用账号 | IM 用户需映射到同一 `user_id`（而非新建账号体系） |
| 部署铁律 | `cp -r` 只覆盖代码不碰 DB；新列走 `db_init.py` | 生态接入若需新表，必须走 `db_init.py`，禁止 `rsync --delete` |

结论先行：**三件事都「能做」，但 ROI 与风险差异大。飞书/钉钉的「通知机器人」是 1–2 天的高 ROI 快赢；IM 交互式机器人中等投入、建议飞书优先；微信必须走「企业微信」而非个人微信。MCP 已真实可用，下一步重点是「权限网关覆盖 + HTTP 传输 + 工具自举」；skills 走「行业技能包 + 新工具 MCP 化」而非硬编码。**

---

## 一、微信 / 飞书 / 钉钉 生态接入可行性

### 1.1 三种接入形态

| 形态 | 做什么 | 难度 | 风险 | 是否动 Agent/经典 |
|------|--------|------|------|-------------------|
| **A. 通知推送**（群机器人） | 方案生成完成 / 客户线索更新时，向群里 POST 一条卡片 | 低（1–2 天） | 低 | 不动，纯后端 adapter |
| **B. 交互式入口**（收消息触发 Agent） | 在 IM 里 @机器人 发需求 → 走 Agent 出方案 → 回 IM | 中（3–7 天） | 中（需公网回调 + 签名校验） | 不动，新增 webhook receiver route |
| **C. 企业身份（SSO）** | 用飞书/钉钉/企业微信账号登录 cloudsol | 中 | 中（OAuth 回调 + 账号绑定） | 不动，新增 OAuth route + 绑定逻辑 |

### 1.2 各平台对比

| 平台 | 通知机器人 | 交互回调 | 官方 API 形态 | 备注 |
|------|-----------|----------|---------------|------|
| **飞书（Lark）** | ✅ 群自定义机器人 webhook + 签名 | ✅ event subscription（URL 校验 + 签名） | 文档最友好，签名简单 | **推荐作为第一个接入对象** |
| **钉钉** | ✅ 自定义机器人（加签/关键词） | ✅ 事件回调（回调 URL + token + AES） | 文档尚可 | 与飞书近乎对称，可复用 adapter |
| **企业微信** | ✅ 群机器人 webhook | ✅ 接收消息回调（AES+token） | 官方、稳定 | 微信生态正路 |
| **个人微信** | ❌ 无官方 API | ❌ 无官方 API | 只有非官方协议（封号/合规风险） | **不建议**；如必须，走企业微信 |

> ⚠️ 关键点：用户说的「微信」大概率是个人微信，但个人微信**没有官方机器人接口**，只能走企业微信。评估时务必先澄清是「企业微信」还是「个人微信」——前者可做，后者不碰（合规+封号风险，违反稳定性铁律）。

### 1.3 推荐落地路线

1. **第一步（快赢）**：飞书群机器人通知。新增 `app/services/notify.py` 适配层，封装 `send_feishu(text/cards)` / `send_dingtalk()` / `send_wecom()`，在 Agent `result` 事件与经典 `match` 完成后调用（受 `NOTIFY_*_WEBHOOK` 配置开关控制，默认关）。产出：销售同学在企业群实时收到「XX 客户方案已生成」卡片，可直接点链接进 cloudsol 看全文。
2. **第二步（中投入）**：飞书交互式机器人。新增 `POST /api/channel/feishu` 回调路由，做 URL 校验 + 签名验签 + 消息解析，把文本映射为一次 `agent.run()`（用 IM 用户 ↔ `user_id` 映射），结果回写 IM。复用现有 SSE/同步生成链路，**Agent 内核零改动**。
3. **第三步（按需）**：企业微信/钉钉对齐第二步；SSO 登录作为可选项（B2B 多租户时才值得）。

### 1.4 架构落点（不动隔离）

```
[Agent/经典 生成完成]
        │ (event)
        ▼
app/services/notify.py  ──> 飞书/钉钉/企业微信 群机器人 webhook   (形态 A，纯推送)
        ▲
        │ (可选) POST /api/channel/<platform> 回调路由 (形态 B/C，独立新增，不碰 Agent/经典)
        │
   验签 + 解析 → 映射 user_id → 复用 agent.run()/match → 回写
```

所有新增代码在 `app/services/notify.py` 与 `api/channel_routes.py`，**完全不触碰** `agent_workspace.js/css`、`script.js/style.css`、`users.db`。

---

## 二、MCP 还能怎么丰富

### 2.1 现状（本轮已落地）

- `app/agent/mcp_client.py`：**真实 stdio JSON-RPC 2.0 客户端**，完成 initialize 握手、tools/list、tools/call，远端工具以 `mcp__<label>__<tool>` 前缀注册进 `ToolRegistry`；默认关闭（`AGENT_MCP_CLIENT=0`），失败自动跳过（优雅降级）。
- 远端工具已作为「逃生舱」注入每个 plan 步工具集（`harness._remote_tool_names`），LLM 可在任意步按需调用。
- `app/agent/mcp_server.py`：把本地 7 个工具暴露为标准 MCP（可供任意外部 MCP client 消费）。

### 2.2 五个增强点（按优先级）

| # | 增强点 | 价值 | 难度 | 优先级 |
|---|--------|------|------|--------|
| 1 | **权限网关覆盖远端工具** | 当前 `tool_permissions` 只按本地工具名映射，远端 `mcp__*` 工具**绕过** human-in-the-loop 确认。应把 `mcp__<label>__*` 纳入现有权限 gate（#3），写操作默认需确认 | 高（安全） | P0 |
| 2 | **HTTP+SSE MCP 传输** | 当前仅 stdio（需 spawn 子进程）。新增 HTTP+SSE transport 可连「远端托管的工具服务」（如云上竞品库/定价服务），不占本地进程 | 中 | P1 |
| 3 | **工具目录自举** | 新增 1–2 个**项目自带** stdio MCP Server（如 `competitor_news` 竞品动态、`cost_calc` 成本测算、`huawei_pricing` 华为报价），让 MCP 生态自我反哺，演示「可插拔」 | 中 | P1 |
| 4 | **热重载 + 调试端点** | `MCP_SERVERS` 改了要重启；加 `/api/agent/mcp/reload` 与 `/api/agent/tools`（列出本地+远端工具）便于运维与排障 | 低 | P2 |
| 5 | **双向暴露** | 已有 stdio server；再加 HTTP server 形式，让**别的** MCP client 也能消费 cloudsol 的工具（生态输出） | 低 | P2 |

### 2.3 关键提醒

- **安全**（最重要）：远端工具来自外部进程，必须过既有权限网关。否则远端工具的写操作（如发邮件、改数据）会绕过确认。这是把 MCP 从「演示」变「生产可用」的硬门槛。
- **命名冲突已处理**：前缀 `mcp__<label>__` 已规避本地重名；但需在权限 gate 的 `DEFAULT_TOOL_POLICY` 里给 `mcp__*` 一个保守默认（写操作 `ask`）。

---

## 三、Skills 还能怎么丰富

「skills」有两层含义，分别给出建议：

### 3.1 A 层：Agent 自身的能力（工具/意图/行业包）

现状：7 个工具 + 意图路由 + P1–P3 推理增强。扩展原则：**核心保持精简，新能力走 MCP 而非硬编码**。

- **行业技能包（Industry Skill Pack）**：把「制造/医疗/政务/金融」等行业的专属提示词 + 推荐工具组合，做成可加载的 bundle。检测到行业后自动挂载对应技能包（复用现有 `intent` + `_plan` 体系），避免把所有行业知识塞进单个 prompt。
- **新原子能力 MCP 化**：如需 `cost_estimator` / `roi_calculator` / `compliance_checker` / `pptx_deep_dive`，优先写成 MCP Server（见 2.2-#3），而非新增 `Tool` 子类——保持「可插拔」哲学，也便于独立测试。
- **反思/自评技能复用**：P3 的 self-check / reflexion 已是「元技能」，可抽成通用 `critic` skill 供其他模式复用。

### 3.2 B 层：WorkBuddy 平台侧的 skill/connector

- 当前 agent 已作为 WorkBuddy 能力运行。可把「华为云方案匹配」**发布为 WorkBuddy skill/connector**，让平台其他用户一键调用——这是把 cloudsol 从「个人作品集」变成「可分发能力」的关键一步。
- 时机：建议等 Agent 模式**生产部署**之后再发布（当前用户明确「先不部署生产」），避免发布半成品。

### 3.3 Skills 扩展优先级

1. 行业技能包（高 ROI、低侵入，复用现有意图/计划体系）。
2. 把 2–3 个高频新能力做成 MCP Server（验证「可插拔」闭环）。
3. 生产部署稳定后，发布 WorkBuddy skill/connector。

---

## 四、总体优先级与风险清单

| 优先级 | 项 | 工作量 | 风险 | 备注 |
|--------|----|--------|------|------|
| P0 | MCP 权限网关覆盖 `mcp__*` 工具 | 0.5–1 天 | 低 | 安全硬门槛，先于「开箱即用」 |
| P0（快赢） | 飞书群机器人通知 | 1–2 天 | 低 | 不动隔离，默认关 |
| P1 | 飞书交互式机器人（webhook receiver） | 3–5 天 | 中 | 需公网 + 验签，飞书优先 |
| P1 | MCP HTTP+SSE 传输 | 2–3 天 | 中 | 连托管工具服务 |
| P1 | 自带 MCP 工具 Server（竞品/成本/报价） | 2–3 天 | 低 | 生态自举 |
| P2 | 企业微信/钉钉通知对齐 | 1–2 天 | 低 | 复用 notify adapter |
| P2 | 行业技能包 | 2–4 天 | 低 | 复用意图/计划体系 |
| P2 | MCP 热重载 + 调试端点 | 0.5–1 天 | 低 | 运维友好 |
| P3 | SSO（企业微信/飞书登录） | 3–5 天 | 中 | 仅 B2B 多租户时做 |
| P3 | 发布 WorkBuddy skill/connector | 1–2 天 | 低 | 等生产部署后 |

**风险红线（不可越）**：
- 微信只走企业微信，不碰个人微信（合规+封号）。
- 所有新增通道默认关闭、异常降级，绝不拖垮主链路。
- 经典/Agent 隔离铁律：新增 adapter/route 不触碰经典代码与 `users.db`。
- 任何新表走 `db_init.py`，部署只 `cp -r` 不 `rsync --delete`。

---

## 五、最小可执行下一步（若开工）

1. `app/services/notify.py`：先实现飞书 webhook（签名+卡片），经典与 Agent 两处完成事件各加一行调用（受 `FEISHU_WEBHOOK` 开关控制）。
2. `app/agent/harness.py` + `permission_gate.py`：把 `mcp__*` 纳入 `DEFAULT_TOOL_POLICY`（写操作 `ask`），补上远端工具权限确认。
3. 验证：本地起后端，配一个 mock webhook（如 webhook.site）验证推送；MCP 权限用现有 Playwright/单测验证拦截。

> 注：以上均为「评估 + 设计」，未动生产（用户本轮要求「先不部署生产」）。代码改动（三项缺口）已本地完成并通过单元测试，待你确认后再走标准部署流程。
