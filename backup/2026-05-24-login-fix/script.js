const Config = {
    API_BASE_URL: window.location.origin + '/api',
    ANIMATION: {
        PARTICLE_COUNT: 45,
        CONNECTION_DISTANCE: 120,
        PARTICLE_SPEED: 0.3
    },
    INDUSTRIES: [
        '智慧农业', '工业互联网', '智慧园区', '智慧城市', '智慧交通',
        '智慧教育', '智慧医疗', '智慧金融', '智慧能源', '智慧文旅'
    ],
    COMPETITORS: [
        '阿里云', '腾讯云', '字节跳动火山引擎', '天翼云', '移动云', '联通云',
        'AWS', '微软Azure', 'Google Cloud', 'Oracle Cloud',
        '西门子', '施耐德电气'
    ]
};

const State = {
    currentPage: 'solution',
    loadingStates: {
        match: false,
        analyze: false,
        rebuild: false,
        clear: false
    },
    knowledgeStats: null,
    resultCache: {}
};

class ParticleSystem {
    constructor(canvas) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.particles = [];
        this.animationId = null;
        this.init();
    }

    init() {
        this.resize();
        window.addEventListener('resize', () => this.resize());
        
        for (let i = 0; i < Config.ANIMATION.PARTICLE_COUNT; i++) {
            this.particles.push({
                x: Math.random() * this.canvas.width,
                y: Math.random() * this.canvas.height,
                vx: (Math.random() - 0.5) * Config.ANIMATION.PARTICLE_SPEED,
                vy: (Math.random() - 0.5) * Config.ANIMATION.PARTICLE_SPEED,
                radius: Math.random() * 2 + 1,
                hue: Math.random() < 0.6 ? 0 : 210
            });
        }
        
        this.animate();
    }

    resize() {
        this.canvas.width = window.innerWidth;
        this.canvas.height = window.innerHeight;
    }

    update() {
        this.particles.forEach(p => {
            p.x += p.vx;
            p.y += p.vy;
            
            if (p.x < 0 || p.x > this.canvas.width) p.vx *= -1;
            if (p.y < 0 || p.y > this.canvas.height) p.vy *= -1;
        });
    }

    draw() {
        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        
        this.particles.forEach((p1, i) => {
            this.particles.slice(i + 1).forEach(p2 => {
                const dist = Math.hypot(p1.x - p2.x, p1.y - p2.y);
                if (dist < Config.ANIMATION.CONNECTION_DISTANCE) {
                    const opacity = 0.3 * (1 - dist / Config.ANIMATION.CONNECTION_DISTANCE);
                    const gradient = this.ctx.createLinearGradient(p1.x, p1.y, p2.x, p2.y);
                    gradient.addColorStop(0, `rgba(199, 0, 11, ${opacity})`);
                    gradient.addColorStop(0.5, `rgba(127, 72, 118, ${opacity * 0.8})`);
                    gradient.addColorStop(1, `rgba(74, 144, 226, ${opacity})`);
                    this.ctx.beginPath();
                    this.ctx.strokeStyle = gradient;
                    this.ctx.lineWidth = 1;
                    this.ctx.moveTo(p1.x, p1.y);
                    this.ctx.lineTo(p2.x, p2.y);
                    this.ctx.stroke();
                }
            });
        });
        
        this.particles.forEach(p => {
            const gradient = this.ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.radius * 3);
            if (p.hue === 0) {
                gradient.addColorStop(0, 'rgba(199, 0, 11, 0.6)');
                gradient.addColorStop(0.5, 'rgba(199, 0, 11, 0.3)');
                gradient.addColorStop(1, 'rgba(199, 0, 11, 0)');
            } else {
                gradient.addColorStop(0, 'rgba(74, 144, 226, 0.5)');
                gradient.addColorStop(0.5, 'rgba(74, 144, 226, 0.25)');
                gradient.addColorStop(1, 'rgba(74, 144, 226, 0)');
            }
            this.ctx.beginPath();
            this.ctx.fillStyle = gradient;
            this.ctx.arc(p.x, p.y, p.radius * 2, 0, Math.PI * 2);
            this.ctx.fill();
        });
    }

    animate() {
        this.update();
        this.draw();
        this.animationId = requestAnimationFrame(() => this.animate());
    }

    destroy() {
        if (this.animationId) {
            cancelAnimationFrame(this.animationId);
        }
    }
}

