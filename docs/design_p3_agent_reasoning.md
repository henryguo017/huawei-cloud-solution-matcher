# P3 设计文档：Agent 推理可靠性增强（真反思-重规划 / 并行子体 / 自检 Gate）

> **撰写时间**：2026-09-01（基于 P1+P2 落地后代码基线，main @ `2b978b0`）
> **前置必读**：`docs/design_p1_agent_reshape.md` + `docs/design_p2_agent_orchestrator.md`
> **目标**：P1 让 Plan 点亮/工具可导出/可联网/失败可反思；P2 让执行真正计划驱动+多角色协作+长程记忆。P3 聚焦**答案质量与执行鲁棒性**：让 Agent 在失败时能"真重规划"、能"并行检索提速"、在交付前过一道"自检闸门"。这直接对应你最关心的「Agent 模式答案质量」。

---

## 0. 设计铁律（不可违反，继承 P1/P2）

1. **经典模式字节不动**：Agent 改动只限 `app/agent/**` + `api/agent_routes.py` + `frontend/js/agent_workspace.js` + `frontend/css/agent_workspace.css` + `app/config.py` + `.env.example`。
2. **稳定性 >> 新功能**：P3 全部新增路径必须保留降级到 P2 两阶段执行 / P1 旧 ReAct 循环 / 现有单 retry 反思。任一新机制异常即回退，绝不卡死用户。
3. **开关隔离**：P3-1/2/3 各一个 config 开关，默认开；`.env` 关掉立即回退旧行为。
4. **前端版本号递增**：改动 `agent_workspace.js`/`css` 时升 `index.html` `?v=`。
5. **每次大改后必须 E2E 验证**（后端脚本优先，浏览器截图兜底）。
6. **复用现有执行协议**：不引入第二套引擎；并行/重规划/自检都在 `_plan_and_execute` / `_execute_step` / `_self_check_answer` 之上叠加。
7. **零新依赖**。

---

## 1. 当前架构事实（P2 落地后，来自代码核实）

- **两阶段执行**：`harness._plan_and_execute`（L343）→ 对 plan 每步 `_execute_step`（L412，每步 ≤`STEP_MAX_ITER=3` 次 LLM）→ `_synthesize_final`（L544）。开关 `AGENT_TWO_PHASE`（默认 1）。
- **多智能体**：`AGENT_MULTI_AGENT`（默认 1），三角色串行（分析师→架构师→校验官），`agent_phase` 事件。
- **反思（P1-3）**：`_reflexion_retry`（L1881）——连续工具失败≥2 或 max_steps 耗尽时调 LLM 反思，返回调整建议文本注入**下一轮 prompt**。**问题：是"软重试"，不重生成 plan、不重跑步骤、不保证修复。**
- **自检（P0）**：`_self_check_answer`（L1717）——终稿后轻量后处理，可能微修，**非硬闸门**（不过 rubric、不迭代、无质量事件）。
- **max_steps=8**；`AGENT_CONTEXT_WINDOW` 控 token 预算。
- **权限闸门**：`tool_permissions` 现可正确透传（本次测试修复）；`permission_request` 阻塞在 asyncio.Future，由 `/api/agent/permission/{id}` 唤醒。

---

## 2. P3-3：自检 Gate（质量闸门，优先级最高，先做）

### 2.1 现状问题
`_self_check_answer` 是"润色"，不是"验收"。售前方案若出现漏竞品对比、缺可执行步骤、或幻觉，当前直接 `final` 下发，前端无质量信号。

### 2.2 设计：`_self_check_gate()`（在 `_synthesize_final` 之后、`emit final` 之前插入）
- 构造 **critic prompt**：原始需求 + 终稿 + 固定 rubric（5 维：①需求覆盖 ②竞品对比（若用户提了友商）③方案可执行性 ④无幻觉/有据 ⑤结构完整）。
- 调 LLM 产出结构化评判：`{"pass": bool, "score": 0-100, "gaps": ["...", "..."], "patch_hint": "..."}`。
- 若 `pass` 或 `score ≥ SELF_CHECK_PASS`（默认 80）：直接放行，emit `self_check` 事件 `{"gate":"pass","score":...}`。
- 若未过且 `iters < SELF_CHECK_MAX_ITERS`（默认 2）：用 `patch_hint` + `gaps` 作为 observation 回到 `_synthesize_final` 二次生成（**不重跑工具**，省 token），循环直到过闸或达上限。
- 达上限仍不过：emit `final` 并附 `quality_warn: true`（事件加字段），**不阻断用户**（稳定性铁律）。
- SSE 新增 `type:"self_check"`：`{"gate":"pass"|"fail"|"warn", "score":int, "gaps":[...], "iter":int}` —— 前端"质量自检"徽标。

