# Agent 模式诊断报告：为什么"不像一个 Agent" + 改造路线

> 调研日期：2026-08-26 ｜ 调研对象：2026 年市面主流 AI Agent（Operator / Claude Agents / Devin / Manus / Coze / Dify 等）
> 诊断对象：cloudsol.cn Agent 模式（app/agent/：intent.py + harness.py + tools.py + agent.py + memory.py，共 ~2525 行）

---

## 一、结论先行（TL;DR）

**你的感觉是对的，不是错觉。** 按 Anthropic《Building Effective Agents》的官方定义，我们目前的产品形态 **90% 是 Workflow（工作流），只有约 10% 是 Agent（自主智能体）**——但界面长着 Agent 的样子，所以产生"包装感"。

**"包装感"的两个技术根源：**

1. **控制权过度在代码**：意图靠 7 条硬规则正则路由（`classify_intent`），输出被"14 章方案模板 / 竞品对比格式"强制重写（`_finalize_answer`）。Anthropic 的定义：**控制权在代码 = Workflow；控制权在 LLM = Agent**。我们大部分决策是代码做的，LLM 只是填空。
2. **执行过程不可见**：主流 Agent（Devin/Operator/Manus）都实时展示"它在干什么"（计划面板、步骤日志、屏幕操作），用户看到的是"一个活的智能体在干活"。我们虽然有 thought 面板，但缺少 **plan（执行计划）** 和 **工具执行结果摘要**，用户只看到"转了 3 圈然后吐出一份模板报告"。

**好消息**：ReAct 循环（thought→action→observation）、工具系统、会话记忆这些 Agent 的地基我们已经有了。缺的是"自主性"的包装层和"过程可见性"。

---

## 二、2026 主流 Agent 全景盘点（表格式）

| Agent | 厂商 | 核心形态 | 最擅长 | 定价 | 对我们最有借鉴意义的点 |
|---|---|---|---|---|---|
| **Operator** | OpenAI | 云端浏览器 Agent（CUA 视觉理解屏幕→点击/输入）| 订机票/填表单/跨站比价（~75% 成功率）| ChatGPT Plus $20 / Pro $200 | **可观看的执行**：实时看到 agent 在页面上点击操作，建立信任 |
| **Claude Agents / Claude Code** | Anthropic | API + Agent SDK + 终端 Agent；跨应用截图/点击/跑 shell | 多应用跨桌面工作流、编码、长任务可靠收敛 | API 按量（$0.1–1/任务）| **"知道何时停、何时问"**：主动澄清、死胡同及时退出而非空转 |
| **Devin** | Cognition | 云端自主编码 agent（开自己的 VS Code、读代码、写 plan、跑测试、开 PR）| 边界清晰的软件 ticket | $500/月 | **Plan 面板**：执行前先展示完整计划再动手 |
| **Manus** | Manus AI（中文）| 通用任务 agent（沙箱内浏览网页+写代码+执行文件，长任务跑数十分钟）| 自主网络调研、报告生成 | $39/月 | **长时间自主跑** + **并行任务** + 结果带引用表格 |
| **Kimi Work** | 月之暗面 | 文档处理 agent（本地文件夹读写、几十份 PDF 批量读）| 投研/咨询/科研文档密集型 | 免费+按量 | **本地文件挂载读写**：直接操作你的文件而不是"上传下载" |
| **实在 Agent** | 实在智能 | 屏幕语义理解 agent（无 API 的老系统按界面操作）| 老旧 ERP/MES 自动化（90.2% 成功率）| 企业定制 | **不做 API 也能自动化**：语义级界面操作 |
| **扣子 Coze** | 字节 | 零代码 Agent 搭建平台（拖拽 + 插件生态 + 多 Agent 协作 v3.0）| 快速搭 Bot 发抖音/飞书/微信 | 免费+按量 | **插件生态**：新闻/天气/日历等即插即用工具 |
| **Dify** | 开源 | 可视化工作流编排 + RAG + Agent 沙箱（v1.16）+ MCP 集成 | 企业级私有化、确定性流程 | 开源免费 | **工作流 vs Agent 分层的产品化表达** |
| AutoGPT / BabyAGI | 开源 | 2023 年先驱，2026 已基本被专用 agent 取代 | 历史价值 | 免费 | 反面教材：无边界自主=烧钱空转 |

**2026 行业共识（多个独立调研一致）：**
- **窄场景 agent 胜出**：每个成功 agent 都选了一条窄道（编码/浏览器/文档/老系统），"什么都干"基本是营销。
- **"Agent 洗白"（agent washing）是 2026 最大吐槽点**：RAND 研究显示 80-90% 的 agent 项目在生产环境失败；Reddit 社区给出了判定真 agent 的 4 问（见下节）。
- **可靠性的四个地基刚成熟**：工具调用（95%+ 成功率）、视觉理解、超大上下文、推理模型（o1/R1/Claude thinking）——我们前两个其实还没用上。

---

## 三、判断标准：Workflow vs Agent（Anthropic 官方）

