# 代码梳理 · MCP 与 Skills 子系统（2026-09-06 基线）

> 范围：围绕「后续还能加什么 MCP 与 Skills」做定向代码梳理。  
> 重点文件：`app/agent/{mcp_server,mcp_client,mcp_server_cost_calc,permission_gate,skill_packs,tools,harness,intent,agent}.py`、`app/config.py`、`data/skill_packs/*`、`api/agent_routes.py`、`deploy/huawei-cloud-api.service`、`.env`。

---

## 0. 一句话结论

MCP 与 Skills 两套机制的**代码骨架已全部就绪、且工程质量很高**（零新依赖、优雅降级、权限网关、命名空间隔离都做了），但**此前生产处于"休眠态"**——因为 `AGENT_MCP_CLIENT` 与 `AGENT_SKILL_PACKS` 两个开关在 `.env` 与 systemd 里均未置 1，按 `config.py` 默认值走 0。

**第一步不是"加新东西"，而是先激活 + 验证已有的 cost_calc MCP 与 5 个行业技能包，再谈扩展。**

> **【P0 进展 · 2026-09-06 22:50】** 激活所需的代码/配置改动已完成、本地冒烟全绿：
> - `.env.example` 已翻为激活态（`AGENT_MCP_CLIENT=1` + `AGENT_SKILL_PACKS=1` + `MCP_SERVERS` 指向 cost_calc）。
> - 本地三项冒烟全通过：cost_calc Server stdio 出 TCO；mcp_client 与 cost Server 握手+调用闭环；skill_packs 命中制造/金融、未覆盖行业优雅返回 None。
> - **待用户执行 ECS 实跑**：把同样三行写入 `/var/www/huawei-cloud-solution-matcher/.env` 并 `systemctl restart huawei-cloud-api`，再把生产 Agent 跑一题确认成本步与行业包生效（命令见 §7）。

---

## 1. MCP 子系统现状

### 1.1 三个文件，各司其职

| 文件                                  | 角色                                        | 状态  | 关键能力                                                                                                                         |
| ----------------------------------- | ----------------------------------------- | --- | ---------------------------------------------------------------------------------------------------------------------------- |
| `app/agent/mcp_server.py`           | **能力自暴露 Server**（把本地 7 工具喂给任意 MCP client） | 已落地 | stdio + HTTP/SSE 双传输；`initialize/tools/list/tools/call`；纯 stdlib                                                             |
| `app/agent/mcp_client.py`           | **消费端**（把外部 Server 的工具拉进本地 ToolRegistry）  | 已落地 | stdio(`MCPClient`) + HTTP(`MCPHttpClient`) 双传输；前缀 `mcp__<label>__<tool>` 隔离；env + `data/mcp_servers.json` manifest 合并；任一失败跳过 |
| `app/agent/mcp_server_cost_calc.py` | **自带业务 Server**（P0）                       | 已落地 | 成本测算 `cost_calc` + `cost_reference_list`；内置 SKU 目录（10 项）；单价只在工具内计算，强制 Agent 调工具报价                                            |

### 1.2 协议与传输

- 协议：`JSON-RPC 2.0`，`protocolVersion="2024-11-05"`。
- 传输：stdio（子进程，零端口）+ Streamable HTTP（`POST /mcp`，`text/event-stream` 回 `data:` 行）。**两套传输共用同一 `_handle_request`**，客户端接口一致（`connect/list_tools/call_tool/close`）。
- 无 `resources`/`prompts` 能力，仅 `tools`（最小子集，`listChanged:False`）。

### 1.3 权限网关（已就绪，且设计正确）

- `app/agent/permission_gate.py`：纯函数 `resolve_tool_policy(tool, user_overrides, default)`。
- **硬规则**：工具名以 `mcp__` 开头 → 默认 `"ask"`（human-in-the-loop 确认），因为外部能力不可信。
- `harness.py` 在每次工具执行前调 `_resolve_tool_policy`，`ask` 时发 `permission_request` SSE 并阻塞等用户决策（120s 超时默认拒绝）。
- `api/agent_routes.py` 显式把 `mcp__cost__cost_calc` / `mcp__cost__cost_reference_list` 设为 `"allow"`（本平台自带的、可信），跳过确认。

