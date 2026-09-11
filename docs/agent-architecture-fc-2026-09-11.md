# Agent 模式重构架构设计：从文本协议编排到真正的 Agent Runtime

> 2026-09-11 ｜ 状态：**待评审（未开工）** ｜ 前置实测：`.workbuddy/Temp/fc_spike.py`、`fc_thinking_probe.py`
> 目标：Agent 工作台模式的执行引擎 = 原生 function calling 的 **model-in-the-loop**
> 铁律：经典模式（`/api/match` + `script.js`/`style.css`）字节级不动；产品层资产全复用；老两阶段管线降为兜底

---

## 0. 判据：什么才算"真 Agent"

先说判据，否则"真/假"会变成口水。四条硬判据（前三条为 Anthropic 标准，C4 为本项目补充）：

| # | 判据 | 现状 | 目标 |
|---|---|---|---|
| **C1** | 控制流在模型：调用哪些工具、几次、何时停 → 由模型决定 | 代码决定（`PLAN_STEP_TOOL_MAP` 硬编码每步工具集） | 模型决定（`tool_calls`；无 tool_calls 即终止） |
| **C2** | 工具接口结构化：机器可读 schema，非文本约定 | 文本 `Action/Action Input` + 正则抠 JSON | OpenAI function schema，原生结构化返回 |
| **C3** | 失败恢复在模型：错误 → 模型自省调整 | 代码补丁（`_force_cost_step`/`_force_crm_step`/`_reflexion_replan`） | 错误作为 observation 回填，模型决策 |
| **C4** | **计划所有权在模型**：计划可被模型随时改写 | planner 一次性生成 → 映射表锁死步序 | `update_plan` 工具，模型自持并改写计划 |

**C4 是最能区分真假的一条**，也是最容易被忽略的：只要"计划由代码生成一次、之后不可改"，那就是 workflow，无论工具调用多花哨。

**当前判定**：C1 不满足、C2 不满足、C3 不满足、C4 不满足 → 0/4，确认为 workflow。

---

## 1. 架构原则：边界画在哪

> **任务决策归模型；不可委托的确定性、安全与质量归宿主。**

### 1.1 宿主职责白名单（只做这五类，绝不替模型做任务决策）

| 职责 | 为什么不可委托 | 现有资产（复用） |
|---|---|---|
| ① 能力供给 | 工具/MCP/沙箱是通向外部世界的唯一接口 | `ToolRegistry`、`dyn_*`、`mcp__*` |
| ② 安全与预算 | 越权、注入、烧钱、跑不完是硬边界 | `permission_gate`、`sandbox`、新增预算守卫 |
| ③ 上下文管理 | 模型窗口有限，必须裁剪/压缩 | `memory_profiles`、`skill_packs` |
| ④ **不可委托计算** | **金额/数量必须程序化，LLM 不碰钱** | `_program_cost_table` / `_synth_cost_table` |
| ⑤ 交付质量门 | 终稿是产品，不能交给模型自评 | `_self_check_gate`、统一增强管线 |

### 1.2 关键澄清（防误读）

真 Agent ≠ 模型干所有事。Claude Code 有权限层、Manus 有 sandbox、Devin 有 VM —— **宿主边界是行业标配，不是"没 agent 化"的残留**。

判据只有一条：**宿主是否替模型做任务决策**。

| 问题 | 属于 | 归属 |
|---|---|---|
| "该不该调 cost_calc" | 任务决策 | **模型** |
| "金额算得对不对" | 不可委托计算 | **宿主** |
| "要不要重试这个失败的工具" | 任务决策 | **模型** |
| "这个工具用户允许执行吗" | 安全 | **宿主** |
| "这步做完没做完" | 任务决策 | **模型**（现状是 `STEP_DONE:` 文本，最典型的假） |

---

## 2. 目标架构

### 2.1 分层视图