### 2.3 文件改动
- `app/agent/harness.py`：`_self_check_gate`（新）+ 在 `_synthesize_final` 收尾处接 gate；`result`/`final` 事件增 `quality_warn` 字段。
- `app/config.py` + `.env.example`：`AGENT_SELF_CHECK`（默认 1）、`SELF_CHECK_PASS=80`、`SELF_CHECK_MAX_ITERS=2`。
- 前端：`agent_workspace.js` 消费 `self_check`（`#ws-quality-badge` 阶段徽标）。

### 2.4 验证
`tests/verify_p3_selfcheck.py`：用一份故意"缺竞品对比"的草稿注入 → gate 判 `fail` → 二次合成后 `pass`；正常方案 → 一次 `pass`。

---

## 3. P3-1：真反思-重规划（True Reflection + Re-plan）

### 3.1 现状问题
P1-3 `_reflexion_retry` 只把反思文本塞进下一轮 prompt，LLM 可能无视；plan 不动、失败步不重跑，鲁棒性弱。

### 3.2 设计：`_reflexion_replan()`（替换/增强 P1-3 的软重试）
触发条件同 P1-3（连续工具失败≥2 或 max_steps 耗尽），但改为：
1. 读取 `_step_results`（哪些步成功/失败 + observation）。
2. 调 **planner LLM**：输入=原始需求 + 失败步摘要 + observation，产出 **修订 plan_v2**（步数可减/调序/拆细）。
3. 对修订 plan 的"未完成/失败步"用 `_execute_step` 重跑（复用 P2 子循环），成功步结果保留。
4. emit `plan` 事件（`plan_version=2`）+ `plan_status` 重新点亮；`reflexion` 事件增 `replanned:true`。
5. 重规划次数受 `REFLEXION_MAX_REPLANS`（默认 2）保护；超限回退到 P1-3 单 retry 文本注入 / 旧循环。

### 3.3 文件改动
- `app/agent/harness.py`：`_reflexion_replan`（新）；`run()`/`_plan_and_execute` 的反思分支改调 replan（受 `AGENT_REFLEXION_REPLAN` 开关，默认 1；关则走旧 `_reflexion_retry`）。
- `app/config.py` + `.env.example`：`AGENT_REFLEXION_REPLAN`、`REFLEXION_MAX_REPLANS=2`。
- `result`/`reflexion` 事件增 `replanned` 字段；前端 reflexion 气泡显示"重规划中"。

### 3.4 验证
`tests/verify_p3_replan.py`：构造一个必败工具（mock 抛错）→ 触发重规划 → 收到 `plan_version=2` 事件且最终 `success=True`（重试路径绕开失败）。

---

## 4. P3-2：并行子体（Parallel Sub-agents / 工具扇出）

### 4.1 现状问题
`_execute_step` 内工具串行；同一 plan 步的 `search_kb`+`search_competitor`+`web_search` 本可并行却排队，拖慢且烧 token。

### 4.2 设计：`_execute_step` 工具扇出（受 `AGENT_PARALLEL_TOOLS` 开关，默认 1）
- 当 LLM 单轮产出**多个 action**（或步级 toolset 内多工具可并行）时，用 `asyncio.gather` 并发执行，上限 `MAX_PARALLEL=3`。
- 并发执行体仍是 `_execute_tool` 单工具路径（含权限闸门）：每个工具的 `permission_request` 仍各自 emit 并阻塞在自身 Future，由外部 `/api/agent/permission/{id}` 唤醒；`gather` 自然等齐。
- observation 按 tool 归并后回注；`tool_start/tool_end` 事件照常发（plan_index=idx），前端按到达顺序点亮。
- 竞品/知识库检索天然独立，收益最大；`generate_doc`/`read_customer_file` 等副作用工具不参与并行扇出（仅放行只读检索类）。

