# Agent 流式输出改造方案（聚焦版 · 仅做"边想边写"）

> 状态：方案待审阅，未改任何代码。
> 范围：**只改流式输出**，左侧栏前端功能不动、双 ID 修复本次不做。
> 约束：本地先做、实测确认后再决定是否部署生产（铁律① `cp -r` + `systemctl restart huawei-cloud-api`）。

---

## 1. 现状与根因（已读代码逐行确认）

链路：`agent_workspace.js:767 _chatStream`（fetch 读 SSE 流）→ `api/agent_routes.py`（Queue 桥接）→ `harness.run()`。

- **思考/工具步骤**（`thought` / `tool_start` / `tool_end`）是**实时**推到「思考面板」的（`harness.py:311-453` 边跑边 emit）。这部分本身已经是"边想"了。
- **最终答案**不是流式的：
  - `harness._finalize_answer`（`harness.py:751`）→ `SolutionMatcherService.generate_enhanced`（`solution_matcher.py:152`），内部是**单次 `get_llm_response`**（`:184`，非流式），整段一次性生成。
  - 后端 `run_agent()` 在 `harness.run()` 返回后，单独发 `result` 事件（带 `answer`）（`agent_routes.py:62-69`）。
  - 前端 `onEvent` 的 `result` 分支（`:728`）把整段 markdown 一次性 `innerHTML` 重渲。
- 所以你看到的是：**思考面板闪一下步骤 → 一大坨方案砸出来**。

**附带 bug（已发现）**：`final` 事件本身不带文字（`harness.py:370` 只发 `{type:"final", step, elapsed}`），但前端在 `final` 分支（`:713`）执行了 `fullAnswer += ''` 然后渲染空 markdown —— 在 `result` 到达前会**闪一下空气泡**。

---

## 2. 改造目标

对话"**边想边写、逐字长出**"：

1. 思考过程（thought/tool）实时可见 —— 已有，保留。
2. 最终答案逐 token 流式长出 —— 新增。
3. 终态一次性 markdown 定稿（避免半截语法闪烁）—— 复用 `result` 事件。

---

## 3. 改动点（函数级）

### 3.1 后端 `app/services/solution_matcher.py`

新增流式变体（照 `match_stream` 模式，`solution_matcher.py:300`，内部 prompt 构建直接复用 `generate_enhanced` 的 `:175` 那段）：

```python
async def generate_enhanced_stream(
    self, demand, context, industry=None, demand_analysis=None,
    client_context="", format_mode="solution", on_delta=None,
) -> Dict[str, Any]:
    playbook_text = self._playbook_text(industry or "")
    final_prompt = self._build_prompt(
        question=demand, context=context, industry=industry or "",
        playbook_text=playbook_text, demand_analysis=demand_analysis or {},
        client_context=client_context, format_mode=format_mode,
    )
    collected: list = []
    async for delta in get_llm_response_stream(final_prompt):   # 照 :326 先例
        if delta:
            collected.append(delta)
            if on_delta:
                await on_delta(delta)
    answer = "".join(collected)
    # 追加参考资料节（与 :187 一致，避免悬空 [资料N]）
    if "参考资料" not in answer:
        refs = build_references_section(context)
        if refs:
            answer = answer.rstrip() + "\n" + refs
    return {"answer": answer, "solution_json": parse_markdown_to_chapters(answer)}
```

- `get_llm_response_stream` 已存在（`app/models/llm.py`），无需改。

### 3.2 后端 `app/agent/harness.py`

- `_finalize_answer`（`harness.py:751`）增加 `event_callback` 参数，把每个 token 经 `_emit` 发成 `delta` 事件；流失败兜底（防丢答案）：

```python
async def _finalize_answer(self, user_input, draft, tool_calls, event_callback=None) -> str:
    try:
        context, industry, demand_analysis = self._collect_context_and_demand(tool_calls)
        if not context.strip():
            return draft
        matcher = SolutionMatcherService()
        async def _on_delta(tok):
            await self._emit(event_callback, {"type": "delta", "text": tok})
        enhanced = await matcher.generate_enhanced_stream(
            demand=user_input, context=context, industry=industry,
            demand_analysis=demand_analysis,
            format_mode=getattr(self, "_format_mode", "solution"),
            on_delta=_on_delta,
        )
        return enhanced["answer"]
    except Exception as e:
        logger.warning(f"[Agent] 流式增强失败，回退草稿并发整段: {e}")
        # 兜底：把草稿作为整段 delta 发出，保证前端仍可见答案
        await self._emit(event_callback, {"type": "delta", "text": draft})
        return draft
```

- 调用点传 `event_callback`：
  - `harness.py:368`（`final_answer` 解析成功）：`await self._finalize_answer(user_input, final_answer, tool_calls_log, event_callback=event_callback)`
  - `harness.py:468`（解析失败但已有数据兜底）：同上加 `event_callback=event_callback`
- `api/agent_routes.py` **无需改** —— `generate()` 通用透传任意 `type`，`delta` 自动经 SSE 送达（`agent_routes.py:83-86`）。

### 3.3 前端 `frontend/js/agent_workspace.js`

`onEvent`（`:698`）三处改动：