const API = {
    _getHeaders() {
        const headers = { 'Content-Type': 'application/json' };
        const token = localStorage.getItem('access_token');
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        return headers;
    },

    _handleResponse(response) {
        if (response.status === 401) {
            localStorage.removeItem('access_token');
            localStorage.removeItem('user_info');
            window.location.href = window.location.origin + '/login.html';
            throw new Error('登录已过期，请重新登录');
        }
        return response;
    },

    async match(demand) {
        const response = await fetch(`${Config.API_BASE_URL}/match`, {
            method: 'POST',
            headers: this._getHeaders(),
            body: JSON.stringify({ demand })
        });
        
        this._handleResponse(response);
        
        if (!response.ok) {
            throw new Error(`匹配失败: ${response.statusText}`);
        }
        
        return await response.json();
    },

    async analyze(competitor, industry) {
        const response = await fetch(`${Config.API_BASE_URL}/analyze`, {
            method: 'POST',
            headers: this._getHeaders(),
            body: JSON.stringify({ competitor, industry })
        });
        
        this._handleResponse(response);
        
        if (!response.ok) {
            throw new Error(`分析失败: ${response.statusText}`);
        }
        
        return await response.json();
    },

    async getKnowledgeStats() {
        const response = await fetch(`${Config.API_BASE_URL}/knowledge/stats`, {
            headers: this._getHeaders()
        });
        
        this._handleResponse(response);
        
        if (!response.ok) {
            throw new Error(`获取统计失败: ${response.statusText}`);
        }
        
        return await response.json();
    },

    async rebuildKnowledge() {
        const response = await fetch(`${Config.API_BASE_URL}/knowledge/rebuild`, {
            method: 'POST',
            headers: this._getHeaders()
        });
        
        this._handleResponse(response);
        
        if (!response.ok) {
            throw new Error(`重建失败: ${response.statusText}`);
        }
        
        return await response.json();
    },

    async clearKnowledge() {
        const response = await fetch(`${Config.API_BASE_URL}/knowledge/clear`, {
            method: 'POST',
            headers: this._getHeaders()
        });
        
        this._handleResponse(response);
        
        if (!response.ok) {
            throw new Error(`清空失败: ${response.statusText}`);
        }
        
        return await response.json();
    },

    async exportReport(reportType, content, format = 'word', metadata = {}) {
        const response = await fetch(`${Config.API_BASE_URL}/export/report`, {
            method: 'POST',
            headers: this._getHeaders(),
            body: JSON.stringify({
                report_type: reportType,
                format: format,
                content: content,
                metadata: metadata
            })
        });
        
        this._handleResponse(response);
        
        if (!response.ok) {
            throw new Error(`导出失败: ${response.statusText}`);
        }
        
        return await response.json();
    },

    async downloadExportFile(taskId) {
        const url = `${Config.API_BASE_URL}/export/download/${taskId}`;
        window.open(url, '_blank');
    }
};