### 1.4 配置开关（当前全部默认关）

`app/config.py`：

```
AGENT_MCP_CLIENT = os.getenv("AGENT_MCP_CLIENT", "0")   # 默认关
MCP_SERVERS       = os.getenv("MCP_SERVERS", "")         # 空
```

`.env` 与 `deploy/huawei-cloud-api.service` **均未见这两个变量** → 生产 = 默认值 0。

### 1.5 🔴 关键发现：MCP 链路此前在生产是"假死"（P0 已解除）

- `agent.py::_ensure_mcp_tools()`：`AGENT_MCP_CLIENT != "1"` 时直接 return，`_remote_tool_names` 永为空。
- `harness.py` 里 `_force_cost_step`（强制成本步）、每步"逃生舱"工具集、plan 注入——都依赖 `self._remote_tool_names` 非空。
- **后果**：开关没开时 `cost_calc` 工具根本不会被注册，Agent 不会做成本测算。
- **P0 修复态**：`.env.example` 已置 `AGENT_MCP_CLIENT=1` + `MCP_SERVERS` 指向 cost_calc；ECS `.env` 写入同值并 restart 后即点亮（本地冒烟已验证握手与 TCO 返回正确）。

---

## 2. Skills 子系统现状

### 2.1 加载器 `app/agent/skill_packs.py`

- 从 `data/skill_packs/<slug>.json` 加载行业技能包，进程内只读缓存一次。
- `match_pack(industries)`：按意图行业词（`intent._INDUSTRY_KEYWORDS`）+ 包 `aliases` 匹配首个命中包。
- **设计铁律**：① 默认关（`AGENT_SKILL_PACKS=0` 时 harness 不调用）；② 失败吞掉（返回 None，不阻断主链路）；③ **只注入提示词，不碰工具集**。
- 注入点（`harness.py`）：角色提示词追加 `pack_prompt_block`（demand_analyst/solution_architect/quality_reviewer 三段）+ 终稿 `pack_synthesize_block`（含 playbook 要点清单）。

### 2.2 已有 5 个行业包（`data/skill_packs/`）

| slug            | industry | 内容规模                                                   |
| --------------- | -------- | ------------------------------------------------------ |
| `manufacturing` | 制造       | demand/architect/reviewer/synthesize 四段 + 7 条 playbook |
| `finance`       | 金融       | 同上结构                                                   |
| `government`    | 政务       | 同上结构                                                   |
| `healthcare`    | 医疗       | 同上结构                                                   |
| `retail`        | 零售       | 同上结构                                                   |

包格式 v1：只含 `prompt_template`（4 段角色提示）+ `playbook`（终稿要点）。**无工具扩展、无示例库、无检索增强**。

### 2.3 配置开关

`app/config.py`：`AGENT_SKILL_PACKS = os.getenv("AGENT_SKILL_PACKS", "0")`（默认关）。  
`.env` 无该 flag → 生产默认 = 0 → **5 个技能包此前未被挂载**（与"已激活"记忆不符，待 ECS `.env` 复核）。

### 2.4 🔴 关键发现：Skills 此前同样休眠（P0 已解除）

`harness.py:909` 的挂载条件是 `(AGENT_SKILL_PACKS or "0").strip()=="1"`。开关没开 → 行业包完全不生效，Agent 跨行业方案质量全靠通用 14 章模板兜底。  
**P0 修复态**：`.env.example` 已置 `AGENT_SKILL_PACKS=1`；ECS `.env` 写入同值并 restart 后，制造/金融/政务/医疗/零售 5 包将按意图自动挂载（本地 `match_pack` 已验证制造/金融命中、未覆盖行业返回 None 优雅降级）。

---

## 3. Agent 如何串联两者（`harness.py` + `agent.py`）

