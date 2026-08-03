/* ============================================================
   cloudsol.cn 对话式主区组件（M1）
   独立模块：不修改 script.js 现有逻辑，通过全局对象对接。
   - 消息流渲染（用户/AI/思考/卡片）
   - 底部输入条（附件/模式/发送）
   - 会话管理（新建/切换/归档，M2 扩展）
   对接：window.API.agentMatchStream / window.applyAgentProgressEvents（存在则复用）
   标准/向导模式：完全走老逻辑，本组件仅接管 Agent 模式的对话体验。
   ============================================================ */
(function () {
    'use strict';

    // ---- 内部状态 ----
    const S = {
        messages: [],       // [{role:'user'|'agent', type:'text'|'think'|'card', content, html}]
        busy: false,        // 是否正在等待 AI 回复
        mode: 'agent',      // 当前模式（仅 agent 模式接管）
        abortCtrl: null,    // 当前请求 AbortController
        currentConvId: null, // 当前会话 id（M2）
    };

    // ---- DOM 引用（延迟获取） ----
    function $el(id) { return document.getElementById(id); }

    // ---- 工具：转义 ----
    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    // 简单 markdown 渲染（段落/粗体/列表/代码块/表格，够用即可）
    function md(s) {
        if (!s) return '';
        let out = esc(s);
        // 代码块
        out = out.replace(/```(\w*)\n([\s\S]*?)```/g, (m, lang, code) => `<pre><code>${code}</code></pre>`);
        // 行内代码
        out = out.replace(/`([^`\n]+)`/g, '<code>$1</code>');
        // 粗体
        out = out.replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>');
        // 表格（简单处理：| a | b | 行）
        const rows = out.split('\n');
        const rendered = rows.map(r => {
            if (r.trim().startsWith('|') && r.trim().endsWith('|')) {
                const cells = r.split('|').filter((_, i, a) => i > 0 && i < a.length - 1 || (a.length === 2));
                const clean = r.trim().replace(/^\||\|$/g, '').split('|').map(c => c.trim());
                if (clean.every(c => /^[-:]+$/.test(c))) return '<hr style="margin:2px 0">';
                return `<div style="display:flex;gap:8px;border-bottom:1px solid rgba(0,0,0,.06);padding:2px 0">${clean.map(c => `<span style="flex:1">${c}</span>`).join('')}</div>`;
            }
            return r;
        }).join('\n');
        // 列表
        out = rendered.replace(/^- (.*)$/gm, '<div>• $1</div>').replace(/^\d+\. (.*)$/gm, '<div>$1</div>');
        // 段落
        out = out.split('\n\n').map(p => `<p>${p.replace(/\n/g, '<br>')}</p>`).join('');
        return out;
    }

    // ---- 消息流渲染 ----
    function renderMessage(m) {
        const stream = $el('chat-stream');
        if (!stream) return;
        const row = document.createElement('div');
        row.className = 'chat-msg ' + (m.role === 'user' ? 'user' : 'agent');

        const avatar = document.createElement('div');
        avatar.className = 'chat-avatar';
        avatar.textContent = m.role === 'user' ? '我' : 'AI';

        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble';
        if (m.html) bubble.innerHTML = m.html;
        else bubble.innerHTML = md(m.content);

        row.appendChild(avatar);
        row.appendChild(bubble);
        stream.appendChild(row);
        stream.scrollTop = stream.scrollHeight;
    }

    function renderTyping() {
        const stream = $el('chat-stream');
        if (!stream) return;
        const row = document.createElement('div');
        row.className = 'chat-msg agent';
        row.id = 'chat-typing-row';
        row.innerHTML = `<div class="chat-avatar">AI</div><div class="chat-bubble"><div class="chat-typing"><span></span><span></span><span></span></div></div>`;
        stream.appendChild(row);
        stream.scrollTop = stream.scrollHeight;
    }

    function removeTyping() {
        const t = $el('chat-typing-row');
        if (t) t.remove();
    }

    function renderEmptyHint() {
        // A 回退：chat-shell 已删，空态由老 form 的 placeholders 提示
    }

    function renderMessage(m) {
        // A 回退：不再使用（chat-shell 已删，AI 答案由老 renderAgentResult 渲染）
    }

    function renderTyping() { /* A 回退：不再使用 */ }
    function removeTyping() { /* A 回退：不再使用 */ }

    function clearStream() {
        // A 回退：chat-shell 已删，clearStream 不再操作 DOM
    }

    // ==================== M2 会话管理 ====================
    // 会话列表容器（chat-shell 左侧栏）
    let convListRendered = false;

    // 当前会话 id（M2）：新建任务=null（后端用 user_id），切换会话=session_id
    S.currentConvId = null;

    // 加载会话列表（主区中间横向卡片）
    async function loadConversations() {
        const box = $el('page-conv-list');
        if (!box) return;
        if (!checkLoggedIn()) return;
        try {
            const raw = localStorage.getItem('hwcloud_auth');
            const d = raw ? JSON.parse(raw) : {};
            const resp = await fetch('/api/agent/conversations?include_archived=false', {
                headers: { 'Authorization': 'Bearer ' + d.token },
            });
            const data = await resp.json();
            const convs = data.conversations || [];
            box.innerHTML = '';
            if (!convs.length) {
                box.innerHTML = '<div class="page-conv-empty">暂无历史任务——开始你的第一次对话吧</div>';
                return;
            }
            convs.forEach(c => {
                const item = document.createElement('button');
                item.className = 'page-conv-item' + (S.currentConvId === c.session_id ? ' active' : '');
                item.dataset.session = c.session_id;
                item.innerHTML = `
                    <span class="page-conv-icon"><svg class="icon" aria-hidden="true"><use href="#i-message-circle"></use></svg></span>
                    <span class="page-conv-text">
                        <span class="page-conv-title">${esc(c.title || c.session_id)}</span>
                        <span class="page-conv-time">${esc(String(c.updated_at || '').slice(0, 16))}</span>
                    </span>
                    <span class="page-conv-archive-btn" title="归档（结束此任务，可在历史中找回）">
                        <svg class="icon" aria-hidden="true"><use href="#i-folder"></use></svg>
                    </span>`;
                item.addEventListener('click', (e) => {
                    if (e.target.closest('.page-conv-archive-btn')) return;
                    switchConversation(c.session_id);
                });
                item.querySelector('.page-conv-archive-btn').addEventListener('click', async (e) => {
                    e.stopPropagation();
                    await archiveConversation(c.session_id, true);
                });
                box.appendChild(item);
            });
        } catch (e) {
            console.warn('[ChatUI] 会话列表加载失败:', e);
        }
    }

    // 切换会话：加载该会话历史
    async function switchConversation(sessionId) {
        S.currentConvId = sessionId;
        clearStream();
        renderEmptyHint();
        // 高亮
        document.querySelectorAll('.page-conv-item').forEach(el => {
            el.classList.toggle('active', el.dataset.session === sessionId);
        });
        // 加载历史消息
        try {
            const raw = localStorage.getItem('hwcloud_auth');
            const d = raw ? JSON.parse(raw) : {};
            const resp = await fetch(`/api/agent/conversations/${encodeURIComponent(sessionId)}/messages`, {
                headers: { 'Authorization': 'Bearer ' + d.token },
            });
            if (resp.ok) {
                const data = await resp.json();
                const msgs = data.messages || [];
                const stream = $el('chat-stream');
                if (stream) {
                    const hint = stream.querySelector('.chat-empty-hint');
                    if (hint) hint.remove();
                }
                msgs.forEach(m => {
                    S.messages.push({ role: m.role === 'user' ? 'user' : 'agent', type: 'text', content: m.content });
                    renderMessage({ role: m.role === 'user' ? 'user' : 'agent', content: m.content });
                });
                if (msgs.length) {
                    const stream = $el('chat-stream');
                    if (stream) stream.scrollTop = stream.scrollHeight;
                }
            }
        } catch (e) {
            console.warn('[ChatUI] 切换会话加载失败:', e);
        }
    }

    // 新建任务：清除当前会话高亮 + 滚动到输入区
    function newConversation() {
        S.currentConvId = null;
        document.querySelectorAll('.page-conv-item').forEach(el => el.classList.remove('active'));
        // 焦点移到主页的 textarea
        const ta = document.getElementById('demand-input');
        if (ta) ta.focus();
    }

    // 归档会话
    async function archiveConversation(sessionId, archived) {
        try {
            const raw = localStorage.getItem('hwcloud_auth');
            const d = raw ? JSON.parse(raw) : {};
            const resp = await fetch(`/api/agent/conversations/${encodeURIComponent(sessionId)}/archive?archived=${archived}`, {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + d.token },
            });
            if (resp.ok) {
                // 若当前会话被归档则新建
                if (S.currentConvId === sessionId) newConversation();
                loadConversations();
                return true;
            }
        } catch (e) { console.warn('[ChatUI] 归档失败:', e); }
        return false;
    }

    // ---- 发送 ----
    async function send(text) {
        if (S.busy) return;
        text = (text || '').trim();
        if (!text) return;
        // 自检登录态：读 localStorage 检查 token + expiresAt
        if (!checkLoggedIn()) {
            try { if (typeof AuthManager !== 'undefined' && AuthManager._openModal) AuthManager._openModal(); } catch(_) {}
            return;
        }

        S.busy = true;
        S.abortCtrl = new AbortController();

        // 用户消息
        S.messages.push({ role: 'user', type: 'text', content: text });
        renderMessage({ role: 'user', content: text });
        renderTyping();

        // 输入框清空
        const input = $el('chat-input');
        if (input) { input.value = ''; input.style.height = 'auto'; }
        setSendDisabled(true);

        // 隐藏空态
        const hint = document.querySelector('.chat-empty-hint');
        if (hint) hint.remove();

        // 聚合 AI 回答
        let aiAnswer = '';
        let aiBubble = null;
        const stream = $el('chat-stream');

        const ensureAiBubble = () => {
            if (!aiBubble) {
                removeTyping();
                const row = document.createElement('div');
                row.className = 'chat-msg agent';
                row.innerHTML = `<div class="chat-avatar">AI</div><div class="chat-bubble" style="min-height:24px"></div>`;
                stream.appendChild(row);
                stream.scrollTop = stream.scrollHeight;
                aiBubble = row.querySelector('.chat-bubble');
            }
            return aiBubble;
        };

        try {
            // 处理单个 SSE 事件
            const onEvent = (event) => {
                if (!event || !event.type) return;
                // 思考流：追加到 AI 消息的折叠区
                if (event.type === 'thought' || event.type === 'tool_start' || event.type === 'tool_end'
                    || event.type === 'exec_cmd' || event.type === 'exec_stdout' || event.type === 'exec_stderr') {
                    const b = ensureAiBubble();
                    // 已有思考详情则复用，否则新建
                    let think = b.parentElement.querySelector('.chat-think');
                    if (!think) {
                        think = document.createElement('details');
                        think.className = 'chat-think';
                        think.innerHTML = `<summary>⚙️ 查看 AI 执行过程</summary><div class="chat-think-body"></div>`;
                        b.insertAdjacentElement('afterend', think);
                    }
                    const body = think.querySelector('.chat-think-body');
                    const d = document.createElement('div');
                    d.className = 'think-entry';
                    const txt = event.text || (event.tool ? `调用工具: ${event.tool}` : '') || event.cmd || event.line || '';
                    d.innerHTML = `<div class="think-text">${esc(String(txt).slice(0, 300))}</div>`;
                    body.appendChild(d);
                    body.scrollTop = body.scrollHeight;
                    return;
                }
                // 卡片事件：自包含渲染（不依赖 script.js 闭包里的 appendXxx）
                if (['pricing_info', 'competitor_table', 'solution_card', 'history_list', 'export_ready', 'file_created'].includes(event.type)) {
                    const b = ensureAiBubble();
                    const cardHost = document.createElement('div');
                    cardHost.innerHTML = renderAgentCard(event);
                    b.insertAdjacentElement('afterend', cardHost);
                    stream.scrollTop = stream.scrollHeight;
                    return;
                }
                // result：完整答案
                if (event.type === 'result') {
                    const data = event.data || {};
                    aiAnswer = data.answer || '';
                    if (aiAnswer) {
                        const b = ensureAiBubble();
                        b.innerHTML = md(aiAnswer);
                        stream.scrollTop = stream.scrollHeight;
                    }
                    return;
                }
                // final：完成后清 busy
                if (event.type === 'final') {
                    // no-op（result 会接上）
                }
                if (event.type === 'error') {
                    const b = ensureAiBubble();
                    b.innerHTML = `<span style="color:#9b1c1c">⚠️ ${esc(event.message || '出错了')}</span>`;
                }
            };

            // 直接 fetch（不依赖 window.API / window.AuthManager，self-contained）
            await agentStreamFetch(text, S.abortCtrl.signal, onEvent);
            // M2：消息完成后刷新会话列表（新任务/新消息都会 upsert）
            loadConversations();
        } catch (e) {
            if (e.name === 'AbortError') {
                removeTyping();
                S.messages.push({ role: 'agent', type: 'text', content: '（已取消）' });
                renderMessage({ role: 'agent', content: '已取消本次请求。' });
            } else {
                console.error('[ChatUI] 请求失败:', e);
                const b = ensureAiBubble();
                b.innerHTML = `<span style="color:#9b1c1c">⚠️ ${esc(e.message || '请求失败')}</span>`;
            }
        } finally {
            removeTyping();
            S.busy = false;
            S.abortCtrl = null;
            setSendDisabled(false);
            if (aiAnswer) {
                S.messages.push({ role: 'agent', type: 'text', content: aiAnswer });
            }
        }
    }

    function setSendDisabled(v) {
        const btn = $el('chat-send-btn');
        if (btn) btn.disabled = v;
    }

    // ---- 自包含渲染各类型结构化卡片 ----
    function renderAgentCard(event) {
        const t = event.type;
        if (t === 'pricing_info') {
            const items = (event.items || []).slice(0, 8);
            const rows = items.map(i => `<div class="price-row"><span class="price-name">${esc(i.product||'')}</span><span class="price-val">¥${i.ref_price||'-'}</span></div><div class="price-spec">${esc(i.spec||'')} ${esc(i.billing||'')}</div>`).join('');
            return `<div class="chat-bubble price-card"><div class="comp-title">💰 价目查询${event.query?'：「'+esc(event.query)+'」':''}</div>${rows||'<div>暂无匹配项</div>'}</div>`;
        }
        if (t === 'competitor_table') {
            const a = event.huawei_snippet || '';
            const b = event.competitor_snippet || '';
            return `<div class="chat-bubble comp-card"><div class="comp-title">⚖️ 竞品对比：华为云 vs ${esc(event.competitor||'')}</div><div class="comp-snippet"><b>华为云：</b>${esc(a).slice(0, 240)}</div><div class="comp-snippet"><b>${esc(event.competitor||'')}：</b>${esc(b).slice(0, 240)}</div></div>`;
        }
        if (t === 'solution_card') {
            const ind = event.industry ? `<span class="sol-industry">${esc(event.industry)}</span>` : '';
            const meta = event.word_count ? `<div class="sol-meta">约 ${event.word_count} 字</div>` : '';
            return `<div class="chat-bubble sol-card">${ind}<div class="sol-preview">${esc((event.preview||'').slice(0, 200))}</div>${meta}</div>`;
        }
        if (t === 'history_list') {
            const items = (event.items || []).slice(0, 10);
            const rows = items.map(i => `<div class="hist-row"><span class="hist-title">${esc(i.title||i.demand_text||('方案 #'+i.id))}</span><span class="hist-time">${esc(String(i.created_at||'').slice(0,16))}</span></div>`).join('');
            return `<div class="chat-bubble hist-card"><div class="comp-title">📋 我的历史方案（${event.total||items.length}）</div><div class="hist-list">${rows||'<div>暂无历史方案</div>'}</div></div>`;
        }
        if (t === 'export_ready') {
            const link = event.download_url || '';
            return `<div class="chat-bubble export-card"><div class="comp-title">📄 报告已生成</div><div class="export-name">${esc(event.file_name||'报告文件')}</div>${link?`<a class="artifact-dl" href="${esc(link)}" target="_blank" download>下载报告</a>`:''}</div>`;
        }
        if (t === 'file_created') {
            const link = event.path ? `/api/agent/artifact?path=${encodeURIComponent(event.path)}` : '';
            return `<div class="chat-bubble artifact-entry"><div class="comp-title">📎 沙箱产物</div><div class="export-name">${esc(event.name||'')}</div>${link?`<a class="artifact-dl" href="${esc(link)}" target="_blank" download>下载</a>`:''}</div>`;
        }
        return `<div class="chat-bubble"><div class="comp-title">${esc(t)}</div><pre>${esc(JSON.stringify(event).slice(0, 300))}</pre></div>`;
    }

    // ---- 自检登录态（直接读 localStorage，不依赖 AuthManager） ----
    function checkLoggedIn() {
        try {
            const raw = localStorage.getItem('hwcloud_auth');
            if (!raw) return false;
            const d = JSON.parse(raw);
            if (!d.token || !d.user) return false;
            if (d.expiresAt && Date.now() >= d.expiresAt) return false;
            return true;
        } catch (e) { return false; }
    }

    // ---- 自包含 SSE fetch（不依赖 window.API） ----
    async function agentStreamFetch(demand, signal, onEvent) {
        const headers = { 'Content-Type': 'application/json' };
        try {
            const raw = localStorage.getItem('hwcloud_auth');
            if (raw) {
                const d = JSON.parse(raw);
                if (d.token) headers['Authorization'] = 'Bearer ' + d.token;
            }
        } catch (e) { /* ignore */ }

        const resp = await fetch('/api/agent/match/stream', {
            method: 'POST',
            headers,
            body: JSON.stringify({ demand, mode: 'agent', customer_files: [], client_id: null, is_quick_demo: false }),
            signal,
        });
        if (!resp.ok) {
            let detail = `HTTP ${resp.status}`;
            try { const j = await resp.json(); if (j.detail) detail = j.detail; } catch (e) { /* ignore */ }
            throw new Error(detail);
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            let sep;
            while ((sep = buffer.indexOf('\n\n')) !== -1) {
                const raw = buffer.slice(0, sep);
                buffer = buffer.slice(sep + 2);
                let etype = '', edata = '';
                for (const line of raw.split('\n')) {
                    if (line.startsWith('event: ')) etype = line.slice(7).trim();
                    else if (line.startsWith('data: ')) edata += line.slice(6).trim();
                }
                if (!etype || !edata) continue;
                let evt;
                try { evt = JSON.parse(edata); } catch (e) { continue; }
                evt.type = etype;
                onEvent(evt);
            }
        }
    }

    // ---- A 回退：applyMode 不再隐藏老表单（chat-shell 已删） ----
    function applyMode() {
        // 不再操作 DOM（老表单始终显示）
    }

    // 初始化
    function init() {
        // 已有对话 UI 则跳过
        if ($el('chat-shell')) return;
        if (!$el('page-conversations')) return; // M3 风格调整：会话列表挂到主区中间

        // 绑定"新建任务"按钮（主区头部）
        const newConvBtn = $el('page-conv-new-btn');
        if (newConvBtn) newConvBtn.addEventListener('click', newConversation);

        // 初始加载会话列表
        loadConversations();

        // M3：首次进入提示（竞品/历史/客户已并入对话）
        try {
            if (!localStorage.getItem('chat_ui_hint_shown')) {
                setTimeout(() => {
                    try {
                        const box = document.createElement('div');
                        box.id = 'chat-hint-toast';
                        box.style.cssText = 'position:fixed;top:70px;left:50%;transform:translateX(-50%);background:rgba(0,0,0,.82);color:#fff;padding:10px 18px;border-radius:10px;font-size:13px;z-index:9999;max-width:90vw;box-shadow:0 4px 16px rgba(0,0,0,.3);display:flex;align-items:center;gap:8px;';
                        box.innerHTML = '<svg class="icon" aria-hidden="true" style="width:16px;height:16px;flex:none"><use href="#i-info"></use></svg><span>竞品分析/历史记录/客户管理已并入对话窗口——直接说出需求即可，如「对比华为云和阿里云」「我最近做过哪些方案」「记个客户」。老功能在「我的」或直接左侧菜单里可找。</span>';
                        document.body.appendChild(box);
                        setTimeout(() => box.remove(), 4000);
                    } catch (e) { /* ignore */ }
                }, 800);
                localStorage.setItem('chat_ui_hint_shown', '1');
            }
        } catch (e) { /* ignore */ }

        // 暴露全局
        window.ChatUI = {
            send: (t) => send(t),
            clear: () => { clearStream(); renderEmptyHint(); },
            getState: () => ({ ...S, messages: S.messages.length }),
        };
    }

    // ---- 自动挂载 ----
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
