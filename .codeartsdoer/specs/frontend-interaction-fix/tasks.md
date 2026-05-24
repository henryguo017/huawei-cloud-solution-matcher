# 前端交互失效修复 - 编码任务规划

## 1. M1: 静态资源路径修正（P0-阻断）

- [ ] 修改 `frontend/index.html` 中 script.js 和 welcome-script.js 的引用路径，将相对路径 `script.js`、`welcome-script.js` 改为绝对路径 `/static/script.js`、`/static/welcome-script.js`
- [ ] 从 `frontend/login.html` 中移除 `<script src="/static/script.js"></script>` 引用，登录页面不需要主页交互逻辑
- [ ] 从 `frontend/register.html` 中移除 `<script src="/static/script.js"></script>` 引用，注册页面不需要主页交互逻辑
- [ ] 验证修改后三个HTML文件中所有CSS/JS资源路径均为 `/static/` 前缀的绝对路径，无遗漏的相对路径

## 2. M2: 欢迎遮罩层修复（P0-阻断）

- [ ] 修改 `frontend/welcome-styles.css` 中 `.welcome-page.hidden` 样式规则，添加 `pointer-events: none` 和 `z-index: -1` 双重保护，确保隐藏时不会拦截底层交互
- [ ] 修改 `frontend/welcome-script.js` 中 `WelcomeManager.hide()` 方法，增加 `this.welcomePage.style.pointerEvents = 'none'` 和 `this.welcomePage.style.zIndex = '-1'` 设置
- [ ] 修改 `frontend/welcome-script.js` 中 `WelcomeManager.show()` 方法，增加 `this.welcomePage.style.pointerEvents = 'auto'` 和 `this.welcomePage.style.zIndex = '9999'` 恢复
- [ ] 修改 `frontend/welcome-script.js` 中 `WelcomeManager.bindEvents()` 方法，增加按钮元素存在性检查：若 `startBtn` 或 `skipBtn` 为 null，打印 console.error 并自动调用 `this.hide()` 避免欢迎页永久遮挡
- [ ] 验证 `hide()` 方法设置了完整的隐藏属性组合：classList.add('hidden')、display:none、pointerEvents:none、zIndex:-1

## 3. M3: CDN容错加载（P1-严重）

- [ ] 修改 `frontend/index.html` 中 marked.js CDN 的 `<script>` 标签，添加 `onerror="console.warn('[CDN] marked.js加载失败，将使用纯文本降级')"` 属性
- [ ] 修改 `frontend/index.html` 中 chart.js CDN 的 `<script>` 标签，添加 `onerror="console.warn('[CDN] chart.js加载失败，图表功能不可用');window.__chartLoadFailed=true"` 属性
- [ ] 修改 `frontend/script.js` 中 `KnowledgeUI.renderChart()` 方法，在方法开头增加 Chart.js 可用性检查：若 `typeof Chart === 'undefined' || window.__chartLoadFailed` 为 true，调用降级方法并 return
- [ ] 在 `frontend/script.js` 中 `KnowledgeUI` 对象内新增 `renderChartFallback(canvas, industryCounts)` 方法，将 canvas 容器替换为纯文本列表形式的行业分布展示
- [ ] 验证 script.js 中 `UI.renderMarkdown()` 已有 `typeof marked !== 'undefined'` 降级检查逻辑，无需额外修改

## 4. M4: Token传递修复（P1-严重）