```
SolutionAgent.__init__  → create_default_tools()  // 7 个本地工具
run() 首调 → _ensure_mcp_tools()   // 按 AGENT_MCP_CLIENT 拉远端工具，写 harness._remote_tool_names
harness.run() 按 intent 路由 → 两阶段/多智能体 plan 驱动
  ├─ 每步 toolset = 角色工具子集 + _remote_tool_names（MCP=逃生舱）
  ├─ solution/competitor 意图 → skill_packs.match_pack 命中则注入行业提示词
  ├─ 定价意图命中 & cost_calc 未调 → _force_cost_step 确定性补成本步
  └─ 每工具执行前 → _resolve_tool_policy（mcp__ 默认 ask，触发 permission SSE）
```

**编排层质量很高**：Plan 面板、单步重跑、反思-重规划、自检 Gate、并行工具、长程记忆、客户上下文——全部就位。MCP/Skills 是"插在编排上的可插拔增强层"，耦合很干净。

---

## 4. 还能加什么 MCP（具体清单）

### 4.1 先激活（P0，零开发）

1. `.env` 加 `AGENT_MCP_CLIENT=1` + `MCP_SERVERS='[{"command":["python","-m","app.agent.mcp_server_cost_calc"],"label":"cost"}]'`，重启。
2. 端到端验证：Agent 方案里出现 TCO 测算、`mcp__cost__cost_calc` 出现在 tool_calls。

### 4.2 新增自带 Server（把本地 7 工具"转正"为对外可消费）

- `mcp_server.py` 已能把 7 工具暴露成 MCP，但**生产从未把它放进 `MCP_SERVERS`**。建议正式登记 `"label":"self"`，让 Agent 在 loopback 下也能通过标准协议调用自家工具（验证协议闭环 + 为外部 client 接入铺路）。

### 4.3 业务型新 Server（高价值，售前场景）

| 候选 Server               | 暴露工具                                            | 价值                                       |
| ----------------------- | ----------------------------------------------- | ---------------------------------------- |
| `mcp_server_kb`         | `kb_stats` / `kb_reindex` / `kb_upload_parse`   | 让 Agent 能自查知识库覆盖度、触发重建、解析新上传文档（现靠人工/接口）  |
| `mcp_server_competitor` | `competitor_battlecard(industry)`               | 把 12 竞品厂商的对比卡片结构化，Agent 直接取而不是每次 RAG 拼   |
| `mcp_server_tco`        | 在 cost_calc 上扩 `quote_compare(skus, providers)` | 华为云 vs 阿里云 vs AWS 同规格比价                  |
| `mcp_server_notify`     | `push_feishu(text)` / `push_dingtalk(text)`     | 把飞书/钉钉推送变成 Agent 可调工具（现是事件触发，非 Agent 主动） |
| `mcp_server_crm`        | `client_add` / `client_list` / `match_history`  | Agent 主动写客户管理/查历史匹配（现只会话内）               |
| `mcp_server_report`     | `gen_word` / `gen_pptx` / `gen_pdf`             | 把导出能力做成标准工具，统一 generate_doc 与 PPT 引擎入口   |

### 4.4 第三方 Server 接入（生态闭环）

- 接一个联网搜索 MCP（Tavily/Exa）替代现 `web_search` 工具里的自写 provider，统一走 MCP 协议。
- 接一个表格/Excel MCP（如本地部署），让"成本表数量列"等导出类操作更稳。

### 4.5 对照 roadmap 的 8 点增强（逐项对齐现状）

| roadmap 点      | 现状                            | 建议                                                                   |
| -------------- | ----------------------------- | -------------------------------------------------------------------- |
| 权限网关覆盖 `mcp__` | ✅ 已做（默认 ask + cost 显式 allow）  | 补：用户级 override 持久化（现内存态，重启丢失）                                        |
| 自带 Server      | ✅ cost_calc                   | 扩 4.3 的 5 个                                                          |
| HTTP+SSE       | ✅ mcp_client 已支持              | 验收：把 cost_calc 也起 HTTP 版做双传输压测                                       |
| 工具发现           | ⚠️ 仅 tools/list               | 加 `listChanged` 通知 + 启动时缓存失效刷新                                       |
| 热重载            | ❌ 未做                          | `data/mcp_servers.json` 改了要重启才生效；加文件 watch 或 `/api/admin/mcp/reload` |
| 双向暴露           | ⚠️ 仅自暴露/自消费                   | 让本平台作为 MCP Server 被 WorkBuddy/Claude Desktop 等外部 client 消费（卖点）       |
| 限流             | ⚠️ 仅 web_search 有 per-session | 加全局 per-server 调用配额 + 超时保护（已有 30s+5s）                                |
| 流式进度           | ❌ 未做                          | tools/call 长任务（如 reindex）改 SSE 进度回报                                  |



