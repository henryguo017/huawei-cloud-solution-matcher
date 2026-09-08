# 规划：草稿保存 + 图片输入理解 + 情报订阅（2026-09-08）

> 范围：登录/OAuth 相关本轮不做（已有邮箱绑定）。三个功能按 ③→②→① 顺序推进，② 有 spike 门禁。
> 部署提醒：①③② 均含 py 变更或 DB schema 变更——**新表走 db_init.py，部署前需确认**；含 py 一律 restart 不能只热更。

---

## ③ 草稿保存（半天，先做）

**目标**：切换对话时未发送的输入内容不丢；回到对话自动恢复。

**设计**（纯前端，只动 `agent_workspace.js`）：
- 存储：`localStorage.agent_drafts_v1` = `{ [convoId]: { text, savedAt } }`，LRU 上限 50 条（超出淘汰最旧）
- 写入：`#ws-input` 的 `input` 事件 → 防抖 300ms → 按 `this.currentConvoId` 写入（与现有字数统计监听同点挂载）
- 恢复：`_openConvo` 渲染完消息后，读该 convo 草稿回填 textarea 并 `dispatchEvent(new Event('input'))`（联动字数统计）；`_newChat` 保持空
- 清除时机：`_send` 成功发出后删该 convo 草稿；删除对话（`_delete`/服务端 purge）时同步删草稿；归档**不清**（取消归档后草稿还在）
- 边界：convoId 缺失（欢迎页未建对话）时不写草稿，保持现状

**测试清单**：A 对话输入不发送→切 B 再切回→内容在；发送成功→草稿消失；删对话→草稿消失；50 条 LRU。

---

## ② 图片输入理解（spike 0.5 天 + 实现 1.5 天，spike 不通过则重新评估）

**P0 spike（门禁，先跑）**：
本地直接 curl DeepSeek，验证 `v4-pro`（`thinking.type=disabled`）与 `v4-flash` 接受
`content=[{type:"text",...},{type:"image_url",image_url:{url:"data:image/png;base64,..."}}]` 是否正常回答。
记录：是否支持、token 消耗、截图类文字识别质量。**不通过则本轮止步**（备选：OCR 文本兜底方案另议）。

**后端**：
- `AgentChatRequest` 增加 `images: Optional[List[str]] = []`（元素为 upload 接口返回的服务端相对路径）
- 安全校验（agent_routes）：路径必须 resolve 在 `user_docs/{uid}/customer_uploads/` 内 + 扩展名白名单（png/jpg/jpeg/webp）+ 每轮 ≤4 张——**防路径穿越读任意文件**
- 读取文件转 base64 data URL → 组装 vision 消息 → 传入 `get_agent().run(new param images=[...])`，harness 把图片块并入本轮用户消息
- ConversationMemory 只存文本：写入占位 `[本轮附带 N 张图片]`（历史恢复后图片不回放，可接受；聊天记录图片链接本地对话内可看）

**前端**（agent_workspace.js/css）：
- 附件按钮已 accept 图片（复用 `/api/upload/customer-file`，30MB 上限）；补两个入口：**textarea paste 事件**（Ctrl+V 截图直进）+ 输入框拖拽
- 待发图片以缩略图 chips 展示在输入框上方（可 × 删除）；客户端 canvas 压缩：最长边 2000px，超过才压，限 4 张
- `_send`：body 带 `images[]`，发出后清空 chips；用户气泡内渲染缩略图条（本地 blob URL）

**测试清单**：spike 结论表；粘贴/拖拽/按钮三入口；越权路径 403（伪造 `../users.db`）；4 张上限；未登录拦截图传（现有逻辑）；E2E 发图问"这张架构图里有什么，帮我出方案"。

---

## ① 情报订阅（定时自动化，后端 1 天 + 前端 0.5 天）

**目标**："每周一 9 点汇总 XX 行业竞品动态推飞书"，结果站内可查。

**数据模型**（`db_init.py`，两张新表）：
```
subscriptions(id, user_id, industry, competitors TEXT/*JSON 数组*/,
  frequency TEXT/*weekly_mon_9 | daily_9 | once*/, scheduled_at DATETIME/*once 专用*/,
  prompt_extra TEXT, enabled INT DEFAULT 1, channel TEXT DEFAULT 'feishu',
  last_run_at DATETIME, next_run_at DATETIME, created_at)
subscription_runs(id, subscription_id, ok INT, summary TEXT, elapsed REAL, created_at)
```

**调度器**（`api/main.py` startup_event 挂 asyncio task，零新依赖）：
- 每 60s 轮询 `enabled=1 AND next_run_at<=now` → 逐条执行；next_run_at 持久化在 DB，**restart 自动恢复不丢**
- 执行：组装 prompt（"联网搜索近 7 天 {industry} 行业及 {competitors} 的动态：产品发布/价格调整/中标项目/重要新闻，输出要点清单+来源链接" + prompt_extra）→ `get_agent().run()` 非流式，`session_id=sub_{id}_{ts}`（**独立会话，不污染用户对话上下文**），headless permissions，`user_id` 归属订阅者（KB 上下文正确）
- 超时 420s 包裹；失败重试 1 次；`once` 执行后 `enabled=0`；周期任务算出下一次 next_run_at
- 推送：`notify.py` 按 user_id 取飞书绑定推送卡片；**未绑定不报错**——结果仅存 `subscription_runs`，站内可看
- 停机补跑策略：错过超 2 小时的周期任务直接跳到下一周期（避免重启后轰炸）

**API**（新 `api/subscription_routes.py`，全部 `Depends(get_current_user)` + rate_limit）：
- `GET /api/subscriptions` 列表（含最近一次 run 摘要）
- `POST /api/subscriptions` 新建（frequency 白名单校验；每人上限 10 条）
- `POST /api/subscriptions/{id}/toggle`、`DELETE /api/subscriptions/{id}`
- `POST /api/subscriptions/{id}/run-now` 手动触发（限流 1 次/分钟，便于测试与演示）

**前端**：把现有 `_openNotifySettings` 小弹层升级为**弹窗 + 两个页签**：「通知绑定」（现有内容平移）/「情报订阅」（列表 + 新建表单：行业文本、竞品多选 tag、频率单选、启用开关、立即运行按钮、最近结果预览）。Agent 只改 agent_workspace.js/css + index.html，经典模式不动。

**测试清单**：建/停/删/立即运行；once 执行后自动停用；未绑飞书时 run-now 站内可见结果；restart 后 next_run_at 恢复；跨用户 403；agent 长超时不阻塞其他订阅。

---

## 执行顺序与里程碑

| 批次 | 内容 | 交付物 |
|---|---|---|
| B1 | ③ 草稿保存 | 纯前端，v=20260909a，可单独部署 |
| B2 | ② spike | spike 结论 → 决定 ② 是否继续 |
| B3 | ② 实现（若 spike 过） | py+前端，restart 部署 |
| B4 | ① 情报订阅 | 两张新表（**DB schema 变更，部署前确认**）+ py + 前端 |