```js
// 1) 新增 delta 分支：纯文本逐字打字（避免 markdown 半截闪烁）
} else if (t === 'delta') {
    fullAnswer += (ev.text || '');
    shell.answer.textContent = fullAnswer;   // 先用纯文本，终态再 markdown 定稿
    self._scrollBottom();

// 2) final 分支（:713）：改成只收尾思考面板，不再渲染空（修闪空 bug）
} else if (t === 'final' || t === 'final_answer') {
    self._finishThinking();
    // 不再 fullAnswer += ''、不再 innerHTML 空 —— 答案已由 delta 逐字长出

// 3) result 分支（:728）：保持用 ev.answer 做终态 markdown 定稿（不变）
} else if (t === 'result') {
    self._finishThinking();
    if (ev.answer) { fullAnswer = ev.answer; shell.answer.innerHTML = renderMarkdownLite(escHtml(fullAnswer)); }
    ...
```

- `frontend/index.html:2207`：把 `agent_workspace.js?v=20260817f` 升版本号破缓存。

---

## 4. 改动文件清单

| 文件 | 改动点 | 风险 |
|------|--------|------|
| `app/services/solution_matcher.py` | 新增 `generate_enhanced_stream`（照 `match_stream`） | 低 |
| `app/agent/harness.py` | `_finalize_answer` 接 `event_callback` 发 `delta` + 兜底；两处调用点传回调 | 低 |
| `api/agent_routes.py` | 不改（通用透传） | — |
| `frontend/js/agent_workspace.js` | `onEvent` 加 `delta` 分支、`final` 改为只收尾（修闪空）、`result` 定稿 | 低 |
| `frontend/index.html` | `agent_workspace.js?v=` 升版本号破缓存 | — |

---

## 5. 实施顺序与验证

1. **本地**：`venv` 起后端 API + 前端静态服务；用 Playwright 抓 SSE 时序，确认 `delta` 连续、`final` 收尾思考面板、`result` 落定稿、无空闪。
2. **真实 LLM** 跑一类方案问题（如「中型制造企业50台设备预测性维护」），肉眼确认答案**逐字长出**、思考面板步骤同步可见。
3. 轻量意图（账户/问候/通用问答）回归：仍走 `thought→final→result`，`final` 不再闪空，答案正常。
4. 本地全部确认 → 你拍板 → 部署（铁律①）。

---

## 6. 风险与取舍

- **markdown 半截语法闪烁** → 用「纯文本打字 + `result` 一次性 markdown 定稿」规避（WorkBuddy/DeepSeek 同理）。
- **长方案即使流式仍是长文** → 接受；更强对话感（多段增量）超出本轮，留待后续。
- **delta 与 result.answer 一致性** → 两者同源（同一段文本）；`result.answer` 为权威定稿，回放一遍完整 markdown。
- **轻量意图不流式** → account/greeting/general 本就短，保持原样，仅顺带修掉 `final` 闪空。
- **不做（按你要求本次不做）**：① 左侧栏重构；② 双 ID 前后端会话连续性修复（属已知问题，留待后续单独处理）。

---

## 7. 备注：为什么"边想边写"之前没做

原设计把"思考面板"和"最终答案"拆成了两段：思考过程实时（好），但答案在 ReAct 收尾时又走了一遍**非流式**增强生成（`generate_enhanced` 单次 `get_llm_response`），导致答案整段砸出。改成 `generate_enhanced_stream` + 前端 `delta` 累积即可补齐"边写"这一段，且 `get_llm_response_stream` / `match_stream` 已有成熟先例，改动小、风险低。

## 8. 双路隔离保障（经典模式零影响 · 用户硬约束）

用户明确要求：Agent 与经典必须**两条独立路径**，本次代码修改**不能碰经典模式**。已逐行查证，方案天然满足：

### 8.1 后端隔离
- `generate_enhanced` / 新增的 `generate_enhanced_stream` 是 **Agent 专属入口**：全代码库仅有 `harness.py:764` 调用 `generate_enhanced`（Agent 引擎）。
- 经典模式走 `main.py:140` 的 `match()` 与 `match_stream()`，**从不调用 `generate_enhanced`**。
- 本次对 `solution_matcher.py` 只**新增** `generate_enhanced_stream` 方法，**不修改** `match` / `match_stream` / `generate_enhanced` 任何一行。
- `harness.py`、`agent_routes.py` 整个文件都是 Agent 专属，经典不加载其逻辑。
- 结论：**经典模式后端代码 0 行改动**。

### 8.2 前端隔离
- 两套独立 JS、两套独立 DOM 根（已在 `index.html` 静态确认）：
  - 经典：`script.js`（`index.html:2205`）+ 根 `#classic-solution`（`:550`）+ 自有 SSE（解析 `token` 事件）。
  - Agent：`agent_workspace.js`（`index.html:2207`）+ 根 `#workspace-solution`（`:1757`）+ 自有 SSE（解析 `delta` 事件）。
- 本次前端只改 `agent_workspace.js` 的 `onEvent`（新增 `delta` 分支、改 `final` 收尾逻辑），**不触碰 `script.js`**。
- 破缓存只升 `agent_workspace.js?v=`（`:2207`），经典的 `script.js?v=20260817e`（`:2205`）不动。
- `delta` 与 `token` 是两种不同事件名，互不串台；经典前端不存在 `delta` 分支，Agent 前端不存在 `token` 分支。
- 结论：**经典模式前端代码 0 行改动，运行时零串扰**。

### 8.3 实施期隔离验证（动手后必做）
- 后端部署后跑一条经典匹配（标准/向导），确认返回结构、`token` 流式、`solution_json` 与改造前逐字节一致（可 git diff 比对 `match`/`match_stream` 确认无改动）。
- 前端硬刷经典视图，确认无报错、SSE 仍按 `token` 渲染、无 `delta` 相关异常。
- Agent 视图单独验证"逐字长出"，与经典互不影响。