### 4.3 文件改动
- `app/agent/harness.py`：`_execute_step` 增加并行分支（识别多 action / toolset 扇出）；`MAX_PARALLEL` 常量。
- `app/config.py` + `.env.example`：`AGENT_PARALLEL_TOOLS`（默认 1）、`MAX_PARALLEL=3`。
- 前端：无协议变更（事件名不变），仅确保多 `tool_start` 同 plan_index 不冲突（已安全）。

### 4.4 验证
`tests/verify_p3_parallel.py`：同一 plan 步注入 search_kb+search_competitor → 观测到两 `tool_start` 并发（时间重叠）+ 两 observation 均进入终稿。

---

## 5. 决策锁定（待你拍板）

- **P3-3 自检 Gate → 做**（最高优先级，直接提升答案质量）。
- **P3-1 真反思-重规划 → 做**（增强鲁棒性，替换 P1-3 软重试）。
- **P3-2 并行子体 → 做**（提速降本，复杂度最高，放最后，权限闸门并发需重点验证）。
- 三者均**默认开 + 可一键降级**，不破坏 P0/P1/P2 已验证路径。

**实现基线版本号**：`frontend/index.html` 资源统一升 `v=20260901a`（P3 首改时递增）。

---

## 6. 验证计划（实现后必跑）

| 验证项 | 脚本 | 断言 |
|---|---|---|
| P3-3 自检 | `tests/verify_p3_selfcheck.py` | 缺陷草稿→fail→二次合成→pass；正常→一次 pass |
| P3-1 重规划 | `tests/verify_p3_replan.py` | 必败工具→plan_v2→success |
| P3-2 并行 | `tests/verify_p3_parallel.py` | 同步多 tool_start 并发 + observation 入稿 |
| 回归 P2 | `verify_p2_*.py` ×6 | 全绿（开关默认开后旧协议仍成立） |
| 回归 P1 | `verify_p1_*.py` ×3 | 全绿 |
| E2E | `tests/verify_p3_e2e.mjs`（Playwright） | 质量徽标 + 重规划事件 + 并行无卡死 |

---

## 7. 实现顺序

1. **P3-3 自检 Gate**（最高价值）→ `verify_p3_selfcheck.py`。
2. **P3-1 重规划**（接 P1-3 反思点）→ `verify_p3_replan.py`。
3. **P3-2 并行**（最后，权限并发重点验）→ `verify_p3_parallel.py`。
4. **前端**（质量徽标 + 重规划气泡）+ 版本 `v=20260901a` → `verify_p3_e2e.mjs`。
5. **全量回归**（P1×3 + P2×6 + P3×3）→ 部署待你拍板。

> 任何一步改完立即跑对应 verify 脚本，全绿再进下一步；P3 全绿后汇总交付。

---

## 8. 实现状态（2026-09-01 落地）

三支柱全部实现并通过本地单元验证，前端接入，配置默认开启、可一键降级。

### 8.1 已落地代码
- **P3-3 自检 Gate**（`harness._self_check_gate` + `_parse_self_check_verdict`）：插在 `_plan_and_execute` 与 `_rerun_plan_step` 的 `_synthesize_final` 之后、`_finalize_answer` 之前；critic LLM 按 6 维 rubric（用户提友商时含竞品对比）验收，`score≥SELF_CHECK_PASS` 直接放行，不过则 `patch_hint`+`gaps` 二次合成（不重跑工具、不流式），达 `SELF_CHECK_MAX_ITERS` 仍不过则放行并附 `quality_warn`（不阻断）。SSE `self_check` 事件 `gate/pass|fail|warn/score/gaps/iter`；前端 `agent_workspace.js` `_appendSelfCheckBadge` + `css` 徽标（绿/红/琥珀）。`result.quality_warn` 透传。
- **P3-1 真反思-重规划**（`harness._reflexion_replan` + `_parse_plan_v2`）：`_plan_and_execute` 检测 `_step_results` 含 `Error:` 的失败步 → 读失败摘要 → planner LLM 产 plan_v2（长度与原 plan 一致、仅替换失败步文本）→ 用 `_execute_step` 重跑失败步（成功步保留）→ emit `plan(plan_version=2)` + `reflexion(replanned=True)` → 重新汇总。受 `REFLEXION_MAX_REPLANS` 保护，超预算/异常回退常规汇总（稳定性铁律）。`result.replanned` 透传；前端反思气泡在 `replanned` 时显示「重规划」红标。
- **P3-2 并行子体**（`harness._parse_react_actions` + `_exec_one_action` + `_execute_step` 扇出）：单轮产出多个只读 Action（`search_kb`/`search_competitor`/`web_search`）且全在步级工具集内、≤`MAX_PARALLEL` 时，`asyncio.gather` 并发执行，各自 `tool_start/tool_end` + 权限 Future 独立阻塞；非只读工具/超上限/不在工具集则顺序兼容旧行为。验证实测并发 0.30s vs 串行 0.60s。