---

## 5. 还能加什么 Skills（具体清单）

### 5.1 补行业包（KB 标称 25 行业，仅 5 包）

优先补高价值、方案差异大的：**能源/电力、交通/智慧物流、教育、文旅、农业、园区/地产、医疗已做**。每个包照 `manufacturing.json` 四段 + playbook 格式即可。

### 5.2 垂直能力包（不按行业，按"动作"）

现有机制只按 intent 行业挂载，**应扩展为"能力包"维度**：

- `skill_ppt`：PPT 12 页生成专属提示词（封面话术/成本页口径/竞品页结构）——让 Agent 口语"做个PPT"时质量更稳。
- `skill_tco`：成本测算报告专属话术（锚定 ROI、折扣口径、量级区间）。
- `skill_battlecard`：竞品对比专属结构（优劣势矩阵、迁移路径、避坑）。
- `skill_execsum`：给老板看的 1 页执行摘要子结构（现 14 章偏全，缺"极简版"）。

### 5.3 把 WorkBuddy 用户级 skills 平移成项目 Skills（强相关）

本机 `~/.workbuddy/skills/` 里有几个可直接转化为 cloudsol 行业/能力包：

- `kb-doc-expansion`（知识库文档扩充）→ 做成"知识库扩写"技能包，喂给 Agent 做 KB 增长。
- `chromadb-embedding-mismatch-diagnosis`（ChromaDB+BGE 嵌入一致性诊断）→ 极贴合本项目（BGE-small-zh + ChromaDB），可固化为运维 Skill。
- `presale-ppt-fullband`（售前 PPT 满版工作流）→ 与项目 PPT 引擎对齐，可作为"PPT 生成"能力包的校验基线。

### 5.4 机制升级（让 Skills 不止于提示词）

当前 `skill_packs.py` 铁律③"不碰工具集"。若要更猛：

- 允许包内声明 `tools:[...]`，命中行业时自动把对应 MCP 工具加进 toolset（如制造包自动挂 `mcp__kb__iot_search`）。
- 允许包内 `few_shot` 示例库，注入到 harness 的 few-shot 段，提升小样本行业准确度。

---

## 6. 优先级建议（先激活，再横扩，后纵深）

1. **P0 激活验证**（1 小时内可上线，零新代码）：开 `AGENT_MCP_CLIENT=1` + `AGENT_SKILL_PACKS=1`，生产跑 50 题核对成本步与行业包是否真生效；若 ECS `.env` 本就缺这俩 flag，则这是"被遗忘的已完工功能"。
2. **P1 横向补包**：补 5~8 个行业包 + 3 个能力包（ppt/tco/battlecard），纯 JSON 工作量。
3. **P2 新 Server**：`mcp_server_kb` / `mcp_server_crm` / `mcp_server_notify`（售前最高频动作工具化）。
4. **P3 机制纵深**：热重载、用户级权限持久化、能力包可挂工具、双向暴露给外部 client（生态卖点）。

---

## 附：待 ECS 复核项（影响结论准确性）

- 本地 `.env` 与 systemd 均无 `AGENT_MCP_CLIENT` / `AGENT_SKILL_PACKS`。若 ECS `/var/www/huawei-cloud-solution-matcher/.env` 也未设，则 §1.5 / §2.4 的"休眠"结论成立，P0 激活即可点亮两套已完工能力。
- 若 ECS 已设 `=1`，则两套已在线，仅需补 §4/§5 的扩展项。

