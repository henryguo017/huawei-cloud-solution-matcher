/* ==========================================================================
 * AgentWorkspace —— Agent 视图（独立分支，与经典模式物理隔离）
 * --------------------------------------------------------------------------
 * 隔离铁律（违反即 bug）：
 *  1. 本模块只操作 #workspace-solution 根容器内的 DOM；绝不 query 经典元素
 *     （.classic-solution / .main-content / 经典顶栏 / #page-* / #demand-input 等）。
 *  2. 绝不读写经典全局状态/对象（State、PageTransition、AuthManager 内部字段等）。
 *     需要用户信息只走中性 API（window.Session.getToken() / getUsername()）。
 *  3. 跨视图通信只通过显式网关 ViewManager（只改 body.view-* 类）。
 *  4. SSE 只打 /api/agent/chat，带中性 Session 同源 JWT；不引用经典 API 模块。
 *  5. 样式全部在 frontend/css/agent_workspace.css（独立文件），不污染经典 style.css。
 * 反向约束：经典模块同样禁止引用本模块内部 DOM，双向隔离。
 *
 * v2 设计（用户拍板：深色框架统一 + 三栏工作台 + 侧栏胶囊 + 多行输入 + 方案预览抽屉）：
 *  - 左栏：品牌 + 新建 + 能力面板（胶囊 2 列）+ 历史对话（localStorage 持久化）
 *  - 中栏：深色工作区顶栏(跟随皮肤) + 对话流 + 多行 textarea 输入
 *  - 右栏：方案预览抽屉（默认展开；窄屏自动折叠为浮层；前端解析 result 文本填充）
 *  - 响应式：屏幕 < 1400px 时抽屉折叠为浮层 + 遮罩
 * ========================================================================== */
