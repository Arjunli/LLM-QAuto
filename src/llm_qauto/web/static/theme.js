/**
 * 主题切换（亮 / 暗色模式）
 * - 读取 localStorage 或 prefers-color-scheme 初始化
 * - header 主题按钮点击切换
 * - 刷新后保持选择
 */
(function () {
    const THEME_KEY = "qauto-theme";

    function isDark() {
        return document.body.classList.contains("theme-dark");
    }

    function applyTheme(theme) {
        const dark = theme === "dark";
        document.body.classList.toggle("theme-dark", dark);
        try {
            localStorage.setItem(THEME_KEY, dark ? "dark" : "light");
        } catch (e) {
            /* localStorage 不可用时静默忽略 */
        }
        updateToggleBtn(dark);
    }

    function updateToggleBtn(dark) {
        const btn = document.getElementById("theme-toggle");
        if (!btn) return;
        btn.setAttribute("aria-label", dark ? "切换到亮色模式" : "切换到暗色模式");
        btn.title = dark ? "切换到亮色模式" : "切换到暗色模式";
        const sun = btn.querySelector(".icon-sun");
        const moon = btn.querySelector(".icon-moon");
        if (sun) sun.style.display = dark ? "" : "none";
        if (moon) moon.style.display = dark ? "none" : "";
    }

    function currentTheme() {
        return localStorage.getItem(THEME_KEY);
    }

    function init() {
        const saved = currentTheme();
        let theme;
        if (saved === "dark" || saved === "light") {
            theme = saved;
        } else {
            const prefersDark =
                window.matchMedia &&
                window.matchMedia("(prefers-color-scheme: dark)").matches;
            theme = prefersDark ? "dark" : "light";
        }
        applyTheme(theme);

        const btn = document.getElementById("theme-toggle");
        if (btn) {
            btn.addEventListener("click", function () {
                applyTheme(isDark() ? "light" : "dark");
            });
        }

        // 跟随系统变化（仅当用户未显式选择时）
        if (window.matchMedia) {
            try {
                window
                    .matchMedia("(prefers-color-scheme: dark)")
                    .addEventListener("change", function (e) {
                        if (!currentTheme()) {
                            applyTheme(e.matches ? "dark" : "light");
                        }
                    });
            } catch (err) {
                /* 旧浏览器 addEventListener 不可用 */
            }
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    // 暴露给快捷键调用
    window.toggleTheme = function () {
        applyTheme(isDark() ? "light" : "dark");
    };
})();