```
┌──────────────────────────────────────────────────────────────┐
│  API 层  api/agent_routes.py                                 │
│  SSE 事件契约（不变）：plan/thought/tool_start/tool_end/     │
│  delta/final/result/self_check/permission_request/…          │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  Agent Runtime（新增 app/agent/runtime/）                     │
│                                                              │
│   runner.py    ── 主循环状态机（本文 §3.1）                   │
│   schema.py    ── Tool → function schema；消息规范化          │
│   guards.py    ── 迭代/预算/时长守卫（只出建议 + 熔断）        │
│   todo.py      ── update_plan 工具（模型自持计划，C4）         │
│   context.py   ── 上下文装配 + 压缩（新增能力）                │
│   verify.py    ── 完成态核验（治"已保存"幻觉）                 │
│   events.py    ── trace → SSE 事件映射（守住前端契约）         │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  能力层（一行不改，全部复用）                                  │
│  10 内置工具 · dyn_* · mcp__* · 权限闸门 · 沙箱                │
│  长程记忆/情景记忆/playbook · 行业+能力技能包                  │
│  统一增强管线 · 自检 Gate · 导出链路                           │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  Fallback：老两阶段文本管线（harness._plan_and_execute）       │
│  仅当 runtime 异常/超预算/无产出时接管，保证"最差也是今天"      │
└──────────────────────────────────────────────────────────────┘
```

### 2.2 与现有代码的关系

| 现有 | 处理后 |
|---|---|
| `harness.run()` | 变为**路由层**：意图预闸门 → runtime / fallback |
| `harness._plan_and_execute`、`_execute_step` | **保留为 fallback**，不删（生产兜底） |
| `harness._parse_react_output`、`_parse_react_actions` | fallback 专用，主路径不再调用 |
| `harness._force_cost_step` / `_force_crm_step` / `_force_kb_stats_step` | 主路径退役；**保留代码**供 fallback 与"轻量保险丝" |
| `_self_check_gate` / `_finalize_answer` / `_maybe_save_episode` / `_execute_tool` / `_gate_tool` | **直接复用**，是宿主职责的落点 |
| `PLAN_STEP_TOOL_MAP`、`_tool_to_plan_index` | 仅 fallback 使用 |
| 前端 `agent_workspace.js` | 只改默认开关与按钮文案 |

---

## 3. 运行时设计

### 3.1 主循环状态机（核心）

```
ASSEMBLE
  ├ system = 角色 + 能力政策 + 工具使用政策 + 输出契约
  │          + 长程记忆块 + 技能包块（行业/能力）+ 客户上下文
  ├ messages = [system, user]
  └ 注册工具 schema（全部可用工具，不再按步切分）

MODEL_TURN  ←──────────────────────────────┐
  ├ resp = chat_with_tools(messages, tools,  │
  │        thinking = 决策轮 enabled)        │
  ├ reasoning_content → emit thought         │  ← 真实推理上屏
  ├ 若 resp.tool_calls 非空 → TOOLS          │
  └ 若为空 → FINAL（resp.content 即草稿）    │
                                             │
TOOLS                                        │
  ├ 按策略分流：只读 → gather 并发（≤MAX）   │
  │            高风险 → 串行（等权限弹窗）   │
  ├ 每个调用：json 解析（无文本抠取）        │
  │           → 权限闸门 allow/ask/deny      │
  │           → 执行 → 结果封装为 tool 消息  │
  ├ 错误 → 原样回填为 observation（C3）      │
  └ guards：轮次/预算/时长 → 超限时注入      │
              "预算将尽，请收口" 系统消息，  │
              由模型决定；硬上限才熔断 ──────┘

FINAL
  ├ verify：完成态核验（§3.8）
  ├ self_check_gate（宿主质量门，可配置为仅 warn 不重写）
  ├ 流式交付（决策 D1）
  ├ episode 落库（学习闭环）
  └ emit final + result
```

**终止条件只有两个**：模型不再请求工具（正常）；宿主硬上限熔断（异常）。**没有任何"步数到了就算完"的逻辑**——那是 workflow 思维。

### 3.2 上下文装配（`context.py`）

