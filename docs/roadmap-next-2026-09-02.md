# 下一步规划 v2（生态：飞书+钉钉优先 / 微信小程序评估 / 个人微信放弃 + MCP + Skills 再丰富）

> 规划时间：2026-09-02（v2，取代 `docs/assessment-ecosystem-mcp-skills-2026-09-02.md` 的路线图部分）
> 决策来源：用户本轮确认——「先接入飞书和钉钉，微信不接了，考虑微信小程序，MCP 和 skills 再丰富一下，重新出一版下一步规划」。
> 背景：cloudsol.cn 已完成 Agent P1/P2/P3 + 三项缺口补齐（Agent 上下文提示 / MCP 真实客户端 / vector_db 可插拔），均本地验收、已 push `origin/main`、未部署生产。

---

## 〇、相对于 v1 评估的决策变更

| 项 | v1 评估 | v2 决策 |
|----|---------|---------|
| 个人微信 | 仅企业微信可做，个人微信不碰 | **明确不接个人微信**（维持） |
| 飞书 / 钉钉 | 建议飞书优先，钉钉对齐 | **飞书 + 钉钉并列第一优先**，先通知后交互 |
| 微信小程序 | 未评估 | **新增评估项**：作为移动端产品面，列为 P3 立项评估（不放弃但后置） |
| MCP | 5 个增强点 | 具体化到 8 点，明确 P0=P0 权限网关 + 自带 Server |
| Skills | 两层（Agent 内部 + WorkBuddy） | 具体化行业技能包 + 意图技能链 + 平台 skill 发布 |

---

## 一、生态接入（飞书 + 钉钉 优先，微信小程序评估，个人微信放弃）

### 1.1 飞书 / 钉钉 接入设计

两类形态，共用一个 `notify.py` adapter，经典与 Agent 两处完成事件各加一行调用：

**形态 A — 群机器人通知（P1 快赢，1–2 天/平台）**
- 飞书：群自定义机器人 webhook + 签名（`timestamp+secret` 做 HMAC），推送 Markdown/卡片。
- 钉钉：自定义机器人 webhook + 加签（`timestamp+secret` 做 HMACBase64），推送 Markdown。
- 触发：Agent `result` 事件、经典 `match` 完成、客户线索更新。
- 内容：方案名 + 行业 + 链接（点开进 cloudsol 看全文）。
- 配置：`FEISHU_WEBHOOK` / `DINGTALK_WEBHOOK` + `SECRET`，默认空=关。

**形态 B — 交互式机器人（P2，3–5 天/平台）**
- 飞书：event subscription（URL 校验 + `timestamp+nonce+sign` 验签）→ 解析消息 → 映射 `user_id` → 复用 `agent.run()` → 回写 IM。
- 钉钉：事件回调（回调 URL + `token` + AES 解密）→ 同理。
- 用户映射：IM 用户 ↔ cloudsol `user_id`（绑定表 `im_user_bind` 走 `db_init.py`；未绑定则匿名 session，回写时提示绑定）。
- 复用现有 SSE/同步生成链路，**Agent 内核零改动**。

### 1.2 微信小程序 评估（P3 立项）

| 维度 | 说明 |
|------|------|
| 是什么 | 运行在微信内的轻量前端 App，作 cloudsol 的移动端产品面（输入需求→看方案/历史/客户） |
| 怎么接 | 小程序前端（WXML/WXSS/JS）+ 后端复用 cloudsol API：MP 后台把 `https://cloudsol.cn` 加进「request 合法域名」白名单，小程序直接带 JWT 调现有 `/api/agent/chat`、`/match` 等；订阅消息（模板消息）做完成通知 |
| 工作量 | 中–高（约 1–2 周）：独立前端工程 + 账号认证（企业小程序 300 元认证）+ 审核；后端几乎复用，仅需少量 CORS/域名适配 |
| 风险 | 中：需小程序账号+资质、审核周期、苹果/安卓无、仅微信生态 |
| 价值 | 高：移动端原生体验、订阅消息推送、微信 12 亿用户触达，是「作品集」最易传播的入口 |
| 建议 | **P3 立项**：先靠飞书/钉钉群机器人验证"推送→点击进 cloudsol"的转化漏斗，再投入小程序（避免过早建独立前端） |

> 关键：小程序**不依赖个人微信机器人**（那是无官方 API 的封号路径），而是走官方「小程序」平台，合规可控。