---

## 7. 执行记录（P0 激活 · 2026-09-06 22:50）

### 7.1 已完成的代码/配置改动
| 文件 | 改动 | 作用 |
|---|---|---|
| `.env.example` | `AGENT_MCP_CLIENT=0→1`；新增 `AGENT_SKILL_PACKS=1`；`MCP_SERVERS=` 填为 `[{"command":["python","-m","app.agent.mcp_server_cost_calc"],"label":"cost"}]` | 可入库的运行时配置模板翻为激活态，随 wget 部署即生效（覆盖默认 0） |

> 注：本地 `.env`（含密钥）未动、也不入库；ECS `.env` 需用户手动追加同样三行（见 7.3）。

### 7.2 本地冒烟测试（全绿，无需 ECS/ChromaDB）
1. **cost_calc Server（stdio）**：`initialize`→`tools/list` 暴露 `cost_calc`+`cost_reference_list`；`tools/call cost_calc items=[ecs.s6.large.2×2, obs.standard×500]` 返回 TCO ¥369.50/月、¥4,434/年。
2. **mcp_client ↔ cost Server 握手闭环**：`MCPClient.connect()` 拉起子进程、`list_tools` 得 2 工具、`call_tool("cost_calc", ecs.c6.2xlarge.2×1×12)` 返回 ¥7,680/月、¥92,160/年，`isError=false`。
3. **skill_packs 加载器**：`list_packs`=[finance,government,healthcare,manufacturing,retail]；`match_pack(["制造"])`→manufacturing、`match_pack(["金融"])`→finance、`match_pack(["能源"])`→None（优雅降级）。

> 结论：MCP 协议闭环与技能包匹配逻辑在代码层完全正确；生产未生效纯属开关未开，非代码缺陷。

### 7.3 待用户执行 · ECS 实跑命令（激活 + 验证）
```bash
# ① 在 ECS 上把三行写入生产 .env（用真实 editor 或 tee 追加）
cd /var/www/huawei-cloud-solution-matcher
grep -q '^AGENT_MCP_CLIENT=' .env && sed -i 's/^AGENT_MCP_CLIENT=.*/AGENT_MCP_CLIENT=1/' .env || echo 'AGENT_MCP_CLIENT=1' >> .env
grep -q '^AGENT_SKILL_PACKS=' .env && sed -i 's/^AGENT_SKILL_PACKS=.*/AGENT_SKILL_PACKS=1/' .env || echo 'AGENT_SKILL_PACKS=1' >> .env
grep -q '^MCP_SERVERS=' .env && sed -i 's#^MCP_SERVERS=.*#MCP_SERVERS=[{"command":["python","-m","app.agent.mcp_server_cost_calc"],"label":"cost"}]#' .env || echo 'MCP_SERVERS=[{"command":["python","-m","app.agent.mcp_server_cost_calc"],"label":"cost"}]' >> .env

# ② 重启服务（ExecStartPost 会等 health 200，最多 60s；按铁律⑥先 chown 防 root 属主）
systemctl restart huawei-cloud-api

# ③ 核验激活（health 应返回 v3.0.0 且进程已加载远端工具）
sleep 12
curl -sf http://127.0.0.1:8000/api/health | head -c 200; echo
journalctl -u huawei-cloud-api --since "2 min ago" | grep -E "MCP|skill|远端工具" | tail -20
```
验证点：日志出现 `[MCP] 已加载 2 个远端工具：['mcp__cost__cost_calc', 'mcp__cost__cost_reference_list']` 即激活成功；随后在 Agent 工作台用制造/金融类需求跑一题，终稿应含 TCO 测算且行业话术更准。

### 7.4 下一步（待 P0 生产确认后）
- 若生产验证通过 → 进入 **P1 横向补包**（§5.1/§5.2，纯 JSON，本地可全做后随 wget 部署）。
- 若生产成本步未触发 → 查 `harness._PRICING_RE` 是否命中该需求文案 + journalctl 有无 `MCP 连接失败` 告警。