const UI = {
    showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.textContent = message;
        container.appendChild(toast);
        
        setTimeout(() => {
            toast.remove();
        }, 3000);
    },

    setButtonLoading(button, loading) {
        if (loading) {
            button.classList.add('loading');
            button.disabled = true;
        } else {
            button.classList.remove('loading');
            button.disabled = false;
        }
    },

    switchPage(pageName) {
        document.querySelectorAll('.page').forEach(page => {
            page.classList.remove('active');
        });
        document.getElementById(`page-${pageName}`).classList.add('active');
        
        document.querySelectorAll('.navbar-item, .mobile-item').forEach(item => {
            item.classList.remove('active');
        });
        document.querySelectorAll(`[data-page="${pageName}"]`).forEach(item => {
            item.classList.add('active');
        });
        
        const mobileMenu = document.getElementById('mobile-menu');
        if (mobileMenu) {
            mobileMenu.classList.remove('open');
        }
        
        State.currentPage = pageName;
    },

    renderMarkdown(content) {
        if (typeof marked !== 'undefined' && !window.__markedFailed) {
            try {
                return marked.parse(content);
            } catch (e) {
                return content.replace(/\n/g, '<br>');
            }
        }
        return content.replace(/\n/g, '<br>');
    },

    renderSources(container, sources) {
        if (!sources || sources.length === 0) {
            container.innerHTML = '<p style="color: var(--neutral-500);">无参考文档</p>';
            return;
        }
        
        container.innerHTML = sources.map((doc, i) => `
            <div class="source-item">
                <p><strong>文档 ${i + 1}:</strong> ${doc.metadata?.source || '未知'}</p>
                <p><strong>行业:</strong> ${doc.metadata?.industry || '未知'}</p>
                <p><strong>内容摘要:</strong> ${doc.page_content?.substring(0, 200) || ''}...</p>
            </div>
        `).join('<hr style="border-color: var(--neutral-200); margin: 16px 0;">');
    },

    downloadFile(content, filename) {
        const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
    }
};

const KnowledgeUI = {
    chart: null,

    async loadStats() {
        try {
            const stats = await API.getKnowledgeStats();
            State.knowledgeStats = stats;
            
            const accuracy = stats.accuracy || 50;
            
            const navDocCount = document.getElementById('nav-doc-count');
            const navIndustryCount = document.getElementById('nav-industry-count');
            const navAccuracy = document.getElementById('nav-accuracy');
            const kbTotalDocs = document.getElementById('kb-total-docs');
            const kbTotalIndustries = document.getElementById('kb-total-industries');
            const kbAccuracy = document.getElementById('kb-accuracy');
            
            if (navDocCount) navDocCount.textContent = stats.total_documents || 0;
            if (navIndustryCount) navIndustryCount.textContent = stats.supported_industries?.length || 0;
            if (navAccuracy) navAccuracy.textContent = `${accuracy}%`;
            
            if (kbTotalDocs) kbTotalDocs.textContent = stats.total_documents || 0;
            if (kbTotalIndustries) kbTotalIndustries.textContent = stats.supported_industries?.length || 0;
            if (kbAccuracy) kbAccuracy.textContent = `${accuracy}%`;
            
            this.renderChart(stats.industry_counts || {});
        } catch (error) {
            console.error('加载统计失败:', error);
            
            const defaults = { nav: ['--', '--', '--%'], kb: ['--', '--', '--%'] };
            ['nav-doc-count', 'nav-industry-count', 'nav-accuracy'].forEach((id, i) => {
                const el = document.getElementById(id);
                if (el) el.textContent = defaults.nav[i];
            });
            ['kb-total-docs', 'kb-total-industries', 'kb-accuracy'].forEach((id, i) => {
                const el = document.getElementById(id);
                if (el) el.textContent = defaults.kb[i];
            });
            
            UI.showToast('加载统计数据失败，请检查后端服务', 'warning');
        }
    },

    renderChart(industryCounts) {
        const canvas = document.getElementById('industry-chart');
        if (!canvas) return;
        
        if (window.__chartFailed || typeof Chart === 'undefined') {
            const labels = Object.keys(industryCounts);
            const data = Object.values(industryCounts);
            const container = canvas.parentElement;
            if (container) {
                container.innerHTML = '<div style="padding: 20px;">' +
                    labels.map((label, i) => `<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #eee;"><span>${label}</span><strong>${data[i]}</strong></div>`).join('') +
                    '</div>';
            }
            return;
        }
        
        const labels = Object.keys(industryCounts);
        const data = Object.values(industryCounts);
        
        if (this.chart) {
            this.chart.destroy();
        }
        
        this.chart = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: '文档数量',
                    data: data,
                    backgroundColor: 'rgba(199, 0, 11, 0.7)',
                    borderColor: 'rgba(199, 0, 11, 1)',
                    borderWidth: 1,
                    borderRadius: 6
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return `文档数量: ${context.raw}`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        beginAtZero: true,
                        max: 50,
                        grid: {
                            color: 'rgba(0, 0, 0, 0.05)'
                        },
                        ticks: {
                            color: '#666666',
                            stepSize: 10,
                            font: { size: 12 }
                        },
                        title: {
                            display: true,
                            text: '文档数量',
                            color: '#666666',
                            font: { size: 14 }
                        }
                    },
                    y: {
                        grid: {
                            display: false
                        },
                        ticks: {
                            color: '#333333',
                            font: { size: 13 }
                        }
                    }
                }
            }
        });
    }
};