```
system 块组装顺序（稳定前缀在前，便于 prompt cache 命中）：
  1. 角色与身份（复用 REACT_SYSTEM_PROMPT_BASE 的自我认知段，去掉文本协议部分）
  2. 能力政策（工具使用政策、何时该澄清、何时该终止）
  3. 输出契约（终稿结构要求；来源标注要求）
  4. 行业/能力技能包块（pack_prompt_block + pack_synthesize_block）
  5. 长程记忆块（build_memory_context + build_profile_context）
  6. 客户上下文（client_context）
  7. 宿主核验事实块（§3.8，若有写操作）
```

**消息管理**：
- `messages` 累积 assistant(tool_calls) + tool(observation) 对
- 单条 observation 截断上限（默认 6000 字符）——防单次检索撑爆窗口
- 系统块 + 工具 schema 作为**稳定前缀**保持不变 → prompt cache 命中（实测已命中 256 tokens）

### 3.3 工具接口层（`schema.py`）

| 能力 | 实现 | 说明 |
|---|---|---|
| Tool → schema | `{"type":"function","function":{"name","description","parameters"}}`，`parameters` 就是 `Tool.parameters` | 零改造，形状本就一致 |
| 参数解析 | `json.loads(tc.function.arguments)` | **不再有正则/括号平衡提取** |
| 未知工具 | 返回 `{"status":"error","message":"unknown tool","available":[...]}` 作为 observation | 模型自行修正，不抛异常 |
| 参数漂移 | 复用 `Tool._normalize_args`（别名吸收 + VAR_KEYWORD 跳过） | 一行不改 |
| 动态工具 | `register_dynamic_tool` 元工具 + `dyn_*` 即时进 schema | 每轮重算 schema，注册后下一轮即可见 |

**并行策略**：实测模型一次响应天然返回多个 `tool_calls`（flash/pro 均 2 个，pro 的 reasoning 原文："我需要并行调用两个工具"）。因此：
- 只读工具集 {`search_kb`,`search_competitor`,`web_search`,`web_extract`,`mcp__crm__*list*`,`mcp__cost__cost_calc`} → `asyncio.gather`，上限 `MAX_PARALLEL`
- 高风险工具（`generate_doc`/`read_customer_file`/`run_python`/mcp 写类）→ 串行，逐个走权限弹窗

### 3.4 计划所有权：`update_plan` 工具（落实 C4）

现状：`_generate_plan` 生成一次 → `PLAN_STEP_TOOL_MAP` 把步与工具锁死 → 计划不可改。

新设计：**计划成为模型可调用的工具**，模型自己维护 todo 列表。

```
Tool: update_plan
参数: {
  "items": [{"step": "分析需求", "status": "done|in_progress|pending", "note": "可选"}],
  "reason": "为什么调整计划"
}
副作用: 仅推送 SSE `plan` 事件 + 记录 trace，不约束任何执行
```

- 系统提示中要求模型：**开工前先 publish 一次计划；计划变化时更新**
- 前端 Plan 面板继续渲染（事件契约不变），但语义从"执行约束"变为"模型意图的可见化"
- **验收点**：跑一次任务，统计 `update_plan` 调用次数与实际工具序列是否**不一致**——不一致恰恰证明计划不再锁死执行（这是 C4 达成的证据，不是 bug）

### 3.5 失败恢复归模型（落实 C3）

| 机制 | 归属 | 说明 |
|---|---|---|
| 工具报错回填 | 宿主 | `{"status":"error", ...}` 作为 tool 消息 |
| 重试/换参/换工具/放弃 | **模型** | 不再有代码替它重试 |
| 反复失败 | 宿主只"提示" | 连续 N 次同类失败 → 注入系统消息（advisory），决策仍归模型 |
| 预算/超时 | 宿主熔断 | 只做硬边界保护，不做任务决策 |
| 反思重规划 | 降级 | `_reflexion_replan` 仅 fallback 使用 |

### 3.6 交付质量门（宿主职责⑤，但需重新定位）

现状：`_self_check_gate` 会**重写**终稿（二次合成）→ 这等于把终稿控制权又收回代码手里，与目标矛盾。

