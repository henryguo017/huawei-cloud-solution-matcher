# 代码梳理 · MCP 与 Skills 子系统（2026-09-06 基线）

> 范围：围绕「后续还能加什么 MCP 与 Skills」做定向代码梳理。  
> 重点文件：`app/agent/{mcp_server,mcp_client,mcp_server_cost_calc,permission_gate,skill_packs,tools,harness,intent,agent}.py`、`app/config.py`、`data/skill_packs/*`、`api/agent_routes.py`、`deploy/huawei-cloud-api.service`、`.env`。

---

## 0. 一句话结论

MCP 与 Skills 两套机制的**代码骨架已全部就绪、且工程质量很高**（零新依赖、优雅降级、权限网关、命名空间隔离都做了），但**此前生产处于"休眠态"**——因为 `AGENT_MCP_CLIENT` 与 `AGENT_SKILL_PACKS` 两个开关在 `.env` 与 systemd 里均未置 1，按 `config.py` 默认值走 0。

**第一步不是"加新东西"，而是先激活 + 验证已有的 cost_calc MCP 与行业技能包，再谈扩展。**（现共 15 包：原 5 + P1-A 新增 6 行业 + P1-B 新增 4 能力；已就绪、未部署生产。）

> **【P0 状态 · 2026-09-06 22:58 已闭环 ✅】** 生产验证通过：
>
> - `.env` 三行写入 ECS 并 restart；`venv/bin/python -c "import app.config"` 实测 `AGENT_MCP_CLIENT=1` / `AGENT_SKILL_PACKS=1` / `MCP_SERVERS=[{cost}]` 全 live。
> - 生产 Agent 首调触发 MCP 懒加载，日志确认：`[MCP] 已加载 2 个远端工具：['mcp__cost__cost_calc', 'mcp__cost__cost_reference_list']`。
> - 本地三项冒烟此前已全绿（cost Server 出 TCO / mcp_client 握手闭环 / skill_packs 命中制造金融）。
> - **历史纠错**：此前提到的"cost_calc 已激活"记忆不准——实际此前因开关默认 0 而休眠；本次才是真激活。详见 §7.5。

**【P1-A 状态 · 2026-09-06 已完成（本地，待部署） ✅】** 横向补 6 个行业包：
> - `data/skill_packs/` 新增 `energy`(能源/电力) / `transportation`(交通/智慧物流) / `education`(教育) / `tourism`(文旅) / `agriculture`(农业) / `park`(园区/地产) 共 6 个，格式同 `manufacturing.json`（4 段 + 7 条 playbook）。
> - 本地加载器冒烟全绿：`list_packs`=11（5 原 + 6 新）；`match_pack` 按行业关键词精准挂载（能源/交通/教育/文旅/农业/园区均命中）；6 包 JSON 结构校验通过（industry 非空、4 段、7 条）。
> - **未部署生产**：纯 JSON 随下次 wget 部署即生效（`AGENT_SKILL_PACKS=1` 已在 P0 打开）。详见 §7.6。
> - **能力包（ppt/tco/battlecard/execsum）P1-B 已完成**：已扩挂载钩子（§5.2），现共 15 包（11 行业 + 4 能力），本地全绿、待部署。详见 §7.7。

**【P1-B 状态 · 2026-09-06 已完成（本地，待部署） ✅】** 挂载钩子 + 4 个能力包 + 行业别名覆盖：
> - `skill_packs.py`：新增 `kind` / `CAPABILITY_KIND`；`match_pack` 显式跳过能力包（两维度正交）；新增 `match_capability(intent, text)` 按包内 `triggers`（`intents` + `keywords`，AND 语义）匹配；提示词头区分「行业技能包 / 能力技能包」。
> - `harness.py`：新增 `_active_capability` 槽位（与行业包**可同时挂载**），挂载 + 角色块 + 终稿块三处注入；门控排除 `greeting`/`account`。
> - `agent_workspace.js`：思考流提示区分「已挂载能力包 / 已挂载行业技能包」（两处），版本号升 `v=20260906c`。
> - `intent.py`：`_INDUSTRY_KEYWORDS` 追加 14 个高频二级别名（电力/电网/地产/高校/港口/养殖等）；**50 题路由回归 0 变化**。
> - 新增 4 个能力包：`capability_ppt`（export + PPT 词）/ `capability_tco`（成本词，不限意图）/ `capability_battlecard`（competitor 意图）/ `capability_execsum`（solution/competitor + 摘要词）。

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

