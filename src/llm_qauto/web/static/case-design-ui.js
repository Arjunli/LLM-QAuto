/**
 * 用例设计模块 Web UI
 */
(function () {
    let caseMessages = [];
    let caseDraft = null;
    let caseSending = false;
    const store = window.PlatformChat && PlatformChat.createSessionStore("llm-qauto-case-design-v1");

    function toast(msg, err) {
        if (window.PlatformChat) PlatformChat.showToast(msg, err);
    }

    function loadCaseDesign(section) {
        if (section === "assistant") {
            if (typeof loadCaseAssistant === "function") loadCaseAssistant();
            return;
        }
        if (section === "sessions") {
            loadCaseSessionsList();
            return;
        }
        loadCaseWorkspace();
    }

    async function loadCaseSessionsList() {
        const content = document.getElementById("main-content");
        const head = typeof renderModulePageHead === "function"
            ? renderModulePageHead("已保存用例", "查看、打开或删除服务端保存的用例会话。", "")
            : '<div class="section-title">已保存用例</div>';
        content.innerHTML = `<div class="module-page">${head}<div class="module-page-body" id="case-sessions-list">加载中…</div></div>`;
        try {
            const { data } = await apiFetch("/api/cases/sessions");
            const list = document.getElementById("case-sessions-list");
            const sessions = data.sessions || [];
            if (!sessions.length) {
                list.innerHTML = emptyStateHtml("暂无保存的用例会话", "在用例工作台生成后点击「保存到本地」");
                return;
            }
            list.innerHTML = `<div class="project-list">${sessions
                .map(
                    (s) => `<div class="project-card"><div class="project-card-inner">
<div class="project-card-body" onclick="openCaseSession('${s.id}')">
<div class="name">${escapeHtml(s.title)}</div>
<div class="desc">${escapeHtml(s.preview || "")}</div>
<div class="meta"><span class="meta-item">${escapeHtml(s.updated_at || "")}</span></div>
</div>
<button type="button" class="btn btn-ghost btn-delete-project" onclick="event.stopPropagation();deleteCaseSession('${s.id}')">删除</button>
</div></div>`
                )
                .join("")}</div>`;
        } catch (e) {
            content.innerHTML = `<div class="error">${escapeHtml(e.message)}</div>`;
        }
    }

    window.openCaseSession = async function (id) {
        const { data } = await apiFetch(`/api/cases/sessions/${id}`);
        caseDraft = data;
        showModuleSection("case_design", "workspace");
        renderCasePreview(data);
    };

    window.deleteCaseSession = async function (id) {
        if (!confirm("删除此用例会话？")) return;
        await apiFetch(`/api/cases/sessions/${id}`, { method: "DELETE" });
        toast("已删除");
        loadCaseSessionsList();
    };

    function bindCaseInputMeta() {
        const ta = document.getElementById("case-input-text");
        const counter = document.getElementById("case-input-count");
        if (!ta || !counter) return;
        const sync = () => {
            const n = (ta.value || "").length;
            counter.textContent = n ? `${n} 字` : "粘贴需求后开始生成";
        };
        ta.addEventListener("input", sync);
        sync();
    }

    function setCasePreviewEmpty(show) {
        const empty = document.getElementById("case-preview-empty");
        const content = document.getElementById("case-preview-content");
        const status = document.getElementById("case-preview-status");
        if (empty) empty.style.display = show ? "flex" : "none";
        if (content) content.style.display = show ? "none" : "block";
        if (status) status.textContent = show ? "尚未生成" : "已生成，可保存或导出";
    }

    function loadCaseWorkspace() {
        const content = document.getElementById("main-content");
        const head = typeof renderModulePageHead === "function"
            ? renderModulePageHead(
                  "快速生成",
                  "一次性粘贴 PRD / AC 直接生成，无需多轮对话。复杂需求请用侧边栏「用例助手」。",
                  `<button type="button" class="btn btn-secondary btn-sm" onclick="showModuleSection('case_design','assistant')">用例助手</button>`
              )
            : '<div class="section-title">用例设计</div>';
        content.innerHTML = `
<div class="module-page">
${head}
<div class="module-page-body case-design-layout">
  <section class="case-design-panel case-design-input">
    <div class="case-design-panel-head">
      <div>
        <div class="case-design-panel-title">需求输入</div>
        <p class="hint case-design-panel-desc">粘贴 PRD、用户故事或验收标准；生成结果含功能 + 弱网/稳定性/边界等非功能用例</p>
      </div>
    </div>
    <textarea id="case-input-text" class="case-input-area" spellcheck="false" placeholder="示例：&#10;作为管理员，我可以在用户列表页搜索、筛选并导出用户数据。&#10;&#10;验收标准：&#10;1. 搜索框支持按姓名/手机号模糊匹配&#10;2. 导出为 CSV，字段包含 id、姓名、手机号&#10;3. 无数据时展示空状态提示"></textarea>
    <div class="case-input-meta"><span id="case-input-count">粘贴需求后开始生成</span></div>
    <div class="case-design-actions">
      <button type="button" class="btn btn-primary btn-sm" id="case-generate-btn" onclick="generateCaseDesign()">生成用例</button>
      <button type="button" class="btn btn-secondary btn-sm" onclick="saveCaseDraft()" ${caseDraft ? "" : "disabled"} id="case-save-btn">保存到服务端</button>
      <a class="btn btn-ghost btn-sm" id="case-export-link" style="display:none" href="#" target="_blank">导出 CSV</a>
    </div>
  </section>
  <section class="case-design-panel case-design-preview" id="case-preview-panel">
    <div class="case-design-panel-head">
      <div>
        <div class="case-design-panel-title">生成结果</div>
        <p class="hint case-design-panel-desc" id="case-preview-status">尚未生成</p>
      </div>
    </div>
    <div id="case-preview-empty" class="case-preview-empty">
      <div class="case-preview-empty-icon" aria-hidden="true">📋</div>
      <p class="case-preview-empty-title">左侧粘贴需求后点击「生成用例」</p>
      <p class="case-preview-empty-desc">将在此展示：假设说明、评审逻辑图、测试覆盖树、可导出的用例表</p>
    </div>
    <div id="case-preview-content" class="case-preview-content" style="display:none">
      <div id="case-assumptions-wrap" class="case-preview-section" style="display:none">
        <h4 class="case-preview-section-title">假设与说明</h4>
        <div id="case-assumptions" class="case-preview-block"></div>
      </div>
      <div class="case-preview-section" id="case-review-wrap" style="display:none">
        <h4 class="case-preview-section-title">评审概览图 <span class="case-diagram-hint">快速过审 · 主流程 + 覆盖分组</span></h4>
        <div id="case-mermaid-review" class="case-mermaid-canvas"></div>
        <details class="case-mermaid-details">
          <summary class="case-diagram-src-toggle">查看 Mermaid 源码</summary>
          <pre id="case-mermaid-review-src" class="case-mermaid-src"></pre>
        </details>
      </div>
      <div class="case-preview-section" id="case-tree-wrap" style="display:none">
        <h4 class="case-preview-section-title">测试覆盖树 <span class="case-diagram-hint">TC 编号导航</span></h4>
        <div id="case-mermaid-tree" class="case-mermaid-canvas"></div>
        <details class="case-mermaid-details">
          <summary class="case-diagram-src-toggle">查看 Mermaid 源码</summary>
          <pre id="case-mermaid-tree-src" class="case-mermaid-src"></pre>
        </details>
      </div>
      <div class="case-preview-section" id="case-table-section" style="display:none">
        <h4 class="case-preview-section-title">用例表</h4>
        <div class="case-table-scroll" id="case-table-wrap"></div>
      </div>
    </div>
  </section>
</div>
</div>`;
        bindCaseInputMeta();
        if (caseDraft) {
            const ta = document.getElementById("case-input-text");
            if (ta && caseDraft.input_text) ta.value = caseDraft.input_text;
            bindCaseInputMeta();
            renderCasePreview(caseDraft);
        } else {
            setCasePreviewEmpty(true);
        }
    }

    async function renderCasePreview(data) {
        caseDraft = data;
        const assumptions = document.getElementById("case-assumptions");
        const assumptionsWrap = document.getElementById("case-assumptions-wrap");
        const reviewWrap = document.getElementById("case-review-wrap");
        const reviewCanvas = document.getElementById("case-mermaid-review");
        const reviewSrc = document.getElementById("case-mermaid-review-src");
        const treeWrap = document.getElementById("case-tree-wrap");
        const treeCanvas = document.getElementById("case-mermaid-tree");
        const treeSrc = document.getElementById("case-mermaid-tree-src");
        const tableWrap = document.getElementById("case-table-wrap");
        const tableSection = document.getElementById("case-table-section");
        const saveBtn = document.getElementById("case-save-btn");
        const exportLink = document.getElementById("case-export-link");
        const hasContent = !!(data.case_table_markdown || data.mermaid_tree || data.mermaid_review || data.assumptions || data.message);
        setCasePreviewEmpty(!hasContent);

        const assumptionText = data.assumptions || data.message || "";
        if (assumptionsWrap && assumptions) {
            const show = !!assumptionText.trim();
            assumptionsWrap.style.display = show ? "block" : "none";
            if (show) assumptions.innerHTML = PlatformChat.renderMarkdownLite(assumptionText);
        }

        const reviewDiagram = data.mermaid_review || "";
        const treeDiagram = data.mermaid_tree || "";
        if (reviewWrap) reviewWrap.style.display = reviewDiagram ? "block" : "none";
        if (treeWrap) treeWrap.style.display = treeDiagram ? "block" : "none";
        if (reviewSrc) reviewSrc.textContent = reviewDiagram;
        if (treeSrc) treeSrc.textContent = treeDiagram;

        if (window.CaseMermaid) {
            await CaseMermaid.renderCaseDiagrams(reviewCanvas, treeCanvas, reviewDiagram, treeDiagram, {
                title: data.title || (data.input_text || "").split("\n")[0].slice(0, 40),
                caseTable: data.case_table_markdown,
            });
        } else {
            if (reviewCanvas && reviewDiagram) reviewCanvas.innerHTML = `<pre class="case-mermaid-src">${escapeHtml(reviewDiagram)}</pre>`;
            if (treeCanvas && treeDiagram) treeCanvas.innerHTML = `<pre class="case-mermaid-src">${escapeHtml(treeDiagram)}</pre>`;
        }

        if (tableSection && tableWrap) {
            const show = !!data.case_table_markdown;
            tableSection.style.display = show ? "block" : "none";
            if (show) tableWrap.innerHTML = markdownTableToHtml(data.case_table_markdown || "");
        }
        if (saveBtn) saveBtn.disabled = !data.case_table_markdown;
        if (exportLink && data.id) {
            exportLink.style.display = "inline-flex";
            exportLink.href = `/api/cases/sessions/${data.id}/export.csv`;
        } else if (exportLink) {
            exportLink.style.display = "none";
        }
    }

    function markdownTableToHtml(md) {
        const lines = (md || "").split("\n").filter((l) => l.trim().startsWith("|"));
        if (lines.length < 2) return `<pre class="cfg-wizard-summary">${escapeHtml(md || "")}</pre>`;
        let html = "<table class='case-table'><thead><tr>";
        const headerCells = lines[0].split("|").filter(Boolean).map((c) => c.trim());
        headerCells.forEach((c) => (html += `<th>${escapeHtml(c)}</th>`));
        html += "</tr></thead><tbody>";
        for (let i = 2; i < lines.length; i++) {
            const cells = lines[i].split("|").filter(Boolean).map((c) => c.trim());
            html += "<tr>" + cells.map((c) => `<td>${escapeHtml(c)}</td>`).join("") + "</tr>";
        }
        html += "</tbody></table>";
        return html;
    }

    window.generateCaseDesign = async function () {
        const text = document.getElementById("case-input-text")?.value?.trim();
        if (!text || caseSending) return;
        caseSending = true;
        const btn = document.getElementById("case-generate-btn");
        const prevLabel = btn ? btn.textContent : "";
        if (btn) {
            btn.disabled = true;
            btn.textContent = "生成中…";
        }
        setCasePreviewEmpty(false);
        const content = document.getElementById("case-preview-content");
        const tableWrap = document.getElementById("case-table-wrap");
        if (content) content.style.display = "block";
        if (tableWrap) {
            tableWrap.innerHTML = `<div class="case-preview-loading">正在生成测试树与用例表…</div>`;
        }
        document.getElementById("case-table-section")?.style.setProperty("display", "block");
        document.getElementById("case-assumptions-wrap")?.style.setProperty("display", "none");
        document.getElementById("case-review-wrap")?.style.setProperty("display", "none");
        document.getElementById("case-tree-wrap")?.style.setProperty("display", "none");
        const status = document.getElementById("case-preview-status");
        if (status) status.textContent = "生成中…";
        try {
            const { data } = await apiFetch("/api/cases/generate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ input_text: text, title: text.split("\n")[0].slice(0, 40) }),
            });
            caseDraft = { ...data, input_text: text };
            renderCasePreview(caseDraft);
            toast("用例已生成");
        } catch (e) {
            setCasePreviewEmpty(true);
            toast(e.message, true);
        } finally {
            caseSending = false;
            if (btn) {
                btn.disabled = false;
                btn.textContent = prevLabel || "生成用例";
            }
        }
    };

    window.saveCaseDraft = async function () {
        if (!caseDraft) return;
        try {
            const { data } = await apiFetch("/api/cases/sessions", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    title: caseDraft.title,
                    input_text: caseDraft.input_text || "",
                    assumptions: caseDraft.assumptions,
                    mermaid_review: caseDraft.mermaid_review,
                    mermaid_tree: caseDraft.mermaid_tree,
                    case_table_markdown: caseDraft.case_table_markdown,
                    message: caseDraft.message,
                }),
            });
            caseDraft = data.session;
            renderCasePreview(caseDraft);
            toast("已保存");
        } catch (e) {
            toast(e.message, true);
        }
    };

    window.loadCaseDesign = loadCaseDesign;
})();
