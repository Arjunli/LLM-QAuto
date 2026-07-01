/**
 * 通用 Skill 工作台 UI（接口契约 / 性能测试 / Mock 造数）
 */
(function () {
    const WORKBENCH = {
        api_contract: {
            kind: "contract",
            pageTitle: "接口契约",
            pageLead: "粘贴 OpenAPI / Swagger 或接口 paths，生成契约矩阵与 pytest 骨架。",
            placeholder:
                "示例：\nopenapi: 3.0.0\npaths:\n  /api/users:\n    get:\n      responses:\n        '200': ...\n\n或粘贴接口列表 + 鉴权说明",
            generateLabel: "生成契约",
            sections: [
                { key: "assumptions", title: "说明", type: "md" },
                { key: "contract_matrix_markdown", title: "契约矩阵", type: "table" },
                { key: "pytest_skeleton", title: "pytest 骨架", type: "code" },
            ],
        },
        perf_test: {
            kind: "perf",
            pageTitle: "性能测试",
            pageLead: "描述压测场景、并发与 SLA，生成 k6 脚本与运行命令。",
            placeholder:
                "示例：\n登录后循环调用 GET /api/orders 与 POST /api/orders/export\n目标：50 VU，5 分钟，p95 < 800ms，错误率 < 1%",
            generateLabel: "生成 k6 脚本",
            sections: [
                { key: "scenario_summary", title: "场景说明", type: "md" },
                { key: "thresholds_note", title: "阈值说明", type: "md" },
                { key: "run_command", title: "运行命令", type: "code" },
                { key: "k6_script", title: "k6 脚本", type: "code" },
            ],
        },
        mock_data: {
            kind: "mock",
            pageTitle: "Mock 造数",
            pageLead: "从接口说明生成 Mock 清单、样例 JSON 与 FastAPI Mock 服务代码。",
            placeholder:
                "示例：\nPOST /api/design/submit 提交设计任务\nGET /api/design/{id} 查询详情\n需要：成功、参数校验失败 422、无权限 403",
            generateLabel: "生成 Mock",
            sections: [
                { key: "assumptions", title: "Mock 策略", type: "md" },
                { key: "mock_spec_markdown", title: "Mock 清单", type: "table" },
                { key: "sample_responses_json", title: "样例 JSON", type: "code" },
                { key: "mock_server_code", title: "Mock 服务代码", type: "code" },
            ],
        },
    };

    let currentModuleId = null;
    let draft = null;
    let sending = false;

    function cfg() {
        return WORKBENCH[currentModuleId];
    }

    function apiBase() {
        return `/api/workbench/${cfg().kind}`;
    }

    function toast(msg, err) {
        if (window.PlatformChat) PlatformChat.showToast(msg, err);
    }

    function markdownTableToHtml(md) {
        const lines = (md || "").split("\n").filter((l) => l.trim().startsWith("|"));
        if (lines.length < 2) return `<pre class="cfg-wizard-summary">${escapeHtml(md || "")}</pre>`;
        let html = "<table class='case-table'><thead><tr>";
        lines[0]
            .split("|")
            .filter(Boolean)
            .forEach((c) => (html += `<th>${escapeHtml(c.trim())}</th>`));
        html += "</tr></thead><tbody>";
        for (let i = 2; i < lines.length; i++) {
            const cells = lines[i].split("|").filter(Boolean).map((c) => c.trim());
            html += "<tr>" + cells.map((c) => `<td>${escapeHtml(c)}</td>`).join("") + "</tr>";
        }
        html += "</tbody></table>";
        return html;
    }

    function renderSection(sec, outputs) {
        const val = outputs[sec.key] || "";
        if (!val) return "";
        if (sec.type === "table") {
            return `<div class="case-preview-section"><h4 class="case-preview-section-title">${escapeHtml(sec.title)}</h4><div class="case-table-scroll">${markdownTableToHtml(val)}</div></div>`;
        }
        if (sec.type === "code") {
            return `<div class="case-preview-section"><h4 class="case-preview-section-title">${escapeHtml(sec.title)}</h4><pre class="cfg-wizard-summary wb-code-preview">${escapeHtml(val)}</pre></div>`;
        }
        return `<div class="case-preview-section"><h4 class="case-preview-section-title">${escapeHtml(sec.title)}</h4><div class="case-preview-block">${PlatformChat ? PlatformChat.renderMarkdownLite(val) : escapeHtml(val)}</div></div>`;
    }

    function renderPreview(data) {
        const outputs = data.outputs || {};
        Object.keys(data).forEach((k) => {
            if (!["id", "title", "input_text", "message", "outputs", "updated_at", "created_at", "module"].includes(k)) {
                outputs[k] = outputs[k] || data[k];
            }
        });
        draft = { ...data, outputs };
        const empty = document.getElementById("wb-preview-empty");
        const content = document.getElementById("wb-preview-content");
        const status = document.getElementById("wb-preview-status");
        const saveBtn = document.getElementById("wb-save-btn");
        const has = cfg().sections.some((s) => outputs[s.key]);
        if (empty) empty.style.display = has ? "none" : "flex";
        if (content) content.style.display = has ? "block" : "none";
        if (status) status.textContent = has ? "已生成，可保存" : "尚未生成";
        if (saveBtn) saveBtn.disabled = !has;
        if (!content) return;
        const parts = cfg()
            .sections.map((s) => renderSection(s, outputs))
            .filter(Boolean)
            .join("");
        content.innerHTML = parts || `<p class="hint">${escapeHtml(data.message || "")}</p>`;
    }

    function loadWorkspace() {
        const c = cfg();
        const content = document.getElementById("main-content");
        const head =
            typeof renderModulePageHead === "function"
                ? renderModulePageHead(c.pageTitle, c.pageLead, "")
                : `<div class="section-title">${escapeHtml(c.pageTitle)}</div>`;
        content.innerHTML = `
<div class="module-page">
${head}
<div class="module-page-body case-design-layout">
  <section class="case-design-panel case-design-input">
    <div class="case-design-panel-head"><div class="case-design-panel-title">输入</div></div>
    <textarea id="wb-input-text" class="case-input-area" spellcheck="false" placeholder="${escapeHtml(c.placeholder)}"></textarea>
    <div class="case-input-meta"><span id="wb-input-count">粘贴内容后开始生成</span></div>
    <div class="case-design-actions">
      <button type="button" class="btn btn-primary btn-sm" id="wb-generate-btn" onclick="workbenchGenerate()">${escapeHtml(c.generateLabel)}</button>
      <button type="button" class="btn btn-secondary btn-sm" onclick="workbenchSave()" disabled id="wb-save-btn">保存到服务端</button>
    </div>
  </section>
  <section class="case-design-panel case-design-preview">
    <div class="case-design-panel-head">
      <div><div class="case-design-panel-title">生成结果</div><p class="hint case-design-panel-desc" id="wb-preview-status">尚未生成</p></div>
    </div>
    <div id="wb-preview-empty" class="case-preview-empty">
      <div class="case-preview-empty-icon" aria-hidden="true">⚡</div>
      <p class="case-preview-empty-title">左侧输入后点击「${escapeHtml(c.generateLabel)}」</p>
    </div>
    <div id="wb-preview-content" class="case-preview-content" style="display:none"></div>
  </section>
</div>
</div>`;
        const ta = document.getElementById("wb-input-text");
        const counter = document.getElementById("wb-input-count");
        if (ta && counter) {
            const sync = () => {
                counter.textContent = ta.value.trim() ? `${ta.value.length} 字` : "粘贴内容后开始生成";
            };
            ta.addEventListener("input", sync);
            sync();
        }
        if (draft?.input_text && ta) {
            ta.value = draft.input_text;
            renderPreview(draft);
        }
    }

    async function loadSessionsList() {
        const c = cfg();
        const content = document.getElementById("main-content");
        const head =
            typeof renderModulePageHead === "function"
                ? renderModulePageHead("已保存", `${c.pageTitle} 历史会话`, "")
                : '<div class="section-title">已保存</div>';
        content.innerHTML = `<div class="module-page">${head}<div class="module-page-body" id="wb-sessions-list">加载中…</div></div>`;
        try {
            const { data } = await apiFetch(`${apiBase()}/sessions`);
            const list = document.getElementById("wb-sessions-list");
            const sessions = data.sessions || [];
            if (!sessions.length) {
                list.innerHTML =
                    typeof emptyStateHtml === "function"
                        ? emptyStateHtml("暂无保存记录", "在工作台生成后点击保存")
                        : "<p>暂无记录</p>";
                return;
            }
            list.innerHTML = `<div class="project-list">${sessions
                .map(
                    (s) => `<div class="project-card"><div class="project-card-inner">
<div class="project-card-body" onclick="workbenchOpenSession('${s.id}')">
<div class="name">${escapeHtml(s.title)}</div>
<div class="desc">${escapeHtml(s.preview || "")}</div>
<div class="meta"><span class="meta-item">${escapeHtml(s.updated_at || "")}</span></div>
</div>
<button type="button" class="btn btn-ghost btn-delete-project" onclick="event.stopPropagation();workbenchDeleteSession('${s.id}')">删除</button>
</div></div>`
                )
                .join("")}</div>`;
        } catch (e) {
            content.innerHTML = `<div class="error">${escapeHtml(e.message)}</div>`;
        }
    }

    window.loadSkillWorkbench = function (moduleId, section) {
        if (!WORKBENCH[moduleId]) return;
        currentModuleId = moduleId;
        if (section === "sessions") loadSessionsList();
        else loadWorkspace();
    };

    window.workbenchGenerate = async function () {
        if (sending) return;
        const text = document.getElementById("wb-input-text")?.value?.trim();
        if (!text) return;
        sending = true;
        const btn = document.getElementById("wb-generate-btn");
        const prev = btn ? btn.textContent : "";
        if (btn) {
            btn.disabled = true;
            btn.textContent = "生成中…";
        }
        try {
            const { data } = await apiFetch(`${apiBase()}/generate`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ input_text: text, title: text.split("\n")[0].slice(0, 40) }),
            });
            draft = { ...data, input_text: text };
            renderPreview(draft);
            toast("已生成");
        } catch (e) {
            toast(e.message, true);
        } finally {
            sending = false;
            if (btn) {
                btn.disabled = false;
                btn.textContent = prev;
            }
        }
    };

    window.workbenchSave = async function () {
        if (!draft) return;
        const outputs = draft.outputs || {};
        cfg().sections.forEach((s) => {
            if (draft[s.key]) outputs[s.key] = draft[s.key];
        });
        try {
            const { data } = await apiFetch(`${apiBase()}/sessions`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    title: draft.title,
                    input_text: draft.input_text || "",
                    message: draft.message || "",
                    outputs,
                }),
            });
            draft = data.session;
            toast("已保存");
        } catch (e) {
            toast(e.message, true);
        }
    };

    window.workbenchOpenSession = async function (id) {
        const { data } = await apiFetch(`${apiBase()}/sessions/${id}`);
        draft = { ...data, ...(data.outputs || {}) };
        showModuleSection(currentModuleId, "workspace");
        loadWorkspace();
    };

    window.workbenchDeleteSession = async function (id) {
        if (!confirm("删除此记录？")) return;
        await apiFetch(`${apiBase()}/sessions/${id}`, { method: "DELETE" });
        toast("已删除");
        loadSessionsList();
    };
})();