### 2.2 已有 15 个包（`data/skill_packs/`）：11 个行业包（5 原 + P1-A 新增 6）+ 4 个能力包（P1-B）

| slug            | industry | 内容规模                                                   |
| --------------- | -------- | ------------------------------------------------------ |
| `manufacturing` | 制造       | demand/architect/reviewer/synthesize 四段 + 7 条 playbook |
| `finance`       | 金融       | 同上结构                                                   |
| `government`    | 政务       | 同上结构                                                   |
| `healthcare`    | 医疗       | 同上结构                                                   |
| `retail`        | 零售       | 同上结构                                                   |
| `energy`        | 能源       | P1-A 新增：发电/电网/综合能源，生产控制大区物理隔离 + 新能源功率预测 + 集团驾驶舱 |
| `transportation`| 交通       | P1-A 新增：智慧交通/物流/港口，视频AI + 车路协同 + WMS弹性 + 断网闭环 |
| `education`     | 教育       | P1-A 新增：高校/K12/职校，科研算力(昇腾/HPC) + 智慧校园 + 信创四层 |
| `tourism`       | 文旅       | P1-A 新增：景区/文博/文旅局，客流热力图 + 智慧导览 + 闸机集成 + 黄金周弹性 |
| `agriculture`   | 农业       | P1-A 新增：种植/养殖/监管，遥感病虫害 + 边缘环控 + BCS溯源 |
| `park`          | 园区       | P1-A 新增：产业/商业/住宅/工业园，IOC一图统管 + 能耗节能 + 安全生产AI |

包格式 v1：只含 `prompt_template`（4 段角色提示）+ `playbook`（终稿要点）。**无工具扩展、无示例库、无检索增强**。

**另有 4 个能力包（P1-B，按「动作」维度挂载，与行业包正交、可同时生效）**

| slug | kind | industry | triggers（intents + keywords，AND） | 内容要点 |
|---|---|---|---|---|
| `capability_ppt` | capability | PPT生成 | `export` + PPT/pptx/幻灯片/演示文稿 | 12 页序列、每页结论句、金额去重、华为红规范 |
| `capability_tco` | capability | 成本测算 | 不限意图 + TCO/成本/报价/预算/多少钱/ROI 等 11 词 | 金额必须 cost_calc 实算、三层数字、隐性成本、有效期口径 |
| `capability_battlecard` | capability | 竞品对比 | `competitor` | 矩阵打分、优势给证据、劣势给对策、四阶段迁移+回退 |
| `capability_execsum` | capability | 执行摘要 | `solution`/`competitor` + 摘要/一页纸/老板/高层 等 9 词 | 一页纸、结论含金额工期、三价值主张、风险带对策 |

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

### 5.1 补行业包（KB 标称 25 行业，P1-A 补 6 个 → 共 11 包）✅

**【P1-A 已完成 · 2026-09-06，纯 JSON，本地验证通过】** 新增 6 个高价值、方案差异大的行业包，格式严格照 `manufacturing.json`（四段角色提示 + 7 条 playbook）：

| slug            | industry（=关键词） | 覆盖别名（部分）                          |
| --------------- | ---------------- | ------------------------------------- |
| `energy`        | 能源               | 电力/电网/电厂/光伏/风电/储能/新能源          |
| `transportation`| 交通               | 交投/物流/仓储/智慧物流/港口/车路协同          |
| `education`     | 教育               | 智慧校园/高校/学校/K12/教育局/科研            |
| `tourism`       | 文旅               | 景区/旅游/博物馆/文旅局/乐园                  |
| `agriculture`   | 农业               | 农场/智慧农业/养殖/种植/高标准农田/农业农村局    |
| `park`          | 园区               | 工业园区/地产/房地产/写字楼/商业综合体/物业      |

> **挂载覆盖度（P1-B 已解决 ✅）**：`match_pack` 只匹配 `intent._INDUSTRY_KEYWORDS` 命中的词，二级别名（电力/电网/地产/高校）原先不在表里、用户不带主词时挂不上。P1-B 已在 `intent.py` 的 `_INDUSTRY_KEYWORDS` 追加 14 个高频二级别名：**电力、电网、电厂、风电、储能、地产、房地产、高校、学校、旅游、智慧交通、港口、养殖、种植**。实测 10 条别名查询全部正确挂载（电网/电力/风电/储能→energy，地产/房地产→park，高校/学校→education，港口→transportation，养殖→agriculture），**50 题路由回归 0 变化**（该表影响意图分类，故必须跑全量路由回归）。

