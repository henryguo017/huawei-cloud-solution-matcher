/*
 * share.js — 方案只读分享页（独立前端，不依赖主站 script.js）
 * 渲染 /api/share/{id} 返回的方案快照，并生成二维码。
 */
(function () {
    function escapeHtml(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function safeUrl(url) {
        const u = String(url || '').trim().toLowerCase();
        return /^(https?:|mailto:)/.test(u) ? url : '#';
    }

    function fmtDate(s) {
        if (!s) return '';
        return String(s).replace('T', ' ').replace(/\.\d+$/, '').slice(0, 19);
    }

    // 复刻自主站 UI.simpleMarkdown，保证渲染样式一致
    function simpleMarkdown(text) {
        if (!text || typeof text !== 'string') return '';
        let html = escapeHtml(text);
        const codeBlocks = [];
        html = html.replace(/```[\s\S]*?```/g, function (m) {
            const idx = codeBlocks.length;
            const inner = m.replace(/```[\w]*\n?/, '').replace(/```$/, '');
            codeBlocks.push('<pre style="background:var(--neutral-300,#F7F8FA);border:1px solid var(--neutral-400,#F2F3F5);color:var(--neutral-900,#1D2129);padding:12px 16px;border-radius:8px;overflow-x:auto;font-size:13px;line-height:1.6;"><code>' + inner + '</code></pre>');
            return '___CODEBLOCK_' + idx + '___';
        });
        html = html.replace(/`([^`]+)`/g, '<code style="background:var(--neutral-300,#F7F8FA);color:var(--primary-color,#C7000B);border:1px solid var(--neutral-400,#F2F3F5);padding:1px 5px;border-radius:4px;font-size:13px;">$1</code>');
        html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
        html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
        html = html.replace(/^# (.+)$/gm, '<h2>$1</h2>');
        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
        html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, function (_, label, url) {
            return '<a href="' + safeUrl(url) + '" target="_blank" style="color:var(--primary-color);">' + label + '</a>';
        });
        html = html.replace(/^[\s]*[-*+] (.+)$/gm, '<li>$1</li>');
        html = html.replace(/(<li>.*<\/li>)/s, '<ul style="padding-left:20px;margin:8px 0;">$1</ul>');
        html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
        html = (function () {
            const lines = html.split('\n');
            const parseCells = (line) => line.split('|').slice(1, -1).map(c => c.trim());
            const buildTable = (headerLine, dataLines) => {
                const headers = parseCells(headerLine);
                let tbl = '<table class="markdown-table" style="width:100%;border-collapse:collapse;margin:12px 0;font-size:var(--font-size-sm,14px);border:1px solid #d9d9d9;">';
                tbl += '<thead><tr>';
                headers.forEach(h => {
                    tbl += '<th style="border:1px solid #d9d9d9;border-bottom:2px solid rgba(199,0,11,0.15);padding:10px 14px;text-align:left;background:rgba(199,0,11,0.06);color:#1f2329;font-weight:600;">' + h + '</th>';
                });
                tbl += '</tr></thead><tbody>';
                dataLines.forEach(row => {
                    const cells = parseCells(row);
                    if (cells.every(c => /^[\s\-:|]+$/.test(c) || c === '')) return;
                    tbl += '<tr>';
                    cells.forEach(c => { tbl += '<td style="border:1px solid #e8e8e8;padding:10px 14px;color:#333;">' + c + '</td>'; });
                    tbl += '</tr>';
                });
                tbl += '</tbody></table>';
                return tbl;
            };
            const isSeparator = (line) => /^\|[\s\-:|]{3,}\|$/.test(line.trim());
            const isTableRow = (line) => /^\s*\|.+\|$/.test(line);
            let i = 0;
            while (i < lines.length) {
                if (isTableRow(lines[i])) {
                    const headerLine = lines[i].trim();
                    let sepIdx = -1;
                    for (let look = i + 1; look <= Math.min(i + 3, lines.length - 1); look++) {
                        if (isSeparator(lines[look])) { sepIdx = look; break; }
                        if (lines[look].trim() !== '' && !isTableRow(lines[look])) break;
                    }
                    if (sepIdx !== -1) {
                        let j = sepIdx + 1;
                        while (j < lines.length) {
                            if (isTableRow(lines[j])) { j++; }
                            else if (lines[j].trim() === '') { j++; }
                            else { break; }
                        }
                        lines.splice(i, j - i, buildTable(headerLine, lines.slice(sepIdx + 1, j).filter(l => isTableRow(l))));
                    } else {
                        let j = i + 1;
                        while (j < lines.length) {
                            if (isTableRow(lines[j])) { j++; }
                            else if (lines[j].trim() === '') { j++; }
                            else { break; }
                        }
                        const rowLines = lines.slice(i, j).filter(l => isTableRow(l));
                        if (rowLines.length >= 2) {
                            const colCount = parseCells(rowLines[0]).length;
                            const allSameCols = rowLines.every(r => parseCells(r).length === colCount);
                            if (allSameCols && colCount >= 2) {
                                lines.splice(i, j - i, buildTable(rowLines[0], rowLines.slice(1)));
                            } else { i++; }
                        } else { i++; }
                    }
                } else { i++; }
            }
            html = lines.join('\n');
            html = html.replace(/^(?:\s*\|.+\|)+$/gm, function (pipeBlock) {
                const pipeLines = pipeBlock.trim().split('\n').filter(l => /^\s*\|/.test(l));
                if (pipeLines.length <= 0) return pipeBlock;
                const maxCols = Math.max.apply(null, pipeLines.map(l => l.split('|').length - 2));
                if (maxCols >= 2 && pipeLines.length >= 2) {
                    return buildTable(pipeLines[0].trim(), pipeLines.slice(1).map(l => l.trim()));
                }
                return pipeLines.map(l => l.replace(/^\s*\|/, '').replace(/\|\s*$/, '').replace(/\|/g, ' | ')).join('<br>');
            });
            return html;
        })();
        html = html.replace(/^---$/gm, '<hr style="border:none;border-top:1px solid var(--neutral-500,#DCE0E6);margin:16px 0;">');
        html = html.replace(/\n\n/g, '<br><br>');
        html = html.replace(/\n/g, '<br>');
        codeBlocks.forEach((block, idx) => { html = html.replace('___CODEBLOCK_' + idx + '___', block); });
        return html;
    }

    function buildSources(sources) {
        if (!sources || !sources.length) return '<p style="color:var(--text-muted);">无参考文档</p>';
        return sources.map((doc, i) => {
            const meta = doc.metadata || {};
            return '<div class="source-item"><p><strong>文档 ' + (i + 1) + '：</strong>' + escapeHtml(meta.source || '未知') + '</p><p><strong>行业:</strong> ' + escapeHtml(meta.industry || '未知') + '</p></div>';
        }).join('');
    }

    function renderQR(url) {
        try {
            const qr = qrcode(0, 'M');
            qr.addData(url);
            qr.make();
            const el = document.getElementById('share-qrcode');
            if (el) el.innerHTML = qr.createSvgTag(5, 4);
        } catch (e) {
            console.warn('[分享] 二维码生成失败:', e);
        }
    }

    // 从方案 answer 提取「执行摘要」章节 → 摘要卡片 HTML（与主站卡片样式一致）
    function buildSummaryCard(markdown) {
        try {
            if (!markdown) return '';
            const lines = String(markdown).split('\n');
            let inSummary = false;
            const contentLines = [];
            for (let i = 0; i < lines.length; i++) {
                const line = lines[i];
                if (/^##\s+.*执行摘要/.test(line)) { inSummary = true; continue; }
                if (inSummary && /^##\s+/.test(line)) { break; }
                if (inSummary) contentLines.push(line);
            }
            const raw = contentLines.map(function(l) { return l.trim(); }).filter(Boolean);
            if (!raw.length) return '';
            const stripMd = function(s) { return s.replace(/\*\*/g, '').replace(/__/g, '').trim(); };
            const firstPara = stripMd(raw[0]);
            const bullets = [];
            for (let i = 1; i < raw.length; i++) {
                let l = raw[i].replace(/^[-*•]\s*/, '').replace(/^\d+[.、]\s*/, '').trim();
                if (l) bullets.push(stripMd(l));
            }
            if (!firstPara && bullets.length === 0) return '';
            let html = '<div class="share-summary-card">';
            html += '<div class="share-summary-head"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="16" height="16"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/></svg><span>方案摘要</span></div>';
            html += '<div class="share-summary-body">';
            if (firstPara) html += '<p class="share-summary-value">' + escapeHtml(firstPara) + '</p>';
            if (bullets.length) {
                html += '<ul class="share-summary-bullets">';
                bullets.forEach(function(b) { html += '<li>' + escapeHtml(b) + '</li>'; });
                html += '</ul>';
            }
            html += '</div></div>';
            return html;
        } catch (e) {
            console.warn('[share] 摘要卡片渲染失败:', e);
            return '';
        }
    }

    function render(data, el) {
        const p = data.payload || {};
        const isAnalyze = p.kind === 'analyze';
        let html = '';
        html += '<span class="share-kind-badge">' + (isAnalyze ? '竞品分析' : '解决方案') + '</span>';
        html += '<h1 class="share-title">' + escapeHtml(p.title || data.title || '方案分享') + '</h1>';
        let meta = '';
        if (p.industry) meta += '<span>行业：' + escapeHtml(p.industry) + '</span>';
        if (data.created_at) meta += '<span>生成：' + fmtDate(data.created_at) + '</span>';
        if (data.view_count != null) meta += '<span>浏览：' + data.view_count + '</span>';
        if (meta) html += '<div class="share-meta">' + meta + '</div>';
        if (p.demand) html += '<div class="share-section-label">客户需求</div><div class="share-demand-box">' + escapeHtml(p.demand) + '</div>';
        const sol = p.solution || p.answer || '';
        if (sol && !isAnalyze) html += buildSummaryCard(sol);
        if (sol) html += '<div class="share-section-label">' + (isAnalyze ? '分析报告' : '解决方案') + '</div><div class="result-content">' + simpleMarkdown(sol) + '</div>';
        if (p.sources && p.sources.length) html += '<div class="share-section-label">参考文档</div><div class="share-sources">' + buildSources(p.sources) + '</div>';
        el.innerHTML = html;
    }

    async function load() {
        const stateEl = document.getElementById('share-state');
        const bodyEl = document.getElementById('share-body');
        const id = new URLSearchParams(location.search).get('id');
        if (!id) { stateEl.textContent = '缺少分享 ID'; return; }
        try {
            const resp = await fetch('/api/share/' + encodeURIComponent(id));
            if (!resp.ok) { stateEl.textContent = '分享不存在或已失效'; return; }
            const data = await resp.json();
            render(data, bodyEl);
            stateEl.style.display = 'none';
            bodyEl.style.display = 'block';
            renderQR(location.origin + '/share?id=' + id);
        } catch (e) {
            console.error(e);
            stateEl.textContent = '加载失败，请稍后重试';
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', load);
    } else {
        load();
    }
})();
