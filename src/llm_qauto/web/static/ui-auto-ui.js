/**

 * UI 自动化模块（Playwright）

 */

(function () {

    let currentSpecName = null;



    function toast(msg, err) {

        if (window.PlatformChat) PlatformChat.showToast(msg, err);

    }



    function stripAnsi(text) {

        return String(text || "")

            .replace(/\u001b\[[0-9;]*m/g, "")

            .replace(/\x1b\[[0-9;]*m/g, "");

    }



    function formatUiRunTime(runId) {

        const m = String(runId || "").match(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})_/);

        if (!m) return runId || "";

        return `${m[1]}-${m[2]}-${m[3]} ${m[4]}:${m[5]}:${m[6]}`;

    }



    function parseUiRunSummary(run) {

        const raw = stripAnsi(run.log || "");

        const lines = raw.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);

        let testTitle = "";

        for (const line of lines) {

            const m = line.match(/›\s*(.+?)\s*›\s*(.+?)(?:\s*\(|$)/);

            if (m) {

                testTitle = `${m[1]} › ${m[2]}`;

                break;

            }

        }

        let errorLine = "";

        for (const line of lines) {

            if (/Test timeout|timeout of \d+ms exceeded/i.test(line)) {

                errorLine = line;

                break;

            }

            if (/^Error:/i.test(line)) {

                errorLine = line.replace(/^Error:\s*/i, "");

                break;

            }

        }

        if (!errorLine) {

            const failedLine = lines.find((l) => /\bfailed\b/i.test(l) && !/attachment/i.test(l));

            errorLine = failedLine || "测试未通过，请展开日志查看详情";

        }

        const passed = raw.match(/(\d+)\s+passed/i);

        const failed = raw.match(/(\d+)\s+failed/i);

        const cleanLog = raw

            .replace(/[─━─\-]{8,}/g, "────────")

            .replace(/\n{3,}/g, "\n\n")

            .trim();

        return {

            testTitle,

            errorLine,

            passed: passed ? passed[1] : null,

            failed: failed ? failed[1] : null,

            cleanLog,

        };

    }



    function renderUiRunCard(run) {

        const ok = run.exit_code === 0;

        const ridEsc = String(run.run_id || "").replace(/'/g, "\\'");

        const summary = parseUiRunSummary(run);

        const title = summary.testTitle || (ok ? "Playwright 测试" : "Playwright 测试失败");

        const timeLabel = formatUiRunTime(run.run_id);

        const modeLabel = run.display_mode === "visible" ? "显示浏览器" : "后台运行";

        const stats = [];

        if (summary.passed) stats.push(`通过 ${summary.passed}`);

        if (summary.failed) stats.push(`失败 ${summary.failed}`);

        const statsHtml = stats.length

            ? `<div class="ui-run-card-stats">${stats.map((s) => `<span>${escapeHtml(s)}</span>`).join("")}</div>`

            : "";

        const reportBtn = run.report_available

            ? `<button type="button" class="btn btn-secondary btn-sm" onclick="openUiReport()">查看报告</button>`

            : "";

        const fixBtn = !ok

            ? `<button type="button" class="btn btn-primary btn-sm" onclick="sendUiRunToAssistant('${ridEsc}')">脚本助手修复</button>`

            : "";

        const logPreview = summary.cleanLog.length > 4000 ? `${summary.cleanLog.slice(-4000)}\n…（已截断）` : summary.cleanLog;

        return `<article class="ui-run-card ui-run-card--${ok ? "ok" : "fail"}">

<header class="ui-run-card-header">

<div class="ui-run-card-status" aria-hidden="true"></div>

<div class="ui-run-card-meta">

<div class="ui-run-card-title">${escapeHtml(title)}</div>

<div class="ui-run-card-sub">

<span>${escapeHtml(timeLabel)}</span>

<span class="ui-run-card-mode">${escapeHtml(modeLabel)}</span>

<code class="ui-run-card-id">${escapeHtml(run.run_id || "")}</code>

</div>

${statsHtml}

</div>

<span class="badge ${ok ? "badge--ok" : "badge--fail"}">${ok ? "通过" : "失败"}</span>

<div class="ui-run-card-actions">

${fixBtn}

${reportBtn}

<button type="button" class="btn btn-danger btn-sm" onclick="deleteUiRun('${ridEsc}')">删除</button>

</div>

</header>

<p class="ui-run-card-error">${escapeHtml(summary.errorLine)}</p>

<details class="ui-run-log-details">

<summary>查看完整日志</summary>

<pre class="ui-run-log-pre">${escapeHtml(logPreview)}</pre>

</details>

</article>`;

    }



    const UI_RUN_MODE_KEY = "uiAutoRunDisplayMode";



    function getUiRunDisplayMode() {

        return localStorage.getItem(UI_RUN_MODE_KEY) === "visible" ? "visible" : "background";

    }



    function uiRunModeToolbarHtml() {

        const bgChecked = getUiRunDisplayMode() === "background" ? " checked" : "";

        const visChecked = getUiRunDisplayMode() === "visible" ? " checked" : "";

        return `<div class="ui-run-toolbar">

<span class="ui-run-toolbar-label">运行方式</span>

<div class="ui-run-mode-toggle" role="radiogroup" aria-label="本机运行方式">

<label class="ui-run-mode-opt${bgChecked ? " is-active" : ""}">

<input type="radio" name="ui-run-mode" value="background"${bgChecked}> 后台运行

</label>

<label class="ui-run-mode-opt${visChecked ? " is-active" : ""}">

<input type="radio" name="ui-run-mode" value="visible"${visChecked}> 显示浏览器

</label>

</div>

<span class="hint ui-run-mode-hint">显示浏览器会弹出窗口，便于观察执行步骤；后台运行不打扰当前工作</span>

</div>`;

    }



    function bindUiRunModeControls(root) {

        if (!root) return;

        root.querySelectorAll('input[name="ui-run-mode"]').forEach((el) => {

            el.addEventListener("change", () => {

                if (!el.checked) return;

                localStorage.setItem(UI_RUN_MODE_KEY, el.value);

                root.querySelectorAll(".ui-run-mode-opt").forEach((lab) => {

                    lab.classList.toggle("is-active", lab.contains(el));

                });

            });

        });

    }



    function syncUiSpecLineNumbers() {

        const ta = document.getElementById("ui-spec-content");

        const gutter = document.getElementById("ui-spec-lines");

        if (!ta || !gutter) return;

        const lineCount = Math.max(1, (ta.value || "").split("\n").length);

        gutter.textContent = Array.from({ length: lineCount }, (_, i) => i + 1).join("\n");

    }



    function bindUiSpecEditor() {

        const ta = document.getElementById("ui-spec-content");

        if (!ta || ta.dataset.bound === "1") return;

        ta.dataset.bound = "1";

        ta.addEventListener("input", syncUiSpecLineNumbers);

        ta.addEventListener("scroll", () => {

            const gutter = document.getElementById("ui-spec-lines");

            if (gutter) gutter.scrollTop = ta.scrollTop;

        });

        ta.addEventListener("keydown", (e) => {

            if (e.key === "Tab") {

                e.preventDefault();

                const start = ta.selectionStart;

                const end = ta.selectionEnd;

                ta.value = `${ta.value.slice(0, start)}  ${ta.value.slice(end)}`;

                ta.selectionStart = ta.selectionEnd = start + 2;

                syncUiSpecLineNumbers();

            }

        });

        syncUiSpecLineNumbers();

    }



    function setUiSpecEditorContent(content) {

        const ta = document.getElementById("ui-spec-content");

        if (!ta) return;

        ta.value = content || "";

        syncUiSpecLineNumbers();

    }



    function loadUiAuto(section) {

        if (section === "assistant") {

            if (typeof loadUiAssistant === "function") loadUiAssistant();

            return;

        }

        if (section === "runs") return loadUiRuns();

        if (section === "ci") return loadUiCi();

        return loadUiSpecs();

    }



    async function loadUiSpecs() {

        const content = document.getElementById("main-content");

        const head = typeof renderModulePageHead === "function"

            ? renderModulePageHead(

                  "脚本管理",

                  "编辑、保存与本机运行 Playwright 脚本；AI 生成请用侧边栏「脚本助手」。",

                  `<button type="button" class="btn btn-primary btn-sm" onclick="showModuleSection('ui_automation','assistant')">脚本助手</button>

<button type="button" class="btn btn-secondary btn-sm" onclick="runUiAuto()">本机运行全部</button>

<button type="button" class="btn btn-secondary btn-sm" onclick="openUiReport()">查看最新报告</button>`

              )

            : '<div class="section-title">Playwright 脚本</div>';

        content.innerHTML = `

<div class="module-page">

${head}

${uiRunModeToolbarHtml()}

<div class="module-page-body ui-auto-split">

  <div class="ui-auto-list" id="ui-spec-list">加载中…</div>

  <div class="ui-auto-editor">

    <div class="ui-auto-editor-head">

      <span class="hint">脚本内容 (.spec.ts)</span>

      <input type="text" id="ui-spec-name" class="ui-spec-name-input" placeholder="example.spec.ts" spellcheck="false" />

    </div>

    <div class="code-editor-wrap">

      <div id="ui-spec-lines" class="code-editor-gutter" aria-hidden="true">1</div>

      <textarea id="ui-spec-content" class="code-editor" spellcheck="false" autocapitalize="off" autocomplete="off" placeholder="// Playwright TypeScript 脚本…"></textarea>

    </div>

    <div class="ui-auto-editor-actions">

      <button type="button" class="btn btn-primary btn-sm" onclick="saveUiSpec()">保存</button>

      <button type="button" class="btn btn-secondary btn-sm" onclick="runUiAutoSelected()">运行此脚本</button>

      <button type="button" class="btn btn-ghost btn-sm" onclick="deleteUiSpec()">删除</button>

    </div>

  </div>

</div>

</div>`;

        bindUiSpecEditor();

        bindUiRunModeControls(content);

        refreshSpecList();

    }



    async function refreshSpecList() {

        const list = document.getElementById("ui-spec-list");

        if (!list) return;

        try {

            const { data } = await apiFetch("/api/ui-auto/specs");

            const specs = data.specs || [];

            if (!specs.length) {

                list.innerHTML = emptyStateHtml("暂无脚本", "使用「脚本助手」生成，或在右侧手动新建");

                return;

            }

            list.innerHTML = specs

                .map(

                    (s) =>

                        `<button type="button" class="ui-spec-item${currentSpecName === s.name ? " active" : ""}" data-name="${escapeHtml(s.name)}" onclick="loadUiSpecByEl(this)">${escapeHtml(s.name)}</button>`

                )

                .join("");

        } catch (e) {

            list.innerHTML = `<div class="error">${escapeHtml(e.message)}</div>`;

        }

    }



    window.showUiGeneratePanel = function () {

        showModuleSection("ui_automation", "assistant");

    };



    window.loadUiSpecByEl = function (el) {

        loadUiSpec(el.dataset.name);

    };



    window.runUiAutoSelected = function () {

        const name = document.getElementById("ui-spec-name")?.value?.trim();

        runUiAuto(name || null);

    };



    window.loadUiSpec = async function (name) {

        currentSpecName = name;

        const { data } = await apiFetch(`/api/ui-auto/specs/${encodeURIComponent(name)}`);

        document.getElementById("ui-spec-name").value = data.name;

        setUiSpecEditorContent(data.content);

        refreshSpecList();

    };



    window.saveUiSpec = async function () {

        const name = document.getElementById("ui-spec-name")?.value?.trim();

        const content = document.getElementById("ui-spec-content")?.value || "";

        if (!name) return toast("请填写脚本文件名", true);

        await apiFetch("/api/ui-auto/specs", {

            method: "POST",

            headers: { "Content-Type": "application/json" },

            body: JSON.stringify({ name, content }),

        });

        currentSpecName = name;

        toast("已保存");

        refreshSpecList();

    };



    window.deleteUiSpec = async function () {

        if (!currentSpecName || !confirm("删除此脚本？")) return;

        await apiFetch(`/api/ui-auto/specs/${encodeURIComponent(currentSpecName)}`, { method: "DELETE" });

        currentSpecName = null;

        setUiSpecEditorContent("");

        document.getElementById("ui-spec-name").value = "";

        toast("已删除");

        refreshSpecList();

    };



    window.generateUiSpec = async function () {

        const description = document.getElementById("ui-gen-desc")?.value?.trim();

        const url = document.getElementById("ui-gen-url")?.value?.trim();

        if (!description) return toast("请描述测试流程", true);

        try {

            const { data } = await apiFetch("/api/ui-auto/generate", {

                method: "POST",

                headers: { "Content-Type": "application/json" },

                body: JSON.stringify({ description, url }),

            });

            document.getElementById("ui-spec-name").value = data.spec_name;

            setUiSpecEditorContent(data.spec_content);

            currentSpecName = data.spec_name;

            toast(data.message || "已生成");

            showUiGeneratePanel();

            refreshSpecList();

        } catch (e) {

            toast(e.message, true);

        }

    };



    window.runUiAuto = async function (specName) {

        try {

            const mode = getUiRunDisplayMode();

            const modeLabel = mode === "visible" ? "显示浏览器" : "后台";

            toast(`正在以「${modeLabel}」方式运行 Playwright…`);

            const { data } = await apiFetch("/api/ui-auto/run", {

                method: "POST",

                headers: { "Content-Type": "application/json" },

                body: JSON.stringify({ spec_name: specName || null, display_mode: mode }),

            });

            toast(data.exit_code === 0 ? "运行完成" : "运行结束（有失败）", data.exit_code !== 0);

            if (typeof showModuleSection === "function") {

                showModuleSection("ui_automation", "runs");

            }

        } catch (e) {

            toast(e.message, true);

        }

    };



    window.openUiReport = function () {

        window.open("/api/ui-auto/report/latest", "_blank");

    };



    const UI_FIX_PENDING_KEY = "llm-qauto-ui-fix-pending";



    function inferSpecNameFromLog(log) {

        const m = String(log || "").match(/specs[\\/][\w.-]+\.spec\.ts/i);

        return m ? m[0].replace(/^specs[\\/]/, "") : null;

    }



    async function loadUiRunDetail(runId) {

        try {

            const { data } = await apiFetch(`/api/ui-auto/runs/${encodeURIComponent(runId)}`);

            return data;

        } catch (e) {

            const { data } = await apiFetch("/api/ui-auto/runs");

            const run = (data.runs || []).find((r) => r.run_id === runId);

            if (!run) throw e;

            return {

                ...run,

                log_full: run.log_full || run.log || "",

                spec_name: run.spec_name || inferSpecNameFromLog(run.log),

                error_summary: run.error_summary || parseUiRunSummary(run).errorLine,

                has_screenshot: !!run.has_screenshot,

            };

        }

    }



    window.sendUiRunToAssistant = async function (runId) {

        try {

            toast("正在载入失败信息…");

            const run = await loadUiRunDetail(runId);

            let specContent = "";

            const specName = run.spec_name || inferSpecNameFromLog(run.log_full || run.log);

            if (specName) {

                try {

                    const { data: spec } = await apiFetch(

                        `/api/ui-auto/specs/${encodeURIComponent(specName)}`

                    );

                    specContent = spec.spec_content || "";

                } catch (e) {

                    /* 脚本可能已删除 */

                }

            }

            const summary = parseUiRunSummary(run);

            sessionStorage.setItem(

                UI_FIX_PENDING_KEY,

                JSON.stringify({

                    run_id: runId,

                    failure_log: run.log_full || run.log || "",

                    error_summary: run.error_summary || summary.errorLine,

                    spec_name: specName || null,

                    spec_content: specContent,

                    has_screenshot: !!run.has_screenshot,

                })

            );

            if (typeof showModuleSection === "function") {

                showModuleSection("ui_automation", "assistant");

            } else {

                toast("无法打开脚本助手", true);

            }

        } catch (e) {

            toast(e.message || "载入失败信息失败", true);

        }

    };



    async function loadUiRuns() {

        const content = document.getElementById("main-content");

        const head = typeof renderModulePageHead === "function"

            ? renderModulePageHead("运行记录", "本机 Playwright 执行历史与日志摘要。", "")

            : '<div class="section-title">UI 运行记录</div>';

        content.innerHTML = `<div class="module-page">${head}<div class="module-page-body" id="ui-runs-list">加载中…</div></div>`;

        try {

            const { data } = await apiFetch("/api/ui-auto/runs");

            const runs = data.runs || [];

            const list = document.getElementById("ui-runs-list");

            if (!runs.length) {

                list.innerHTML = emptyStateHtml("暂无运行记录", "在脚本管理页点击「本机运行」");

                return;

            }

            list.innerHTML = `<div class="ui-run-list">${runs.map((r) => renderUiRunCard(r)).join("")}</div>`;

        } catch (e) {

            content.innerHTML = `<div class="error">${escapeHtml(e.message)}</div>`;

        }

    }



    async function loadUiCi() {

        const content = document.getElementById("main-content");

        const head = typeof renderModulePageHead === "function"

            ? renderModulePageHead("GitHub Actions CI", "生成 Playwright CI 工作流模板到 .github/workflows/ui-automation.yml", "")

            : '<div class="section-title">GitHub Actions CI</div>';

        content.innerHTML = `

<div class="module-page">

${head}

<div class="module-page-body">

<p class="hint">生成后可在仓库根目录查看工作流文件</p>

<button type="button" class="btn btn-primary" onclick="generateUiCi()">生成 CI 工作流</button>

<pre id="ui-ci-output" class="cfg-wizard-summary" style="margin-top:16px;display:none"></pre>

</div>

</div>`;

    }



    window.deleteUiRun = async function (runId) {
        if (!confirm("确定删除该条 Playwright 运行记录？将删除 ui_tests/runs 下对应目录，且不可恢复。")) {
            return;
        }
        try {
            await apiFetch(`/api/ui-auto/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
            toast("已删除");
            loadUiRuns();
        } catch (e) {
            const detail = String(e.message || "");
            if (detail === "Not Found") {
                toast("删除接口未生效，请重启 web_server.py 后再试", true);
                return;
            }
            if (detail.includes("不存在")) {
                toast("记录已不存在，已刷新列表");
                loadUiRuns();
                return;
            }
            toast(detail, true);
        }
    };

    window.generateUiCi = async function () {

        try {

            const { data } = await apiFetch("/api/ui-auto/ci/generate-workflow", { method: "POST" });

            const pre = document.getElementById("ui-ci-output");

            if (pre) {

                pre.style.display = "block";

                pre.textContent = `已写入: ${data.path}\n\n${data.content}`;

            }

            toast("CI 模板已生成");

        } catch (e) {

            toast(e.message, true);

        }

    };



    window.loadUiAuto = loadUiAuto;

})();