Anthropic（2024.12《Building Effective Agents》+ 2026 eBook）给出了行业最权威的分界：

> **Workflow（工作流）**：LLM 与工具通过**预定义的代码路径**编排，控制权在代码。像"有轨列车"——轨道提前铺好。
> **Agent（智能体）**：LLM **自主动态规划流程、选择工具**，控制权在 LLM。像"自动驾驶"——根据路况动态调整。

官方决策表：

| 维度 | Workflow | Agent |
|---|---|---|
| 适合任务 | 步骤可预测、可枚举 | 开放任务、步骤不可预测 |
| 可预测性 | 高（显式代码路径）| 低（LLM 决定控制流）|
| 成本/延迟 | 低 | 高（多轮 LLM 调用累积）|
| 可调试性 | 易（失败定位到某一步）| 难（需沙箱+护栏）|
| 官方建议 | **生产环境首选** | 仅在真正需要动态决策时才用 |

**Reddit 社区判真 Agent 的 4 问（用户可自测）：**
1. 它会主动推进任务，还是等用户每一步指令？
2. 遇到意外情况会自行处理，还是崩掉等重新提示？
3. 会用外部工具（搜索/代码执行/文件），还是只输出文本？
4. 多步任务中能记住上下文不重复，还是反复要用户重复？

---

## 四、我们的现状诊断（对照代码逐条核对）

### 4.1 架构实况（app/agent/，~2525 行）

```
用户输入
  ↓
classify_intent（7 条硬规则正则 + LLM 兜底分类）   ← 控制权在代码（Routing 模式）
  ├─ greeting  → 固定模板极短回复                 ← Workflow
  ├─ account   → 后端真实取数直答（成就/方案/收藏）← Workflow（Retriever-Executor）
  ├─ general   → LLM 直答（带会话历史）            ← 增强型 LLM（非 agent）
  ├─ file_ops  → ReAct：list_dir/read_customer_file ← ✅ 真正的 Agent 片段
  ├─ knowledge_q → ReAct：search_kb 结构化呈现      ← ✅ 真正的 Agent 片段
  ├─ competitor → ReAct：search_huawei+search_competitor ← ✅ + 强制对比格式模板
  └─ solution  → ReAct：analyze_demand→search_kb(多轮) → ✅ + 强制 14 章方案模板
                                                    ← ← 最后一步 _finalize_answer 强制模板化
```

**工具清单（5 个）**：`analyze_demand` / `search_kb` / `search_competitor` / `read_customer_file` / `list_dir` —— 全部是 RAG + 文件类，**没有代码执行、没有网页实时检索、没有输出工件（PPT/Word）生成**。

### 4.2 用 Anthropic 定义逐条打分

| 判断项 | 现状 | 判定 |
|---|---|---|
| 意图分流控制权 | 7 条硬规则正则优先，LLM 只兜底模糊输入 | ⚠️ 代码控制（Workflow）|
| solution 输出形态 | ReAct 草稿 → **强制重写为 14 章售前方案书** | ⚠️ 模板控制（Workflow）|
| competitor 输出形态 | ReAct 草稿 → **强制竞品对比格式** | ⚠️ 模板控制（Workflow）|
| file_ops / knowledge_q | ReAct 草稿 → 直接返回（不套模板）| ✅ LLM 自主（Agent）|
| 执行计划（plan）| **无**。直接进 ReAct，没有"先列计划再执行" | ❌ 缺失 |
| 自我纠正（reflection）| 仅 try/except + max_steps=8 兜底 fallback | ⚠️ 有兜底无反思 |
| 工具执行过程可见 | thought 面板 + tool_start/end 事件（有基础）| ⚠️ 有但缺"结果摘要" |
| 多工具组合 | 单条链（analyze→search），无并行/分支 | ⚠️ 线性 |
| 记忆 | short-term 会话记忆（memory.py），无长程记忆 | ⚠️ 只做了 1/3 |

### 4.3 "包装感"根因（一句话）

**我们给用户看的界面是 Agent 的样子（思考面板+工具调用徽章），但用户实际拿到手的是"预定义路由 + 强制模板"的 Workflow 产物**——当用户连续提问、看执行过程时，会发现"它并没有真正自己规划、自己决定、自己完成任务"，而是"按代码写好的剧本在演戏"。这正是 Anthropic 说的"workflow 是演员照剧本演，agent 是即兴发挥"。

---

## 五、差距矩阵（我们 vs 主流 Agent）

