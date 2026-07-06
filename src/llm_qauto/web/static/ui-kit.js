/**
 * UI 工具包：Toast 通知 / 加载骨架屏 / 键盘快捷键
 * 依赖全局 escapeHtml()（app.js 定义）。本文件须在 app.js 之前或之后加载均可，
 * 但快捷键中调用的导航函数（showModuleHome 等）由其它脚本运行时提供。
 */
(function () {
    /* ============================ Toast 通知 ============================ */

    const TOAST_ICONS = {
        success:
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
        error:
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
        warning:
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
        info:
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    };

    function esc(s) {
        return typeof window.escapeHtml === "function"
            ? window.escapeHtml(s)
            : String(s == null ? "" : s)
                  .replace(/&/g, "&")
                  .replace(/</g, "<")
                  .replace(/>/g, ">");
    }

    /**
     * 显示一条 toast。
     * @param {string} message
     * @param {"success"|"error"|"warning"|"info"} type
     * @param {{duration?: number}} opts
     */
    function showToast(message, type, opts) {
        type = type || "info";
        opts = opts || {};
        let container = document.getElementById("toast-container");
        if (!container) {
            container = document.createElement("div");
            container.id = "toast-container";
            container.className = "toast-container";
            container.setAttribute("aria-live", "assertive");
            document.body.appendChild(container);
        }
        const el = document.createElement("div");
        el.className = "toast toast--" + type;
        el.setAttribute("role", type === "error" ? "alert" : "status");
        el.innerHTML =
            '<span class="toast-icon" aria-hidden="true">' +
            (TOAST_ICONS[type] || TOAST_ICONS.info) +
            "</span>" +
            '<span class="toast-msg">' +
            esc(message) +
            "</span>";
        el.addEventListener("click", function () {
            dismiss(el);
        });
        container.appendChild(el);
        requestAnimationFrame(function () {
            el.classList.add("toast--show");
        });
        const duration =
            opts.duration != null
                ? opts.duration
                : type === "error"
                  ? 6000
                  : 3500;
        if (duration > 0) {
            setTimeout(function () {
                dismiss(el);
            }, duration);
        }
        return el;
    }

    function dismiss(el) {
        if (!el || !el.parentNode) return;
        el.classList.remove("toast--show");
        el.classList.add("toast--leaving");
        const done = function () {
            if (el.parentNode) el.parentNode.removeChild(el);
        };
        el.addEventListener("transitionend", done, { once: true });
        // 兜底：动画未触发时 400ms 后强制移除
        setTimeout(done, 400);
    }

    window.showToast = showToast;

    /* ============================ 加载骨架屏 ============================ */

    /**
     * 生成骨架屏列表 HTML。
     * @param {number} count 行数
     * @param {function(index): string} rowTpl 单行骨架模板
     */
    function skeletonList(count, rowTpl) {
        count = count || 3;
        let html = "";
        for (let i = 0; i < count; i++) {
            html += rowTpl ? rowTpl(i) : '<div class="skeleton skeleton-line"></div>';
        }
        return '<div class="skeleton-wrap">' + html + "</div>";
    }

    /** 项目卡片骨架 */
    function skeletonProjectCards(count) {
        count = count || 4;
        let html = "";
        for (let i = 0; i < count; i++) {
            html +=
                '<div class="project-card"><div class="project-card-inner">' +
                '<div class="project-card-icon"><div class="project-card-icon-inner skeleton skeleton-square"></div></div>' +
                '<div class="project-card-body">' +
                '<div class="skeleton skeleton-line" style="width:55%"></div>' +
                '<div class="skeleton skeleton-line" style="width:80%;margin-top:8px"></div>' +
                '<div class="skeleton skeleton-line" style="width:35%;margin-top:8px"></div>' +
                "</div></div></div>";
        }
        return html;
    }

    /** 通用行骨架（运行列表 / 会话列表） */
    function skeletonRows(count) {
        count = count || 4;
        let html = "";
        for (let i = 0; i < count; i++) {
            html +=
                '<div class="skeleton-row">' +
                '<div class="skeleton skeleton-line" style="width:30%"></div>' +
                '<div class="skeleton skeleton-line" style="width:20%"></div>' +
                '<div class="skeleton skeleton-line" style="width:15%"></div>' +
                "</div>";
        }
        return html;
    }

    window.skeletonList = skeletonList;
    window.skeletonProjectCards = skeletonProjectCards;
    window.skeletonRows = skeletonRows;

    /* ============================ 键盘快捷键 ============================ */

    // 双键序列超时（ms）
    const SEQ_TIMEOUT = 350;
    let seqBuffer = "";
    let seqTimer = null;

    function isTyping(target) {
        if (!target) return false;
        const tag = (target.tagName || "").toLowerCase();
        return (
            tag === "input" ||
            tag === "textarea" ||
            tag === "select" ||
            target.isContentEditable
        );
    }

    function closeAllModals() {
        document.querySelectorAll(".modal-overlay.active").forEach(function (m) {
            m.classList.remove("active");
            m.setAttribute("aria-hidden", "true");
        });
        const help = document.getElementById("shortcuts-help-modal");
        if (help) {
            help.classList.remove("active");
            help.setAttribute("aria-hidden", "true");
        }
    }

    function callIfExists(fn) {
        if (typeof window[fn] === "function") {
            window[fn]();
            return true;
        }
        return false;
    }

    function handleKey(e) {
        const target = e.target;

        // Esc 任何时候都生效：关闭模态 / 帮助面板
        if (e.key === "Escape") {
            const help = document.getElementById("shortcuts-help-modal");
            if (help && help.classList.contains("active")) {
                closeAllModals();
                e.preventDefault();
                return;
            }
            if (document.querySelector(".modal-overlay.active")) {
                closeAllModals();
                e.preventDefault();
            }
            return;
        }

        // 输入框中：仅 ? 在 textarea 可触发帮助需配合 Shift，这里放行所有
        if (isTyping(target)) return;

        // Ctrl/Cmd/Meta 组合键交给浏览器
        if (e.ctrlKey || e.metaKey || e.altKey) return;

        const key = e.key;

        // 双键序列处理（g h / g p / g r）
        if (seqBuffer === "g") {
            clearTimeout(seqTimer);
            seqBuffer = "";
            if (key === "h") {
                callIfExists("showModuleHome");
                e.preventDefault();
                return;
            }
            if (key === "p") {
                callIfExists("showApiQcSection") &&
                    window.showApiQcSection("projects");
                e.preventDefault();
                return;
            }
            if (key === "r") {
                callIfExists("showApiQcSection") &&
                    window.showApiQcSection("runs");
                e.preventDefault();
                return;
            }
            // g 后接其它键，回退到单键处理
        }

        if (key === "g") {
            seqBuffer = "g";
            seqTimer = setTimeout(function () {
                seqBuffer = "";
            }, SEQ_TIMEOUT);
            return;
        }

        // 单键快捷键
        if (key === "?") {
            toggleHelpPanel();
            e.preventDefault();
            return;
        }
        if (key === "n") {
            if (callIfExists("showCurlWizardModal")) e.preventDefault();
            return;
        }
        if (key === "t") {
            if (typeof window.toggleTheme === "function") {
                window.toggleTheme();
                e.preventDefault();
            }
            return;
        }
        if (key === "/") {
            // 聚焦当前可见搜索框
            const search = document.querySelector(
                ".content input[type='search'], .content input[id*='search'], .content input[placeholder*='搜索'], .content input[placeholder*='search']"
            );
            if (search) {
                search.focus();
                e.preventDefault();
            }
            return;
        }
    }

    function toggleHelpPanel() {
        let help = document.getElementById("shortcuts-help-modal");
        if (!help) {
            help = document.createElement("div");
            help.id = "shortcuts-help-modal";
            help.className = "modal-overlay";
            help.innerHTML =
                '<div class="modal modal--sm" onclick="event.stopPropagation()">' +
                '<div class="modal-header"><h2>键盘快捷键</h2>' +
                '<button type="button" class="modal-close" onclick="document.getElementById(\'shortcuts-help-modal\').classList.remove(\'active\')">&times;</button></div>' +
                '<div class="modal-body"><table class="kbd-table">' +
                "<tbody>" +
                kbdRow("? ", "打开此帮助面板") +
                kbdRow("g h", "回到工作台首页") +
                kbdRow("g p", "跳转测试项目") +
                kbdRow("g r", "跳转测试运行") +
                kbdRow("n", "从 cURL 快速创建项目") +
                kbdRow("t", "切换亮 / 暗主题") +
                kbdRow("/", "聚焦搜索框") +
                kbdRow("Esc", "关闭弹窗 / 帮助面板") +
                "</tbody></table></div></div>";
            help.addEventListener("click", function () {
                help.classList.remove("active");
                help.setAttribute("aria-hidden", "true");
            });
            document.body.appendChild(help);
        }
        const open = !help.classList.contains("active");
        help.classList.toggle("active", open);
        help.setAttribute("aria-hidden", open ? "false" : "true");
    }

    function kbdRow(keys, desc) {
        const keySpans = keys
            .split(" ")
            .map(function (k) {
                return "<kbd>" + esc(k) + "</kbd>";
            })
            .join('<span class="kbd-plus">+</span>');
        return (
            "<tr><td class='kbd-keys'>" +
            keySpans +
            "</td><td>" +
            esc(desc) +
            "</td></tr>"
        );
    }

    document.addEventListener("keydown", handleKey);

    window.toggleShortcutsHelp = toggleHelpPanel;
})();