**决策 D1（需拍板）**：终稿归属
- **A 现状延续**：模型草稿 → 自检重写 → 统一增强重写 → 流式交付。质量稳，但双重生成、成本翻倍、模型的自主结构可能被模板回拉。
- **B 真 Agent 优先（推荐）**：模型的最终消息**就是终稿**，直接流式交付；宿主只做两件机械事：① 来源标注后处理（`[资料N]` → 文件名映射）② 自检 Gate 降级为"仅告警，不重写"。
- 缓解措施（B 的配套）：把"结构要求 / 来源标注 / 防幻觉"写进 system 输出契约；`generate_doc` 导出仍走原链路（导出模板是产品要求，与内容自主不冲突）。

### 3.7 上下文压缩（新增能力，`context.py`）

FC 循环会让 `messages` 无限增长——**这是老管线不需要、新架构必须解决的**问题。

```
触发：估算 token > 窗口 × AGENT_COMPACT_AT（默认 0.75）
策略：把最早的 K 轮（assistant tool_calls + tool 结果）交给 LLM 摘要为
     一条「阶段性工作记忆」system 消息（保留：已得结论 / 关键数据 / 未完成事项），
     原文丢弃。保留最近 M 轮原文。
约束：压缩不改变 system 稳定前缀（保 cache）；压缩事件记 trace，可审计。
```

### 3.8 完成态核验（新增，`verify.py`）——治"已保存"幻觉

这是本项目踩过的真实坑（模型声称"已存档"但未落库）。架构级解法：

```
1. 宿主记录：本轮真实执行的**写操作**清单 + 执行结果状态
   （mcp__crm__client_add/update、generate_doc 等）
2. 交付前：把"宿主核验事实"块注入终稿生成/核验提示
   「本次真实执行的操作：[…]；你**不得**声称执行过列表之外的操作；
     列表为空时，如需承诺须表述为『需要你确认后我才会执行』」
3. 交付后：扫描终稿完成态断言（已保存/已更新/已生成），
   与写操作清单比对；无记录 → 改写为如实表述（机械改写，不改内容语义）
```

原则：**完成态声明必须由宿主核验**。这是宿主职责⑤的延伸，也是"产品可信度"的底线。

---

## 4. 模块清单（新增 7 文件，可合并为 3，但建议保留职责边界）

| 文件 | 职责 | 预估 |
|---|---|---|
| `app/agent/runtime/__init__.py` | 导出 `AgentRuntime` | 10 行 |
| `app/agent/runtime/runner.py` | 主循环状态机 + 与 harness 资产对接 | ~180 行 |
| `app/agent/runtime/schema.py` | Tool→schema、消息规范化、结果封装、并行分流定义 | ~90 行 |
| `app/agent/runtime/guards.py` | 迭代/预算/时长守卫 + 熔断 + advisory 注入 | ~70 行 |
| `app/agent/runtime/todo.py` | `update_plan` 工具 | ~60 行 |
| `app/agent/runtime/context.py` | 上下文装配 + 压缩 | ~110 行 |
| `app/agent/runtime/verify.py` | 完成态核验 | ~70 行 |
| `app/agent/runtime/events.py` | trace → SSE 事件映射（守契约） | ~80 行 |
| `app/models/llm.py`（改） | `chat_with_tools`（含 `reasoning_content`）+ 流式变体 | +60 行 |
| `app/config.py`（改） | 8 个运行时开关 | +20 行 |
| `app/agent/harness.py`（改） | `run()` 变为路由层 + 复用方法暴露 | +40 行（净减若干行） |

---

## 5. 接口契约

### 5.1 LLM 层

```python
async def chat_with_tools(
    messages: list[dict], tools: list[dict],
    model: str | None = None,
    temperature: float | None = None,
    thinking: str = "enabled",          # 决策轮 enabled / 终稿轮 disabled
    tool_choice: str = "auto",
) -> dict
# 返回: {"content": str, "tool_calls": [{"id","type","function":{"name","arguments"(str)}}],
#        "reasoning_content": str, "usage": {...}, "finish_reason": str}
```