**剩余缺口**：KB 标称 25 行业，现 11 包覆盖 11 个主行业；其余如游戏/出海/汽车/矿山/钢铁/化工/冶金/生物医药等已有别名兜底（挂在制造/金融/医疗等包），是否单独立包视价值再定。

### 5.2 垂直能力包（不按行业，按"动作"）✅ P1-B 已完成

原机制只按 intent 行业挂载，能力包是"动作"维度、根本挂不上——**P1-B 已扩展为「能力包」维度**，与行业包正交、可同时生效：

| 能力包 | 用途 | 触发条件（写死在包内 `triggers`） |
|---|---|---|
| `capability_ppt` | PPT 12 页生成专属提示词（每页结论句/成本页口径/竞品页结构）——Agent 口语"做个PPT"时质量更稳 | intent=`export` + 原文含 PPT/幻灯片 |
| `capability_tco` | 成本测算报告专属话术（金额必须 cost_calc 实算、ROI、折扣口径、量级区间） | 不限意图 + 原文含 TCO/成本/报价/ROI 等 11 词 |
| `capability_battlecard` | 竞品对比专属结构（优劣势矩阵、迁移路径、避坑清单） | intent=`competitor` |
| `capability_execsum` | 给老板看的 1 页执行摘要子结构（现 14 章偏全，缺"极简版"） | intent=`solution`/`competitor` + 含摘要/一页纸/老板 等 9 词 |

**挂载钩子设计（关键）**：
- 包内新增 `"kind": "capability"`（缺省即行业包 → 11 个老包零改动向后兼容）与 `"triggers": {"intents": [...], "keywords": [...]}`。
- `match_capability(intent, text)`：AND 语义——**声明了的维度必须命中，未声明的维度不限制**；两者都空则该包永不生效（防空 triggers 误挂全部会话）。**纯数据驱动，以后新增能力包只写 JSON、不改代码**。
- `match_pack` 显式跳过 `kind=capability`，两维度互不干扰。
- 单槽位：一次只挂 1 个能力包（按 slug 排序取首个命中）；与主行业包**可叠加**。重叠场景罕见（对比+cost 时取 battlecard），已是可接受取舍。

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
2. **P1 横向补包** ✅ 已完成（本地绿，待部署）：行业包 +6、能力包 +4（挂载钩子已扩，`kind`/`triggers` 纯数据驱动）、行业别名 +14（50 题路由 0 变化）。现共 15 包（11 行业 + 4 能力）。
3. **P2 新 Server**：`mcp_server_kb` / `mcp_server_crm` / `mcp_server_notify`（售前最高频动作工具化）。
4. **P3 机制纵深**：热重载、用户级权限持久化、能力包可挂工具、双向暴露给外部 client（生态卖点）。

---

## 附：待 ECS 复核项（影响结论准确性）

- 本地 `.env` 与 systemd 均无 `AGENT_MCP_CLIENT` / `AGENT_SKILL_PACKS`。若 ECS `/var/www/huawei-cloud-solution-matcher/.env` 也未设，则 §1.5 / §2.4 的"休眠"结论成立，P0 激活即可点亮两套已完工能力。
- 若 ECS 已设 `=1`，则两套已在线，仅需补 §4/§5 的扩展项。

---

## 7. 执行记录（P0 激活 · 2026-09-06 22:50）

### 7.1 已完成的代码/配置改动

| 文件             | 改动                                                                                                                                                | 作用                                    |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| `.env.example` | `AGENT_MCP_CLIENT=0→1`；新增 `AGENT_SKILL_PACKS=1`；`MCP_SERVERS=` 填为 `[{"command":["python","-m","app.agent.mcp_server_cost_calc"],"label":"cost"}]` | 可入库的运行时配置模板翻为激活态，随 wget 部署即生效（覆盖默认 0） |

> 注：本地 `.env`（含密钥）未动、也不入库；ECS `.env` 需用户手动追加同样三行（见 7.3）。

### 7.2 本地冒烟测试（全绿，无需 ECS/ChromaDB）