### 8.2 校准修正（实现中发现）
- `SELF_CHECK_PASS` 由设计初值 **80 下调至 70**：flash critic 初版对「简练但维度齐全」的方案也判 fail（实测完整 6 章方案仅 62 分），且偏好冗长（缺陷草稿二次合成爆到 15k 字）。改为「按维度覆盖而非篇幅」评分后，完整方案首闸即 pass（实测 88 分），缺陷草稿 fail→二次合成→pass（90 分，3.4k 字，外科手术式补强）。避免每个正常方案都浪费 2 次重合成。
- `_reflexion_replan` 的 rerun 不重置 `_step_count` 语义；`_exec_one_action` 内 `self._step_count += 1` 保证并发工具各自独立的 step 编号；`__init__` 增加 `_last_trajectory=""` 防御（`_record_trajectory` 在直接调用路径需该属性）。

### 8.3 验证脚本（均本地通过）
- `tests/verify_p3_selfcheck.py`（缺陷→fail→二次合成→pass；正常→首闸 pass）
- `tests/verify_p3_replan.py`（失败步→plan_v2→重跑修复→success）
- `tests/verify_p3_parallel.py`（并发 tool_start + 耗时≈0.3s 证明真正并行）
- `tests/verify_p3_e2e_inproc.py`（真实 LLM 跑通 plan→工具→self_check→终稿，断言 P3 字段透传 + flash 模型）
- 回归：`verify_p1_plan_step.py`（A 静态映射）、`verify_p1_reflexion.py`（A/B/C 全绿，P3-1 未破坏 P1-3）

### 8.4 前端版本
`frontend/index.html` 资源升 `v=20260901b`（P3-1 反思气泡 + P3-3 自检徽标均在 `20260901a` 基础上）。

### 8.5 验收跑出的隐性工具参数漂移 Bug（2026-09-02 修复）
- **现象**：`verify_p3_e2e_inproc.py` 真实 LLM 跑通但日志报 `Tool [list_dir] execution error: _tool_list_dir() got an unexpected keyword argument 'path'`，并连带 `search_competitor` 收 `query`、`search_kb` 收 `top_k/limit`。根因：LLM 偶发把参数名写成 `query/path/top_k/limit`，与函数签名 `(competitor)/(dir)/(query, industry)` 不符 → `TypeError` → 检索整段失败 → Agent 退化为凭 LLM 记忆作答（正是 P3 要提升的「答案质量」被悄悄拖累），且一次失败步还触发了本可避免的重规划。
- **修复**：在 `app/agent/tools.py` 的 `Tool.execute` 分发前增加 `_normalize_args`：用 `inspect.signature` 取函数真实签名，做「别名对齐 + 丢弃未知参数」——`query→competitor`（仅当 competitor 未显式传入）、`path→dir`、`top_k/limit` 等未知项直接丢弃。工具函数本体保持干净，分发层一处收敛、所有工具受益。
- **验证**：`tests/verify_p3_tool_normalize.py`（6 例全绿：search_competitor 收 query→competitor、list_dir 收 path→dir、search_kb 收 top_k/limit 被丢弃、web_search/read_customer_file 不变）；复跑 `verify_p3_e2e_inproc.py` 确认无 `execution error`、KB 检索真实命中。