### 1.3 个人微信：明确不接
无官方机器人接口，只有非官方协议（封号+合规风险），违反稳定性铁律。最终用户口径：**飞书/钉钉/企业微信/小程序走官方，个人微信不碰**。

### 1.4 架构落点（不动隔离）
```
[Agent/经典 生成完成] ──event──> app/services/notify.py ──> 飞书/钉钉 群机器人 (形态A, 纯推送, 默认关)
                                    │
                                    └─ POST /api/channel/<platform> 回调 (形态B, 新增 route, 不碰 Agent/经典)
                                       验签+解析 → 映射 user_id → 复用 agent.run()/match → 回写
微信小程序 ──HTTPS(JWT, cloudsol.cn 白名单)──> 现有 /api/* (P3, 复用, 不加新内核)
```
所有新增代码在 `app/services/notify.py` + `api/channel_routes.py` + `db_init.py`(绑定表)，**不触碰** `agent_workspace.js/css`、`script.js/style.css`、`users.db`。

---

## 二、MCP 再丰富（具体化 8 点）

### 2.1 已落地（本轮）
- `mcp_client.py` 真实 stdio JSON-RPC 客户端；远端工具前缀 `mcp__<label>__<tool>` 注册进 `ToolRegistry`；默认关、失败降级；远端工具作 plan 步「逃生舱」。

### 2.2 增强清单

| # | 增强点 | 价值 | 难度 | 优先级 |
|---|--------|------|------|--------|
| 1 | **权限网关覆盖 `mcp__*` 工具** | 远端工具当前绕过 human-in-the-loop 确认（安全硬门槛） | 低 | **P0** |
| 2 | **自带项目 MCP Server**（竞品动态 `competitor_news` / 成本测算 `cost_calc` / 华为报价 `huawei_pricing` / 文档导出 `doc_export`） | 让 MCP 生态自我反哺，验证「可插拔」闭环 | 中 | **P0/P1** |
| 3 | **HTTP+SSE 传输** | 连「远端托管工具服务」不占本地进程 | 中 | P1 |
| 4 | **工具目录/发现**（well-known manifest 或本地 `mcp_servers.json`） | Agent 自发现可用 server，免手填命令 | 低 | P1 |
| 5 | **热重载 + 调试端点** | `MCP_SERVERS` 改了免重启；`/api/agent/mcp/reload`、`/api/agent/tools` 列本地+远端 | 低 | P2 |
| 6 | **双向暴露** | 已有 stdio server；加 HTTP server 形式，让外部 MCP client 消费 cloudsol 工具 | 低 | P2 |
| 7 | **远端工具结果限流/缓存** | 对标 web_search 限流（3 次/会话），防远端服务被打爆 | 低 | P2 |
| 8 | **远端工具流式进度** | 长耗时远端工具经 `tool_end` summary 回传进度（复用既有机制） | 低 | P3 |

### 2.3 推荐先做（P0）
- **权限网关**：在 `permission_gate.py` 的 `DEFAULT_TOOL_POLICY` 给 `mcp__*` 一个保守默认（写操作 `ask`），`_openPermissionModal` 已支持任意工具名。
- **自带 Server**：先写 1 个 `cost_calc`（数据来自现有 `cost_reference` 公开价目），证明「项目能力→MCP→Agent 可调用」闭环，同时给演示用。

---

## 三、Skills 再丰富（具体化）

### 3.1 Agent 内部技能（不硬编码，走 MCP/配置）
- **行业技能包（Industry Skill Pack）**：制造/医疗/政务/金融/零售，每包 = {提示词模板 + 推荐工具子集 + playbook}；检测行业后自动挂载（复用 `intent` + `_plan` 体系）。避免把所有行业知识塞进单 prompt。
- **意图技能链（Skill Chain）**：把高频组合固化成链，如「投标场景」= analyze_demand → search_kb → search_competitor → cost_calc → generate_doc(pptx)；「客户复盘」= read_customer_file → search_kb → _build_client_context。链本身不新增内核，只是编排。
- **元技能复用**：P3 的 `critic`(self-check) / `reflexion` 抽成通用 skill，供其他模式/工具复用。
- **新原子能力 MCP 化**：`cost_estimator` / `roi_calculator` / `compliance_checker` / `pptx_deep_dive` / `competitor_news_monitor` 优先写成 MCP Server（见 2.2-#2），而非新增 `Tool` 子类——守住「可插拔」哲学。