1. **cost_calc Server（stdio）**：`initialize`→`tools/list` 暴露 `cost_calc`+`cost_reference_list`；`tools/call cost_calc items=[ecs.s6.large.2×2, obs.standard×500]` 返回 TCO ¥369.50/月、¥4,434/年。
2. **mcp_client ↔ cost Server 握手闭环**：`MCPClient.connect()` 拉起子进程、`list_tools` 得 2 工具、`call_tool("cost_calc", ecs.c6.2xlarge.2×1×12)` 返回 ¥7,680/月、¥92,160/年，`isError=false`。
3. **skill_packs 加载器**：`list_packs`=[finance,government,healthcare,manufacturing,retail]；`match_pack(["制造"])`→manufacturing、`match_pack(["金融"])`→finance、`match_pack(["能源"])`→None（优雅降级）。

> 结论：MCP 协议闭环与技能包匹配逻辑在代码层完全正确；生产未生效纯属开关未开，非代码缺陷。


### 7.3 待用户执行 · ECS 实跑命令（激活 + 验证）

> ⚠️ **易错点（2026-09-06 实测踩坑）**：`AGENT_MCP_CLIENT=1` 这类单独成行的写法在 bash 里只是给**当前 shell 设临时变量**，退出即失效，**不会写进 `.env`**；`MCP_SERVERS=[...]` 那行还会被 bash 当 `[` 测试命令解析报错。务必用下面的 `grep+sed/echo >>` 命令把三行**写进文件**，不要直接粘贴那三行当命令跑。

```bash
# ① 在 ECS 上把三行写入生产 .env（grep 命中则 sed 替换，未命中则 echo 追加）
cd /var/www/huawei-cloud-solution-matcher
grep -q '^AGENT_MCP_CLIENT=' .env && sed -i 's/^AGENT_MCP_CLIENT=.*/AGENT_MCP_CLIENT=1/' .env || echo 'AGENT_MCP_CLIENT=1' >> .env
grep -q '^AGENT_SKILL_PACKS=' .env && sed -i 's/^AGENT_SKILL_PACKS=.*/AGENT_SKILL_PACKS=1/' .env || echo 'AGENT_SKILL_PACKS=1' >> .env
grep -q '^MCP_SERVERS=' .env && sed -i 's#^MCP_SERVERS=.*#MCP_SERVERS=[{"command":["python","-m","app.agent.mcp_server_cost_calc"],"label":"cost"}]#' .env || echo 'MCP_SERVERS=[{"command":["python","-m","app.agent.mcp_server_cost_calc"],"label":"cost"}]' >> .env

# ② 确认已写入（应输出三行非注释值）
grep -E '^(AGENT_MCP_CLIENT|AGENT_SKILL_PACKS|MCP_SERVERS)=' .env

# ③ 重启服务（ExecStartPost 会等 health 200，最多 60s；按铁律⑥先 chown 防 root 属主）
systemctl restart huawei-cloud-api

# ④ 核验激活（health 应返回 v3.0.0 且进程已加载远端工具）
sleep 12
curl -sf http://127.0.0.1:8000/api/health | head -c 200; echo
journalctl -u huawei-cloud-api --since "2 min ago" | grep -E "MCP|远端工具" | tail -20
```

验证点：日志出现 `[MCP] 已加载 2 个远端工具：['mcp__cost__cost_calc', 'mcp__cost__cost_reference_list']` 即激活成功；随后在 Agent 工作台用制造/金融类需求跑一题，终稿应含 TCO 测算且行业话术更准。

### 7.4 下一步（待 P0 生产确认后）

- 若生产验证通过 → 进入 **P1 横向补包**（§5.1/§5.2，纯 JSON，本地可全做后随 wget 部署）。
- 若生产成本步未触发 → 查 `harness._PRICING_RE` 是否命中该需求文案 + journalctl 有无 `MCP 连接失败` 告警。


### 7.5 P0 验证结果（2026-09-06 22:58 · 已闭环 ✅）

**① 配置实测（ECS 进程解析值）**

```
AGENT_MCP_CLIENT = 1
AGENT_SKILL_PACKS = 1
MCP_SERVERS = [{"command":["python","-m","app.agent.mcp_server_cost_calc"],"label":"cost"}]
```

> 注：早期用 `cat /proc/$PID/environ` 查为空是**假阴性**——Linux 的 `/proc/PID/environ` 只保留 exec 启动时的环境快照，不反映 Python `os.environ` 运行期改动（load_dotenv 走的后者）。改用 `venv/bin/python -c "import app.config"` 才是正确的实测方式。

**② 功能实测（Agent 工作台发制造类需求后 journalctl）**

