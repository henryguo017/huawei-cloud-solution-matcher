const Config = {
    API_BASE_URL: '/api',
    ANIMATION: {
        PARTICLE_COUNT: 80,
        CONNECTION_DISTANCE: 150,
        PARTICLE_SPEED: 0.5
    },
    INDUSTRIES: [
        '智慧农业', '工业互联网', '智慧园区', '智慧城市', '智慧医疗',
        '智慧金融', '智慧能源', '智慧交通', '智慧教育', '智慧文旅'
    ],
    COMPETITORS: [
        // 国内主流云服务商
        '阿里云', '腾讯云', '字节跳动火山引擎', '天翼云', '移动云', '联通云',
        // 国际主流云服务商
        'AWS', '微软Azure', 'Google Cloud', 'Oracle Cloud',
        // 行业解决方案提供商
        '西门子', '施耐德电气'
    ]
};

// Chart.js 全局默认配置（确保所有图表字体统一）
if (typeof Chart !== 'undefined') {
    Chart.defaults.color = 'rgba(255, 255, 255, 0.85)';
    Chart.defaults.font = {
        family: "'Inter', 'PingFang SC', 'Microsoft YaHei', sans-serif",
        size: 14,
        weight: '500'
    };
    Chart.defaults.scale.grid.color = 'rgba(255, 255, 255, 0.08)';
}