实测依据：`thinking=enabled` 与 tools **完全兼容**（flash 44 reasoning tokens/1.7s；pro 87 字/4.1s）。**终稿生成轮必须 disabled**（反证：无 tools + thinking 生成方案 = 31.0s / 3830 reasoning tokens）。

### 5.2 事件契约（守住，前端零改）

| 事件 | 来源 | 前端消费（现状，不改） |
|---|---|---|
| `plan` | `update_plan` 工具 | Plan 面板渲染 + 步状态点亮 |
| `thought` | `reasoning_content` / 工具前 content | 思考面板追加 |
| `tool_start` / `tool_end` | 工具执行前后（含 `plan_index`） | 工具链 chip + 摘要 |
| `delta` | 终稿流式（决策 D1-B 时来自模型自带流） | 逐字渲染 |
| `self_check` | 自检 Gate | 质量徽标 |
| `permission_request` | 权限闸门 | 确认弹窗 |
| `agent_phase` / `skill_pack` / `doc_generated` / `reflexion` | 同上，复用 | 同上 |

### 5.3 配置开关（默认值待拍板）

```
AGENT_RUNTIME            = fc | legacy     # 引擎选择（默认 fc?）
AGENT_MAX_TURNS          = 16
AGENT_TOKEN_BUDGET       = 60000
AGENT_WALL_BUDGET        = 420            # 秒（对齐现有 480s 硬超时）
AGENT_THINKING_DECISION  = enabled
AGENT_THINKING_FINAL     = disabled
AGENT_PARALLEL_READONLY  = 1
AGENT_COMPACT_AT         = 0.75
AGENT_FINAL_OWNED_BY     = model | pipeline   # 决策 D1
```

---

## 6. 观测与评估：如何**证明**它真的是 Agent

指标设计必须能区分"真 agent"与"看起来像 agent"。新增 4 个**agent-ness 指标**：

| 指标 | 定义 | 目标 | 证明什么 |
|---|---|---|---|
| A1 自主拆解率 | 30 例裸目标产出可执行计划的比例 | ≥70% | C1/C4 |
| A2 工具链深度 | 平均每任务链式工具调用次数 | ≥2 | C1 |
| **A7 自主终止率** | 模型自发终止占全部运行的比例（宿主熔断 ≤10%） | ≥90% | **C1 的核心证据** |
| **A8 错误自愈率** | 工具报错后模型自行修正并成功的比例 | ≥60% | **C3 的核心证据** |
| **A9 计划自治度** | 触发 `update_plan` 且计划与最终工具序列不同的运行占比 | >0 | **C4 的核心证据** |
| **A10 压缩保真** | 触发压缩后仍成功完成任务的占比 | ≥90% | §3.7 有效性 |
| A6 不倒退 | 意图 100 例 + 沙箱 16 例回归 | 0 失败 | 稳定性 |

**A7/A8/A9 是这份架构的验收核心**：如果 A7 低（总靠熔断）、A8 低（一错就崩），那说明"模型在环"只是形式，需要回到提示词/工具粒度重新设计。

**Trace 存储（v1 不改表，避开 DB schema 变更）**：全量 trace（messages + 每轮 tokens + reasoning + tool_calls）序列化进现有 `agent_episodes.trajectory_json`。需要按轮查询时再新增 `agent_turns` 表——**届时单独提请确认**。

---

## 7. 迁移计划与回滚

| 阶段 | 内容 | 验收 | 是否动生产 |
|---|---|---|---|
| S0 ✅ | 能力探针（tools/thinking/并行/缓存） | 6 例全绿 | 否 |
| S1 | `llm.chat_with_tools` + `runtime/` 骨架（runner+schema+events） | U1 schema 齐全、U2 循环单测（mock）、U3 嵌套参数完整 | 否 |
| S2 | `harness.run()` 路由接入（`AGENT_RUNTIME=fc`，**默认关**） | U4 本地真 E2E（方案/竞品/闲聊）+ U5 回退可用 | 否 |
| S3 | `context.py` 压缩 + `verify.py` 核验 + `todo.py` + A7-A10 埋点 | U6 压缩后任务继续；U7 写操作零幻觉 | 否 |
| S4 | 30 例对照（FC vs 老管线）：A1/A2/A7/A8/A9 | 达标线见 §6 | 灰度 |
| S5 | 灰度转默认；老管线明确为兜底；清理死代码 | 生产 7 天无回退 | 是 |