### 3.2 WorkBuddy 平台技能（生产稳定后）
- 发布「华为云方案匹配」skill/connector，让平台其他用户一键调用（把个人作品集变可分发能力）。
- 发布「售前方案质检」skill（包 self-check critic）、「竞品对比」skill。
- 时机：等 Agent 模式**生产部署**后（当前未部署，用户明确先不部署）。

### 3.3 行业技能包落地形态（草案）
```
data/skill_packs/<industry>.json
{
  "industry": "制造",
  "prompt_template": "...",
  "tool_subset": ["analyze_demand","search_kb","search_competitor","cost_calc"],
  "playbook_ref": "docs/playbook_manufacturing.md"
}
```
`harness` 在 `_plan_and_execute` 前按检测行业 load 对应包 → 注入提示词 + 收窄工具集（与现有 plan 工具集取并集）。

---

## 四、下一步规划（分阶段路线图）

| 阶段 | 项 | 工作量 | 风险 | 默认关 | 依赖 |
|------|----|--------|------|--------|------|
| **P0 基建收尾** | MCP 权限网关覆盖 `mcp__*` | 0.5–1 天 | 低 | 是 | 无 |
| **P0 基建收尾** | 自带 1 个 MCP Server（cost_calc） | 1–2 天 | 低 | 是 | MCP 客户端 |
| **P1 生态快赢** | 飞书群机器人通知 | 1–2 天 | 低 | 是 | notify adapter |
| **P1 生态快赢** | 钉钉群机器人通知 | 1 天 | 低 | 是 | notify adapter（复用） |
| **P1 MCP** | HTTP+SSE 传输 + 工具发现 | 2–3 天 | 中 | 是 | MCP 客户端 |
| **P2 生态交互** | 飞书 webhook receiver（交互） | 3–5 天 | 中 | 是 | P1 通知 |
| **P2 生态交互** | 钉钉 event callback（交互） | 2–3 天 | 中 | 是 | P1 通知 |
| **P2 Skills** | 行业技能包（制造/医疗/政务/金融） | 2–4 天 | 低 | 是 | intent/plan 体系 |
| **P3 小程序** | 微信小程序前端 + 订阅消息 + 域名白名单 | 1–2 周 | 中 | 是 | 需小程序账号+认证 |
| **P3 MCP** | 双向暴露（HTTP server）/ 限流 / 流式进度 | 2–3 天 | 低 | 是 | P1 |
| **P4 平台** | 发布 WorkBuddy skill/connector | 1–2 天 | 低 | — | 生产部署后 |
| **P4 可选** | 企业微信（通知+交互，复用 adapter） | 2–3 天 | 中 | 是 | P1 |
| **P4 可选** | SSO（飞书/钉钉/企业微信登录） | 3–5 天 | 中 | 是 | B2B 多租户时 |

**建议执行顺序**：P0（权限+自带Server，先把 MCP 从演示变安全可用）→ P1（飞书+钉钉通知，最快出业务价值）→ P1 MCP（HTTP 传输）→ P2（飞书/钉钉交互 + 行业技能包）→ P3（小程序，验证转化后再投入）→ P4（平台发布/企业微信/SSO）。

---

## 五、与铁律对齐（不可越）

- **默认关 + 自动降级**：所有新开关（`FEISHU_WEBHOOK`/`DINGTALK_WEBHOOK`/`AGENT_MCP_CLIENT`/新 skill 包）默认空/关，异常不拖垮主链路。
- **隔离**：新增 adapter/route 不碰经典 `script.js/style.css/users.db` 与 Agent 隔离边界。
- **DB**：IM 绑定表、skill 包元数据等新表走 `db_init.py`；部署只 `cp -r` 不 `rsync --delete`。
- **部署**：仍按用户要求**先不部署生产**；代码可 commit/push，上线走标准流程 + 全量 E2E。

---

## 六、若开工，最小可执行第一步

1. `app/agent/permission_gate.py` + `harness`：把 `mcp__*` 纳入 `DEFAULT_TOOL_POLICY`（写操作 `ask`），补远端工具权限确认（P0）。
2. `app/services/notify.py`：先实现飞书 webhook（签名+卡片），经典与 Agent 完成事件各加一行调用（受 `FEISHU_WEBHOOK` 开关控制）；用 mock webhook（webhook.site）本地验证。
3. `app/agent/mcp_server_cost_calc.py` + `MCP_SERVERS` 配置：自带 1 个 cost_calc Server，验证项目能力→MCP→Agent 闭环。

> 以上为规划（v2），未动代码。确认执行顺序后我再逐阶段实现并给出验证。
