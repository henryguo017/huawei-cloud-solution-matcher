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
        const stream = $el('chat-stream');
        if (!stream || stream.querySelector('.chat-msg')) return;
        stream.innerHTML = `<div class="chat-empty-hint">
            <div style="font-size:22px;margin-bottom:6px">💬</div>
            <div style="font-size:15px;font-weight:600">我能帮你做什么？</div>
            <div style="font-size:13px;margin-top:4px">方案匹配 / 竞品对比 / 价目查询 / 生成文件 / 查历史 / 记客户</div>
            <div class="chat-suggestions">
                <button data-q="给某地市政务局做一个一网通办的方案，预算有限">做政务一网通办方案</button>
                <button data-q="对比华为云和阿里云在政务云上谁强">对比华为云和阿里云</button>
                <button data-q="我最近做过哪些方案？帮我查一下">查我的历史</button>
                <button data-q="ModelArts 推理多少钱一小时">查 ModelArts 价格</button>
            </div>
        </div>`;
        stream.querySelectorAll('.chat-suggestions button').forEach(btn => {
            btn.addEventListener('click', () => {
                const input = $el('chat-input');
                if (input) { input.value = btn.dataset.q || ''; input.focus(); }
            });
        });
    }

    function clearStream() {
        const stream = $el('chat-stream');
        if (stream) stream.innerHTML = '';
        S.messages = [];
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

    // ---- 模式切换（仅 agent 接管对话） ----
    function applyMode() {
        const chatShell = $el('chat-shell');
        if (!chatShell) return;
        const agentMode = S.mode === 'agent';
        chatShell.style.display = agentMode ? 'flex' : 'none';

        // Agent 模式：隐藏老表单区（需求输入/模式切换/客户档案），避免双 UI 冲突
        const host = $el('page-solution');
        if (!host) return;
        const formCard = host.querySelector('.content-card .form-group');
        const modeBar = host.querySelector('.mode-toggle-bar');
        if (agentMode) {
            if (formCard) formCard.closest('.content-card').style.display = 'none';
            if (modeBar) modeBar.style.display = 'none';
        } else {
            if (formCard) formCard.closest('.content-card').style.display = '';
            if (modeBar) modeBar.style.display = '';
        }
    }

    // ---- 初始化 ----
    function init() {
        // 已有对话 UI 则跳过
        if ($el('chat-shell')) return;
        // 获取宿主容器（page-solution）
        const host = $el('page-solution');
        if (!host) return;

        // 构建对话壳
        const shell = document.createElement('div');
        shell.id = 'chat-shell';
        shell.className = 'chat-shell';
        shell.innerHTML = `
            <div class="chat-stream" id="chat-stream"></div>
            <div class="chat-inputbar">
                <div class="chat-inputbar-row">
                    <textarea id="chat-input" placeholder="输入你的需求，如：给某地市政务局做一个一网通办的方案" rows="1"></textarea>
                    <button class="chat-send-btn" id="chat-send-btn" title="发送 (Enter)">➤</button>
                </div>
                <div class="chat-toolbar">
                    <button class="chat-tool-btn" id="chat-attach-btn" title="上传客户资料（可选）">📎 附件</button>
                    <select class="chat-mode-select" id="chat-mode-select" title="匹配模式">
                        <option value="agent" selected>Agent 智能对话（推荐）</option>
                        <option value="normal">标准模式</option>
                        <option value="wizard">向导模式</option>
                    </select>
                    <span style="flex:1"></span>
                    <span class="chat-mode-hint" id="chat-mode-hint" style="font-size:12px;color:var(--text-muted,#8890A4)">Enter 发送 · Shift+Enter 换行</span>
                </div>
            </div>
        `;
        // 插入到 page-solution 顶部（header 之后）
        const header = host.querySelector('.page-header');
        if (header) header.insertAdjacentElement('afterend', shell);
        else host.prepend(shell);

        // 事件绑定
        const input = $el('chat-input');
        const sendBtn = $el('chat-send-btn');
        const modeSelect = $el('chat-mode-select');

        // 自动撑高
        input.addEventListener('input', () => {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 120) + 'px';
        });
        // Enter 发送 / Shift+Enter 换行
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send(input.value);
            }
        });
        sendBtn.addEventListener('click', () => send(input.value));

        // 模式选择：agent → 对话接管；其他 → 恢复老表单（隐藏对话壳）
        modeSelect.addEventListener('change', () => {
            const m = modeSelect.value;
            S.mode = m;
            if (m !== 'agent') {
                shell.style.display = 'none';
                // 让老表单可见（模式切换逻辑在 script.js，触发它）
                const modeToggle = $el('mode-toggle');
                if (modeToggle) {
                    const opt = modeToggle.querySelector(`[data-mode="${m}"]`);
                    if (opt) opt.click();
                }
            } else {
                shell.style.display = 'flex';
                const modeToggle = $el('mode-toggle');
                if (modeToggle) {
                    const opt = modeToggle.querySelector('[data-mode="agent"]');
                    if (opt) opt.click();
                }
            }
        });

        // 附件按钮：触发老的上传组件（若存在）
        const attachBtn = $el('chat-attach-btn');
        attachBtn.addEventListener('click', () => {
            if (window.CustomerFileUploader && CustomerFileUploader.trigger) {
                CustomerFileUploader.trigger();
            } else {
                const dropzone = $el('cf-dropzone');
                if (dropzone) dropzone.click();
            }
        });

        // 初始渲染
        renderEmptyHint();
        applyMode();

        // 暴露全局（供 script.js 或调试使用）
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