- [ ] 在 `frontend/script.js` 中 `API` 对象内新增 `_getHeaders()` 方法：构建基础 `{'Content-Type': 'application/json'}` 请求头，若 localStorage 中存在 access_token 则追加 `Authorization: Bearer {token}`
- [ ] 在 `frontend/script.js` 中 `API` 对象内新增 `_handleResponse(response)` 方法：若状态码为 401 则清除 localStorage 的 access_token 和 user_info、显示 Toast 提示"登录已过期，请重新登录"、1.5秒后跳转 login.html；若非 ok 则抛出 Error；否则返回 response.json()
- [ ] 修改 `frontend/script.js` 中 `API.match()` 方法，将 headers 替换为 `this._getHeaders()`，移除硬编码的 Content-Type，返回值使用 `this._handleResponse(response)` 处理
- [ ] 修改 `frontend/script.js` 中 `API.analyze()` 方法，将 headers 替换为 `this._getHeaders()`，返回值使用 `this._handleResponse(response)` 处理
- [ ] 修改 `frontend/script.js` 中 `API.getKnowledgeStats()` 方法，将 headers 替换为 `this._getHeaders()`，返回值使用 `this._handleResponse(response)` 处理
- [ ] 修改 `frontend/script.js` 中 `API.rebuildKnowledge()` 方法，将 headers 替换为 `this._getHeaders()`，返回值使用 `this._handleResponse(response)` 处理
- [ ] 修改 `frontend/script.js` 中 `API.clearKnowledge()` 方法，将 headers 替换为 `this._getHeaders()`，返回值使用 `this._handleResponse(response)` 处理
- [ ] 修改 `frontend/script.js` 中 `API.exportReport()` 方法，将 headers 替换为 `this._getHeaders()`，返回值使用 `this._handleResponse(response)` 处理
- [ ] 修改 `frontend/script.js` 中 `API.downloadExportFile()` 方法，从 localStorage 读取 token 并拼接到下载 URL 参数中
- [ ] 验证所有 API 方法均使用 `_getHeaders()` 和 `_handleResponse()`，无遗漏的硬编码 headers

## 5. M5: 脚本执行时序修复（P2-重要）

- [ ] 修改 `frontend/index.html` 中 auth-check.js 的 `<script>` 标签位置，从 `<body>` 顶部移至 `</body>` 前的脚本区域，排在 CDN 资源之后、script.js 之前
- [ ] 确保 `frontend/index.html` 中 `</body>` 前的脚本加载顺序为：CDN（marked.js、chart.js）→ auth-check.js → script.js → welcome-script.js
- [ ] 验证移除 auth-check.js 的 `<body>` 顶部旧引用位置，不留下残余的空 `<script>` 标签

## 6. M6: 事件监听健壮性加固（P3-一般）

- [ ] 修改 `frontend/script.js` 中 `match-btn` 的 click 回调，在获取 demandInput.value 前增加 demandInput 空值检查，为 null 时显示 Toast 错误提示并 return
- [ ] 修改 `frontend/script.js` 中 `clear-solution-btn` 的 click 回调，确保 demandInput、charCount 等元素使用可选链或空值检查保护
- [ ] 修改 `frontend/script.js` 中 `KnowledgeUI.loadStats()` 方法，在 catch 块中设置所有统计显示元素的默认值（文档数0、行业数0、准确率--%），并显示 Toast 友好提示
- [ ] 修改 `frontend/script.js` 中其他关键按钮（analyze-btn、rebuild-kb-btn、clear-kb-btn 等）的 click 回调，增加必要的目标元素存在性检查
- [ ] 修改 `frontend/welcome-script.js` 中 `WelcomeManager` 的其他方法（如 `startAnimations`、`initParticleCanvas`），确保目标元素不存在时不会抛出异常

## 7. 验证与测试

- [ ] TC-01 静态资源加载验证：打开 http://localhost:8000，F12 Network 面板确认所有 /static/* 资源返回 200，无 404
- [ ] TC-02 欢迎页关闭后交互恢复：点击"跳过引导"后，确认导航栏可切换、按钮可点击、输入框可聚焦
- [ ] TC-03 CDN 不可用时降级：屏蔽 cdn.jsdelivr.net 后刷新，确认页面可交互、Markdown 纯文本显示、图表降级为列表
- [ ] TC-04 已登录用户 API 携带 Token：登录后点击"开始匹配"，F12 Network 确认请求包含 Authorization 头
- [ ] TC-05 401 自动跳转：设置无效 Token 后发请求，确认 Toast 提示并自动跳转 login.html
- [ ] TC-06 登录后用户状态正确：登录后确认导航栏显示用户名和退出按钮，退出后切换为登录按钮
- [ ] TC-07 login/register 页面无主脚本干扰：访问 login.html 和 register.html，确认 Console 无 script.js 相关报错