const State = {
    currentPage: 'solution',
    loadingStates: {
        match: false,
        analyze: false,
        rebuild: false,
        clear: false
    },
    knowledgeStats: null,
    resultCache: {},
    abortControllers: {
        match: null,
        analyze: null
    }
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
                radius: Math.random() * 2 + 1
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
                    this.ctx.beginPath();
                    this.ctx.strokeStyle = `rgba(100, 150, 255, ${1 - dist / Config.ANIMATION.CONNECTION_DISTANCE})`;
                    this.ctx.lineWidth = 0.5;
                    this.ctx.moveTo(p1.x, p1.y);
                    this.ctx.lineTo(p2.x, p2.y);
                    this.ctx.stroke();
                }
            });
        });
        
        this.particles.forEach(p => {
            this.ctx.beginPath();
            this.ctx.fillStyle = 'rgba(100, 150, 255, 0.6)';
            this.ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
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
    async match(demand, signal) {
        const response = await fetch(`${Config.API_BASE_URL}/match`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ demand }),
            signal
        });

        if (!response.ok) {
            throw new Error(`匹配失败: ${response.statusText}`);
        }

        return await response.json();
    },

    async analyze(competitor, industry, signal) {
        const response = await fetch(`${Config.API_BASE_URL}/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ competitor, industry }),
            signal
        });

        if (!response.ok) {
            throw new Error(`分析失败: ${response.statusText}`);
        }

        return await response.json();
    },

    async getKnowledgeStats() {
        const response = await fetch(`${Config.API_BASE_URL}/knowledge/stats`);
        
        if (!response.ok) {
            throw new Error(`获取统计失败: ${response.statusText}`);
        }
        
        return await response.json();
    },

    async getDashboardStats() {
        const response = await fetch(`${Config.API_BASE_URL}/dashboard/stats`);
        
        if (!response.ok) {
            throw new Error(`获取仪表盘数据失败: ${response.statusText}`);
        }
        
        return await response.json();
    },

    async rebuildKnowledge() {
        const response = await fetch(`${Config.API_BASE_URL}/knowledge/rebuild`, {
            method: 'POST'
        });
        
        if (!response.ok) {
            throw new Error(`重建失败: ${response.statusText}`);
        }
        
        return await response.json();
    },

    async clearKnowledge() {
        const response = await fetch(`${Config.API_BASE_URL}/knowledge/clear`, {
            method: 'POST'
        });

        if (!response.ok) {
            throw new Error(`清空失败: ${response.statusText}`);
        }

        return await response.json();
    },

    // ========== 历史记录 API ==========
    async getHistoryList() {
        const response = await fetch(`${Config.API_BASE_URL}/history/list`);
        if (!response.ok) throw new Error(`获取历史记录失败: ${response.statusText}`);
        return await response.json();
    },

    async getHistoryDetail(id) {
        const response = await fetch(`${Config.API_BASE_URL}/history/${id}`);
        if (!response.ok) throw new Error(`获取详情失败: ${response.statusText}`);
        return await response.json();
    },

    async compareHistory(idA, idB) {
        const response = await fetch(`${Config.API_BASE_URL}/history/compare`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id_a: idA, id_b: idB })
        });
        if (!response.ok) throw new Error(`对比失败: ${response.statusText}`);
        return await response.json();
    },

    async getCompareAISummary(idA, idB) {
        const response = await fetch(`${Config.API_BASE_URL}/history/ai-summary`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id_a: idA, id_b: idB })
        });
        if (!response.ok) throw new Error(`AI总结失败: ${response.statusText}`);
        return await response.json();
    },

    async refineSolution(originalDemand, currentSolution, followUp, conversationHistory) {
        const response = await fetch(`${Config.API_BASE_URL}/solution/refine`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                original_demand: originalDemand,
                current_solution: currentSolution,
                follow_up: followUp,
                conversation_history: conversationHistory || []
            })
        });
        if (!response.ok) throw new Error(`方案优化失败: ${response.statusText}`);
        return await response.json();
    },

    async updateHistorySolution(historyId, solution) {
        const response = await fetch(`${Config.API_BASE_URL}/history/${historyId}/solution`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ solution })
        });
        if (!response.ok) throw new Error(`更新历史方案失败: ${response.statusText}`);
        return await response.json();
    }
};

/* ==================== 进度管理器 ==================== */

class ProgressManager {
    constructor(panelId, barId, stepsId, timeId) {
        this.panel = document.getElementById(panelId);
        this.bar = document.getElementById(barId);
        this.stepsContainer = document.getElementById(stepsId);
        this.timeEl = timeId ? document.getElementById(timeId) : null;
        this.startTime = null;
        this.timer = null;
        this.currentStep = -1;
        this.simulationTimer = null;
    }

    start() {
        if (!this.panel) return this;
        this.panel.style.display = 'block';
        this.panel.classList.remove('success', 'fade-out');
        this.panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        if (this.bar) {
            this.bar.style.width = '0%';
            this.bar.classList.remove('indeterminate');
        }
        this.currentStep = -1;
        this.startTime = Date.now();

        // 重置所有步骤状态
        if (this.stepsContainer) {
            this.stepsContainer.querySelectorAll('.progress-step').forEach(step => {
                step.classList.remove('active', 'done');
                const status = step.querySelector('.step-status');
                if (status) status.className = 'step-status waiting';
            });
        }

        // 启动计时器
        if (this.timeEl) {
            this.timeEl.textContent = '已用时 0.0s';
            this.timer = setInterval(() => this.updateTime(), 100);
        }

        return this;
    }

    setStep(index) {
        if (!this.stepsContainer) return;
        // 标记之前的步骤为完成
        for (let i = 0; i < index; i++) {
            const step = this.stepsContainer.querySelector(`[data-step="${i}"]`);
            if (step) {
                step.classList.remove('active');
                step.classList.add('done');
                const status = step.querySelector('.step-status');
                if (status) status.className = 'step-status completed';
            }
        }
        // 标记当前步骤为进行中
        const currentStep = this.stepsContainer.querySelector(`[data-step="${index}"]`);
        if (currentStep) {
            currentStep.classList.add('active');
            const status = currentStep.querySelector('.step-status');
            if (status) status.className = 'step-status running';
        }
        this.currentStep = index;
    }

    setProgress(percent) {
        if (this.bar) this.bar.style.width = `${percent}%`;
    }

    updateTime() {
        if (!this.startTime || !this.timeEl) return;
        const elapsed = (Date.now() - this.startTime) / 1000;
        this.timeEl.textContent = `已用时 ${elapsed.toFixed(1)}s`;
    }

    // 模拟进度增长（用于非流式后端）
    simulateProgress(steps, totalDuration) {
        if (!this.stepsContainer) return;
        const stepCount = this.stepsContainer.querySelectorAll('.progress-step').length;
        const stepDuration = totalDuration / stepCount;
        let currentStepIndex = 0;

        this.simulationTimer = setInterval(() => {
            if (currentStepIndex < stepCount) {
                this.setStep(currentStepIndex);
                const progress = ((currentStepIndex + 0.5) / stepCount) * 90; // 最多到90%，等API完成后再到100%
                this.setProgress(progress);
                currentStepIndex++;
            }
        }, stepDuration);
    }

    stopSimulation() {
        if (this.simulationTimer) {
            clearInterval(this.simulationTimer);
            this.simulationTimer = null;
        }
    }

    success(message) {
        this.stopSimulation();
        this.setProgress(100);
        if (this.panel) this.panel.classList.add('success');
        
        // 标记所有步骤为完成
        if (this.stepsContainer) {
            this.stepsContainer.querySelectorAll('.progress-step').forEach(step => {
                step.classList.remove('active');
                step.classList.add('done');
                const status = step.querySelector('.step-status');
                if (status) status.className = 'step-status completed';
            });
        }

        const title = this.panel ? this.panel.querySelector('.progress-title') : null;
        if (title) title.textContent = message || '完成！';

        clearInterval(this.timer);

        // 1.5秒后淡出
        setTimeout(() => {
            if (this.panel) this.panel.classList.add('fade-out');
            setTimeout(() => {
                if (this.panel) {
                    this.panel.style.display = 'none';
                    this.panel.classList.remove('success', 'fade-out');
                }
                // 重置进度条颜色
                if (this.bar) this.bar.style.background = '';
            }, 500);
        }, 1500);
    }

    error(message) {
        this.stopSimulation();
        clearInterval(this.timer);
        if (this.panel) this.panel.classList.remove('success');
        const title = this.panel ? this.panel.querySelector('.progress-title') : null;
        if (title) title.textContent = message || '出错了';
        if (this.bar) this.bar.style.background = 'linear-gradient(90deg, var(--error) 0%, #D4191F 100%)';
    }

    cancel() {
        this.stopSimulation();
        clearInterval(this.timer);
        if (this.panel) {
            this.panel.classList.add('fade-out');
            setTimeout(() => {
                this.panel.style.display = 'none';
                this.panel.classList.remove('fade-out');
            }, 500);
        }
        // 重置所有步骤状态
        if (this.stepsContainer) {
            this.stepsContainer.querySelectorAll('.progress-step').forEach(step => {
                step.classList.remove('active', 'done');
                const status = step.querySelector('.step-status');
                if (status) status.className = 'step-status waiting';
            });
        }
        if (this.bar) {
            this.bar.style.width = '0%';
            this.bar.style.background = '';
        }
        const title = this.panel ? this.panel.querySelector('.progress-title') : null;
        if (title) title.textContent = this.panel.id === 'match-progress-panel' ? '正在为您匹配最佳方案...' : '正在生成竞争分析报告...';
    }

    hide() {
        this.stopSimulation();
        clearInterval(this.timer);
        if (this.panel) this.panel.style.display = 'none';
    }
}

// 初始化进度管理器实例
const MatchProgress = new ProgressManager('match-progress-panel', 'match-progress-bar', 'match-progress-steps', 'match-time-elapsed');
const AnalyzeProgress = new ProgressManager('analyze-progress-panel', 'analyze-progress-bar', 'analyze-progress-steps', 'analyze-time-elapsed');
const RebuildProgress = new ProgressManager('rebuild-progress-panel', 'rebuild-progress-bar', null, null);

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
        
        document.querySelectorAll('.navbar-item').forEach(item => {
            item.classList.remove('active');
        });
        const navbarItem = document.querySelector(`.navbar-item[data-page="${pageName}"]`);
        if (navbarItem) navbarItem.classList.add('active');
        
        document.querySelectorAll('.mobile-item').forEach(item => {
            item.classList.remove('active');
        });
        const mobileItem = document.querySelector(`.mobile-item[data-page="${pageName}"]`);
        if (mobileItem) mobileItem.classList.add('active');
        
        State.currentPage = pageName;
    },

    renderMarkdown(content) {
        let html;
        if (typeof marked !== 'undefined') {
            html = marked.parse(content);
        } else {
            html = content.replace(/\n/g, '<br>');
        }
        // 确保渲染内容在深色背景下可见：去除内联深色样式，用CSS控制颜色
        html = html.replace(/style="[^"]*color\s*:\s*#[0-9a-fA-F]{1,6}[^"]*"/gi, '');
        html = html.replace(/color\s*:\s*#[0-3][0-9a-fA-F]{5}/gi, 'color: rgba(255,255,255,0.88)');
        return html;
    },

    renderSources(container, sources) {
        if (!sources || sources.length === 0) {
            container.innerHTML = '<p style="color: var(--text-secondary);">无参考文档</p>';
            return;
        }
        
        container.innerHTML = sources.map((doc, i) => `
            <div class="source-item">
                <p><strong>文档 ${i + 1}:</strong> ${doc.metadata?.source || '未知'}</p>
                <p><strong>行业:</strong> ${doc.metadata?.industry || '未知'}</p>
                <p><strong>内容摘要:</strong> ${doc.page_content?.substring(0, 200) || ''}...</p>
            </div>
        `).join('<hr style="border-color: rgba(255,255,255,0.1); margin: 16px 0;">');
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
            
            document.getElementById('nav-doc-count').textContent = stats.total_documents || 0;
            document.getElementById('nav-industry-count').textContent = stats.supported_industries?.length || 0;
            document.getElementById('nav-accuracy').textContent = `${accuracy}%`;
            
            document.getElementById('kb-total-docs').textContent = stats.total_documents || 0;
            document.getElementById('kb-total-industries').textContent = stats.supported_industries?.length || 0;
            document.getElementById('kb-accuracy').textContent = `${accuracy}%`;
            
            this.renderChart(stats.industry_counts || {});
        } catch (error) {
            console.error('加载统计失败:', error);
            UI.showToast('加载统计数据失败，请检查后端服务', 'warning');
        }
    },

    renderChart(industryCounts) {
        const canvas = document.getElementById('industry-chart');
        if (!canvas) return;
        
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
                    backgroundColor: 'rgba(255, 0, 0, 0.6)',
                    borderColor: 'rgba(255, 0, 0, 1)',
                    borderWidth: 1,
                    borderRadius: 8
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
                            color: 'rgba(255, 255, 255, 0.1)'
                        },
                        ticks: {
                            color: '#B0B8C8',
                            stepSize: 10,
                            font: {
                                size: 12
                            }
                        },
                        title: {
                            display: true,
                            text: '文档数量',
                            color: '#B0B8C8',
                            font: {
                                size: 14
                            }
                        }
                    },
                    y: {
                        grid: {
                            display: false
                        },
                        ticks: {
                            color: '#FFFFFF',
                            font: {
                                size: 13
                            }
                        }
                    }
                }
            }
        });
    }
};

/* ==================== Dashboard 仪表盘 ==================== */

const DashboardUI = {
    charts: {},
    stats: null,

    async loadStats() {
        try {
            const stats = await API.getDashboardStats();
            this.stats = stats;
            this.renderKPIs(stats);
            this.renderIndustryHeatmap(stats.industry_coverage || {});
            this.renderMatchTrend(stats.match_trends || []);
            this.renderCompetitorFreq(stats.competitor_frequency || {});
            this.renderInfoBar(stats);
        } catch (error) {
            console.error('加载仪表盘数据失败:', error);
            UI.showToast('加载仪表盘数据失败', 'warning');
        }
    },

    renderKPIs(stats) {
        const animateValue = (el, target, suffix = '') => {
            if (!el) return;
            const start = 0;
            const duration = 1000;
            const startTime = performance.now();
            const step = (now) => {
                const progress = Math.min((now - startTime) / duration, 1);
                const easeOut = 1 - Math.pow(1 - progress, 3);
                el.textContent = Math.floor(start + (target - start) * easeOut) + suffix;
                if (progress < 1) requestAnimationFrame(step);
            };
            requestAnimationFrame(step);
        };

        animateValue(document.getElementById('dash-total-matches'), stats.recent_matches || 0);
        animateValue(document.getElementById('dash-total-analyses'), stats.recent_analyses || 0);
        animateValue(document.getElementById('dash-total-docs'), stats.total_documents || 0);

        const accEl = document.getElementById('dash-accuracy');
        if (accEl) accEl.textContent = (stats.accuracy || 87) + '%';

        // 涨幅显示（7日环比）
        const formatTrend = (val) => {
            if (val === null) return { text: '↗ 新增长', cls: '' };
            if (val > 0)   return { text: `↗ +${val}%`,  cls: '' };
            if (val < 0)   return { text: `↘ ${val}%`,  cls: 'trend-down' };
            return              { text: '— 0%',       cls: '' };
        };

        const m = formatTrend(stats.match_growth);
        const matchEl = document.getElementById('dash-match-trend');
        if (matchEl) { matchEl.textContent = m.text; matchEl.className = 'kpi-trend' + (m.cls ? ' ' + m.cls : ''); }

        const a = formatTrend(stats.analyze_growth);
        const analyzeEl = document.getElementById('dash-analyze-trend');
        if (analyzeEl) { analyzeEl.textContent = a.text; analyzeEl.className = 'kpi-trend' + (a.cls ? ' ' + a.cls : ''); }
    },

    renderIndustryHeatmap(coverage) {
        const canvas = document.getElementById('industry-heatmap-chart');
        if (!canvas || typeof Chart === 'undefined') return;
        if (this.charts.heatmap) this.charts.heatmap.destroy();

        const labels = Object.keys(coverage);
        const data = Object.values(coverage);
        
        // 生成热力图颜色
        const maxVal = Math.max(...data, 1);
        const bgColors = data.map(v => {
            const intensity = v / maxVal;
            return `rgba(199, 0, 11, ${0.3 + intensity * 0.7})`;
        });

        this.charts.heatmap = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: '文档覆盖数',
                    data: data,
                    backgroundColor: bgColors,
                    borderColor: 'rgba(199, 0, 11, 0.8)',
                    borderWidth: 1,
                    borderRadius: 8
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `文档数: ${ctx.raw} 篇`
                        }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(255, 255, 255, 0.08)' },
                        ticks: { color: 'rgba(255, 255, 255, 0.7)', font: { size: 13 } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { color: 'rgba(255, 255, 255, 0.85)', font: { size: 13, weight: '500' } }
                    }
                }
            }
        });
    },

    renderMatchTrend(trends) {
        const canvas = document.getElementById('match-trend-chart');
        if (!canvas || typeof Chart === 'undefined') return;
        if (this.charts.trend) this.charts.trend.destroy();

        const labels = trends.map(t => t.date);
        const matchData = trends.map(t => t.matches);
        const analyzeData = trends.map(t => t.analyses);

        this.charts.trend = new Chart(canvas, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: '方案匹配',
                        data: matchData,
                        borderColor: '#C7000B',
                        backgroundColor: 'rgba(199, 0, 11, 0.1)',
                        borderWidth: 3,
                        tension: 0.4,
                        fill: true,
                        pointBackgroundColor: '#C7000B',
                        pointRadius: 4,
                        pointHoverRadius: 6
                    },
                    {
                        label: '竞品分析',
                        data: analyzeData,
                        borderColor: '#4A90E2',
                        backgroundColor: 'rgba(74, 144, 226, 0.1)',
                        borderWidth: 3,
                        tension: 0.4,
                        fill: true,
                        pointBackgroundColor: '#4A90E2',
                        pointRadius: 4,
                        pointHoverRadius: 6
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    legend: {
                        labels: { color: 'rgba(255, 255, 255, 0.8)', font: { size: 12 } }
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        grid: { color: 'rgba(255, 255, 255, 0.08)' },
                        ticks: { color: 'rgba(255, 255, 255, 0.7)', font: { size: 13 } }
                    },
                    x: {
                        grid: { display: false },
                        ticks: { 
                            color: 'rgba(255, 255, 255, 0.75)', 
                            font: { size: 14, weight: '500' },
                            maxRotation: 0
                        }
                    }
                }
            }
        });
    },

    renderCompetitorFreq(freq) {
        const canvas = document.getElementById('competitor-freq-chart');
        if (!canvas || typeof Chart === 'undefined') return;
        if (this.charts.freq) this.charts.freq.destroy();

        // 排序取Top10
        const sorted = Object.entries(freq).sort((a, b) => b[1] - a[1]).slice(0, 12);
        const labels = sorted.map(([k]) => k);
        const data = sorted.map(([, v]) => v);

        this.charts.freq = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: labels,
                datasets: [{
                    label: '分析次数',
                    data: data,
                    backgroundColor: [
                        'rgba(199, 0, 11, 0.85)',
                        'rgba(199, 0, 11, 0.75)',
                        'rgba(199, 0, 11, 0.65)',
                        'rgba(74, 144, 226, 0.7)',
                        'rgba(74, 144, 226, 0.6)',
                        'rgba(74, 144, 226, 0.5)',
                        'rgba(82, 196, 26, 0.6)',
                        'rgba(82, 196, 26, 0.5)',
                        'rgba(250, 173, 20, 0.6)',
                        'rgba(250, 173, 20, 0.5)'
                    ],
                    borderRadius: 6,
                    borderSkipped: false
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',
                plugins: {
                    legend: { display: false },
                    tooltip: {
                        callbacks: {
                            label: (ctx) => `分析 ${ctx.raw} 次`
                        }
                    }
                },
                scales: {
                    x: {
                        type: 'linear',
                        grid: { color: 'rgba(255, 255, 255, 0.08)' },
                        ticks: {
                            color: 'rgba(255, 255, 255, 0.85)',
                            font: { family: 'Inter, sans-serif', size: 15, weight: '600' },
                            precision: 0,
                            padding: 8
                        },
                        border: { display: false }
                    },
                    y: {
                        grid: { display: false },
                        ticks: {
                            color: 'rgba(255, 255, 255, 0.9)',
                            font: { family: 'Inter, sans-serif', size: 14, weight: '600' },
                            padding: 12
                        },
                        border: { display: false }
                    }
                },
                layout: {
                    padding: { left: 4, right: 20, top: 8, bottom: 8 }
                }
            }
        });
    },

    renderInfoBar(stats) {
        const versionEl = document.getElementById('dash-version');
        const uptimeEl = document.getElementById('dash-uptime');
        const updateEl = document.getElementById('dash-last-update');

        if (versionEl) versionEl.textContent = stats.version || 'v1.0.0';
        if (uptimeEl) uptimeEl.textContent = stats.system_uptime || '--';
        if (updateEl) updateEl.textContent = stats.last_update || '--';
    }
};

/* ==================== 历史记录 ==================== */

const HistoryUI = {
    items: [],
    selectedIds: new Set(),
    isCompareMode: false,
    currentCompareIds: [],

    async loadHistory() {
        try {
            const data = await API.getHistoryList();
            this.items = data.items || [];
            this.renderList();
            this.updateCount();
        } catch (error) {
            console.error('加载历史记录失败:', error);
            UI.showToast('加载历史记录失败', 'warning');
        }
    },

    updateCount() {
        const el = document.getElementById('history-count');
        if (el) el.textContent = `共 ${this.items.length} 条记录`;
    },

    renderList() {
        const container = document.getElementById('history-list');
        if (!container) return;

        if (this.items.length === 0) {
            container.innerHTML = `
                <div class="history-empty">
                    <div class="empty-icon">📋</div>
                    <p>暂无历史记录</p>
                    <p class="empty-sub">在「解决方案匹配」页面输入需求并匹配后，方案会自动保存到这里</p>
                </div>
            `;
            return;
        }

        container.innerHTML = this.items.map(item => {
            const isSelected = this.selectedIds.has(item.id);
            const dateStr = item.created_at ? item.created_at.replace('T', ' ').substring(0, 16) : '--';
            const demandPreview = (item.demand_text || '').substring(0, 120);
            return `
                <div class="history-item ${isSelected ? 'selected' : ''}" data-id="${item.id}" onclick="HistoryUI.onItemClick(event, ${item.id})">
                    <div class="history-item-checkbox">${isSelected ? '✓' : ''}</div>
                    <div class="history-item-content">
                        <div class="history-item-header">
                            <span class="history-item-date">${dateStr}</span>
                            ${item.industry ? `<span class="history-item-industry">${item.industry}</span>` : ''}
                        </div>
                        <div class="history-item-demand">${this.escapeHtml(demandPreview)}${item.demand_text && item.demand_text.length > 120 ? '...' : ''}</div>
                    </div>
                    <div class="history-item-actions">
                        <button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); HistoryUI.showDetail(${item.id})">查看</button>
                    </div>
                </div>
            `;
        }).join('');
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    onItemClick(event, id) {
        if (!this.isCompareMode) {
            this.showDetail(id);
            return;
        }
        // 对比模式：切换选中
        if (this.selectedIds.has(id)) {
            this.selectedIds.delete(id);
        } else {
            if (this.selectedIds.size >= 2) {
                UI.showToast('最多选择两条记录进行对比', 'warning');
                return;
            }
            this.selectedIds.add(id);
        }
        this.renderList();
        this.updateCompareUI();
    },

    updateCompareUI() {
        const hint = document.getElementById('compare-hint');
        const btn = document.getElementById('btn-do-compare');
        if (!hint || !btn) return;

        if (!this.isCompareMode) {
            hint.textContent = '';
            hint.classList.remove('visible');
            btn.textContent = '开始对比';
            btn.disabled = false;
            return;
        }

        const count = this.selectedIds.size;
        btn.textContent = `确认对比 (${count}/2)`;

        if (count === 0) {
            hint.textContent = '请勾选两条记录进行对比';
            hint.classList.add('visible');
            btn.disabled = true;
        } else if (count === 1) {
            hint.textContent = '再勾选一条记录';
            hint.classList.add('visible');
            btn.disabled = true;
        } else {
            hint.textContent = '已选满两条，点击确认对比';
            hint.classList.add('visible');
            btn.disabled = false;
        }
    },

    enterCompareMode() {
        this.isCompareMode = true;
        this.selectedIds.clear();
        this.renderList();
        this.updateCompareUI();
        const btnDo = document.getElementById('btn-do-compare');
        const btnClear = document.getElementById('btn-clear-compare');
        if (btnDo) { btnDo.style.display = ''; btnDo.disabled = true; }
        if (btnClear) btnClear.style.display = '';
        UI.showToast('请勾选两条记录，然后点击「确认对比」', 'info');
    },

    exitCompareMode() {
        this.isCompareMode = false;
        this.selectedIds.clear();
        this.renderList();
        this.updateCompareUI();
        const btnDo = document.getElementById('btn-do-compare');
        const btnClear = document.getElementById('btn-clear-compare');
        if (btnDo) { btnDo.style.display = ''; btnDo.disabled = false; btnDo.textContent = '开始对比'; }
        if (btnClear) btnClear.style.display = 'none';
    },

    async doCompare() {
        if (this.selectedIds.size !== 2) return;
        const [idA, idB] = Array.from(this.selectedIds);
        try {
            const data = await API.compareHistory(idA, idB);
            this.renderCompare(data.item_a, data.item_b);
        } catch (error) {
            console.error('对比失败:', error);
            UI.showToast('对比失败: ' + error.message, 'error');
        }
    },

    renderCompare(itemA, itemB) {
        const panel = document.getElementById('history-compare-panel');
        const body = document.getElementById('compare-body');
        if (!panel || !body) return;

        this.currentCompareIds = [itemA.id, itemB.id];

        // 重置 AI 总结区域
        const aiSummaryBottom = document.getElementById('compare-ai-summary-bottom');
        const aiContent = document.getElementById('ai-summary-content');
        const aiAction = document.getElementById('compare-ai-action');
        const aiBtn = document.getElementById('btn-ai-summary');
        const aiLoading = document.getElementById('ai-summary-loading');
        if (aiSummaryBottom) aiSummaryBottom.style.display = 'none';
        if (aiContent) aiContent.innerHTML = '';
        if (aiAction) aiAction.style.display = 'flex';
        if (aiBtn) aiBtn.style.display = 'flex';
        if (aiLoading) aiLoading.style.display = 'none';

        const renderCol = (item, label) => `
            <div class="compare-column">
                <div class="compare-column-header">${label} · ${item.created_at ? item.created_at.replace('T', ' ').substring(0, 16) : ''}</div>
                <div class="compare-column-demand">
                    <strong>需求：</strong>${this.escapeHtml(item.demand_text || '')}
                </div>
                <div class="compare-column-solution result-content">
                    ${item.solution ? UI.renderMarkdown(item.solution) : '<p style="color: var(--text-muted)">无方案内容</p>'}
                </div>
            </div>
        `;

        body.innerHTML = renderCol(itemA, '方案 A') + renderCol(itemB, '方案 B');
        panel.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    },

    async doAISummary() {
        if (this.currentCompareIds.length !== 2) return;
        const [idA, idB] = this.currentCompareIds;

        const aiBtn = document.getElementById('btn-ai-summary');
        const aiLoading = document.getElementById('ai-summary-loading');
        if (aiBtn) aiBtn.style.display = 'none';
        if (aiLoading) aiLoading.style.display = 'flex';

        try {
            const data = await API.getCompareAISummary(idA, idB);
            const aiSummaryBottom = document.getElementById('compare-ai-summary-bottom');
            const aiContent = document.getElementById('ai-summary-content');
            const aiAction = document.getElementById('compare-ai-action');
            if (aiContent) aiContent.innerHTML = UI.renderMarkdown(data.summary);
            if (aiSummaryBottom) aiSummaryBottom.style.display = '';
            if (aiAction) aiAction.style.display = 'none';
        } catch (error) {
            console.error('AI总结失败:', error);
            UI.showToast('AI总结生成失败: ' + error.message, 'error');
            if (aiBtn) aiBtn.style.display = 'flex';
            if (aiLoading) aiLoading.style.display = 'none';
        }
    },

    closeCompare() {
        const panel = document.getElementById('history-compare-panel');
        const aiSummaryBottom = document.getElementById('compare-ai-summary-bottom');
        if (panel) panel.style.display = 'none';
        if (aiSummaryBottom) aiSummaryBottom.style.display = 'none';
        document.body.style.overflow = '';
        this.currentCompareIds = [];
    },

    async showDetail(id) {
        try {
            const item = await API.getHistoryDetail(id);
            const modal = document.getElementById('history-detail-modal');
            const body = document.getElementById('detail-body');
            if (!modal || !body) return;

            const dateStr = item.created_at ? item.created_at.replace('T', ' ').substring(0, 16) : '--';
            body.innerHTML = `
                <div class="detail-section">
                    <div class="detail-section-label">创建时间</div>
                    <div style="font-size: var(--font-size-sm); color: var(--text-secondary);">${dateStr}</div>
                </div>
                <div class="detail-section">
                    <div class="detail-section-label">客户需求</div>
                    <div class="detail-demand">${this.escapeHtml(item.demand_text || '')}</div>
                </div>
                <div class="detail-section">
                    <div class="detail-section-label">匹配方案</div>
                    <div class="detail-solution result-content">${item.solution ? UI.renderMarkdown(item.solution) : '<p style="color: var(--text-muted)">无方案内容</p>'}</div>
                </div>
            `;
            modal.style.display = 'flex';
            document.body.style.overflow = 'hidden';
        } catch (error) {
            console.error('加载详情失败:', error);
            UI.showToast('加载详情失败', 'warning');
        }
    },

    closeDetail() {
        const modal = document.getElementById('history-detail-modal');
        if (modal) modal.style.display = 'none';
        document.body.style.overflow = '';
    },

    init() {
        const btnCompare = document.getElementById('btn-do-compare');
        const btnClear = document.getElementById('btn-clear-compare');
        const btnCloseDetail = document.getElementById('close-detail');
        const btnCloseCompare = document.getElementById('close-compare');

        if (btnCompare) {
            btnCompare.addEventListener('click', () => {
                if (this.isCompareMode) {
                    this.doCompare();
                } else {
                    this.enterCompareMode();
                }
            });
        }
        if (btnClear) btnClear.addEventListener('click', () => this.exitCompareMode());
        if (btnCloseDetail) btnCloseDetail.addEventListener('click', () => this.closeDetail());
        if (btnCloseCompare) btnCloseCompare.addEventListener('click', () => this.closeCompare());

        // AI 总结按钮
        const btnAISummary = document.getElementById('btn-ai-summary');
        if (btnAISummary) btnAISummary.addEventListener('click', () => this.doAISummary());

        // 点击遮罩关闭
        document.getElementById('history-detail-modal')?.addEventListener('click', (e) => {
            if (e.target === e.currentTarget) this.closeDetail();
        });
        document.getElementById('history-compare-panel')?.addEventListener('click', (e) => {
            if (e.target === e.currentTarget) this.closeCompare();
        });

        // 初始化按钮状态（解除 HTML 中的 disabled）
        this.updateCompareUI();
    }
};

function initEventListeners() {
    document.querySelectorAll('.navbar-item').forEach(item => {
        item.addEventListener('click', () => {
            const page = item.dataset.page;
            UI.switchPage(page);
            
            if (page === 'knowledge') {
                KnowledgeUI.loadStats();
            }
            if (page === 'dashboard') {
                DashboardUI.loadStats();
            }
            if (page === 'history') {
                HistoryUI.loadHistory();
            }
        });
    });

    document.querySelectorAll('.mobile-item').forEach(item => {
        item.addEventListener('click', () => {
            const page = item.dataset.page;
            UI.switchPage(page);
            
            if (page === 'knowledge') {
                KnowledgeUI.loadStats();
            }
            if (page === 'dashboard') {
                DashboardUI.loadStats();
            }
            if (page === 'history') {
                HistoryUI.loadHistory();
            }

            const mobileMenu = document.getElementById('mobile-menu');
            mobileMenu?.classList.remove('open');
        });
    });
    
    const navbarToggle = document.getElementById('navbar-toggle');
    const mobileMenu = document.getElementById('mobile-menu');
    
    navbarToggle?.addEventListener('click', () => {
        mobileMenu.classList.toggle('open');
    });
    
    const demandInput = document.getElementById('demand-input');
    const charCount = document.getElementById('demand-char-count');
    
    demandInput?.addEventListener('input', () => {
        const length = demandInput.value.length;
        charCount.textContent = length;
        
        if (length > 2000) {
            charCount.style.color = 'var(--error)';
        } else {
            charCount.style.color = 'var(--text-secondary)';
        }
    });
    
    const matchBtn = document.getElementById('match-btn');
    const matchBtnText = matchBtn?.querySelector('.btn-text');

    matchBtn?.addEventListener('click', async () => {
        // --- 取消模式 ---
        if (State.loadingStates.match) {
            if (State.abortControllers.match) {
                State.abortControllers.match.abort();
            }
            MatchProgress.cancel();
            State.loadingStates.match = false;
            if (matchBtnText) matchBtnText.textContent = '开始匹配';
            matchBtn.classList.remove('btn-cancel');
            UI.setButtonLoading(matchBtn, false);
            State.abortControllers.match = null;
            UI.showToast('已取消匹配', 'info');
            return;
        }

        const demand = demandInput.value.trim();
        
        if (!demand) {
            UI.showToast('请输入客户需求描述', 'warning');
            return;
        }
        
        if (demand.length > 2000) {
            UI.showToast('需求描述不能超过2000字符', 'warning');
            return;
        }

        // 隐藏之前的结果
        document.getElementById('solution-result').style.display = 'none';
        
        // 创建 AbortController
        const controller = new AbortController();
        State.abortControllers.match = controller;
        State.loadingStates.match = true;
        
        // 切换为取消按钮
        if (matchBtnText) matchBtnText.textContent = '取消匹配';
        matchBtn.classList.add('btn-cancel');
        
        // 启动进度面板
        MatchProgress.start();
        MatchProgress.simulateProgress(3, 6000);
        
        try {
            const result = await API.match(demand, controller.signal);
            
            // API返回，显示完成
            MatchProgress.success('方案匹配完成！');
            
            const resultContainer = document.getElementById('solution-result');
            const resultContent = document.getElementById('solution-content');
            const sourcesContainer = document.getElementById('solution-sources');
            
            resultContent.innerHTML = UI.renderMarkdown(result.answer);
            UI.renderSources(sourcesContainer, result.source_documents);
            resultContainer.style.display = 'block';
            resultContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
            
            State.resultCache.solution = result;
            FollowUpUI.show(demand, result.answer, result.history_id);
            
            UI.showToast('匹配完成！', 'success');
        } catch (error) {
            if (error.name === 'AbortError') {
                // 用户主动取消，不报错
                console.log('匹配已取消');
                return;
            }
            console.error('匹配失败:', error);
            MatchProgress.error('匹配失败，请重试');
            UI.showToast(error.message || '匹配失败，请重试', 'error');
        } finally {
            State.loadingStates.match = false;
            if (matchBtnText) matchBtnText.textContent = '开始匹配';
            matchBtn.classList.remove('btn-cancel');
            State.abortControllers.match = null;
        }
    });
    
    document.getElementById('clear-solution-btn')?.addEventListener('click', () => {
        // 如果正在匹配，先触发取消
        if (State.loadingStates.match && matchBtn) {
            matchBtn.click();
        }
        demandInput.value = '';
        charCount.textContent = '0';
        document.getElementById('solution-result').style.display = 'none';
        MatchProgress.hide();
        State.resultCache.solution = null;
    });
    
    document.getElementById('download-solution-btn')?.addEventListener('click', () => {
        if (State.resultCache.solution) {
            UI.downloadFile(
                State.resultCache.solution.answer,
                '华为云解决方案建议书.md'
            );
        }
    });
    
    const analyzeBtn = document.getElementById('analyze-btn');
    const analyzeBtnText = analyzeBtn?.querySelector('.btn-text');

    analyzeBtn?.addEventListener('click', async () => {
        // --- 取消模式 ---
        if (State.loadingStates.analyze) {
            if (State.abortControllers.analyze) {
                State.abortControllers.analyze.abort();
            }
            AnalyzeProgress.cancel();
            State.loadingStates.analyze = false;
            if (analyzeBtnText) analyzeBtnText.textContent = '开始分析';
            analyzeBtn.classList.remove('btn-cancel');
            UI.setButtonLoading(analyzeBtn, false);
            State.abortControllers.analyze = null;
            UI.showToast('已取消分析', 'info');
            return;
        }

        const competitor = document.getElementById('competitor-select').value;
        const industry = document.getElementById('industry-select').value;
        
        // 隐藏之前的结果
        document.getElementById('competitor-result').style.display = 'none';
        
        // 创建 AbortController
        const controller = new AbortController();
        State.abortControllers.analyze = controller;
        State.loadingStates.analyze = true;
        
        // 切换为取消按钮
        if (analyzeBtnText) analyzeBtnText.textContent = '取消分析';
        analyzeBtn.classList.add('btn-cancel');
        
        // 启动进度面板
        AnalyzeProgress.start();
        AnalyzeProgress.simulateProgress(4, 8000);
        
        try {
            const result = await API.analyze(competitor, industry, controller.signal);
            
            // API返回，显示完成
            AnalyzeProgress.success('竞争分析完成！');
            
            const resultContainer = document.getElementById('competitor-result');
            const resultContent = document.getElementById('competitor-content');
            const sourcesContainer = document.getElementById('competitor-sources');
            
            resultContent.innerHTML = UI.renderMarkdown(result.answer);
            UI.renderSources(sourcesContainer, result.source_documents);
            resultContainer.style.display = 'block';
            resultContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });
            
            State.resultCache.competitor = { ...result, competitor, industry };
            
            UI.showToast('分析完成！', 'success');
        } catch (error) {
            if (error.name === 'AbortError') {
                console.log('分析已取消');
                return;
            }
            console.error('分析失败:', error);
            AnalyzeProgress.error('分析失败，请重试');
            UI.showToast(error.message || '分析失败，请重试', 'error');
        } finally {
            State.loadingStates.analyze = false;
            if (analyzeBtnText) analyzeBtnText.textContent = '开始分析';
            analyzeBtn.classList.remove('btn-cancel');
            State.abortControllers.analyze = null;
        }
    });
    
    document.getElementById('clear-competitor-btn')?.addEventListener('click', () => {
        // 如果正在分析，先触发取消
        if (State.loadingStates.analyze && analyzeBtn) {
            analyzeBtn.click();
        }
        document.getElementById('competitor-result').style.display = 'none';
        AnalyzeProgress.hide();
        State.resultCache.competitor = null;
    });
    
    document.getElementById('download-competitor-btn')?.addEventListener('click', () => {
        if (State.resultCache.competitor) {
            const { competitor, industry, answer } = State.resultCache.competitor;
            UI.downloadFile(
                answer,
                `华为云vs${competitor}_${industry}行业竞争分析报告.md`
            );
        }
    });
    
    const rebuildBtn = document.getElementById('rebuild-btn');
    const rebuildProgressPanel = document.getElementById('rebuild-progress-panel');
    const rebuildStatusText = document.getElementById('rebuild-status-text');
    
    rebuildBtn?.addEventListener('click', async () => {
        UI.setButtonLoading(rebuildBtn, true);
        
        // 显示重建进度面板
        if (rebuildProgressPanel) {
            rebuildProgressPanel.style.display = 'block';
            rebuildProgressPanel.classList.remove('success', 'fade-out');
        }
        if (rebuildStatusText) rebuildStatusText.textContent = '正在读取文档目录...';
        
        // 模拟状态更新
        const statusMessages = [
            { delay: 1500, text: '正在加载华为云方案文档...' },
            { delay: 3000, text: '正在加载竞品方案文档...' },
            { delay: 5000, text: '正在分割文档为片段...' },
            { delay: 7000, text: '正在生成向量嵌入（这可能需要一些时间）...' },
            { delay: 10000, text: '正在写入向量数据库...' }
        ];
        
        const statusTimers = statusMessages.map(msg => 
            setTimeout(() => {
                if (rebuildStatusText) rebuildStatusText.textContent = msg.text;
            }, msg.delay)
        );
        
        try {
            const result = await API.rebuildKnowledge();
            
            // 清除所有定时器
            statusTimers.forEach(t => clearTimeout(t));
            
            // 显示成功状态
            if (rebuildProgressPanel) {
                rebuildProgressPanel.classList.add('success');
                const title = rebuildProgressPanel.querySelector('.progress-title');
                if (title) title.textContent = '知识库重建完成！';
            }
            if (rebuildStatusText) {
                rebuildStatusText.textContent = `成功添加 ${result.count || 0} 个文档片段到知识库`;
            }
            
            UI.showToast(`知识库重建完成！共添加 ${result.count || 0} 个文档片段`, 'success');
            await KnowledgeUI.loadStats();
            
            // 3秒后淡出
            setTimeout(() => {
                if (rebuildProgressPanel) {
                    rebuildProgressPanel.classList.add('fade-out');
                    setTimeout(() => {
                        rebuildProgressPanel.style.display = 'none';
                        rebuildProgressPanel.classList.remove('success', 'fade-out');
                    }, 500);
                }
            }, 3000);
        } catch (error) {
            // 清除所有定时器
            statusTimers.forEach(t => clearTimeout(t));
            
            console.error('重建失败:', error);
            if (rebuildProgressPanel) {
                rebuildProgressPanel.classList.remove('success');
                const title = rebuildProgressPanel.querySelector('.progress-title');
                if (title) title.textContent = '重建失败';
            }
            if (rebuildStatusText) rebuildStatusText.textContent = error.message || '重建失败，请重试';
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

const FollowUpUI = {
    history: [],
    originalDemand: '',
    currentSolution: '',
    currentHistoryId: null,

    init() {
        const input = document.getElementById('follow-up-input');
        const sendBtn = document.getElementById('send-follow-up-btn');
        const clearBtn = document.getElementById('clear-follow-up-btn');
        if (sendBtn) sendBtn.addEventListener('click', () => this.sendFollowUp());
        if (input) {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this.sendFollowUp();
                }
            });
        }
        if (clearBtn) clearBtn.addEventListener('click', () => this.clearHistory());

        const applyBtn = document.getElementById('apply-refined-btn');
        if (applyBtn) applyBtn.addEventListener('click', () => this.applyRefined());
    },

    show(originalDemand, currentSolution, historyId) {
        this.originalDemand = originalDemand;
        this.currentSolution = currentSolution;
        this.currentHistoryId = historyId || null;
        this.history = [];
        const section = document.getElementById('follow-up-section');
        if (section) section.style.display = 'block';
        this.renderHistory();
    },

    hide() {
        const section = document.getElementById('follow-up-section');
        if (section) section.style.display = 'none';
        this.history = [];
    },

    async sendFollowUp() {
        const input = document.getElementById('follow-up-input');
        const text = input?.value?.trim();
        if (!text) return;
        this.history.push({ role: 'user', content: text });
        this.renderHistory();
        if (input) input.value = '';
        this.showLoading(true);
        try {
            const data = await API.refineSolution(
                this.originalDemand,
                this.currentSolution,
                text,
                this.history.slice(0, -1)
            );
            this.history.push({ role: 'ai', content: data.refined_solution });
            this.currentSolution = data.refined_solution;
            this.renderHistory();
        } catch (error) {
            console.error('方案优化失败:', error);
            UI.showToast('方案优化失败: ' + error.message, 'error');
        } finally {
            this.showLoading(false);
        }
    },

    renderHistory() {
        const container = document.getElementById('follow-up-history');
        if (!container) return;
        container.innerHTML = this.history.map(msg => {
            if (msg.role === 'user') {
                return '<div class="follow-up-msg follow-up-user-msg">' + this.escapeHtml(msg.content) + '</div>';
            } else {
                return '<div class="follow-up-msg follow-up-ai-msg"><div class="result-content">' + UI.renderMarkdown(msg.content) + '</div></div>';
            }
        }).join('');
        container.scrollTop = container.scrollHeight;

        // 显示/隐藏"使用此优化结果"按钮
        const actions = document.getElementById('follow-up-actions');
        if (actions) {
            const hasAiMsg = this.history.some(m => m.role === 'ai');
            actions.style.display = hasAiMsg && this.currentHistoryId ? 'flex' : 'none';
        }
    },

    showLoading(show) {
        const loadingEl = document.getElementById('follow-up-loading');
        const sendBtn = document.getElementById('send-follow-up-btn');
        if (loadingEl) loadingEl.style.display = show ? 'flex' : 'none';
        if (sendBtn) sendBtn.disabled = show;
    },

    clearHistory() {
        this.history = [];
        this.renderHistory();
    },

    async applyRefined() {
        if (!this.currentHistoryId || !this.currentSolution) return;
        const btn = document.getElementById('apply-refined-btn');
        if (btn) btn.disabled = true;
        try {
            await API.updateHistorySolution(this.currentHistoryId, this.currentSolution);
            UI.showToast('方案已更新到历史记录', 'success');
        } catch (error) {
            console.error('更新历史方案失败:', error);
            UI.showToast('更新失败: ' + error.message, 'error');
        } finally {
            if (btn) btn.disabled = false;
        }
    },

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

function init() {
    const canvas = document.getElementById('particle-canvas');
    if (canvas) {
        new ParticleSystem(canvas);
    }
    
    initEventListeners();
    HistoryUI.init();
    FollowUpUI.init();
    
    KnowledgeUI.loadStats();
}

document.addEventListener('DOMContentLoaded', init);