| 维度 | 主流 Agent（2026） | 我们（现状） | 差距 | 改造优先级 |
|---|---|---|---|---|
| **计划能力** | Plan-and-Execute：先出 plan 再执行 | 无 plan，直接 ReAct | 大 | 🔴 P0 |
| **执行可见性** | 计划面板 + 步骤日志 + 结果摘要 | 只有 thought 面板 | 中 | 🔴 P0 |
| **自我纠正** | Reflexion / Evaluator-Optimizer | 仅异常兜底 | 中 | 🟡 P1 |
| **工具广度** | 浏览器/代码执行/shell/文件（10-30+）| 5 个 RAG/文件工具 | 大 | 🟡 P1 |
| **输出自主性** | Agent 自己决定输出结构 | 强制 14 章模板 | 大 | 🔴 P0 |
| **人机协作点** | 高风险动作前暂停确认（HITL）| 澄清追问（有基础）| 小 | 🟢 P2 |
| **长程记忆** | episodic/procedural memory | 仅会话记忆 | 中 | 🟢 P2 |
| **多智能体** | Orchestrator-Workers / 评审 | 单 agent | 大 | 🟢 P2（可选）|

---

## 六、改造路线建议（分阶段，从易到难）

### 阶段 1（P0，1-2 周）：去掉"包装感"的最低成本方案 —— 让"自主性"可见

**目标**：用户能明显感到"它真的是在替我干活"，而不是"套壳模板"。

1. **加 Plan 面板**（效果最大）：
   - ReAct 第 1 步前，让 LLM 生成 3-6 条执行计划（如：①分析需求②检索华为方案③检索竞品④生成对比⑤自检完整性）
   - 界面展示计划列表，每完成一步打勾 ✓ —— 这是 Devin/Manus 的核心信任建立机制
2. **工具结果摘要**：tool_end 事件里附上"检索到 6 篇资料，其中《xxx》最相关"这类一句话摘要，而不是只有工具名
3. **方案意图的模板降权**：
   - 14 章模板从"强制"改为"建议结构"：`_finalize_answer` 改为"LLM 自主组织输出，模板仅作为结构提示注入 prompt"，不再强制重写
   - 保留"一键导出 Word/PPT"（模板在导出时应用，而不是在生成时）——**这是关键**：模板是给导出用的，不是给对话用的
4. **自我检查一步**：finalize 前加一次"完整性自检"（Evaluator-Optimizer 的轻量版）：LLM 自查"方案是否覆盖客户背景/产品组合/实施路径/风险"，缺失则补写

### 阶段 2（P1，2-4 周）：真正 Agent 化的骨架

1. **引入 Plan-and-Execute**：solution/competitor 意图改为"先 plan → 按 plan 逐步执行（每步可独立调工具）→ 汇总"，而非现在的单循环 ReAct
2. **补 2 个高价值工具**：
   - `generate_doc(format)`：把方案导出为 Word/PPT（售前刚需，当前已有部分能力，做成 agent 工具）
   - `web_search(query)`：补充知识库之外的最新资讯（华为云产品页/白皮书/新闻），让 agent 真正"能上网"
3. **Reflexion 反思**：当 max_steps 耗尽或生成失败时，让 LLM 反思"刚才哪里不对"再重试一次（而非直接 fallback）

### 阶段 3（P2，可选）：进阶形态

1. **多智能体（Orchestrator-Workers）**：方案生成拆成"需求分析师 → 方案架构师 → 质量校验官"三个子 agent，各配独立工具
2. **长程记忆**：把用户历史方案/偏好做成向量记忆，新任务自动注入（有 Plan A 客户上下文基础）
3. **MCP 集成**：接 MCP 标准让工具生态可插拔

---

## 七、给你的建议（针对作品集定位）

**1. 对外口径不变**：简历/面试继续称 "agentic workflow"（这是诚实的，且 Anthropic 也说生产环境首选 workflow）——**但产品体验要往 Agent 靠**，让面试官点开项目时"哇，它真的在自主规划"。

**2. 优先级排序建议**：Plan 面板 + 模板降权（P0）是投入产出比最高的两项，基本不碰核心逻辑，只改前端展示 + finalize 策略。

**3. 一句话面试话术**（人话版）：
> "我们的方案生成链路是『意图路由 → LLM 自主规划 → 分步检索执行 → 自我检查 → 结构化交付』，底层是 ReAct 循环 + 5 个工具。相比纯 RAG 问答，它能自主决定检索什么、怎么组织答案，并且把每一步思考过程展示给用户。按 Anthropic 的分类，这是 agentic workflow——固定流程内的自主智能。"

**4. 避坑提醒**：不要为了"像 agent"而盲目上多智能体/全自主（AutoGPT 前车之鉴：烧钱空转、不可控）。**当前产品场景（售前方案生成）本质是半开放任务**，最合适的是"workflow 骨架 + agent 自主决策"的混合形态——这恰好也是 Anthropic 推荐的生产级做法。

---

*附：本文引用的主要外部资料*
- Anthropic《Building Effective Agents》(2024.12) 及 2026 eBook、Claude 官方工作流模式博客
- 2026 多份 agent 横向评测（techverdict / rightaichoice / en.ai-pedias / Reddit 社区共识）
- 2026 Agent 架构实践指南（futureagi / creativegenius / breyta / devstarsj）
- 国内 Agent 平台对比（搜狐科技：11 款国产 Agent / Dify vs Coze / 2026 办公 Agent 选型指南）