function initEventListeners() {
    document.querySelectorAll('.navbar-item, .mobile-item').forEach(item => {
        item.addEventListener('click', () => {
            const page = item.dataset.page;
            UI.switchPage(page);
            
            if (page === 'knowledge') {
                KnowledgeUI.loadStats();
            }
        });
    });
    
    const navbarToggle = document.getElementById('navbar-toggle');
    const mobileMenu = document.getElementById('mobile-menu');
    
    navbarToggle?.addEventListener('click', () => {
        mobileMenu?.classList.toggle('open');
    });
    
    const demandInput = document.getElementById('demand-input');
    const charCount = document.getElementById('demand-char-count');
    
    demandInput?.addEventListener('input', () => {
        const length = demandInput.value.length;
        charCount.textContent = length;
        
        if (length > 2000) {
            charCount.style.color = 'var(--error)';
        } else {
            charCount.style.color = 'var(--neutral-500)';
        }
    });
    
    const matchBtn = document.getElementById('match-btn');
    matchBtn?.addEventListener('click', async () => {
        const demand = demandInput.value.trim();
        
        if (!demand) {
            UI.showToast('请输入客户需求描述', 'warning');
            return;
        }
        
        if (demand.length > 2000) {
            UI.showToast('需求描述不能超过2000字符', 'warning');
            return;
        }
        
        UI.setButtonLoading(matchBtn, true);
        
        try {
            const result = await API.match(demand);
            
            const resultContainer = document.getElementById('solution-result');
            const resultContent = document.getElementById('solution-content');
            const sourcesContainer = document.getElementById('solution-sources');
            
            resultContent.innerHTML = UI.renderMarkdown(result.answer);
            UI.renderSources(sourcesContainer, result.source_documents);
            resultContainer.style.display = 'block';
            
            State.resultCache.solution = result;
            
            UI.showToast('匹配完成！', 'success');
        } catch (error) {
            console.error('匹配失败:', error);
            UI.showToast(error.message || '匹配失败，请重试', 'error');
        } finally {
            UI.setButtonLoading(matchBtn, false);
        }
    });
    
    document.getElementById('clear-solution-btn')?.addEventListener('click', () => {
        demandInput.value = '';
        charCount.textContent = '0';
        document.getElementById('solution-result').style.display = 'none';
        State.resultCache.solution = null;
    });
    
    document.getElementById('download-solution-btn')?.addEventListener('click', async () => {
        if (State.resultCache.solution) {
            try {
                UI.showToast('正在生成报告...', 'info');
                const result = await API.exportReport('solution', State.resultCache.solution.answer, 'word');
                
                if (result.status === 'completed') {
                    UI.showToast('报告生成成功！', 'success');
                    API.downloadExportFile(result.task_id);
                } else {
                    UI.downloadFile(State.resultCache.solution.answer, '华为云解决方案建议书.md');
                }
            } catch (error) {
                console.error('导出失败:', error);
                UI.showToast('导出失败，使用Markdown下载', 'warning');
                UI.downloadFile(State.resultCache.solution.answer, '华为云解决方案建议书.md');
            }
        }
    });
    
    const analyzeBtn = document.getElementById('analyze-btn');
    analyzeBtn?.addEventListener('click', async () => {
        const competitor = document.getElementById('competitor-select').value;
        const industry = document.getElementById('industry-select').value;
        
        UI.setButtonLoading(analyzeBtn, true);
        
        try {
            const result = await API.analyze(competitor, industry);
            
            const resultContainer = document.getElementById('competitor-result');
            const resultContent = document.getElementById('competitor-content');
            const sourcesContainer = document.getElementById('competitor-sources');
            
            resultContent.innerHTML = UI.renderMarkdown(result.answer);
            UI.renderSources(sourcesContainer, result.source_documents);
            resultContainer.style.display = 'block';
            
            State.resultCache.competitor = { ...result, competitor, industry };
            
            UI.showToast('分析完成！', 'success');
        } catch (error) {
            console.error('分析失败:', error);
            UI.showToast(error.message || '分析失败，请重试', 'error');
        } finally {
            UI.setButtonLoading(analyzeBtn, false);
        }
    });
    
    document.getElementById('clear-competitor-btn')?.addEventListener('click', () => {
        document.getElementById('competitor-result').style.display = 'none';
        State.resultCache.competitor = null;
    });
    
    document.getElementById('download-competitor-btn')?.addEventListener('click', async () => {
        if (State.resultCache.competitor) {
            const { competitor, industry, answer } = State.resultCache.competitor;
            try {
                UI.showToast('正在生成报告...', 'info');
                const result = await API.exportReport('competitor', answer, 'word', { competitor, industry });
                
                if (result.status === 'completed') {
                    UI.showToast('报告生成成功！', 'success');
                    API.downloadExportFile(result.task_id);
                } else {
                    UI.downloadFile(answer, `华为云vs${competitor}_${industry}行业竞争分析报告.md`);
                }
            } catch (error) {
                console.error('导出失败:', error);
                UI.showToast('导出失败，使用Markdown下载', 'warning');
                UI.downloadFile(answer, `华为云vs${competitor}_${industry}行业竞争分析报告.md`);
            }
        }
    });
    
    const rebuildBtn = document.getElementById('rebuild-btn');
    rebuildBtn?.addEventListener('click', async () => {
        UI.setButtonLoading(rebuildBtn, true);
        
        try {
            const result = await API.rebuildKnowledge();
            UI.showToast(`知识库重建完成！共添加 ${result.count || 0} 个文档片段`, 'success');
            await KnowledgeUI.loadStats();
        } catch (error) {
            console.error('重建失败:', error);
            UI.showToast(error.message || '重建失败，请重试', 'error');
        } finally {
            UI.setButtonLoading(rebuildBtn, false);
        }
    });
    
    const clearKbBtn = document.getElementById('clear-kb-btn');
    const confirmDialog = document.getElementById('confirm-clear');
    const confirmCheckbox = document.getElementById('confirm-checkbox');
    const confirmClearBtn = document.getElementById('confirm-clear-btn');
    
    clearKbBtn?.addEventListener('click', () => {
        confirmDialog.style.display = 'flex';
    });
    
    confirmClearBtn?.addEventListener('click', async () => {
        if (!confirmCheckbox.checked) {
            UI.showToast('请先确认清空知识库', 'warning');
            return;
        }
        
        try {
            await API.clearKnowledge();
            UI.showToast('知识库已清空', 'success');
            confirmDialog.style.display = 'none';
            confirmCheckbox.checked = false;
            await KnowledgeUI.loadStats();
        } catch (error) {
            console.error('清空失败:', error);
            UI.showToast(error.message || '清空失败，请重试', 'error');
        }
    });
}

function init() {
    const canvas = document.getElementById('particle-canvas');
    if (canvas) {
        new ParticleSystem(canvas);
    }
    
    const isMainPage = document.getElementById('page-solution') !== null;
    
    if (isMainPage) {
        initEventListeners();
        KnowledgeUI.loadStats();
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}