```
[MCP] 正在连接 Server「cost」: ['python', '-m', 'app.agent.mcp_server_cost_calc']
Registered tool: mcp__cost__cost_calc
[MCP] 已注册远端工具: mcp__cost__cost_calc
[MCP] 已注册远端工具: mcp__cost__cost_reference_list
[MCP] 共注册 2 个远端工具
[MCP] 已加载 2 个远端工具：['mcp__cost__cost_calc', 'mcp__cost__cost_reference_list']
```

**结论**：cost_calc MCP 已正式接入生产 Agent 工具集（且 `api/agent_routes.py` 中本就是 `allow` 免确认）。P0 完成。

**③ 实跑踩坑备忘（给未来参考）**

- 那三行配置**必须写进 `.env` 文件**（grep+sed/echo >>），绝不能当 shell 命令裸跑（裸跑只是给当前 shell 设临时变量，退出即失效，且 `MCP_SERVERS=[...]` 会被 bash 当 `[` 测试命令解析报错）。
- 重启后 health 偶发空响应是模型加载窗口（~16s）竞态，多等几秒再探即 HTTP 200；`systemctl status` 看 `active (running)` + `Application startup complete` 才是真起稳。
- 验证 MCP 是否加载**不能看服务启动日志**，要看**首次 Agent 调用后**的 journalctl（MCP 是懒加载，不在 startup）。

### 7.6 P1-A 执行记录（2026-09-06 · 行业包补 6 个）

**① 新增文件（均 `data/skill_packs/`）**
| 文件 | industry | 作用 |
|---|---|---|
| `energy.json` | 能源 | 发电/电网/综合能源；生产控制大区物理隔离 + 新能源功率预测（盘古气象大模型）+ 集团驾驶舱跨站对标 |
| `transportation.json` | 交通 | 智慧交通/智慧物流/港口；视频AI + 车路协同 + WMS 弹性 + 断网闭环 |
| `education.json` | 教育 | 高校/K12/职校；科研算力(昇腾/HPC) + 智慧校园 + 信创四层 + 平安校园 |
| `tourism.json` | 文旅 | 景区/文博/文旅局；客流热力图 + 智慧导览 + 闸机集成 + 黄金周弹性 |
| `agriculture.json` | 农业 | 种植/养殖/监管；遥感病虫害 + 边缘环控断网续传 + BCS 溯源 |
| `park.json` | 园区 | 产业/商业/住宅/工业园；IOC 一图统管 + 能耗节能 + 安全生产视频AI + 招商 CDP |

**② 本地加载器冒烟（全绿，无需 ECS/ChromaDB）**
- `list_packs()` → 11 个（原 5 + 新 6）：agriculture / education / energy / finance / government / healthcare / manufacturing / park / retail / tourism / transportation。
- `match_pack(["能源"])`→energy、`["交通"]`→transportation、`["教育"]`→education、`["文旅"]`→tourism、`["农业"]`→agriculture、`["园区"]`→park；原 5 包仍精准挂载。
- 6 包 JSON 结构校验：industry 非空 + 4 段（demand/architect/reviewer/synthesize）均有内容 + playbook 7 条，全部通过。
- alias 级匹配在加载器层验证正确（电力/电网→energy，地产/房地产→park，高校→education）；**生产实际挂载依赖 `intent._INDUSTRY_KEYWORDS` 是否含该词**（见 §5.1 提示）。

**③ 部署说明**
- 纯 JSON，随下次 `wget main zip → cp → restart` 即生效（`AGENT_SKILL_PACKS=1` 已在 P0 打开，无需改 `.env`）。
- 按铁律，本次仅新增 JSON 资源文件、KB 文档/DB schema 无变更，可随常规部署；建议生产跑 50 题时顺带核对 6 个新行业包是否命中。

**④ 下一步（待确认）**
- 能力包（ppt/tco/battlecard/execsum）：当前挂载机制不支持"动作"维度，需扩 `skill_packs.py` + `harness.py` 的挂载钩子（小代码改动）。方案待你拍板（见正文提问）。
- 二级别名覆盖：在 `intent.py` `_INDUSTRY_KEYWORDS` 追加高频别名（低危），待你确认。

### 7.7 P1-B 执行记录（2026-09-06 · 能力包挂载钩子 + 4 能力包 + 行业别名）