(function () {
    'use strict';

    var ROOT_ID = 'workspace-solution';
    var AGENT_ENDPOINT = '/api/agent/chat';
    var STORE_KEY = 'agent_convos_v1';
    var DRAWER_BREAKPOINT = 1400;
    var MAX_INPUT = 2000;
    var MAX_CONVOS = 50;
    /* Agent 工具栏默认模型：默认 deepseek-v4-pro（高质量），用户可切换 Pro/Flash */
    var DEFAULT_AGENT_MODEL = 'deepseek-v4-pro';
    var DEFAULT_AGENT_MODEL_LABEL = 'Deepseek-V4-Pro';
    var MODEL_LABEL_MAP = {
        'deepseek-v4-pro': 'Deepseek-V4-Pro',
        'deepseek-v4-flash': 'Deepseek-V4-Flash'
    };
    var THINKING_STORAGE_KEY = 'agent_thinking_enabled_v1';
    var MODEL_STORAGE_KEY = 'agent_model_choice_v1';

    /* 方案预览解析词库（v1 前端轻量解析，后续可由后端 structured 字段替代） */
    var PRODUCT_DB = {
        'IoTDA': { name: 'IoTDA', desc: '设备接入服务，支持 MQTT/CoAP/LwM2M', role: '核心接入层' },
        'ModelArts': { name: 'ModelArts', desc: 'AI 开发平台，Notebook + 训练 + 推理', role: '模型训练层' },
        'ECS': { name: 'ECS', desc: '弹性云服务器，应用托管基础算力', role: '应用部署层' },
        'CCE': { name: 'CCE', desc: '云容器引擎，Kubernetes 容器编排', role: '应用部署层' },
        'AOM': { name: 'AOM', desc: '应用运维管理，告警与运维大屏', role: '运维监控层' },
        'OBS': { name: 'OBS', desc: '对象存储服务，海量数据湖底座', role: '数据存储层' },
        'DWS': { name: 'DWS', desc: '数据仓库服务，PB 级分析', role: '数据分析层' },
        'ROMA Connect': { name: 'ROMA Connect', desc: '应用与数据集成平台', role: '集成层' },
        'FunctionGraph': { name: 'FunctionGraph', desc: '函数工作流，事件驱动 Serverless', role: '计算层' },
        'GES': { name: 'GES', desc: '图引擎服务，关系图谱分析', role: '数据分析层' },
        'SIS': { name: 'SIS', desc: '语音交互服务，ASR/TTS', role: 'AI 能力层' },
        'OCR': { name: 'OCR', desc: '文字识别服务，票据/证件/通用', role: 'AI 能力层' },
        'DIS': { name: 'DIS', desc: '数据接入服务，实时流数据总线', role: '数据接入层' }
    };
    var COMPETITOR_NAMES = ['阿里云', '腾讯云', 'AWS', 'Azure', '天翼云', '移动云', '百度智能云', '京东云'];
    var COST_PATTERNS = [
        /约\s*[￥¥]\s*([\d.]+)\s*元/g,
        /([\d.]+)\s*元\/小时/g,
        /([\d.]+)\s*元\/千条/g,
        /([\d.]+)\s*元\/月/g,
        /([\d.]+)\s*万元/g,
        /成本.*?([\d.]+)\s*万/g
    ];

    /* 能力路由表：点击填入结构化提示模板 + 会话打 capability 标签 */
    var CAPS = {
        'match': { label: '方案匹配', icon: 'i-search', tpl: '请在【行业，如制造业】为【客户/场景】做华为云方案匹配，输出可落地的产品组合、实施要点与预期收益。' },
        'compete': { label: '竞品分析', icon: 'i-swords', tpl: '请分析【竞品，如阿里云】与华为云在【场景/行业】的对比，给出优劣势、差异化卖点与应对话术。' },
        'kb': { label: '知识库问答', icon: 'i-book-open', tpl: '请从知识库检索【主题】相关资料，提炼关键结论并标注出处。' },
        'graph': { label: '产品图谱', icon: 'i-map', tpl: '请查询华为云【产品/领域，如 IoT/IoTDA】的产品图谱，说明能力边界与关联产品。' },
        'insight': { label: '客户洞察', icon: 'i-building-2', tpl: '请基于【客户画像/行业/需求】做客户洞察，给出切入策略与推荐方案。' },
        'dashboard': { label: '数据看板', icon: 'i-bar-chart-3', tpl: '请汇总当前账号的【指标，如方案覆盖度/使用趋势】数据看板要点与解读。' }
    };

    /* 欢迎区快捷场景（与侧栏能力并列，点击一键填入输入框） */
    var QUICK_SCENES = [
        '帮我在制造业客户做设备预测性维护方案匹配',
        '对比华为云与阿里云在政企安全领域的优劣势',
        '查询华为云 IoTDA 的产品图谱与关联产品',
        '从知识库检索智慧园区相关案例与方案'
    ];
    /* 欢迎区展示的核心能力胶囊（取 CAPS 中最常用的 4 个） */
    var WELCOME_CAP_KEYS = ['match', 'compete', 'graph', 'kb'];

    /* ---------------- 工具函数 ---------------- */
    function escHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function autoTitle(text) {
        var t = String(text || '').replace(/\r/g, '').split('\n')[0].trim();
        t = t.replace(/【[^】]*】/g, '');                       // 去【占位】
        t = t.replace(/^(请|帮我|我想|我们|客户|在|给|把|需要|想|要|麻烦|能否|可以)\s*/i, '');
        t = t.replace(/[，,。.！!？?\s]+$/g, '');
        t = Array.from(t).slice(0, 16).join('');               // ≤16 字（按 Unicode 码点）
        return t || '新对话';
    }
    function relTime(ts) {
        var d = Date.now() - (ts || 0);
        if (d < 60000) return '刚刚';
        if (d < 3600000) return Math.floor(d / 60000) + ' 分钟前';
        if (d < 86400000) return Math.floor(d / 3600000) + ' 小时前';
        return Math.floor(d / 86400000) + ' 天前';
    }
    /* 完整 Markdown 渲染（与经典 UI.simpleMarkdown 同级：表格/代码块/有序列表/链接/斜体/标题/横线）：
       自包含、不依赖经典模块；入参为原始文本，内部做 HTML 转义，安全。 */
    function renderMarkdown(text) {
        if (!text || typeof text !== 'string') return '';
        var html = escHtml(text);
        var codeBlocks = [];
        html = html.replace(/```[\s\S]*?```/g, function (m) {
            var idx = codeBlocks.length;
            var inner = m.replace(/```[\w]*\n?/, '').replace(/```$/, '');
            codeBlocks.push('<pre class="ws-code-block"><code>' + inner + '</code></pre>');
            return '___CODEBLOCK_' + idx + '___';
        });
        html = html.replace(/`([^`]+)`/g, '<code class="ws-code-inline">$1</code>');
        html = html.replace(/^### (.+)$/gm, '<h4 class="ws-md-h">$1</h4>');
        html = html.replace(/^## (.+)$/gm, '<h3 class="ws-md-h">$1</h3>');
        html = html.replace(/^# (.+)$/gm, '<h2 class="ws-md-h">$1</h2>');
        html = html.replace(/!\[([^\]]*)\]\(([^)]*)\)/g, function (_, alt) {
            var desc = String(alt || '').substring(0, 40);
            return '<span class="ws-md-img">[图片] ' + desc + '</span>';
        });
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function (_, label, url) {
            var u = String(url || '').trim().toLowerCase();
            var safe = /^(https?:|mailto:)/.test(u) ? url : '#';
            return '<a href="' + safe + '" target="_blank" class="ws-md-link">' + label + '</a>';
        });
        html = html.replace(/^[\s]*[-*+] (.+)$/gm, '<li>$1</li>');
        html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
        html = (function () {
            var lines = html.split('\n');
            var parseCells = function (line) { return line.split('|').slice(1, -1).map(function (c) { return c.trim(); }); };
            var buildTable = function (headerLine, dataLines) {
                var headers = parseCells(headerLine);
                var tbl = '<table class="ws-md-table"><thead><tr>';
                headers.forEach(function (h) { tbl += '<th>' + h + '</th>'; });
                tbl += '</tr></thead><tbody>';
                dataLines.forEach(function (row) {
                    var cells = parseCells(row);
                    if (cells.every(function (c) { return /^[\s\-:|]+$/.test(c) || c === ''; })) return;
                    tbl += '<tr>';
                    cells.forEach(function (c) { tbl += '<td>' + c + '</td>'; });
                    tbl += '</tr>';
                });
                tbl += '</tbody></table>';
                return tbl;
            };
            var isSeparator = function (line) { return /^\|[\s\-:|]{3,}\|$/.test(line.trim()); };
            var isTableRow = function (line) { return /^\s*\|.+\|$/.test(line); };
            var i = 0;
            while (i < lines.length) {
                if (isTableRow(lines[i])) {
                    var headerLine = lines[i].trim();
                    var sepIdx = -1;
                    for (var look = i + 1; look <= Math.min(i + 3, lines.length - 1); look++) {
                        if (isSeparator(lines[look])) { sepIdx = look; break; }
                        if (lines[look].trim() !== '' && !isTableRow(lines[look])) break;
                    }
                    if (sepIdx !== -1) {
                        var j = sepIdx + 1;
                        while (j < lines.length) {
                            if (isTableRow(lines[j]) || lines[j].trim() === '') j++; else break;
                        }
                        lines.splice(i, j - i, buildTable(headerLine, lines.slice(sepIdx + 1, j).filter(function (l) { return isTableRow(l); })));
                    } else {
                        var k = i + 1;
                        while (k < lines.length) {
                            if (isTableRow(lines[k]) || lines[k].trim() === '') k++; else break;
                        }
                        var rowLines = lines.slice(i, k).filter(function (l) { return isTableRow(l); });
                        if (rowLines.length >= 2) {
                            var colCount = parseCells(rowLines[0]).length;
                            var allSame = rowLines.every(function (r) { return parseCells(r).length === colCount; });
                            if (allSame && colCount >= 2) lines.splice(i, k - i, buildTable(rowLines[0], rowLines.slice(1)));
                            else i++;
                        } else i++;
                    }
                } else i++;
            }
            html = lines.join('\n');
            html = html.replace(/^(?:\s*\|.+\|)+$/gm, function (pipeBlock) {
                var pl = pipeBlock.trim().split('\n').filter(function (l) { return /^\s*\|/.test(l); });
                if (pl.length < 2) return pipeBlock;
                var maxc = Math.max.apply(null, pl.map(function (l) { return l.split('|').length - 2; }));
                if (maxc >= 2) return buildTable(pl[0].trim(), pl.slice(1).map(function (l) { return l.trim(); }));
                return pl.map(function (l) { return l.replace(/^\s*\|/, '').replace(/\|\s*$/, '').replace(/\|/g, ' | '); }).join('<br>');
            });
            return html;
        })();
        html = html.replace(/(?:<li>[\s\S]*?<\/li>)+/g, function (m) {
            return '<ul class="ws-md-ul">' + m.replace(/\n+/g, '') + '</ul>';
        });
        html = html.replace(/^---$/gm, '<hr class="ws-md-hr">');
        html = html.replace(/\n\n/g, '<br><br>');
        html = html.replace(/\n/g, '<br>');
        codeBlocks.forEach(function (block, idx) { html = html.replace('___CODEBLOCK_' + idx + '___', block); });
        return html;
    }

    var AgentWorkspace = {
        root: null,
        sessionId: null,
        currentCtrl: null,
        currentConvoId: null,
        _streamDone: false,            // 当前流式请求是否已结束（result/final 置真）
        _streamConvoId: null,          // 当前流式请求归属的对话 id（用于切走前兜底 flush）
        _streamFullAnswer: '',         // 当前流式已累积的完整回答（最新一份）
        activeCap: '',
        drawerOpen: false,
        prevNarrow: false,
        sidebarCollapsed: false,
        agentModel: DEFAULT_AGENT_MODEL,         // Agent 对话当前模型（用户可切 Pro/Flash）
        agentThinking: false,                    // Agent 对话是否启用深度思考
        selectedClient: null,          // 方案 B：当前客户上下文 {id, name, industry}
        clients: [],                   // /clients 缓存
        capOpen: true,                 // 能力面板是否展开（默认展开，进入 Agent 模式即展开能力入口）
        readOnly: false,               // 当前对话是否为只读（仅打开归档对话时为真：隐藏输入框、不允许继续对话）
        els: {},

        userToken: function () {
            return (window.Session && typeof window.Session.getToken === 'function') ? window.Session.getToken() : null;
        },
        userName: function () {
            if (!window.Session || typeof window.Session.getUsername !== 'function') return 'guo';
            var u = window.Session.getUsername();
            return u ? u.slice(0, 2) : 'guo';
        },

        init: function () {
            this.root = document.getElementById(ROOT_ID);
            if (!this.root) { console.warn('[AgentWorkspace] 未找到 #' + ROOT_ID); return; }
            this.sessionId = this._genSessionId();
            this.prevNarrow = window.innerWidth < DRAWER_BREAKPOINT;
            this.drawerOpen = false;                     // 默认收起，点击方案预览再以浮层覆盖方式展开
            this._render();
            this._bind();
            this._renderTasks();
            this._updateContextUI();
            this._loadClients();
            this._loadStats();
            this._updateDrawerState();
        },

        _render: function () {
            var menuHtml = '';
            Object.keys(CAPS).forEach(function (k) {
                menuHtml += '<button class="ws-menu-item" type="button" data-cap="' + k + '" id="ws-menu-' + k + '">' +
                    '<span class="ws-menu-icon"><svg class="icon" aria-hidden="true"><use href="#' + CAPS[k].icon + '"></use></svg></span>' +
                    '<span>' + CAPS[k].label + '</span>' +
                '</button>';
            });
            this.root.innerHTML =
                '<div class="ws-agent">' +
                    '<div class="ws-sidebar">' +
                        '<div class="ws-brand">' +
                            '<div class="ws-brand-titles">' +
                                '<span class="ws-brand-cloud-icon"><svg class="icon" aria-hidden="true"><use href="#i-cloud"></use></svg></span>' +
                                '<div class="ws-brand-texts">' +
                                    '<div class="ws-brand-title">华为云方案</div>' +
                                    '<div class="ws-brand-sub">Agent 模式</div>' +
                                '</div>' +
                            '</div>' +
                            '<button class="ws-sidebar-collapse-btn" id="ws-sidebar-toggle" type="button" title="收起 / 展开侧边栏">' +
                                '<svg class="icon" aria-hidden="true"><use href="#i-arrow-left"></use></svg>' +
                            '</button>' +
                        '</div>' +
                        '<div class="ws-menu">' +
                            '<button class="ws-menu-item" type="button" id="ws-new">' +
                                '<span class="ws-menu-icon"><svg class="icon" aria-hidden="true"><use href="#i-plus"></use></svg></span>' +
                                '<span>新建对话</span>' +
                            '</button>' +
                            '<div class="ws-context-readout" id="ws-context" title="当前对话绑定的客户上下文">' +
                                '<div class="ws-context-label-row">' +
                                    '<span class="ws-context-dot"></span>' +
                                    '<span class="ws-context-label">当前对话</span>' +
                                '</div>' +
                                '<div class="ws-context-body">' +
                                    '<span class="ws-context-btn-icon" id="ws-context-btn-icon"><svg class="icon" aria-hidden="true"><use href="#i-message-circle"></use></svg></span>' +
                                    '<span class="ws-context-current" id="ws-context-current">通用对话</span>' +
                                '</div>' +
                            '</div>' +
                            '<div class="ws-cap-group open" id="ws-cap-group">' +
                                '<button class="ws-menu-item ws-cap-toggle" type="button" id="ws-cap-toggle">' +
                                    '<span class="ws-menu-icon"><svg class="icon" aria-hidden="true"><use href="#i-grid"></use></svg></span>' +
                                    '<span>能力</span>' +
                                    '<svg class="icon ws-cap-caret" aria-hidden="true"><use href="#i-chevron-right"></use></svg>' +
                                '</button>' +
                                '<div class="ws-cap-list" id="ws-cap-list">' + menuHtml + '</div>' +
                            '</div>' +
                            '<div class="ws-menu-section">历史对话</div>' +
                            '<div class="ws-tasks" id="ws-tasks"><div class="ws-task-empty">暂无历史对话</div></div>' +
                            '<div class="ws-archive-entry" id="ws-archive-entry" role="button" tabindex="0" title="查看已归档对话">' +
                                '<svg class="icon" aria-hidden="true"><use href="#i-archive"></use></svg>' +
                                '<span class="ws-archive-entry-label">已归档对话</span>' +
                                '<span class="ws-archive-entry-count" id="ws-archive-entry-count">0</span>' +
                            '</div>' +
                        '</div>' +
                        '<div class="theme-switcher ws-theme-switcher" id="ws-theme-switcher">' +
                            '<span class="theme-label">THEME</span>' +
                            '<div class="theme-palette" id="ws-theme-palette">' +
                                '<div class="theme-option">' +
                                    '<button class="theme-color" type="button" data-skin="classic-blue" data-sidebar="#1B4F72" data-topbar="#154360" style="background:#1B4F72;" title="经典蓝"></button>' +
                                    '<span class="theme-name">经典蓝</span>' +
                                '</div>' +
                                '<div class="theme-option">' +
                                    '<button class="theme-color" type="button" data-skin="teal" data-sidebar="#17A58B" data-topbar="#148F77" style="background:#17A58B;" title="浅葱绿"></button>' +
                                    '<span class="theme-name">浅葱绿</span>' +
                                '</div>' +
                                '<div class="theme-option">' +
                                    '<button class="theme-color" type="button" data-skin="summer-yellow" data-sidebar="#D4AC0D" data-topbar="#B7950B" style="background:#D4AC0D;" title="盛夏黄"></button>' +
                                    '<span class="theme-name">盛夏黄</span>' +
                                '</div>' +
                                '<div class="theme-option">' +
                                    '<button class="theme-color" type="button" data-skin="peach-pink" data-sidebar="#E74C7A" data-topbar="#C23B65" style="background:#E74C7A;" title="桃桃粉"></button>' +
                                    '<span class="theme-name">桃桃粉</span>' +
                                '</div>' +
                            '</div>' +
                        '</div>' +
                        '<div class="ws-sidebar-footer">' +
                            '<div class="ws-sidebar-status">' +
                                '<span class="ws-footer-meta">文档 <b id="ws-nav-doc-count">--</b> · 行业 <b id="ws-nav-industry-count">--</b></span>' +
                                '<span class="ws-status-text"><span class="ws-status-dot"></span>Agent 就绪</span>' +
                            '</div>' +
                        '</div>' +
                    '</div>' +
                    '<div class="ws-main">' +
                        '<div class="ws-chat-header">' +
                            '<span class="ws-title" id="ws-title">新对话</span>' +
                            '<span class="ws-readonly-badge" id="ws-readonly-badge" style="display:none;">只读 · 已归档</span>' +
                            '<div class="ws-header-actions">' +
                                '<button class="ws-header-icon-btn" id="ws-drawer-toggle" type="button" title="方案预览" aria-label="方案预览">' +
                                    '<svg class="icon" aria-hidden="true"><use href="#i-layers"></use></svg>' +
                                '</button>' +
                                '<button class="ws-header-icon-btn" id="ws-archive" type="button" title="归档当前对话" aria-label="归档当前对话">' +
                                    '<svg class="icon" aria-hidden="true"><use href="#i-archive"></use></svg>' +
                                '</button>' +
                                '<button class="ws-header-icon-btn" id="ws-copy" type="button" title="复制对话" aria-label="复制对话">' +
                                    '<svg class="icon" aria-hidden="true"><use href="#i-copy"></use></svg>' +
                                '</button>' +
                                '<button class="ws-header-icon-btn" id="ws-header-more" type="button" title="更多" aria-label="更多">' +
                                    '<svg class="icon" aria-hidden="true"><use href="#i-more-horizontal"></use></svg>' +
                                '</button>' +
                            '</div>' +
                        '</div>' +
                        '<div class="ws-stream" id="ws-stream"></div>' +
                        '<div class="ws-context-hint" id="ws-context-hint" style="display:none;"></div>' +
                        '<div class="ws-input-bar">' +
                            '<div class="ws-input-row ws-input-row-top">' +
                                '<div class="ws-input-wrap">' +
                                    '<textarea id="ws-input" class="ws-input" rows="1" autocomplete="off" ' +
                                        'placeholder="输入需求，Shift+Enter 换行，Enter 发送（如：帮我在制造业客户做设备预测性维护方案匹配）"></textarea>' +
                                    '<span class="ws-input-count" id="ws-input-count">0 / ' + MAX_INPUT + '</span>' +
                                    '<div class="ws-input-actions" id="ws-input-actions">' +
                                        /* voice-input.js 注入的 .voice-mic-btn 出现在这里（target=.ws-input-actions），位于发送按钮之前 */
                                    '</div>' +
                                    '<button class="ws-send-btn" id="ws-send" type="button" title="发送" aria-label="发送">' +
                                        '<svg class="icon" aria-hidden="true"><use href="#i-send"></use></svg>' +
                                    '</button>' +
                                '</div>' +
                            '</div>' +
                            '<div class="ws-toolbar" id="ws-toolbar">' +
                                '<button class="ws-tool-btn ws-input-attach" id="ws-input-attach" type="button" title="附件 / 上传" aria-label="附件 / 上传">' +
                                    '<svg class="icon" aria-hidden="true"><use href="#i-plus"></use></svg>' +
                                    '<span class="ws-tool-btn-label">附件</span>' +
                                '</button>' +
                                '<button class="ws-tool-btn ws-thinking-toggle" id="ws-thinking-toggle" type="button" title="深度思考" aria-pressed="false" aria-label="深度思考">' +
                                    '<svg class="icon" aria-hidden="true"><use href="#i-sparkles"></use></svg>' +
                                    '<span class="ws-tool-btn-label">深度思考</span>' +
                                '</button>' +
                                '<div class="ws-model-pick" id="ws-model-pick">' +
                                    '<button class="ws-tool-btn ws-model-btn" id="ws-model-btn" type="button" title="选择模型" aria-haspopup="listbox">' +
                                        '<svg class="icon" aria-hidden="true"><use href="#i-cpu"></use></svg>' +
                                        '<span class="ws-tool-btn-label ws-model-label" id="ws-model-label">' + (DEFAULT_AGENT_MODEL_LABEL) + '</span>' +
                                        '<svg class="icon ws-model-caret" aria-hidden="true"><use href="#i-chevron-down"></use></svg>' +
                                    '</button>' +
                                    '<ul class="ws-model-menu" id="ws-model-menu" role="listbox" hidden>' +
                                        '<li role="option" data-value="deepseek-v4-pro" data-thinking="disabled" class="ws-model-item">' +
                                            '<span class="ws-model-item-name">Deepseek-V4-Pro</span>' +
                                            '<span class="ws-model-item-tag">高质量</span>' +
                                        '</li>' +
                                        '<li role="option" data-value="deepseek-v4-flash" data-thinking="disabled" class="ws-model-item">' +
                                            '<span class="ws-model-item-name">Deepseek-V4-Flash</span>' +
                                            '<span class="ws-model-item-tag">快速</span>' +
                                        '</li>' +
                                    '</ul>' +
                                '</div>' +
                            '</div>' +
                        '</div>' +
                        '<div class="ws-context-picker" id="ws-context-picker">' +
                            '<span class="ws-context-picker-label">客户上下文</span>' +
                            '<button class="ws-context-pick-btn" id="ws-context-pick-btn" type="button">' +
                                '<span class="ws-context-pick-icon" id="ws-context-pick-icon"><svg class="icon" aria-hidden="true"><use href="#i-message-circle"></use></svg></span>' +
                                '<span class="ws-context-pick-current" id="ws-context-pick-current">通用对话</span>' +
                                '<svg class="icon ws-context-pick-caret" aria-hidden="true"><use href="#i-chevron-down"></use></svg>' +
                            '</button>' +
                            '<div class="ws-context-pick-menu" id="ws-context-pick-menu" style="display:none;"></div>' +
                        '</div>' +
                    '</div>' +
                    '<div class="ws-drawer closed" id="ws-drawer">' +
                        '<div class="ws-drawer-header">' +
                            '<span>方案预览</span>' +
                            '<button class="ws-drawer-close" id="ws-drawer-close" type="button">收起</button>' +
                        '</div>' +
                        '<div class="ws-drawer-body" id="ws-drawer-body">' +
                            '<div class="ws-preview-empty" id="ws-preview-empty">' +
                                '<div class="ws-preview-empty-icon"><svg class="icon" aria-hidden="true"><use href="#i-layers"></use></svg></div>' +
                                '<div class="ws-preview-empty-title">暂无方案预览</div>' +
                                '<div class="ws-preview-empty-desc">发送需求后，Agent 生成的推荐产品、竞品对比、参考成本将在这里聚合。</div>' +
                            '</div>' +
                            '<div class="ws-preview-section" id="ws-preview-products" style="display:none;">' +
                                '<div class="ws-preview-title">推荐产品组合</div>' +
                                '<div class="ws-preview-list" id="ws-preview-product-list"></div>' +
                            '</div>' +
                            '<div class="ws-preview-section" id="ws-preview-competitors" style="display:none;">' +
                                '<div class="ws-preview-title">竞品对比</div>' +
                                '<div class="ws-preview-list" id="ws-preview-competitor-list"></div>' +
                            '</div>' +
                            '<div class="ws-preview-section" id="ws-preview-costs" style="display:none;">' +
                                '<div class="ws-preview-title">参考成本</div>' +
                                '<div class="ws-preview-list" id="ws-preview-cost-list"></div>' +
                            '</div>' +
                        '</div>' +
                    '</div>' +
                    '<div class="ws-drawer-mask" id="ws-drawer-mask"></div>' +
                '</div>';
            this.els = {
                title: this.root.querySelector('#ws-title'),
                chatHeader: this.root.querySelector('.ws-chat-header'),
                stream: this.root.querySelector('#ws-stream'),
                input: this.root.querySelector('#ws-input'),
                inputBar: this.root.querySelector('.ws-input-bar'),
                inputAttach: this.root.querySelector('#ws-input-attach'),
                count: this.root.querySelector('#ws-input-count'),
                sendBtn: this.root.querySelector('#ws-send'),
                thinkingToggle: this.root.querySelector('#ws-thinking-toggle'),
                modelPick: this.root.querySelector('#ws-model-pick'),
                modelBtn: this.root.querySelector('#ws-model-btn'),
                modelLabel: this.root.querySelector('#ws-model-label'),
                modelMenu: this.root.querySelector('#ws-model-menu'),
                tasks: this.root.querySelector('#ws-tasks'),
                archiveEntry: this.root.querySelector('#ws-archive-entry'),
                archiveEntryCount: this.root.querySelector('#ws-archive-entry-count'),
                drawer: this.root.querySelector('#ws-drawer'),
                drawerMask: this.root.querySelector('#ws-drawer-mask'),
                drawerToggle: this.root.querySelector('#ws-drawer-toggle'),
                copyBtn: this.root.querySelector('#ws-copy'),
                headerMore: this.root.querySelector('#ws-header-more'),
                drawerClose: this.root.querySelector('#ws-drawer-close'),
                previewEmpty: this.root.querySelector('#ws-preview-empty'),
                previewProducts: this.root.querySelector('#ws-preview-products'),
                previewProductList: this.root.querySelector('#ws-preview-product-list'),
                previewCompetitors: this.root.querySelector('#ws-preview-competitors'),
                previewCompetitorList: this.root.querySelector('#ws-preview-competitor-list'),
                previewCosts: this.root.querySelector('#ws-preview-costs'),
                previewCostList: this.root.querySelector('#ws-preview-cost-list')
            };
            this._renderWelcome();
        },

        _renderWelcome: function () {
            var stream = this.els.stream;
            if (!stream) return;
            // 全白居中 WorkBuddy 式欢迎区：标题 + 能力胶囊 + 经典 content-card 大输入框 + 快捷场景 + 知识库状态
            var capsHtml = WELCOME_CAP_KEYS.map(function (key) {
                var cap = CAPS[key];
                return '<button class="ws-cap-pill" type="button" data-cap="' + key + '">' +
                    '<svg class="icon" aria-hidden="true"><use href="#' + cap.icon + '"></use></svg>' +
                    '<span>' + escHtml(cap.label) + '</span>' +
                '</button>';
            }).join('');
            /* 快捷场景 chips 已在 v=20260825c 删除（4 个能力胶囊已替代其角色），scenesHtml 暂保留以兼容
               _scene 委托与旧版 _renderToolsTab 等老逻辑；不再渲染到 DOM */
            var scenesHtml = '';

            stream.innerHTML =
                '<div class="ws-welcome">' +
                    '<div class="ws-welcome-inner">' +
                        '<div class="ws-welcome-head">' +
                            '<div class="ws-welcome-title">华为云方案智能助手</div>' +
                            '<div class="ws-welcome-sub">描述你的客户需求，或选择下方能力胶囊快速开始，我来匹配方案、分析竞品、检索知识库。</div>' +
                        '</div>' +
                        '<div class="ws-caps-row">' + capsHtml + '</div>' +
                        '<div class="ws-welcome-hint">在下方输入需求 · 工具栏可加附件 / 切模型 / 启深度思考 / 语音输入</div>' +
                        '<div class="ws-kb-status">知识库就绪 · 点击上方能力可一键填入示例</div>' +
                    '</div>' +
                '</div>';
            this._hideWelcomeChrome();   // 欢迎态：隐藏 chat-header（已用 ws-welcome 居中标题替代），底部输入栏统一显示（含工具栏）
        },

        _bind: function () {
            var self = this, root = this.root;
            root.querySelector('#ws-new').addEventListener('click', function () { self._newChat(); });
            root.querySelector('#ws-send').addEventListener('click', function () { self._send(); });
            root.querySelector('#ws-archive').addEventListener('click', function () { self._archive(); });
            if (this.els.archiveEntry) {
                this.els.archiveEntry.addEventListener('click', function () { self._openArchiveModal(); });
                this.els.archiveEntry.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); self._openArchiveModal(); } });
            }
            root.querySelector('#ws-sidebar-toggle').addEventListener('click', function () { self._toggleSidebar(); });

            root.querySelector('#ws-drawer-toggle').addEventListener('click', function () { self._toggleDrawer(); });
            root.querySelector('#ws-drawer-close').addEventListener('click', function () { self._toggleDrawer(); });
            if (this.els.copyBtn) this.els.copyBtn.addEventListener('click', function () { self._copyConversation(); });
            if (this.els.headerMore) this.els.headerMore.addEventListener('click', function (e) { e.stopPropagation(); self._showHeaderMoreMenu(e.currentTarget); });
            root.querySelector('#ws-drawer-mask').addEventListener('click', function () { self._toggleDrawer(); });

            // ===== Agent 输入工具栏：附件 / 深度思考 / 模型选择 / 语音 =====
            if (this.els.thinkingToggle) {
                this.els.thinkingToggle.addEventListener('click', function () {
                    self.agentThinking = !self.agentThinking;
                    self.els.thinkingToggle.setAttribute('aria-pressed', self.agentThinking ? 'true' : 'false');
                    self.els.thinkingToggle.classList.toggle('active', self.agentThinking);
                    self.els.thinkingToggle.title = self.agentThinking ? '深度思考（已开启）' : '深度思考';
                    try { localStorage.setItem(THINKING_STORAGE_KEY, self.agentThinking ? '1' : '0'); } catch (_) {}
                });
            }
            if (this.els.modelBtn && this.els.modelMenu) {
                // 恢复用户上次选择
                var savedModel = null;
                try { savedModel = localStorage.getItem(MODEL_STORAGE_KEY); } catch (_) {}
                if (savedModel && MODEL_LABEL_MAP[savedModel]) {
                    this.agentModel = savedModel;
                    if (this.els.modelLabel) this.els.modelLabel.textContent = MODEL_LABEL_MAP[savedModel];
                    var savedLi = this.els.modelMenu.querySelector('[data-value="' + savedModel + '"]');
                    if (savedLi) {
                        this.els.modelMenu.querySelectorAll('.ws-model-item').forEach(function (x) { x.classList.remove('active'); });
                        savedLi.classList.add('active');
                    }
                } else {
                    var defaultLi = this.els.modelMenu.querySelector('[data-value="' + DEFAULT_AGENT_MODEL + '"]');
                    if (defaultLi) defaultLi.classList.add('active');
                }
                // 恢复深度思考开关
                var savedThinking = null;
                try { savedThinking = localStorage.getItem(THINKING_STORAGE_KEY); } catch (_) {}
                if (savedThinking === '1' && this.els.thinkingToggle) {
                    this.agentThinking = true;
                    this.els.thinkingToggle.classList.add('active');
                    this.els.thinkingToggle.setAttribute('aria-pressed', 'true');
                    this.els.thinkingToggle.title = '深度思考（已开启）';
                }
                this.els.modelBtn.addEventListener('click', function (e) {
                    e.stopPropagation();
                    var hidden = self.els.modelMenu.hidden;
                    self.els.modelMenu.hidden = !hidden ? true : false;
                });
                this.els.modelMenu.querySelectorAll('.ws-model-item').forEach(function (li) {
                    li.addEventListener('click', function (ev) {
                        ev.stopPropagation();
                        var val = li.getAttribute('data-value');
                        if (!val || !MODEL_LABEL_MAP[val]) return;
                        self.agentModel = val;
                        if (self.els.modelLabel) self.els.modelLabel.textContent = MODEL_LABEL_MAP[val];
                        self.els.modelMenu.querySelectorAll('.ws-model-item').forEach(function (x) { x.classList.remove('active'); });
                        li.classList.add('active');
                        self.els.modelMenu.hidden = true;
                        try { localStorage.setItem(MODEL_STORAGE_KEY, val); } catch (_) {}
                    });
                });
                // 点击外部关闭
                document.addEventListener('click', function (e) {
                    if (self.els.modelPick && self.els.modelPick.contains(e.target)) return;
                    self.els.modelMenu.hidden = true;
                });
            }
            // 语音输入：voice-input.js 的 TARGETS 已配置 #ws-input → .ws-toolbar。
            // 其 init() 只在 DOMContentLoaded 执行，此时 #ws-input 尚不存在；这里在渲染完成后补一次 init，
            // 让 voice-input.js 把真正的 .voice-mic-btn 注入到工具栏（与 [+附件][✨深度思考][模型] 同排）。
            if (window.CloudSolVoice && typeof window.CloudSolVoice.init === 'function') {
                try { window.CloudSolVoice.init(); } catch (_) {}
            }

            // 附件按钮：真实文件上传（POST /upload/customer-file，与经典模式同一接口）。
            // 上传成功后文件进入 user_docs/{uid}/customer_uploads/，Agent 的 list_dir/read_customer_file 可直接读取。
            if (this.els.inputAttach) {
                var fileInput = document.createElement('input');
                fileInput.type = 'file';
                fileInput.multiple = true;
                fileInput.style.display = 'none';
                fileInput.accept = '.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.md,.csv,.png,.jpg,.jpeg';
                root.appendChild(fileInput);
                this.els.inputAttach.addEventListener('click', function () {
                    fileInput.click();
                });
                fileInput.addEventListener('change', function () {
                    var files = Array.prototype.slice.call(fileInput.files || []);
                    fileInput.value = '';
                    if (!files.length) return;
                    var token = self.userToken();
                    var pending = files.length;
                    files.forEach(function (f) {
                        if (f.size > 30 * 1024 * 1024) {
                            pending--;
                            self._toast('超过 30MB 上限：' + f.name, 'warning');
                            if (pending <= 0) self._toast('文件上传完成', 'success');
                            return;
                        }
                        var form = new FormData();
                        form.append('file', f);
                        fetch('/api/upload/customer-file', {
                            method: 'POST',
                            headers: token ? { 'Authorization': 'Bearer ' + token } : {},
                            body: form
                        }).then(function (r) {
                            if (!r.ok) { var m = '上传失败 (' + r.status + ')'; return r.json().then(function (j) { throw new Error(j.detail || m); }); }
                            return r.json();
                        }).then(function () {
                            self._toast('已上传：' + f.name, 'success');
                        }).catch(function (e) {
                            self._toast((e && e.message) || '上传失败：' + f.name, 'warning');
                        }).finally(function () {
                            pending--;
                            if (pending <= 0) {
                                self._toast('文件上传完成，可在对话中让我读取客户资料', 'success');
                                var ta = root.querySelector('#ws-input');
                                if (ta) { ta.focus(); }
                            }
                        });
                    });
                });
            }

            // 方案 B：客户上下文选择器（放在主区输入框下方，点击展开下拉）
            var pickBtn = root.querySelector('#ws-context-pick-btn');
            var pickWrap = root.querySelector('#ws-context-picker');
            var pickMenu = root.querySelector('#ws-context-pick-menu');
            if (pickBtn && pickMenu) {
                pickBtn.addEventListener('click', function (e) {
                    e.stopPropagation();
                    var open = pickMenu.style.display === 'block';
                    pickMenu.style.display = open ? 'none' : 'block';
                    if (pickWrap) pickWrap.classList.toggle('open', !open);
                    self._renderContextMenu();     // 每次展开确保数据最新
                });
                // 点击外部关闭
                document.addEventListener('click', function (ev) {
                    if (pickWrap && pickWrap.contains(ev.target)) return;
                    pickMenu.style.display = 'none';
                    if (pickWrap) pickWrap.classList.remove('open');
                });
            }

            // 快捷场景 chips：v=20260825c 后删除（用户反馈太挤，4 个工具已全部进 input row）；
            // cap pills（4 个能力）仍保留在 welcome 区作快速入口。

            // 能力面板：折叠为单个入口，点击展开/收起
            var capToggle = root.querySelector('#ws-cap-toggle');
            var capGroup = root.querySelector('#ws-cap-group');
            var capList = root.querySelector('#ws-cap-list');
            if (capToggle && capList && capGroup) {
                // 初始状态由 this.capOpen 决定（默认 true，进入 Agent 即展开）
                capList.style.display = this.capOpen ? '' : 'none';
                capGroup.classList.toggle('open', this.capOpen);
                capToggle.addEventListener('click', function (e) {
                    e.stopPropagation();
                    self.capOpen = !self.capOpen;
                    capList.style.display = self.capOpen ? '' : 'none';
                    capGroup.classList.toggle('open', self.capOpen);
                });
            }

            var input = this.els.input;
            input.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); self._send(); }
            });
            input.addEventListener('input', function () { self._autoResizeInput(); self._updateCount(); });

            // 能力胶囊 / 欢迎场景 / compose 发送：事件委托（欢迎区会被 _renderWelcome 重渲染，委托可避免监听失效）
            root.addEventListener('click', function (e) {
                var pill = e.target.closest('.ws-cap-pill, .ws-menu-item[data-cap]');
                if (pill) {
                    var key = pill.getAttribute('data-cap');
                    if (!CAPS[key]) return;
                    self.activeCap = key;
                    var inp = self._getActiveInput();
                    inp.value = CAPS[key].tpl;
                    inp.focus();
                    root.querySelectorAll('.ws-menu-item[data-cap]').forEach(function (x) { x.classList.toggle('active', x.getAttribute('data-cap') === key); });
                    if (capList && capGroup) { capList.style.display = 'none'; capGroup.classList.remove('open'); }
                    self._autoResizeActive(); self._updateCount();
                    return;
                }
                var scene = e.target.closest('.ws-scene');
                if (scene) {
                    var idx = parseInt(scene.getAttribute('data-scene-idx'), 10);
                    var txt = QUICK_SCENES[idx] || '';
                    var inp2 = self._getActiveInput();
                    inp2.value = txt;
                    inp2.focus();
                    self._autoResizeActive(); self._updateCount();
                    return;
                }
                if (e.target.closest('#ws-compose-send')) { self._send(); return; }
            });
            // 欢迎 compose 输入框：Enter 发送 / 自动增高（委托，重渲染不失效）
            root.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' && !e.shiftKey && e.target && e.target.id === 'ws-compose-input') { e.preventDefault(); self._send(); }
            });
            root.addEventListener('input', function (e) {
                if (e.target && e.target.id === 'ws-compose-input') self._autoResizeActive();
            });
            window.addEventListener('resize', function () { self._onResize(); });

            // 主题切换器：与经典模式共用 body[data-skin]，点击即改全局皮肤
            var wsPalette = root.querySelector('#ws-theme-palette');
            if (wsPalette) {
                wsPalette.addEventListener('click', function (e) {
                    var btn = e.target.closest('.theme-color');
                    if (!btn) return;
                    var skin = btn.dataset.skin;
                    document.body.setAttribute('data-skin', skin);
                    try { localStorage.setItem('skin', skin); } catch (_) {}
                    self._syncThemeActive(skin);
                });
            }
            // 监听经典侧切换主题（反之亦然），保持两侧调色板 active 一致
            if (!self._themeObserver) {
                self._themeObserver = new MutationObserver(function () {
                    self._syncThemeActive(document.body.getAttribute('data-skin'));
                });
                self._themeObserver.observe(document.body, { attributes: true, attributeFilter: ['data-skin'] });
            }
            self._syncThemeActive(document.body.getAttribute('data-skin'));
        },

        _autoResizeInput: function () {
            var el = this.els.input;
            el.style.height = 'auto';
            el.style.height = Math.min(Math.max(el.scrollHeight, 44), 160) + 'px';
        },
        _updateCount: function () {
            var n = (this.els.input.value || '').length;
            this.els.count.textContent = n + ' / ' + MAX_INPUT;
            this.els.count.classList.toggle('ws-count-over', n > MAX_INPUT);
        },
        /* 欢迎态：隐藏 Agent 顶栏、底部输入框、上下文选择器与顶栏标题，
           让全白欢迎内容铺满主区 */
        _hideWelcomeChrome: function () {
            // 欢迎态只隐藏 chat-header（已用 ws-welcome 居中标题替代），不隐藏 inputBar 与 toolbar，
            // 这样新话题页也能看到模型选择/深度思考/语音等工具栏；compose 卡仅作欢迎引导填充
            if (this.els.chatHeader) this.els.chatHeader.style.display = 'none';
            if (this.els.title) this.els.title.style.display = 'none';
        },
        /* 对话态：显示 Agent 顶栏、底部输入框、上下文选择器与顶栏标题 */
        _showChatInput: function () {
            if (this.els.chatHeader) this.els.chatHeader.style.display = '';
            if (this.els.inputBar) this.els.inputBar.style.display = this.readOnly ? 'none' : '';
            var picker = this.root.querySelector('#ws-context-picker');
            if (picker) picker.style.display = this.readOnly ? 'none' : '';
            if (this.els.title) this.els.title.style.display = '';
            // 只读态：隐藏「归档当前对话」按钮（已归档无需再归档）、显示只读徽标
            var archiveBtn = this.root.querySelector('#ws-archive');
            if (archiveBtn) archiveBtn.style.display = this.readOnly ? 'none' : '';
            var badge = this.root.querySelector('#ws-readonly-badge');
            if (badge) badge.style.display = this.readOnly ? '' : 'none';
        },
        /* 当前激活输入框：欢迎态也统一使用底部 #ws-input（避免与工具栏重复的 compose 卡）。
   旧版 compose-input 在 v=20260824f 移除，但保留 def 逻辑不报错，详见 _renderWelcome。 */
        _getActiveInput: function () {
            return this.els.input;
        },
        _autoResizeActive: function () {
            var inp = this._getActiveInput();
            if (inp === this.els.input) { this._autoResizeInput(); return; }
            inp.style.height = 'auto';
            inp.style.height = Math.min(Math.max(inp.scrollHeight, 44), 200) + 'px';
        },
        _onResize: function () {
            var narrow = window.innerWidth < DRAWER_BREAKPOINT;
            if (narrow && !this.prevNarrow) this.drawerOpen = false;   // 进入窄屏自动折叠
            this.prevNarrow = narrow;
            this._updateDrawerState();
        },
        _toggleSidebar: function () {
            this.sidebarCollapsed = !this.sidebarCollapsed;
            var sidebar = this.root.querySelector('.ws-sidebar');
            if (sidebar) sidebar.classList.toggle('collapsed', this.sidebarCollapsed);
        },
        _toggleDrawer: function () {
            this.drawerOpen = !this.drawerOpen;
            this._updateDrawerState();
        },
        _updateDrawerState: function () {
            var drawer = this.els.drawer, mask = this.els.drawerMask, toggle = this.els.drawerToggle;
            if (!drawer || !mask || !toggle) return;
            drawer.classList.toggle('closed', !this.drawerOpen);
            toggle.classList.toggle('active', this.drawerOpen);
            mask.style.display = this.drawerOpen ? 'block' : 'none';
        },

        /* 生成 session_id：'user_<uid>_<ts>' 格式，含 user_id 防串号，
           未登录时降级为 'guest_<ts>'。后端 _parse_user_id 按冒号/前缀解析时仍可拿到 user_id
           （本次同步把后端 _parse_user_id 升级为支持 'user_<uid>_' 前缀）。 */
        _genSessionId: function () {
            var uid = null;
            try {
                var u = window.Session && typeof window.Session.getUser === 'function' ? window.Session.getUser() : null;
                if (u && u.id != null) uid = u.id;
            } catch (e) {}
            return (uid != null ? ('user_' + uid + '_') : 'guest_') + Date.now();
        },

        /* ---------------- 对话流程 ---------------- */
        _send: function () {
            var input = this._getActiveInput(), raw = input.value || '', message = raw.trim();
            if (!message) return;
            if (message.length > MAX_INPUT) { alert('消息长度超过 ' + MAX_INPUT + ' 字符限制'); return; }
            if (!this.userToken()) { this._showLoginHint(); return; }

            // 对话管理意图（问/打开/恢复归档）→ 本地处理，不调 LLM
            var intent = this._classifyIntent(message);
            if (intent) {
                this._appendUser(message);
                this.els.input.value = ''; this.els.input.style.height = 'auto'; this._updateCount();
                this._handleIntent(intent);
                return;
            }

            var isFirst = !this.currentConvoId;            // 用逻辑状态判定，不被 DOM 增删干扰：已有 currentConvoId 即"已在当前对话"
            var title = isFirst ? autoTitle(message) : null;

            this._appendUser(message);
            this.els.input.value = ''; this.els.input.style.height = 'auto'; this._updateCount();

            if (isFirst) {
                this.els.title.textContent = title;
                this._saveConvoMeta(title);
            }
            this._persistUser(message);                  // 补齐用户消息持久化（修复历史恢复丢半边）
            if (isFirst) {
                // 首条消息发出后隐藏主区选择器，上下文锁定为只读，避免聊到一半串客户
                var picker = this.root.querySelector('#ws-context-picker');
                if (picker) picker.style.display = 'none';
            }
            this._run(message);
        },
        _hasMessages: function () {
            var s = this.els.stream;
            return s && s.querySelectorAll('.ws-msg-wrap').length > 0;
        },
        _newChat: function () {
            this.sessionId = this._genSessionId();
            this.currentConvoId = null;
            this.readOnly = false;                      // 新对话默认可编辑（退出只读态）
            this.activeCap = '';
            this.selectedClient = null;                 // 新对话默认通用对话，重新选择客户
            this.els.title.textContent = '新对话';
            this._renderWelcome();
            this.els.input.value = ''; this.els.input.style.height = 'auto'; this._updateCount();
            this._clearPreview();
            this._updateContextUI();
            this.root.querySelectorAll('.ws-menu-item[data-cap]').forEach(function (x) { x.classList.remove('active'); });
            this._renderTasks();
        },
        /* 归档当前打开的对话（chat-header 右上"归档"按钮调用） */
        _archive: function (id) {
            var targetId = id || this.currentConvoId;
            if (!targetId) return;
            var convos = this._loadConvos();
            for (var i = 0; i < convos.length; i++) {
                if (convos[i].id === targetId) {
                    convos[i].archived = true;
                    convos[i].updatedAt = Date.now();
                    break;
                }
            }
            this._saveConvos(convos);
            if (targetId === this.currentConvoId) this._newChat();
            else this._renderTasks();
        },
        /* 取消归档 */
        _restore: function (id) {
            var convos = this._loadConvos();
            for (var i = 0; i < convos.length; i++) {
                if (convos[i].id === id) {
                    convos[i].archived = false;
                    convos[i].updatedAt = Date.now();
                    break;
                }
            }
            this._saveConvos(convos);
            this._renderTasks();
        },
        /* 真删：物理删除；二次确认由调用方负责 */
        _delete: function (id) {
            var convos = this._loadConvos().filter(function (c) { return c.id !== id; });
            this._saveConvos(convos);
            if (id === this.currentConvoId) this._newChat();
            else this._renderTasks();
        },
        /* 重命名：弹窗输入新标题，空/未变不保存 */
        _rename: function (id, newTitle) {
            var t = (newTitle || '').trim();
            if (!t) return false;
            var convos = this._loadConvos();
            for (var i = 0; i < convos.length; i++) {
                if (convos[i].id === id) {
                    convos[i].title = t.slice(0, 40);
                    convos[i].updatedAt = Date.now();
                    break;
                }
            }
            this._saveConvos(convos);
            if (id === this.currentConvoId) this.els.title.textContent = convos.find(function (c) { return c.id === id; }).title;
            this._renderTasks();
            return true;
        },
        /* 轻量 toast：优先用经典 UI.showToast，缺失时降级为 console */
        _toast: function (msg, type) {
            try {
                if (window.UI && typeof window.UI.showToast === 'function') {
                    window.UI.showToast(msg, type || 'info');
                } else if (window.alert) {
                    window.alert(msg);
                }
            } catch (e) { /* 忽略 */ }
        },
        /* 复制当前整段对话为纯文本到剪贴板（WorkBuddy 顶栏第 3 个图标） */
        _copyConversation: function () {
            var self = this;
            var found = null, list = this._loadConvos();
            for (var i = 0; i < list.length; i++) { if (list[i].id === this.currentConvoId) { found = list[i]; break; } }
            if (!found || !found.messages || !found.messages.length) {
                if (window.UI && window.UI.showToast) window.UI.showToast('当前没有可复制的对话', 'warning');
                return;
            }
            var text = (found.title || '对话') + '\n\n';
            found.messages.forEach(function (m) {
                var who = m.role === 'user' ? (self.userName() || '我') : '华为云方案助手';
                text += '【' + who + '】\n' + String(m.content || '').replace(/\n{3,}/g, '\n\n').trim() + '\n\n';
            });
            var done = function (ok) {
                if (window.UI && window.UI.showToast) window.UI.showToast(ok ? '对话已复制到剪贴板' : '复制失败', ok ? 'success' : 'error');
            };
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
            } else {
                try {
                    var ta = document.createElement('textarea');
                    ta.value = text; ta.style.position = 'fixed'; ta.style.left = '-9999px';
                    document.body.appendChild(ta); ta.select();
                    var ok = document.execCommand('copy');
                    document.body.removeChild(ta); done(ok);
                } catch (e) { done(false); }
            }
        },
        /* 顶栏 ⋮ 更多菜单：重命名 / 删除当前对话 */
        _showHeaderMoreMenu: function (anchor) {
            var self = this;
            var id = this.currentConvoId;
            if (!id) return;
            self._closeHeaderMoreMenu();
            var menu = document.createElement('div');
            menu.className = 'ws-header-more-menu';
            menu.innerHTML =
                '<button type="button" class="ws-header-more-item" data-act="rename">重命名</button>' +
                '<button type="button" class="ws-header-more-item danger" data-act="delete">删除对话</button>';
            document.body.appendChild(menu);
            var r = anchor.getBoundingClientRect();
            menu.style.top = (r.bottom + 6) + 'px';
            menu.style.right = Math.max(8, window.innerWidth - r.right) + 'px';
            menu.addEventListener('click', function (e) {
                var btn = e.target.closest('[data-act]');
                if (!btn) return;
                self._closeHeaderMoreMenu();
                var act = btn.getAttribute('data-act');
                if (act === 'rename') {
                    var cur = self._loadConvos().filter(function (c) { return c.id === id; })[0];
                    var v = window.prompt('重命名对话', (cur && cur.title) || '');
                    if (v != null) self._rename(id, v);
                } else if (act === 'delete') {
                    self._confirmDelete({ id: id });
                }
            });
            setTimeout(function () {
                document.addEventListener('click', self._headerMoreCloseHandler = function () { self._closeHeaderMoreMenu(); });
            }, 0);
        },
        _closeHeaderMoreMenu: function () {
            var m = document.querySelector('.ws-header-more-menu');
            if (m) m.parentNode.removeChild(m);
            if (this._headerMoreCloseHandler) { document.removeEventListener('click', this._headerMoreCloseHandler); this._headerMoreCloseHandler = null; }
        },
        /* 复制为新对话：拷贝当前消息列表、清空、更新 id/时间 */
        _cloneConvo: function (id) {
            var convos = this._loadConvos();
            var src = null;
            for (var i = 0; i < convos.length; i++) { if (convos[i].id === id) { src = convos[i]; break; } }
            if (!src) return;
            var newId = this._genSessionId();
            var cloned = JSON.parse(JSON.stringify(src));
            cloned.id = newId;
            cloned.title = (src.title || '未命名对话') + '（副本）';
            cloned.archived = false;
            cloned.updatedAt = Date.now();
            cloned.messages = [];                    // 新对话从空白开始
            convos.unshift(cloned);
            this._saveConvos(convos);
            this._renderTasks();
            this._openConvo(newId);
        },

        /* 把 conv 与时间分离为活跃 vs 归档两个数组（兼容老数据无 archived 字段） */
        _splitConvos: function () {
            var list = this._loadConvos();
            var active = [], archive = [];
            for (var i = 0; i < list.length; i++) {
                if (list[i].archived) archive.push(list[i]);
                else active.push(list[i]);
            }
            active.sort(function (a, b) { return (b.updatedAt || 0) - (a.updatedAt || 0); });
            archive.sort(function (a, b) { return (b.updatedAt || 0) - (a.updatedAt || 0); });
            return { active: active, archive: archive };
        },

        /* ---------------- ⋮ 菜单（WorkBuddy 风）与确认弹窗 ---------------- */
        _showTaskMenu: function (anchor, conv) {
            this._closeContextMenu();
            var rect = anchor.getBoundingClientRect();
            var self = this;
            var menu = document.createElement('div');
            menu.className = 'ws-context-menu';
            menu.id = 'ws-active-menu';
            menu.innerHTML =
                '<button type="button" class="ws-menu-item" data-act="rename">' +
                    '<svg class="icon" aria-hidden="true"><use href="#i-edit-2"></use></svg>' +
                    '<span>重命名</span>' +
                '</button>' +
                '<button type="button" class="ws-menu-item" data-act="clone">' +
                    '<svg class="icon" aria-hidden="true"><use href="#i-copy"></use></svg>' +
                    '<span>复制为新对话</span>' +
                '</button>' +
                '<button type="button" class="ws-menu-item" data-act="archive">' +
                    '<svg class="icon" aria-hidden="true"><use href="#i-archive"></use></svg>' +
                    '<span>归档</span>' +
                '</button>' +
                '<div class="ws-menu-divider"></div>' +
                '<button type="button" class="ws-menu-item danger" data-act="delete">' +
                    '<svg class="icon" aria-hidden="true"><use href="#i-trash-2"></use></svg>' +
                    '<span>删除</span>' +
                '</button>';
            document.body.appendChild(menu);
            // 定位：优先菜单右下角对齐按钮右下角；超出右边界则反向
            var mw = menu.offsetWidth, mh = menu.offsetHeight;
            var left = rect.right - mw;
            var top = rect.bottom + 6;
            if (left < 8) left = 8;
            if (top + mh > window.innerHeight - 8) top = rect.top - mh - 6;
            if (top < 8) top = 8;
            menu.style.left = left + 'px';
            menu.style.top = top + 'px';
            menu.addEventListener('click', function (e) {
                var btn = e.target.closest('[data-act]');
                if (!btn) return;
                e.stopPropagation();
                var act = btn.getAttribute('data-act');
                self._closeContextMenu();
                if (act === 'rename') self._renamePrompt(conv);
                else if (act === 'clone') self._cloneConvo(conv.id);
                else if (act === 'archive') {
                    self._archive(conv.id);
                    if (conv.id === self.currentConvoId) self._newChat();
                }
                else if (act === 'delete') self._confirmDelete(conv);
            });
            // 单击空白或 Esc 关闭
            var onDoc = function (ev) {
                if (!menu.contains(ev.target)) { self._closeContextMenu(); document.removeEventListener('mousedown', onDoc, true); }
            };
            var onKey = function (ev) { if (ev.key === 'Escape') { self._closeContextMenu(); document.removeEventListener('keydown', onKey, true); } };
            setTimeout(function () {
                document.addEventListener('mousedown', onDoc, true);
                document.addEventListener('keydown', onKey, true);
            }, 0);
        },
        _closeContextMenu: function () {
            var m = document.getElementById('ws-active-menu');
            if (m) m.remove();
        },
        _renamePrompt: function (conv) {
            var self = this;
            this._confirmDialog({
                title: '重命名对话',
                body: '给这条对话起一个新的标题。',
                inputValue: conv.title || '',
                primary: '保存',
                onConfirm: function (val) { self._rename(conv.id, val); }
            });
        },
        _confirmDelete: function (conv) {
            var self = this;
            this._confirmDialog({
                title: '删除这条对话？',
                body: '将永久删除该对话历史，删除后不可恢复。',
                inputValue: null,
                primary: '删除',
                danger: true,
                onConfirm: function () { self._delete(conv.id); }
            });
        },
        _confirmDialog: function (opts) {
            // 移除已有
            var old = document.getElementById('ws-confirm-overlay');
            if (old) old.remove();
            var overlay = document.createElement('div');
            overlay.className = 'ws-confirm-overlay';
            overlay.id = 'ws-confirm-overlay';
            var inputHtml = opts.inputValue !== null && opts.inputValue !== undefined
                ? '<input type="text" class="ws-confirm-input" id="ws-confirm-input" maxlength="40" value="' + escHtml(opts.inputValue) + '" />'
                : '';
            overlay.innerHTML =
                '<div class="ws-confirm" role="dialog" aria-modal="true">' +
                    '<div class="ws-confirm-header">' + escHtml(opts.title || '') + '</div>' +
                    '<div class="ws-confirm-body">' +
                        escHtml(opts.body || '') +
                        inputHtml +
                    '</div>' +
                    '<div class="ws-confirm-actions">' +
                        '<button type="button" class="ws-confirm-btn ghost" data-act="cancel">取消</button>' +
                        '<button type="button" class="ws-confirm-btn ' + (opts.danger ? 'danger' : 'primary') + '" data-act="ok">' + escHtml(opts.primary || '确定') + '</button>' +
                    '</div>' +
                '</div>';
            document.body.appendChild(overlay);
            var input = overlay.querySelector('#ws-confirm-input');
            if (input) { input.focus(); input.select(); }
            var close = function (val) {
                if (overlay.parentNode) overlay.remove();
                if (typeof opts.onClose === 'function') opts.onClose(val);
            };
            overlay.addEventListener('click', function (e) {
                var btn = e.target.closest('[data-act]');
                if (!btn) { if (e.target === overlay) { close(null); } return; }
                if (btn.getAttribute('data-act') === 'cancel') { close(null); return; }
                var val = input ? input.value : null;
                if (input && !val.trim()) { input.focus(); return; }
                if (typeof opts.onConfirm === 'function') opts.onConfirm(val);
                close(val);
            });
            if (input) {
                input.addEventListener('keydown', function (e) {
                    if (e.key === 'Enter') { e.preventDefault(); overlay.querySelector('[data-act="ok"]').click(); }
                    else if (e.key === 'Escape') { e.preventDefault(); overlay.querySelector('[data-act="cancel"]').click(); }
                });
            }
        },

        /* 取对话首句用户消息作为摘要（用于弹窗/聊天意图匹配） */
        _convoSnippet: function (c) {
            var msgs = c.messages || [];
            for (var i = 0; i < msgs.length; i++) {
                if (msgs[i].role === 'user' && msgs[i].content) return String(msgs[i].content);
            }
            return c.title || '';
        },

        /* 已归档对话管理弹窗：列表 + 搜索 + 打开/恢复/删除 */
        _openArchiveModal: function (searchQuery) {
            var self = this;
            self._closeArchiveModal();
            var overlay = document.createElement('div');
            overlay.className = 'ws-archive-modal-overlay';
            overlay.id = 'ws-archive-modal';
            overlay.innerHTML =
                '<div class="ws-archive-modal" role="dialog" aria-modal="true">' +
                    '<div class="ws-archive-modal-head">' +
                        '<div class="ws-archive-modal-title">已归档对话 <span class="ws-archive-modal-count" id="ws-archive-modal-count">0</span></div>' +
                        '<button type="button" class="ws-archive-modal-close" id="ws-archive-modal-close" aria-label="关闭">' +
                            '<svg class="icon" aria-hidden="true"><use href="#i-x"></use></svg>' +
                        '</button>' +
                    '</div>' +
                    '<div class="ws-archive-modal-search">' +
                        '<input type="text" id="ws-archive-modal-search" placeholder="搜索归档对话标题或内容…" />' +
                    '</div>' +
                    '<div class="ws-archive-modal-list" id="ws-archive-modal-list"></div>' +
                '</div>';
            document.body.appendChild(overlay);

            var listEl = overlay.querySelector('#ws-archive-modal-list');
            var countEl = overlay.querySelector('#ws-archive-modal-count');
            var searchEl = overlay.querySelector('#ws-archive-modal-search');

            function getArchived() {
                return self._loadConvos().filter(function (c) { return c.archived; })
                    .sort(function (a, b) { return (b.updatedAt || 0) - (a.updatedAt || 0); });
            }
            function renderList(q) {
                var items = getArchived();
                if (q) {
                    var kw = q.trim().toLowerCase();
                    items = items.filter(function (c) {
                        return (c.title || '').toLowerCase().indexOf(kw) >= 0 ||
                               self._convoSnippet(c).toLowerCase().indexOf(kw) >= 0;
                    });
                }
                countEl.textContent = getArchived().length;
                if (!items.length) {
                    listEl.innerHTML = '<div class="ws-archive-modal-empty">' + (q ? '没有匹配的归档对话' : '暂无归档对话') + '</div>';
                    return;
                }
                listEl.innerHTML = '';
                items.forEach(function (c) {
                    var card = document.createElement('div');
                    card.className = 'ws-archive-modal-card';
                    card.innerHTML =
                        '<div class="ws-archive-modal-card-top">' +
                            '<span class="ws-archive-modal-card-title">' + escHtml(c.title || '未命名对话') + '</span>' +
                            '<span class="ws-archive-modal-card-time">' + relTime(c.updatedAt) + '</span>' +
                        '</div>' +
                        '<div class="ws-archive-modal-card-snippet">' + escHtml(self._convoSnippet(c)) + '</div>' +
                        '<div class="ws-archive-modal-card-actions">' +
                            '<button type="button" class="ws-archive-modal-btn" data-act="open">打开</button>' +
                            '<button type="button" class="ws-archive-modal-btn danger" data-act="delete">删除</button>' +
                        '</div>';
                    card.querySelector('[data-act="open"]').addEventListener('click', function () {
                        self._openConvo(c.id); self._closeArchiveModal();
                    });
                    card.querySelector('[data-act="delete"]').addEventListener('click', function () {
                        self._confirmDialog({
                            title: '删除这条归档对话？',
                            body: '将永久删除该对话历史，删除后不可恢复。',
                            primary: '删除', danger: true,
                            onConfirm: function () {
                                self._delete(c.id);
                                renderList(searchEl.value);
                            }
                        });
                    });
                    listEl.appendChild(card);
                });
            }
            renderList(searchQuery || '');
            if (searchQuery) { searchEl.value = searchQuery; }

            overlay.querySelector('#ws-archive-modal-close').addEventListener('click', function () { self._closeArchiveModal(); });
            overlay.addEventListener('click', function (e) { if (e.target === overlay) self._closeArchiveModal(); });
            searchEl.addEventListener('input', function () { renderList(searchEl.value); });
            document.addEventListener('keydown', self._archiveModalKeyHandler = function (e) {
                if (e.key === 'Escape') self._closeArchiveModal();
            });
        },
        _closeArchiveModal: function () {
            var m = document.getElementById('ws-archive-modal');
            if (m && m.parentNode) m.parentNode.removeChild(m);
            if (this._archiveModalKeyHandler) { document.removeEventListener('keydown', this._archiveModalKeyHandler); this._archiveModalKeyHandler = null; }
        },

        /* ---- 对话框自然语言入口：识别「管理自己的对话」意图，本地处理不调 LLM ---- */
        _classifyIntent: function (text) {
            var raw = (text || '').trim();
            if (!raw) return null;
            var self = this;
            var t = raw.toLowerCase().replace(/\s+/g, '');
            // 列出归档：显式对话管理语境才匹配（勿写裸"我归档"，会命中"帮我归档一份方案"这类 RAG 请求）
            if (/(已归档|归档的对话|有哪些归档|归档了?哪些|归档列表|archived)/.test(t)) {
                return { action: 'list' };
            }
            // 打开：必须先命中一条归档对话才接管，否则交回 RAG（避免「打开华为云官网」误触发）
            // 恢复功能已删除（用户要求"打开之后不能继续对话"，归档为终态：仅查看/删除）
            var cand = this._extractIntent(t, [
                { action: 'open', keys: ['打开', '进入', '继续聊', 'open'] }
            ]);
            if (cand) {
                var q = (cand.query || '').toLowerCase().replace(/\s+/g, '');
                if (!q) return null;
                var list = this._loadConvos().filter(function (c) { return c.archived; });
                var hit = list.filter(function (c) { return (c.title || '').toLowerCase().indexOf(q) >= 0; })[0]
                       || list.filter(function (c) { return self._convoSnippet(c).toLowerCase().indexOf(q) >= 0; })[0];
                return hit ? cand : null;
            }
            // 搜索：原文须带「对话」语境才接管（剥离后 query 可能已无"对话"二字）
            var search = this._extractIntent(t, [{ action: 'search', keys: ['找一下', '搜索', '查一下', '找', '查', 'search'] }]);
            if (search && /(对话|conversation)/.test(t)) return search;
            return null;
        },
        _extractIntent: function (t, defs) {
            for (var i = 0; i < defs.length; i++) {
                var d = defs[i];
                for (var k = 0; k < d.keys.length; k++) {
                    var key = d.keys[k].toLowerCase().replace(/\s+/g, '');
                    var idx = t.indexOf(key);
                    if (idx >= 0) {
                        var after = t.slice(idx + key.length)
                            .replace(/^(对话|那个|一下|我的|conversation)/, '')
                            .replace(/(对话|conversation)$/, '');
                        if (after.length) return { action: d.action, query: after };
                    }
                }
            }
            return null;
        },
        _handleIntent: function (intent) {
            var self = this;
            // 列表 / 搜索 → 直接打开管理弹窗（搜索带预填词）
            if (intent.action === 'list' || intent.action === 'search') {
                this._openArchiveModal(intent.action === 'search' ? intent.query : null);
                return;
            }
            // 打开：在归档对话里按标题或首句模糊匹配；命中后只读打开（归档=只读）
            var list = this._loadConvos().filter(function (c) { return c.archived; });
            var q = (intent.query || '').toLowerCase().replace(/\s+/g, '');
            var match = null;
            if (q) {
                match = list.filter(function (c) { return (c.title || '').toLowerCase().indexOf(q) >= 0; })[0]
                     || list.filter(function (c) { return self._convoSnippet(c).toLowerCase().indexOf(q) >= 0; })[0];
            }
            if (!match) { this._openArchiveModal(); return; }   // 没匹配到 → 弹窗让用户挑
            this._openConvo(match.id);
            if (window.UI && window.UI.showToast) {
                window.UI.showToast('已打开：' + (match.title || ''), 'success');
            }
        },

        _showLoginHint: function () {
            alert('请先登录后使用 Agent 对话（登录后数据对同一账号生效）。');
        },

        _appendUser: function (text) {
            var stream = this.els.stream;
            // 只在欢迎态（首次提问）清掉 welcome 卡，进入对话态后追加新用户消息而非整体清空
            // ——旧版无条件 innerHTML='' 会把上一轮整段对话 UI 都覆盖掉，是用户报的"每次新问题覆盖旧消息"主因之一
            if (stream.querySelector('.ws-welcome')) stream.innerHTML = '';
            this._showChatInput();
            var samplesBar = this.root.querySelector('.ws-samples-bar');
            if (samplesBar) samplesBar.style.display = 'none';
            var wrap = document.createElement('div');
            wrap.className = 'ws-msg-wrap ws-msg-wrap-user';
            wrap.innerHTML =
                '<div class="ws-msg ws-msg-user">' +
                    '<div class="ws-msg-author">' + escHtml(this.userName() || 'guo') + '</div>' +
                    '<div class="ws-msg-body">' + renderMarkdown(text) + '</div>' +
                '</div>';
            stream.appendChild(wrap);
            this._scrollBottom();
        },
        _appendAgentShell: function () {
            var stream = this.els.stream;
            if (stream.querySelector('.ws-welcome')) stream.innerHTML = '';
            var samplesBar = this.root.querySelector('.ws-samples-bar');
            if (samplesBar) samplesBar.style.display = 'none';
            var wrap = document.createElement('div');
            wrap.className = 'ws-msg-wrap ws-msg-wrap-agent';
            wrap.innerHTML =
                '<div class="ws-msg ws-msg-agent">' +
                    '<div class="ws-msg-author">华为云方案助手</div>' +
                    '<div class="ws-msg-content">' +
                        '<div class="ws-thinking" id="ws-thinking">' +
                            '<button type="button" class="ws-thinking-head" id="ws-thinking-toggle">' +
                                '<span class="ws-think-spin"></span>' +
                                '<span class="ws-thinking-title">深度思考</span>' +
                                '<span class="ws-thinking-count" id="ws-thinking-count">0 步</span>' +
                                '<span class="ws-thinking-caret"><svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"/></svg></span>' +
                            '</button>' +
                            '<div class="ws-plan" id="ws-plan" style="display:none;">' +
                                '<div class="ws-plan-title">执行计划</div>' +
                                '<div class="ws-plan-list" id="ws-plan-list"></div>' +
                            '</div>' +
                            '<div class="ws-thinking-body" id="ws-thinking-body"></div>' +
                        '</div>' +
                        '<div class="ws-msg-tools" id="ws-tools"></div>' +
                        '<div class="ws-msg-answer" id="ws-answer"></div>' +
                        '<div class="ws-msg-actions" id="ws-actions" style="display:none;"></div>' +
                        '<div class="ws-msg-clarify" id="ws-clarify" style="display:none;"></div>' +
                    '</div>' +
                '</div>';
            stream.appendChild(wrap);
            this._scrollBottom();
            return {
                tools: wrap.querySelector('#ws-tools'),
                answer: wrap.querySelector('#ws-answer'),
                actions: wrap.querySelector('#ws-actions'),
                clarify: wrap.querySelector('#ws-clarify'),
                thinking: wrap.querySelector('#ws-thinking'),
                thinkingBody: wrap.querySelector('#ws-thinking-body'),
                thinkingToggle: wrap.querySelector('#ws-thinking-toggle'),
                plan: wrap.querySelector('#ws-plan'),
                planList: wrap.querySelector('#ws-plan-list'),
                wrap: wrap
            };
        },

        /* 向"思考过程"面板追加一行（流式）。返回该行元素，工具步骤可后续标记完成。 */
        _appendThinkingStep: function (text, kind) {
            var shell = this.currentShell;
            if (!shell || !shell.thinkingBody) return null;
            var body = shell.thinkingBody;
            var countEl = shell.thinking.querySelector('#ws-thinking-count');
            var step = document.createElement('div');
            step.className = 'ws-think-step' +
                (kind === 'tool' ? ' ws-think-step-tool' : '') +
                (kind === 'phase' ? ' ws-think-step-phase' : '');
            var icon = kind === 'tool'
                ? '<span class="ws-think-tool-spin"></span>'
                : (kind === 'phase' ? '<span class="ws-think-phase-dot"></span>' : '<span class="ws-think-dot-live"></span>');
            step.innerHTML = '<span class="ws-think-icon">' + icon + '</span>' +
                             '<span class="ws-think-text">' + escHtml(text) + '</span>';
            body.appendChild(step);
            this._thinkCount = (this._thinkCount || 0) + 1;
            if (countEl) countEl.textContent = this._thinkCount + ' 步';
            shell.thinking.classList.remove('collapsed');
            shell.thinking.classList.add('active');
            this._scrollBottom();
            return step;
        },
        _markLastToolStepDone: function () {
            var shell = this.currentShell;
            if (!shell) return;
            var steps = shell.thinkingBody.querySelectorAll('.ws-think-step-tool:not(.done)');
            if (steps.length) {
                var last = steps[steps.length - 1];
                last.classList.add('done');
                var spin = last.querySelector('.ws-think-tool-spin');
                if (spin) spin.outerHTML = '<span class="ws-think-check">✓</span>';
            }
        },
        /* P0 Plan 面板：渲染执行计划（Devin 式，执行前展示"它打算怎么做"） */
        _renderPlan: function (shell, steps, statusList) {
            if (!shell || !shell.plan || !shell.planList) return;
            var list = Array.isArray(steps) ? steps : [];
            if (!list.length) return;
            var status = Array.isArray(statusList) ? statusList : [];
            var self = this;
            shell.planList.innerHTML = '';
            list.forEach(function (s, i) {
                var st = status[i] === 'done' ? ' done' : (status[i] === 'running' ? ' running' : ' pending');
                var item = document.createElement('div');
                item.className = 'ws-plan-item' + st;
                item.setAttribute('data-index', String(i));
                item.innerHTML = '<span class="ws-plan-check"></span>' +
                    '<span class="ws-plan-text">' + escHtml(String(s)) + '</span>' +
                    '<button type="button" class="ws-plan-rerun" title="重跑本步" data-index="' + i + '">↻ 重跑</button>';
                shell.planList.appendChild(item);
            });
            // P2-D5：Plan 单步重跑（点击行内"重跑"按钮 → 复用 SSE 通道发 rerun_plan_index）
            shell.planList.querySelectorAll('.ws-plan-rerun').forEach(function (btn) {
                btn.addEventListener('click', function (e) {
                    e.stopPropagation();
                    var idx = parseInt(btn.getAttribute('data-index'), 10);
                    if (isNaN(idx)) return;
                    self._rerunPlanStep(shell, idx);
                });
            });
            shell.plan.style.display = 'block';
            this._scrollBottom();
        },
        /* P2-D5：Plan 单步重跑（发带 rerun_plan_index 的消息，复用同一 SSE 通道） */
        _rerunPlanStep: function (shell, idx) {
            var self = this;
            var input = this.root ? this.root.querySelector('#ws-input') : null;
            var btn = shell.planList.querySelector('.ws-plan-rerun[data-index="' + idx + '"]');
            if (btn) { btn.disabled = true; btn.textContent = '重跑中…'; }
            if (input) { input.disabled = true; }
            // 复用 _run 的 SSE 通道：追加一个轻量消息（rerun 由后端按 rerun_plan_index 分支处理）
            var promise = this._runWithRerun('重跑第 ' + (idx + 1) + ' 步', idx);
            if (promise && typeof promise.finally === 'function') {
                promise.finally(function () {
                    if (btn) { btn.disabled = false; btn.textContent = '↻ 重跑'; }
                    if (input) { input.disabled = false; }
                });
            }
        },
        /* P2-D5：向 /api/agent/chat 发 rerun_plan_index 请求（复用流式事件管线） */
        _runWithRerun: function (message, idx) {
            var self = this;
            var shell = this.currentShell;
            if (!shell) return;
            // 简化实现：直接调 _send 无法带 rerun_plan_index；这里走专用 SSE 请求
            return this._fetchRerun(shell, idx);
        },
        /* P2-D5：专用 SSE fetch（rerun_plan_index）→ 内联事件处理（agent_phase/tool/plan/doc/final/result） */
        _fetchRerun: function (shell, idx) {
            var self = this;
            var sessionId = this.sessionId || 'agent_' + (this.currentUserId || '');
            var token = '';
            try {
                var raw = localStorage.getItem('hwcloud_auth');
                if (raw) {
                    var data = JSON.parse(raw);
                    if (data && data.token) token = data.token;
                }
            } catch (e) { /* ignore */ }
            if (!token) { this._toast && this._toast('请先登录后再操作'); return; }
            var body = JSON.stringify({
                message: '__rerun_plan__',
                session_id: sessionId,
                rerun_plan_index: idx,
            });
            var ctrl = new AbortController();
            self.currentCtrl = ctrl;
            var fullAnswer = '';
            fetch('/api/agent/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
                body: body,
                signal: ctrl.signal,
            })
            .then(function (r) {
                if (!r.ok || !r.body) throw new Error('HTTP ' + r.status);
                var reader = r.body.getReader();
                var decoder = new TextDecoder('utf-8');
                var buf = '';
                var evtType = '';
                function handle(ev) {
                    var t = ev.type || evtType;
                    if (t === 'agent_phase') {
                        // P2-1-B：当前执行阶段徽标
                        self._appendThinkingStep('进入阶段：' + (ev.label || '') , 'phase');
                    } else if (t === 'tool_start') {
                        if (typeof ev.plan_index === 'number' && ev.plan_index >= 0) {
                            self._updatePlanStatus(shell, ev.plan_index, 'running');
                        }
                        self._appendThinkingStep('调用工具：' + (ev.tool || ev.name || '工具'), 'tool');
                    } else if (t === 'tool_end') {
                        self._markLastToolStepDone();
                        if (typeof ev.plan_index === 'number' && ev.plan_index >= 0) {
                            self._updatePlanStatus(shell, ev.plan_index, 'done');
                        }
                    } else if (t === 'delta') {
                        fullAnswer += (ev.text || '');
                        shell.answer.innerHTML = renderMarkdown(fullAnswer);
                    } else if (t === 'doc_generated') {
                        self._renderDocChip(shell, ev.download_url, ev.file_name, ev.fmt);
                    } else if (t === 'final' || t === 'final_answer') {
                        self._finishThinking();
                        if (typeof ev.plan_index === 'number' && ev.plan_index >= 0) {
                            self._updatePlanStatus(shell, ev.plan_index, 'done');
                        }
                        if (fullAnswer && fullAnswer.trim()) {
                            self._appendExportActions(shell, fullAnswer, ev.format_mode || 'solution');
                        }
                    } else if (t === 'result') {
                        self._finishThinking();
                        if (ev.answer) { fullAnswer = ev.answer; shell.answer.innerHTML = renderMarkdown(fullAnswer); }
                        if (Array.isArray(ev.plan_status)) {
                            ev.plan_status.forEach(function (st, i) {
                                if (st === 'done' || st === 'running') self._updatePlanStatus(shell, i, st);
                            });
                        }
                        if (fullAnswer && fullAnswer.trim()) {
                            self._appendExportActions(shell, fullAnswer, ev.format_mode || 'solution');
                        }
                    } else if (t === 'error') {
                        self._finishThinking();
                        shell.answer.innerHTML = '<div style="color:var(--error)">' + escHtml(ev.message || '重跑失败') + '</div>';
                    }
                    self._scrollBottom();
                }
                function pump() {
                    return reader.read().then(function (res) {
                        if (res.done) return;
                        buf += decoder.decode(res.value, { stream: true });
                        var parts = buf.split('\n\n');
                        buf = parts.pop();
                        parts.forEach(function (block) {
                            var lines = block.split('\n');
                            var data = null;
                            lines.forEach(function (ln) {
                                if (ln.startsWith('event:')) evtType = ln.slice(6).trim();
                                else if (ln.startsWith('data:')) data = ln.slice(5).trim();
                            });
                            if (data) {
                                try { handle(JSON.parse(data)); } catch (e) { /* ignore */ }
                            }
                        });
                        return pump();
                    });
                }
                return pump();
            })
            .catch(function (e) {
                if (e.name === 'AbortError') return;
                console.warn('[rerun] SSE 失败:', e);
            });
        },
        /* P1-1：把 plan 第 index 步状态切到 pending/running/done（实时点亮，与后端 plan_index 一一对应） */
        _updatePlanStatus: function (shell, index, status) {
            if (!shell || !shell.planList) return;
            if (typeof index !== 'number' || index < 0) return;
            var items = shell.planList.querySelectorAll('.ws-plan-item');
            if (index < items.length) {
                var el = items[index];
                el.classList.remove('pending', 'running', 'done');
                el.classList.add(status);
            }
        },
        _finishThinking: function () {
            var shell = this.currentShell;
            if (!shell) return;
            shell.thinking.classList.remove('active');
            shell.thinking.classList.add('done');
            var spin = shell.thinking.querySelector('.ws-think-spin');
            if (spin) { spin.textContent = '✓'; spin.classList.add('stop'); }
            var self = this;
            clearTimeout(this._thinkCollapseTimer);
            this._thinkCollapseTimer = setTimeout(function () {
                if (shell.thinking && !shell.thinking.classList.contains('user-open')) {
                    shell.thinking.classList.add('collapsed');
                }
            }, 1500);
        },

        _run: function (message) {
            var self = this;
            var shell = this._appendAgentShell();
            self.currentShell = shell;
            self._thinkCount = 0;
            var fullAnswer = '';
            var toolNames = [];
            var clarified = false;
            // 本次请求的归属标记：切换对话/视图后晚到的事件一律忽略，避免写入错误的对话
            var runConvoId = this.currentConvoId;
            var runSessionId = this.sessionId;
            // 流式进度落库相关（节流 + 离开时兜底 flush）
            var lastSave = 0;
            self._streamDone = false;
            self._streamConvoId = runConvoId;
            self._streamFullAnswer = '';
            // 预置一个 agent 占位：保证流式过程中即时落库，且后续 upsert 有确定目标（幂等、不重复）
            if (runConvoId) this._upsertAgentTail('', runConvoId);
            // 思考过程面板：手动折叠/展开（标记 user-open 以免被自动收起覆盖）
            shell.thinkingToggle.addEventListener('click', function () {
                shell.thinking.classList.toggle('collapsed');
                shell.thinking.classList.toggle('user-open');
                clearTimeout(self._thinkCollapseTimer);
            });

            // 真实 AbortController 作为请求中断句柄；TaskGuard 只负责"切换视图时"触发中断。
            var ctrl = new AbortController();
            self.currentCtrl = ctrl;
            if (window.TaskGuard && typeof window.TaskGuard.begin === 'function') {
                window.TaskGuard.begin('agent-chat', 'Agent 对话进行中', function () {
                    if (!ctrl.signal.aborted) ctrl.abort();
                });
            }

            function onEvent(ev) {
                // 归属校验：本次请求归属的对话若已被切换走，丢弃晚期事件（竞态隔离）
                if (self.currentConvoId !== runConvoId || self.sessionId !== runSessionId) return;
                var t = ev.type;
                if (t === 'plan') {
                    // P1-1 Plan 面板：渲染执行计划（带初始 plan_status：pending/running/done），随思考面板折叠/展开
                    self._renderPlan(shell, ev.steps || [], ev.plan_status || []);
                } else if (t === 'agent_phase') {
                    // P2-1-B：多智能体阶段徽标（需求分析师→方案架构师→质量校验官）
                    self._appendThinkingStep('进入阶段：' + (ev.label || ev.phase || '执行'), 'phase');
                } else if (t === 'thought') {
                    self._appendThinkingStep(ev.text || ev.message || '正在分析需求...', 'thought');
                } else if (t === 'tool_start') {
                    var nm = ev.name || ev.tool || '工具';
                    if (toolNames.indexOf(nm) < 0) toolNames.push(nm);
                    shell.tools.innerHTML = '<span class="ws-tools-label">已调用：</span>' + toolNames.map(function (n) {
                        return '<span class="ws-tool-chip"><span class="ws-tool-dot" style="background:var(--primary-color)"></span>' + escHtml(n) + '</span>';
                    }).join('');
                    self._appendThinkingStep('调用工具：' + nm, 'tool');
                    // P1-1：点亮对应 plan 步（running），与后端 plan_index 一一对应
                    if (typeof ev.plan_index === 'number' && ev.plan_index >= 0) {
                        self._updatePlanStatus(shell, ev.plan_index, 'running');
                    }
                } else if (t === 'tool_end') {
                    self._markLastToolStepDone();
                    // P1-1：点亮对应 plan 步（done）
                    if (typeof ev.plan_index === 'number' && ev.plan_index >= 0) {
                        self._updatePlanStatus(shell, ev.plan_index, 'done');
                    }
                    // P0 工具结果摘要：在工具行追加一句话结果说明，增强执行可见性
                    if (ev.summary) {
                        var toolLine = shell.thinkingBody.querySelector('.ws-think-step-tool.done:last-child');
                        if (toolLine) {
                            var note = document.createElement('div');
                            note.className = 'ws-think-tool-result';
                            note.textContent = ev.summary;
                            toolLine.appendChild(note);
                        }
                    }
                } else if (t === 'delta') {
                    // 边想边写：实时按完整 Markdown 渲染（与经典流式一致），半截语法容忍、不崩
                    fullAnswer += (ev.text || '');
                    self._streamFullAnswer = fullAnswer;
                    shell.answer.innerHTML = renderMarkdown(fullAnswer);
                    // 节流落库（~150ms）：既保证刷新/切走不丢，又不至于每字一次写 localStorage
                    var now = Date.now();
                    if (now - lastSave > 150) { lastSave = now; self._upsertAgentTail(fullAnswer, runConvoId); }
                } else if (t === 'final' || t === 'final_answer') {
                    self._finishThinking();
                    // P1-1：点亮最后一步（综合/生成步）为 done
                    if (typeof ev.plan_index === 'number' && ev.plan_index >= 0) {
                        self._updatePlanStatus(shell, ev.plan_index, 'done');
                    }
                    // 答案已由 delta 逐字长出；此处兜底把最终全文落库（覆盖 final 不带 answer 的情况）
                    self._streamFullAnswer = fullAnswer;
                    self._upsertAgentTail(fullAnswer, runConvoId);
                    self._streamDone = true;
                    self._renderTasks();
                    // P0：流式结束时同样追加导出操作行（避免只有 result 事件才出现）
                    if (fullAnswer && fullAnswer.trim()) {
                        self._appendExportActions(shell, fullAnswer, ev.format_mode || 'solution');
                    }
                } else if (t === 'doc_generated') {
                    // P1-2：后端已生成可下载文档 → 渲染下载 chip（与导出按钮共存）
                    self._renderDocChip(shell, ev.download_url, ev.file_name, ev.fmt);
                } else if (t === 'reflexion') {
                    // P1-3：Agent 自我反思 → 在思考面板追加反思气泡，让用户看到纠错过程
                    self._appendReflexionBubble(shell, ev.text || '');
                } else if (t === 'clarify') {
                    if (!clarified) {
                        clarified = true;
                        self._finishThinking();
                        var qs = ev.questions || [];
                        var html = '<div class="ws-clarify-title">需要补充信息：</div>';
                        qs.forEach(function (q) { html += '<div class="ws-clarify-q">· ' + escHtml(String(q)) + '</div>'; });
                        // 澄清续跑输入（后端 /api/agent/clarify 完整支持，这里补齐交互）
                        html += '<textarea class="ws-clarify-input" rows="2" placeholder="补充回答后点击提交，Agent 将继续为你生成方案…"></textarea>';
                        html += '<button class="ws-clarify-btn">提交回答并继续</button>';
                        shell.clarify.innerHTML = html;
                        shell.clarify.style.display = 'block';
                        var inp = shell.clarify.querySelector('.ws-clarify-input');
                        var btn = shell.clarify.querySelector('.ws-clarify-btn');
                        var cid = ev.clarify_id || '';
                        function doResume() {
                            var ans = inp.value.trim();
                            if (!ans) { inp.focus(); return; }
                            shell.clarify.style.display = 'none';
                            self._resumeClarify(cid, qs, ans, runConvoId);
                        }
                        btn.addEventListener('click', doResume);
                        inp.addEventListener('keydown', function (e) {
                            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') doResume();
                        });
                    }
                } else if (t === 'result') {
                    self._finishThinking();
                    if (ev.answer) { fullAnswer = ev.answer; self._streamFullAnswer = fullAnswer; shell.answer.innerHTML = renderMarkdown(fullAnswer); }
                    // P1-1：用 result 携带的 plan_status 终态，对齐/补全 Plan 面板点亮（防止个别 tool 事件丢失）
                    if (Array.isArray(ev.plan_status) && ev.plan_status.length) {
                        ev.plan_status.forEach(function (st, i) {
                            if (st === 'done' || st === 'running') self._updatePlanStatus(shell, i, st);
                        });
                    }
                    if (ev.questions && ev.questions.length && !clarified) {
                        clarified = true;
                        var q2 = '';
                        ev.questions.forEach(function (q) { q2 += '<div class="ws-clarify-q">· ' + escHtml(String(q)) + '</div>'; });
                        shell.clarify.innerHTML = '<div class="ws-clarify-title">需要补充信息：</div>' + q2;
                        shell.clarify.style.display = 'block';
                    }
                    self._updatePreview(fullAnswer);
                    // 幂等 upsert：result 多次触发也只更新尾部 agent，不会重复追加
                    self._upsertAgentTail(fullAnswer, runConvoId);
                    self._streamDone = true;
                    self._renderTasks();
                    // P0：答案就绪后追加导出操作行（模板在导出时应用，对话侧保持自主结构）
                    if (fullAnswer && fullAnswer.trim()) {
                        self._appendExportActions(shell, fullAnswer, ev.format_mode || 'solution');
                    }
                } else if (t === 'error') {
                    self._finishThinking();
                    shell.answer.innerHTML = '<div style="color:var(--error)">' + escHtml(ev.message || '请求失败') + '</div>';
                    self._streamDone = true;
                    // 若占位仍是空，清理掉，避免历史里留一个空 agent 气泡
                    self._cleanEmptyAgentTail(runConvoId);
                }
                self._scrollBottom();
            }

            this._chatStream(message, this.sessionId, ctrl.signal, onEvent)
            .catch(function (err) {
                // 仅当本次请求仍归属于当前对话时做清理，避免污染已切换走的对话
                var owns = (self.currentConvoId === runConvoId && self.sessionId === runSessionId);
                if (err && err.name === 'AbortError') {
                    self._finishThinking();
                } else if (err && err.message === 'UNAUTH') {
                    self._finishThinking();
                    self._showLoginHint();
                } else {
                    self._finishThinking();
                    shell.answer.innerHTML = '<div style="color:var(--error)">' + escHtml((err && err.message) || '网络错误') + '</div>';
                }
                if (owns) self._cleanEmptyAgentTail(runConvoId);
            })
                .finally(function () {
                    if (window.TaskGuard && typeof window.TaskGuard.end === 'function') {
                        window.TaskGuard.end('agent-chat');
                    }
                });
        },

        /* 独立 SSE 解析（不引用经典 API 模块） */
        _chatStream: function (message, sessionId, signal, onEvent) {
            var self = this;
            return fetch(AGENT_ENDPOINT, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (self.userToken() || '') },
                body: JSON.stringify({
                    message: message,
                    session_id: sessionId,
                    client_id: self.selectedClient ? self.selectedClient.id : null,
                    model: self.agentModel,
                    thinking: self.agentThinking ? 'enabled' : 'disabled'
                }),
                signal: signal
            }).then(function (resp) {
                if (resp.status === 401) return Promise.reject(new Error('UNAUTH'));
                if (!resp.ok) return Promise.reject(new Error('HTTP ' + resp.status));
                if (!resp.body || !resp.body.getReader) return Promise.reject(new Error('不支持的流'));
                var reader = resp.body.getReader();
                var decoder = new TextDecoder('utf-8');
                var buf = '';
                var evtType = 'message';
                function pump() {
                    return reader.read().then(function (r) {
                        if (r.done) return;
                        buf += decoder.decode(r.value, { stream: true });
                        var parts = buf.split('\n\n');
                        buf = parts.pop();
                        for (var i = 0; i < parts.length; i++) {
                            var block = parts[i];
                            var m = block.match(/^event:\s*(.+)$/m);
                            if (m) evtType = m[1].trim();
                            var dm = block.match(/^data:\s*([\s\S]*)$/m);
                            if (dm) {
                                try {
                                    var data = JSON.parse(dm[1]);
                                    data.type = data.type || evtType;
                                    onEvent(data);
                                } catch (e) { /* 忽略非 JSON 行 */ }
                            }
                        }
                        return pump();
                    });
                }
                return pump();
            });
        },

        /* 澄清续跑：带 clarify_id + 用户回答调 /api/agent/clarify（后端以嵌套 result.data 下发），
           把续跑生成的方案渲染进当前对话气泡。 */
        _resumeClarify: function (clarifyId, questions, answer, runConvoId) {
            var self = this;
            var shell = self.currentShell;
            if (!shell) return;
            self._streamDone = false;
            if (shell.thinking) shell.thinking.classList.add('active');
            self._appendThinkingStep('正在根据你的补充继续生成方案...', 'thought');
            var answers = [];
            if (questions && questions.length) {
                answers = questions.map(function (q) {
                    var qs = String(q);
                    if (typeof q === 'object' && q) qs = q.question || q.text || '';
                    return { question: qs, answer: answer };
                });
            } else {
                answers = [{ question: '', answer: answer }];
            }
            var ctrl = new AbortController();
            self._clarifyCtrl = ctrl;
            var fullAnswer = '';
            fetch('/api/agent/clarify', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + (self.userToken() || '') },
                body: JSON.stringify({
                    clarify_id: clarifyId,
                    answers: answers,
                    client_id: self.selectedClient ? self.selectedClient.id : null
                }),
                signal: ctrl.signal
            }).then(function (resp) {
                if (resp.status === 401) return Promise.reject(new Error('UNAUTH'));
                if (!resp.ok) return resp.text().then(function (t) { throw new Error('HTTP ' + resp.status + ': ' + t.slice(0, 120)); });
                var reader = resp.body.getReader();
                var decoder = new TextDecoder('utf-8');
                var buf = '';
                function pump() {
                    return reader.read().then(function (r) {
                        if (r.done) return;
                        buf += decoder.decode(r.value, { stream: true });
                        var parts = buf.split('\n\n');
                        buf = parts.pop();
                        parts.forEach(function (block) {
                            var evLine = '';
                            var dataLine = '';
                            block.split('\n').forEach(function (l) {
                                if (l.indexOf('event: ') === 0) evLine = l.slice(7).trim();
                                else if (l.indexOf('data: ') === 0) dataLine += l.slice(6);
                            });
                            if (!dataLine) return;
                            var ev;
                            try { ev = JSON.parse(dataLine); } catch (e) { return; }
                            if (evLine === 'result') {
                                // 续跑接口 result 为嵌套结构 {type:'result', data:{...}}
                                var d = ev.data || ev;
                                var ans = d.answer || '';
                                if (ans) { fullAnswer = ans; self._streamFullAnswer = fullAnswer; shell.answer.innerHTML = renderMarkdown(fullAnswer); }
                                self._updatePreview(fullAnswer);
                                self._upsertAgentTail(fullAnswer, runConvoId);
                                self._streamDone = true;
                                self._renderTasks();
                            } else if (evLine === 'error') {
                                throw new Error(ev.message || '续跑失败');
                            }
                        });
                        return pump();
                    });
                }
                return pump();
            }).catch(function (err) {
                self._finishThinking();
                if (shell.answer) shell.answer.innerHTML = '<div style="color:var(--error)">' + escHtml((err && err.message) || '续跑失败') + '</div>';
            }).finally(function () {
                self._finishThinking();
                self._scrollBottom();
            });
        },

        _scrollBottom: function () {
            var s = this.els.stream;
            if (s) s.scrollTop = s.scrollHeight;
        },

        /* ---------------- 方案预览抽屉（前端解析） ---------------- */
        _clearPreview: function () {
            this.els.previewEmpty.style.display = '';
            this.els.previewProducts.style.display = 'none';
            this.els.previewCompetitors.style.display = 'none';
            this.els.previewCosts.style.display = 'none';
            this.els.previewProductList.innerHTML = '';
            this.els.previewCompetitorList.innerHTML = '';
            this.els.previewCostList.innerHTML = '';
        },
        /* P0：答案就绪后追加导出操作行（模板在导出时应用，对话侧保持自主结构）
           format_mode: solution=方案书 / competitor=竞品对比；导出复用经典 /api/export/report 链路 */
        _appendExportActions: function (shell, answer, formatMode) {
            if (!shell || !shell.actions) return;
            var actions = shell.actions;
            if (actions.querySelector('.ws-export-btn')) return;  // 幂等：不重复追加
            actions.style.display = '';
            var isComp = formatMode === 'competitor';
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'ws-export-btn';
            btn.setAttribute('data-format', isComp ? 'competitor' : 'solution');
            btn.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#i-download"></use></svg>' +
                (isComp ? '导出竞品分析 (Word)' : '导出方案书 (Word)');
            // 用 appendChild 而非 innerHTML 替换：避免覆盖已存在的 doc_generated 下载 chip
            actions.appendChild(btn);
            var self = this;
            btn.addEventListener('click', function () {
                self._exportAnswer(shell, answer, btn.getAttribute('data-format'));
            });
        },
        /* P1-2：doc_generated 事件 → 渲染可下载文档 chip（与导出按钮共存于 actions 面板） */
        _renderDocChip: function (shell, downloadUrl, fileName, fmt) {
            if (!shell || !shell.actions) return;
            var actions = shell.actions;
            actions.style.display = '';
            var url = String(downloadUrl || '');
            if (!url) return;
            // 幂等：同一文件只渲染一个 chip
            var sel = '.ws-doc-chip[data-url="' + (window.CSS && CSS.escape ? CSS.escape(url) : url) + '"]';
            if (actions.querySelector(sel)) return;
            var label = fmt === 'pdf' ? 'PDF 已生成' : (fmt === 'pptx' ? 'PPTX 已生成' : 'Word 已生成');
            var chip = document.createElement('button');
            chip.type = 'button';
            chip.className = 'ws-doc-chip';
            chip.setAttribute('data-url', url);
            chip.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#i-download"></use></svg>' + escHtml(label);
            var self = this;
            chip.addEventListener('click', function () { self._downloadDoc(url); });
            actions.appendChild(chip);
        },
        /* P1-2：直接下载后端生成的文档（download_url 形如 /api/export/download/{task_id}，下载路由无需鉴权） */
        _downloadDoc: function (downloadUrl) {
            if (!downloadUrl) return;
            var url = String(downloadUrl);
            var self = this;
            fetch(url).then(function (fr) {
                if (!fr.ok) throw new Error('文件下载失败');
                return fr.blob();
            }).then(function (blob) {
                var obj = URL.createObjectURL(blob);
                var a = document.createElement('a');
                a.href = obj;
                document.body.appendChild(a);
                a.click();
                a.remove();
                URL.revokeObjectURL(obj);
                self._toast('文档已下载', 'success');
            }).catch(function (e) {
                console.error('[Agent doc] 下载失败:', e);
                self._toast('文档下载失败', 'error');
            });
        },
        /* P1-3：reflexion 事件 → 在思考面板追加反思气泡，让用户看到 Agent 自我纠错 */
        _appendReflexionBubble: function (shell, text) {
            if (!shell || !shell.thinkingBody) return;
            var note = document.createElement('div');
            note.className = 'ws-reflexion-bubble';
            note.innerHTML = '<span class="ws-reflexion-tag">反思</span>' +
                '<span class="ws-reflexion-text">' + escHtml(String(text || '')) + '</span>';
            shell.thinkingBody.appendChild(note);
            this._scrollBottom();
        },

        /* P0：调 /api/export/report 生成 Word 并下载（模板在导出端应用） */
        _exportAnswer: function (shell, answer, reportType) {
            var self = this;
            var btn = shell.actions ? shell.actions.querySelector('.ws-export-btn') : null;
            var orig = btn ? btn.innerHTML : '';
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<svg class="icon" aria-hidden="true"><use href="#i-loader"></use></svg> 生成中...';
            }
            var doErr = function (msg) {
                self._toast(msg || '导出失败，请重试', 'error');
            };
            var token = self.userToken() || '';
            fetch('/api/export/report', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token },
                body: JSON.stringify({
                    report_type: reportType,
                    format: 'word',
                    content: String(answer || ''),
                    title: reportType === 'competitor' ? '华为云竞品对比分析' : '华为云解决方案建议书',
                    metadata: { title: reportType === 'competitor' ? '华为云竞品对比分析' : '华为云解决方案建议书' },
                    source_documents: []
                })
            }).then(function (resp) {
                if (!resp.ok) return resp.json().catch(function () { return {}; }).then(function (d) {
                    throw new Error(d.detail || ('HTTP ' + resp.status));
                });
                return resp.json();
            }).then(function (data) {
                var status = String(data.status || '').toUpperCase();
                if (status !== 'COMPLETED') throw new Error(data.error_message || '方案书生成失败');
                var dlPath = String(data.download_url || '').replace(/^\/api/, '');
                return fetch('/api' + dlPath).then(function (fr) {
                    if (!fr.ok) throw new Error('文件下载失败');
                    return fr.blob().then(function (blob) {
                        var url = URL.createObjectURL(blob);
                        var a = document.createElement('a');
                        a.href = url;
                        a.download = data.file_name || (reportType === 'competitor' ? 'competitor_report.docx' : 'solution_report.docx');
                        document.body.appendChild(a);
                        a.click();
                        a.remove();
                        URL.revokeObjectURL(url);
                        self._toast('文档已生成并下载', 'success');
                    });
                });
            }).catch(function (e) {
                console.error('[Agent导出] 失败:', e);
                doErr(e && e.message);
            }).then(function () {
                // 不论成功/失败，最终还原按钮（之前只 catch 还原导致成功后卡"生成中..."）
                if (btn) { btn.disabled = false; btn.innerHTML = orig; }
            });
        },

        _updatePreview: function (text) {
            var t = String(text || '');
            var prods = [], comps = [], costs = [];
            Object.keys(PRODUCT_DB).forEach(function (k) {
                if (t.indexOf(k) >= 0) { var p = PRODUCT_DB[k]; prods.push('<div class="ws-preview-item"><div class="ws-preview-item-name">' + escHtml(p.name) + '</div><div class="ws-preview-item-desc">' + escHtml(p.desc) + '</div><div class="ws-preview-item-role">' + escHtml(p.role) + '</div></div>'); }
            });
            COMPETITOR_NAMES.forEach(function (n) {
                if (t.indexOf(n) >= 0) { comps.push('<div class="ws-preview-item"><div class="ws-preview-item-name">' + escHtml(n) + '</div><div class="ws-preview-item-desc">竞品对比维度：优势 / 短板 / 差异化卖点 / 应对话术</div></div>'); }
            });
            COST_PATTERNS.forEach(function (re) {
                var mm; re.lastIndex = 0;
                while ((mm = re.exec(t)) !== null) { costs.push('<div class="ws-preview-item"><div class="ws-preview-item-cost">' + escHtml(mm[0]) + '</div></div>'); if (mm.index === re.lastIndex) re.lastIndex++; }
            });
            var hasAny = prods.length || comps.length || costs.length;
            this.els.previewEmpty.style.display = hasAny ? 'none' : '';
            if (prods.length) { this.els.previewProducts.style.display = ''; this.els.previewProductList.innerHTML = prods.join(''); }
            else this.els.previewProducts.style.display = 'none';
            if (comps.length) { this.els.previewCompetitors.style.display = ''; this.els.previewCompetitorList.innerHTML = comps.join(''); }
            else this.els.previewCompetitors.style.display = 'none';
            if (costs.length) { this.els.previewCosts.style.display = ''; this.els.previewCostList.innerHTML = costs.join(''); }
            else this.els.previewCosts.style.display = 'none';
        },

        /* ---------------- 历史对话持久化（localStorage） ---------------- */
        _loadConvos: function () {
            try { var v = localStorage.getItem(STORE_KEY); return v ? JSON.parse(v) : []; } catch (e) { return []; }
        },
        _saveConvos: function (list) {
            try {
                // 活跃对话按更新时间降序，仅受 MAX_CONVOS(50) 上限约束；
                // 归档对话不计入上限，单独全量保留，避免堆积反噬活跃对话。
                var active = [], archived = [];
                for (var i = 0; i < list.length; i++) { (list[i].archived ? archived : active).push(list[i]); }
                active.sort(function (a, b) { return (b.updatedAt || 0) - (a.updatedAt || 0); });
                active = active.slice(0, MAX_CONVOS);
                localStorage.setItem(STORE_KEY, JSON.stringify(active.concat(archived)));
            } catch (e) {}
        },
        _saveConvoMeta: function (title) {
            var list = this._loadConvos();
            // 复用当前 sessionId 作为 conv.id —— 与后端 harness 用的 session_id 一一对应，
            // 使"恢复历史后继续提问"能命中后端 ConversationMemory 的累积，实现真上下文连续
            var id = this.sessionId || ('agent_' + Date.now());
            this.currentConvoId = id;
            list.unshift({
                id: id, title: title, cap: this.activeCap,
                clientId: this.selectedClient ? this.selectedClient.id : null,
                clientName: this.selectedClient ? this.selectedClient.name : null,
                updatedAt: Date.now(), messages: []
            });
            this._saveConvos(list);
            this._renderTasks();
        },
        /* 幂等写入：更新当前对话最后一条 agent 消息（而非重复追加）。
           convoId 可选——用于"离开对话前的兜底 flush"写入指定对话，不依赖 this.currentConvoId。 */
        _upsertAgentTail: function (answer, convoId) {
            var targetId = convoId || this.currentConvoId;
            if (!targetId) return;
            var list = this._loadConvos(), found = null;
            for (var i = 0; i < list.length; i++) { if (list[i].id === targetId) { found = list[i]; break; } }
            if (!found) return;
            if (!found.messages) found.messages = [];
            // 找到最后一条 agent 消息并就地更新；没有则新建一条
            for (var j = found.messages.length - 1; j >= 0; j--) {
                if (found.messages[j].role === 'agent') {
                    found.messages[j].content = answer;
                    found.updatedAt = Date.now();
                    this._saveConvos(list);
                    return;
                }
            }
            found.messages.push({ role: 'agent', content: answer });
            found.updatedAt = Date.now();
            this._saveConvos(list);
        },
        /* 清理预置的空 agent 占位（请求失败/被中断且尚无内容时调用），避免历史留空气泡 */
        _cleanEmptyAgentTail: function (convoId) {
            var targetId = convoId || this.currentConvoId;
            if (!targetId) return;
            var list = this._loadConvos(), found = null;
            for (var i = 0; i < list.length; i++) { if (list[i].id === targetId) { found = list[i]; break; } }
            if (!found || !found.messages || !found.messages.length) return;
            var last = found.messages[found.messages.length - 1];
            if (last.role === 'agent' && !String(last.content || '').trim()) {
                found.messages.pop();
                found.updatedAt = Date.now();
                this._saveConvos(list);
            }
        },
        _persistUser: function (text) {
            if (!this.currentConvoId) return;
            var list = this._loadConvos(), found = null;
            for (var i = 0; i < list.length; i++) { if (list[i].id === this.currentConvoId) { found = list[i]; break; } }
            if (!found) return;
            if (!found.messages) found.messages = [];
            found.messages.push({ role: 'user', content: text });
            this._saveConvos(list);
        },
        /* 渲染主列表 + 归档列表（避免一处刷新把对方也冲掉） */
        _renderTasks: function () {
            var self = this, s = this._splitConvos();
            var box = this.els.tasks;
            // 主列表
            if (!s.active.length) {
                box.innerHTML = '<div class="ws-task-empty">暂无历史对话</div>';
            } else {
                box.innerHTML = '';
                s.active.forEach(function (c) { box.appendChild(self._buildTaskItem(c, 'active')); });
            }
            // 已归档列表已从侧栏移除：归档数据保留（archived=true），由侧栏「已归档对话」入口 + 弹窗管理
            self._updateArchiveEntry();
        },
        /* 侧栏「已归档对话 (N)」入口：更新计数徽标；无归档时隐藏徽标（入口仍可见） */
        _updateArchiveEntry: function () {
            var entry = this.els.archiveEntry, count = this.els.archiveEntryCount;
            if (!entry || !count) return;
            var n = 0, list = this._loadConvos();
            for (var i = 0; i < list.length; i++) { if (list[i].archived) n++; }
            count.textContent = n;
            count.style.display = n > 0 ? '' : 'none';
        },
        _buildTaskItem: function (c, mode) {
            var self = this;
            var item = document.createElement('div');
            item.className = 'ws-task-item' + (c.id === self.currentConvoId ? ' active' : '');
            item.dataset.id = c.id;
            var tpl =
                '<div class="ws-task-name">' +
                    '<span class="ws-task-name-text">' + escHtml(c.title || '未命名对话') + '</span>' +
                    '<span class="ws-task-time">' + relTime(c.updatedAt) + '</span>' +
                '</div>';
            // 鼠标移上去时直接显示操作按钮（无方框、仅图标）；活跃项：归档+删除；归档项：恢复+删除
            var actionsHtml = (mode === 'archive')
                ? '<button type="button" class="ws-task-hover-btn" data-action="restore" title="恢复" aria-label="恢复">' +
                    '<svg class="icon" aria-hidden="true"><use href="#i-rotate-ccw"></use></svg>' +
                  '</button>' +
                  '<button type="button" class="ws-task-hover-btn danger" data-action="delete" title="删除" aria-label="删除">' +
                    '<svg class="icon" aria-hidden="true"><use href="#i-trash-2"></use></svg>' +
                  '</button>'
                : '<button type="button" class="ws-task-hover-btn" data-action="archive" title="归档" aria-label="归档">' +
                    '<svg class="icon" aria-hidden="true"><use href="#i-archive"></use></svg>' +
                  '</button>' +
                  '<button type="button" class="ws-task-hover-btn danger" data-action="delete" title="删除" aria-label="删除">' +
                    '<svg class="icon" aria-hidden="true"><use href="#i-trash-2"></use></svg>' +
                  '</button>';
            tpl += '<div class="ws-task-hover-actions">' + actionsHtml + '</div>';
            item.innerHTML = tpl;
            item.addEventListener('click', function (e) {
                var btn = e.target.closest('[data-action]');
                if (btn) {
                    e.stopPropagation();
                    var act = btn.getAttribute('data-action');
                    if (act === 'archive') self._archive(c.id);
                    else if (act === 'restore') self._restore(c.id);
                    else if (act === 'delete') self._confirmDelete(c);
                    return;
                }
                self._openConvo(c.id);
            });
            // 右键菜单仍保留作为补充入口（重命名/复制为新对话）
            item.addEventListener('contextmenu', function (e) {
                e.preventDefault();
                self._showTaskMenu(item, c);
            });
            return item;
        },
        _openConvo: function (id) {
            // 取消仍在进行的流式请求：避免晚期 delta/result 写入已被切换走的对话（竞态隔离）
            if (this.currentCtrl) {
                try { this.currentCtrl.abort(); } catch (_) {}
                this.currentCtrl = null;
            }
            clearTimeout(this._thinkCollapseTimer);
            this.currentShell = null;
            // 离开上一个对话前，把"尚未完成的流式回答"兜底落库，避免历史里丢半句
            var prevConvoId = this.currentConvoId;
            if (prevConvoId && prevConvoId !== id && this._streamConvoId === prevConvoId && !this._streamDone && this._streamFullAnswer) {
                this._upsertAgentTail(this._streamFullAnswer, prevConvoId);
            }
            this._streamConvoId = null;
            this._streamFullAnswer = '';

            var list = this._loadConvos(), found = null;
            for (var i = 0; i < list.length; i++) { if (list[i].id === id) { found = list[i]; break; } }
            if (!found) return;
            // 归档对话 → 只读：隐藏输入框、不允许继续对话（用户要求"打开之后不能继续对话"）
            this.readOnly = !!found.archived;
            this.currentConvoId = id;
            // 切换 sessionId 与 convId 对齐，让后续追问命中后端按 session_id 累积的 ConversationMemory
            this.sessionId = id;
            this.activeCap = found.cap || '';
            this.selectedClient = (found.clientId != null) ? { id: found.clientId, name: found.clientName } : null;
            this.els.title.textContent = found.title || '未命名对话';
            this._showChatInput();                          // 同步显示顶栏 + 底部输入框 + 选择器 + 标题
            this._updateContextUI();                   // 还原侧栏上下文显示
            // 历史对话：只读态或已绑定客户则隐藏主区选择器，未绑定且非只读则允许重新选择
            var picker = this.root.querySelector('#ws-context-picker');
            if (picker) picker.style.display = (this.readOnly || found.clientId != null) ? 'none' : '';
            this._clearPreview();
            this.root.querySelectorAll('.ws-menu-item[data-cap]').forEach(function (x) { x.classList.toggle('active', x.getAttribute('data-cap') === (found.cap || '')); });
            var stream = this.els.stream; stream.innerHTML = '';
            var msgs = found.messages || [];
            for (var j = 0; j < msgs.length; j++) {
                var m = msgs[j];
                var isUser = m.role === 'user';
                var wrap = document.createElement('div');
                wrap.className = 'ws-msg-wrap ' + (isUser ? 'ws-msg-wrap-user' : 'ws-msg-wrap-agent');
                wrap.innerHTML =
                    '<div class="ws-msg ' + (isUser ? 'ws-msg-user' : 'ws-msg-agent') + '">' +
                        '<div class="ws-msg-author">' + (isUser ? escHtml(this.userName() || 'guo') : '华为云方案助手') + '</div>' +
                        '<div class="ws-msg-body">' + renderMarkdown(m.content) + '</div>' +
                    '</div>';
                stream.appendChild(wrap);
            }
            if (!msgs.length) {
                // 空历史：保持 currentConvoId 不被回退 —— 避免用户在「打开一条空 conv」后发消息被识别成"新建"
                // 显示一个简洁的空态占位，等待用户提问
                stream.innerHTML =
                    '<div class="ws-empty-convo">' +
                        '<div class="ws-empty-convo-icon">' +
                            '<svg class="icon" aria-hidden="true"><use href="#i-message-circle"></use></svg>' +
                        '</div>' +
                        '<div class="ws-empty-convo-title">还没有消息</div>' +
                        '<div class="ws-empty-convo-sub">在下方输入你的需求，开始这段对话。</div>' +
                    '</div>';
            } else {
                var samplesBar = this.root.querySelector('.ws-samples-bar');
                if (samplesBar) samplesBar.style.display = 'none';
            }
            this._renderTasks();
            this._scrollBottom();
        },

        /* ---------------- 方案 B：客户上下文选择器 ---------------- */
        _loadClients: function () {
            var self = this, token = this.userToken();
            if (!token) return;
            fetch('/api/clients', { headers: { 'Authorization': 'Bearer ' + token } })
                .then(function (r) { return r.ok ? r.json() : { clients: [] }; })
                .then(function (data) {
                    self.clients = Array.isArray(data) ? data : (data.clients || []);
                    self._renderContextMenu();
                })
                .catch(function () { /* 拉取失败静默，选择器仍可回到通用对话 */ });
        },
        _loadStats: function () {
            var self = this;
            var token = this.userToken();
            // 未登录时静默跳过：与经典模式 KnowledgeUI.loadStats 一致，保持 -- 占位符（统计反映登录用户自己的知识库）
            if (!token) return;
            var headers = { 'Authorization': 'Bearer ' + token };
            fetch('/api/knowledge/stats', { headers: headers })
                .then(function (r) { return r.ok ? r.json() : {}; })
                .then(function (data) {
                    var docEl = self.root.querySelector('#ws-nav-doc-count');
                    var indEl = self.root.querySelector('#ws-nav-industry-count');
                    if (docEl) docEl.textContent = data.total_documents || 0;
                    if (indEl && data.supported_industries) indEl.textContent = data.supported_industries.length || 0;
                })
                .catch(function () { /* 统计失败保持 -- */ });
        },

        /* 主题切换：与经典模式共用 body[data-skin]，同步两侧调色板 active 态 */
        _syncThemeActive: function (skin) {
            document.querySelectorAll('.theme-color').forEach(function (b) {
                b.classList.toggle('active', b.dataset.skin === skin);
            });
            document.querySelectorAll('.mine-theme-dot').forEach(function (b) {
                b.classList.toggle('active', b.dataset.skin === skin);
            });
        },

        _renderContextMenu: function () {
            var menu = this.root.querySelector('#ws-context-pick-menu');
            if (!menu) return;
            var self = this;
            var html = '<div class="ws-context-item clear" data-id=""><span class="ws-context-item-icon"><svg class="icon" aria-hidden="true"><use href="#i-message-circle"></use></svg></span><span>通用对话</span></div>';
            this.clients.forEach(function (c) {
                html += '<div class="ws-context-item" data-id="' + escHtml(String(c.id)) + '">' +
                    '<span class="ws-context-item-icon"><svg class="icon" aria-hidden="true"><use href="#i-building-2"></use></svg></span>' +
                    '<div class="ws-context-item-body">' +
                        '<div class="ws-context-item-name">' + escHtml(c.name || ('客户' + c.id)) + '</div>' +
                        (c.industry ? '<div class="ws-context-item-meta">' + escHtml(c.industry) + '</div>' : '') +
                    '</div>' +
                '</div>';
            });
            menu.innerHTML = html;
            menu.querySelectorAll('.ws-context-item').forEach(function (it) {
                it.addEventListener('click', function () {
                    var id = it.getAttribute('data-id');
                    if (!id) { self._selectClient(null); return; }
                    var c = null;
                    for (var i = 0; i < self.clients.length; i++) {
                        if (String(self.clients[i].id) === id) { c = self.clients[i]; break; }
                    }
                    self._selectClient(c ? { id: c.id, name: c.name, industry: c.industry } : null);
                });
            });
            // 反映当前已选客户
            if (this.selectedClient) {
                menu.querySelectorAll('.ws-context-item').forEach(function (it) {
                    it.classList.toggle('active', it.getAttribute('data-id') === String(self.selectedClient.id));
                });
            }
        },
        _selectClient: function (client) {
            this.selectedClient = client;
            this._updateContextUI();
            // 关闭主区选择器菜单并同步 active 态
            var ctx = this.root.querySelector('#ws-context-picker');
            var menu = this.root.querySelector('#ws-context-pick-menu');
            if (ctx) ctx.classList.remove('open');
            if (menu) {
                menu.style.display = 'none';
                menu.querySelectorAll('.ws-context-item').forEach(function (it) {
                    it.classList.toggle('active', client && it.getAttribute('data-id') === String(client.id));
                });
            }
        },
        _updateContextUI: function () {
            var current = this.root.querySelector('#ws-context-current');
            var btnIcon = this.root.querySelector('#ws-context-btn-icon use');
            var pickCur = this.root.querySelector('#ws-context-pick-current');
            var pickIcon = this.root.querySelector('#ws-context-pick-icon use');
            var hint = this.root.querySelector('#ws-context-hint');
            if (this.selectedClient) {
                var label = this.selectedClient.name + (this.selectedClient.industry ? ' · ' + this.selectedClient.industry : '');
                if (current) current.textContent = label;
                if (btnIcon) btnIcon.setAttribute('href', '#i-building-2');
                if (pickCur) pickCur.textContent = label;
                if (pickIcon) pickIcon.setAttribute('href', '#i-building-2');
                if (hint) {
                    hint.style.display = '';
                    hint.innerHTML =
                        '<span class="ws-hint-icon"><svg class="icon" aria-hidden="true"><use href="#i-building-2"></use></svg></span>' +
                        '<span class="ws-hint-text">已关联客户：' + escHtml(this.selectedClient.name) + '，Agent 将参考该客户历史</span>' +
                        '<button class="ws-hint-clear" id="ws-hint-clear" type="button">清除</button>';
                    var self = this;
                    var clr = hint.querySelector('#ws-hint-clear');
                    if (clr) clr.addEventListener('click', function (e) { e.stopPropagation(); self._selectClient(null); });
                }
            } else {
                if (current) current.textContent = '通用对话';
                if (btnIcon) btnIcon.setAttribute('href', '#i-message-circle');
                if (pickCur) pickCur.textContent = '通用对话';
                if (pickIcon) pickIcon.setAttribute('href', '#i-message-circle');
                if (hint) hint.style.display = 'none';
            }
        }
    };

    window.AgentWorkspace = AgentWorkspace;

    // 暴露生命周期钩子，由 script.js 的 ViewManager 统一调度
    AgentWorkspace.beforeLeave = function () {
        if (window.TaskGuard && typeof window.TaskGuard.abortAll === 'function') {
            window.TaskGuard.abortAll();
        }
        if (AgentWorkspace.currentCtrl) {
            AgentWorkspace.currentCtrl.abort();
            AgentWorkspace.currentCtrl = null;
        }
        // 切走前兜底落库未完成的流式回答，避免历史里丢半句
        if (AgentWorkspace._streamConvoId && !AgentWorkspace._streamDone && AgentWorkspace._streamFullAnswer) {
            AgentWorkspace._upsertAgentTail(AgentWorkspace._streamFullAnswer, AgentWorkspace._streamConvoId);
        }
        AgentWorkspace._streamConvoId = null;
        AgentWorkspace._streamFullAnswer = '';
    };

    // 由 script.js ViewManager 在切换到 agent 视图时调用 init；
    // 兜底：如果本脚本执行时 body 已经是 agent（直接访问 agent 视图），也主动初始化。
    if (document.body.classList.contains('view-agent')) {
        AgentWorkspace.init();
    }
})();