**回滚**：`AGENT_RUNTIME=legacy` 一个环境变量 + restart，或前端 ⚡ 关闭。回滚后行为与今天**完全一致**。

---

## 8. 删除 / 保留清单

**主路径删除（重构到位的标志）**
- `_parse_react_output` / `_parse_react_actions` 在主路径的调用（正则抠 JSON）
- `PLAN_STEP_TOOL_MAP` 对执行的控制（降级为 fallback 内部实现）
- `_tool_to_plan_index` 的步归属推导（计划改由模型自持）
- `STEP_DONE:` 文本协议
- 主路径上的 `_force_cost_step` / `_force_crm_step` / `_force_kb_stats_step`（**保留代码给 fallback + 轻量保险丝**）

**保留（产品层资产，一行不动）**
知识库/RAG、CRM、技能包、权限闸门、沙箱、SSE 前端契约、经验记忆 + 打法库、统一增强管线、导出链路、评估门禁、经典模式全链路。

---

## 9. 风险登记册

| # | 风险 | 影响 | 对策 |
|---|---|---|---|
| R1 | 确定性下降：cost_calc/CRM 写入不再 100% 触发 | 中 | 保留**轻量保险丝**：仅在终稿缺成本数据/客户写操作未执行时补一步（不是全量预设） |
| R2 | 时延/成本上升（决策轮开 thinking + 轮数增加） | 中 | 预算守卫 + 只读并行 + prompt cache + 终稿轮关 thinking |
| R3 | 上下文爆炸 | 高 | §3.7 压缩 + 单条 observation 截断 |
| R4 | 模型选错工具/编造工具名 | 中 | schema 严格 + unknown tool 结构化回填 + 观测 A8 |
| R5 | 弱模型导致"真但弱" | 高 | 灰度对照给出数字；不达标不上线；FC 是必要不充分条件，不作 L4 背书 |
| R6 | 计划与执行不一致被误解为 bug | 低 | §3.4 明确定义为 C4 证据；前端文案区分"意图计划" |
| R7 | 终稿不再重写导致质量下滑（决策 D1-B） | 中 | 先 30 例对照；`AGENT_FINAL_OWNED_BY` 可切回 pipeline |

---

## 10. 待拍板（决策清单）

| # | 决策 | 选项 | 我的建议 |
|---|---|---|---|
| D1 | 终稿归属 | A 管线重写 / **B 模型自主（宿主只做标注+核验）** | **B**（A 与"真 agent"目标自相矛盾，且成本翻倍） |
| D2 | 决策轮 thinking | 开 / 关 | **开**（实测 44 tokens、1.7s，换来真实推理上屏） |
| D3 | 确定性保险丝 | 全退役 / **保留轻量保险丝** | **保留轻量**（R1，先保住 cost_calc） |
| D4 | 引擎默认值 | 直接 fc / **先 legacy，S4 后翻 fc** | **先 legacy**（避免污染正在跑的对照基线） |
| D5 | 接管范围 | 只 solution/competitor / 含 knowledge_q | **只接管方案与竞品**；闲聊/问候/账户/导出保持确定性分支 |
| D6 | 计划面板 | 保留 / 隐藏 | **保留**，语义改为"模型意图可见化" |

---

**结论**：这份设计的核心不是"换一个 API 调用方式"，而是**把四个判据的控制权从代码交还模型**，同时用宿主边界（能力/安全/上下文/不可委托计算/质量门）保证产品底线。C1-C4 有明确验收指标（A1/A2/A7/A8/A9），做不到就不算改完。
