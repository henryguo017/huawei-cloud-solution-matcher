/*
 * 语音输入模块（cloudsol.cn）
 * 基于浏览器原生 Web Speech API（webkitSpeechRecognition / SpeechRecognition）。
 * - 免费、零后端改动、无需 API key。
 * - 支持 zh-CN，连续识别 + 临时结果实时回填。
 * - 不支持的浏览器（如 Firefox）自动不挂载麦克风按钮。
 * - 填充后 dispatch 'input' 事件，联动现有自动增高 / 发送按钮启用 / 字数统计。
 * 纯 IIFE，仅挂 window.CloudSolVoice，避免与 script.js 全局命名冲突。
 */
(function () {
    'use strict';

    var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) {
        // 浏览器不支持：不挂载任何按钮
        window.CloudSolVoice = { supported: false, init: function () {} };
        return;
    }

    var MIC_SVG =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path>' +
        '<path d="M19 10v2a7 7 0 0 1-14 0v-2"></path>' +
        '<line x1="12" y1="19" x2="12" y2="23"></line>' +
        '<line x1="8" y1="23" x2="16" y2="23"></line></svg>';

    // 目标输入框：mode=wrap 包裹（独立文本框）；mode=inline 内联（与发送按钮同排的 flex 容器）
    // target 为可选：直接指定按钮插入的容器（如 Agent 工具栏 .ws-toolbar），优先级高于 parent。
    var TARGETS = [
        { sel: '#demand-input', mode: 'wrap' },                 // 标准模式需求描述
        { sel: '#wizard-extra', mode: 'wrap' },                 // 向导模式补充信息
        { sel: '#wizard-custom-pain', mode: 'wrap' },           // 向导模式自定义痛点
        { sel: '#follow-up-input', mode: 'wrap' },              // 匹配结果后追问
        { sel: '#competitor-follow-up-input', mode: 'wrap' },   // 竞品分析后追问
        { sel: '#kb-editor-content', mode: 'wrap' },            // 知识库编辑器正文
        { sel: '#ai-input', mode: 'inline', parent: '.ai-input-box' }, // Agent 对话输入（经典 AI 助手）
        { sel: '#ws-input', mode: 'inline', target: '.ws-input-actions' }   // Agent 对话输入：mic 按钮注入到 .ws-input-actions（位于发送按钮左侧，输入框内右端）
    ];

    function setVal(el, text) {
        el.value = text;
        el.dispatchEvent(new Event('input', { bubbles: true }));
    }

    function attach(el, cfg) {
        if (!el || el.dataset.voiceReady) return;
        el.dataset.voiceReady = '1';

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'voice-mic-btn';
        btn.setAttribute('aria-label', '语音输入');
        btn.title = '点击开始 / 停止语音输入（中文）';
        btn.innerHTML = MIC_SVG;

        if (cfg.mode === 'wrap') {
            var wrap = document.createElement('div');
            wrap.className = 'voice-field';
            el.parentNode.insertBefore(wrap, el);
            wrap.appendChild(el);
            wrap.appendChild(btn);
            el.classList.add('has-voice');
        } else {
            // inline 模式：优先 target（直接指定容器），其次 parent（祖先选择器），最后父节点
            var parent = null;
            if (cfg.target) parent = document.querySelector(cfg.target);
            if (!parent && cfg.parent) parent = el.closest(cfg.parent);
            if (!parent) parent = el.parentNode;
            parent.appendChild(btn);
            el.classList.add('has-voice');
        }

        var rec = new SR();
        rec.lang = 'zh-CN';
        rec.interimResults = true;
        rec.continuous = true;

        var baseValue = '';
        var finalTranscript = '';
        var listening = false;
        var failed = false;           // 该输入框语音已被判定不可用（如识别服务连不上）
        var watchdog = null;          // 静默挂起看门狗：开始后长时间无结果则判定失败

        function notify(msg, type) {
            if (window.UI && typeof window.UI.showToast === 'function') {
                window.UI.showToast(msg, type || 'warning');
            } else {
                alert(msg);
            }
        }

        function markUnsupported(reason) {
            if (failed) return;
            failed = true;
            listening = false;
            if (watchdog) { clearTimeout(watchdog); watchdog = null; }
            btn.classList.remove('listening');
            btn.classList.add('is-disabled');
            btn.title = '当前浏览器语音识别不可用';
            btn.disabled = true;
            notify('语音识别不可用：' + reason + ' 请直接输入文字（建议用 Chrome / Edge / Safari 的语音输入）。', 'warning');
        }

        function render(interim) {
            setVal(el, baseValue + finalTranscript + (interim || ''));
        }

        function armWatchdog() {
            if (watchdog) clearTimeout(watchdog);
            // 开始后 10s 仍无任何识别结果 → 判定静默失败（如设备无法连接识别服务器）
            watchdog = setTimeout(function () {
                if (listening && !failed) {
                    try { rec.stop(); } catch (e) {}
                    markUnsupported('识别服务无响应');
                }
            }, 10000);
        }

        rec.onstart = function () {
            listening = true;
            btn.classList.add('listening');
            armWatchdog();
        };

        rec.onresult = function (e) {
            if (watchdog) { clearTimeout(watchdog); watchdog = null; }
            var interim = '';
            for (var i = e.resultIndex; i < e.results.length; i++) {
                var t = e.results[i][0].transcript;
                if (e.results[i].isFinal) finalTranscript += t;
                else interim += t;
            }
            render(interim);
        };

        rec.onerror = function (e) {
            listening = false;
            btn.classList.remove('listening');
            if (watchdog) { clearTimeout(watchdog); watchdog = null; }
            var err = e && e.error;
            if (err === 'not-allowed') {
                // 用户拒绝了麦克风权限，可重新授权，不判定为永久不可用
                notify('麦克风权限被拒绝，请在浏览器地址栏允许麦克风后重试。', 'warning');
            } else if (err === 'service-not-allowed') {
                // 浏览器/设备层面禁止（如无法连接识别服务）→ 永久降级
                markUnsupported('浏览器或设备未授权语音识别服务');
            } else if (err === 'network') {
                // 连不上识别服务器（华为等无 GMS 设备典型症状）→ 永久降级
                markUnsupported('无法连接语音识别服务器（多为设备/网络限制）');
            } else if (err === 'audio-capture') {
                notify('未检测到麦克风设备。', 'warning');
            }
            // no-speech / aborted 等瞬时错误：忽略，保持按钮可用
        };

        rec.onend = function () {
            if (watchdog) { clearTimeout(watchdog); watchdog = null; }
            // 提交最终文本（去掉临时 interim）
            setVal(el, baseValue + finalTranscript);
            finalTranscript = '';
            if (listening && !failed) {
                // continuous 模式浏览器静音自动结束后，保持续听
                try { rec.start(); } catch (err) { /* 已在监听则忽略 */ }
            } else {
                btn.classList.remove('listening');
            }
        };

        btn.addEventListener('click', function () {
            if (failed) return;            // 已判定不可用，直接忽略
            if (listening) {
                listening = false;
                rec.stop();
                btn.classList.remove('listening');
            } else {
                var v = el.value || '';
                baseValue = v.trim() ? v.replace(/\s+$/, '') + ' ' : v;
                finalTranscript = '';
                try { rec.start(); } catch (err) { /* 已在监听则忽略 */ }
            }
        });
    }

    function init() {
        TARGETS.forEach(function (cfg) {
            var el = document.querySelector(cfg.sel);
            if (el) attach(el, cfg);
        });
    }

    window.CloudSolVoice = { supported: true, init: init };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
