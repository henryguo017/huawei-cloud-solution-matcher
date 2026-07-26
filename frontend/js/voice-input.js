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
    var TARGETS = [
        { sel: '#demand-input', mode: 'wrap' },                 // 标准模式需求描述
        { sel: '#wizard-extra', mode: 'wrap' },                 // 向导模式补充信息
        { sel: '#wizard-custom-pain', mode: 'wrap' },           // 向导模式自定义痛点
        { sel: '#follow-up-input', mode: 'wrap' },              // 匹配结果后追问
        { sel: '#competitor-follow-up-input', mode: 'wrap' },   // 竞品分析后追问
        { sel: '#kb-editor-content', mode: 'wrap' },            // 知识库编辑器正文
        { sel: '#ai-input', mode: 'inline', parent: '.ai-input-box' } // Agent 对话输入
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
            var parent = cfg.parent ? el.closest(cfg.parent) : el.parentNode;
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

        function render(interim) {
            setVal(el, baseValue + finalTranscript + (interim || ''));
        }

        rec.onstart = function () {
            listening = true;
            btn.classList.add('listening');
        };

        rec.onresult = function (e) {
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
            if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
                alert('麦克风权限被拒绝，请在浏览器地址栏允许麦克风后重试。');
            }
        };

        rec.onend = function () {
            // 提交最终文本（去掉临时 interim）
            setVal(el, baseValue + finalTranscript);
            finalTranscript = '';
            if (listening) {
                // continuous 模式浏览器静音自动结束后，保持续听
                try { rec.start(); } catch (err) { /* 已在监听则忽略 */ }
            } else {
                btn.classList.remove('listening');
            }
        };

        btn.addEventListener('click', function () {
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