**① 代码改动（4 文件）**
| 文件 | 改动 | 作用 |
|---|---|---|
| `app/agent/skill_packs.py` | 新增 `CAPABILITY_KIND`；`match_pack` 显式跳过能力包；新增 `match_capability(intent, text)`；`pack_prompt_block` 头按 kind 区分 | 挂载机制从"只有行业维度"扩为"行业 + 动作"两维度正交；能力包触发条件数据驱动，加包不改代码 |
| `app/agent/harness.py` | 新增 `_active_capability` 槽位（复位/挂载/角色块/终稿块四处）；挂载门控排除 `greeting`/`account` | 能力包与行业包**可同时挂载**；角色提示与终稿口径均叠加注入 |
| `frontend/js/agent_workspace.js` | 思考流 `skill_pack` 事件按 `ev.kind` 显示「已挂载能力包 / 已挂载行业技能包」（两处） | 前端不把能力包误显示成行业包 |
| `app/agent/intent.py` | `_INDUSTRY_KEYWORDS` +14 二级别名（电力/电网/电厂/风电/储能/地产/房地产/高校/学校/旅游/智慧交通/港口/养殖/种植） | 用户只说别名不带主词时也能挂载，方案覆盖度拉满 |

**② 新增 4 个能力包（`data/skill_packs/capability_*.json`）**
| 包 | triggers（AND 语义） | 关键口径 |
|---|---|---|
| `capability_ppt` | `export` + PPT/pptx/幻灯片/演示文稿 | 12 页序列、每页结论句、成本页金额去重、缺项标占位禁编造 |
| `capability_tco` | 不限意图 + TCO/成本/报价/预算/多少钱/ROI 等 11 词 | 金额必须 cost_calc 实算、月度/年度/三年三层、隐性成本、有效期口径 |
| `capability_battlecard` | `competitor` | 矩阵逐维打分、优势给证据、劣势给对策、四阶段迁移带回退 |
| `capability_execsum` | `solution`/`competitor` + 摘要/一页纸/老板/高层 等 9 词 | 一页纸、结论含金额工期、三价值主张、风险带对策 |

**③ 本地验证（全绿）**
- `list_packs`=15（11 行业 + 4 能力）；`match_pack` 11 个主行业精准命中，且**直接拿能力包 industry 当行业词查询全部返回 None**（隔离生效，无串挂）。
- `match_capability` 8 条用例全对：`(export,"给我生成一个PPT")`→ppt、`(export,"做个ppt")`→ppt（大小写不敏感）、`(export,"导出为word文档")`→None、`(solution,"这套方案成本多少钱")`→tco、`(competitor,"对比一下阿里云和华为云")`→battlecard、`(solution,"给老板看的执行摘要")`→execsum、`(solution,"普通的园区上云方案")`→None、`(export,"导出PPT")`→ppt。
- 4 包结构校验：`kind=capability`、`industry` 非空、triggers 非空、4 段、7 条 playbook 全通过。
- 提示词头正确区分：`【行业技能包 · 能源】` vs `【能力技能包 · PPT生成】`。
- 别名端到端 10 条全对：电网/电力/风电/储能→energy，地产/房地产→park，高校/学校→education，港口→transportation，养殖→agriculture。
- **回归**：50 题路由 0 变化（`tests/agent_50q.py` 全量 `classify_intent` 比对）；`py_compile` 三个 py 文件 OK；`node --check` agent_workspace.js OK。

**④ 部署说明**
- 本次**含 Python 改动**（skill_packs/harness/intent），必须 `restart` 生效，不能只热更前端；前端 `agent_workspace.js` 版本已升 `v=20260906c`。
- 按铁律：非 KB 文档/DB schema 变更，走标准 `wget main zip → cp -r → restart`；restart 前 `chown -R www-data:www-data data api.log*`（铁律⑥）。
- 部署后建议抽查：Agent 说「给我生成一个PPT」→ 思考流出现「已挂载能力包：PPT生成」；说「电网公司上云」→ 「已挂载行业技能包：能源」。

**⑤ 已知取舍**
- 能力包**单槽位**：一次只挂 1 个（按 slug 排序取首个命中）。重叠场景（如竞品对比+成本）取 `capability_battlecard`。真实重叠罕见，若后续需要多能力叠加，把 `_active_capability` 改成列表即可。
- 能力包只注入提示词（与行业包同铁律），不改工具集；`capability_tco` 里"金额必须 cost_calc 实算"是**口径约束**，真正强制调工具仍靠 harness 既有的 `_force_cost_step` 确定性逻辑（提示词无法保证工具调用，这点已在 §3 记录）。
