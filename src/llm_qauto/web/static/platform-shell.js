/**
 * 测试工作台 — 模块首页与侧栏编排
 */
(function () {
    let platformModules = [];
    let platformMeta = {};
    let currentModule = null;

    const MODULE_ICONS = {
        api: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>',
        cases: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
        browser: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>',
        contract: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 7V4a2 2 0 0 1 2-2h8.5L20 7.5V20a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-3"/><polyline points="14 2 14 8 20 8"/><path d="M8 13h8M8 17h5"/></svg>',
        gauge: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 14l3-3"/><path d="M12 22a10 10 0 1 0-10-10"/><path d="M12 2v2M4.93 4.93l1.41 1.41"/></svg>',
        mock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><path d="M14 17h7M17.5 14v7"/></svg>',
    };

    const MODULE_EXTRAS_FALLBACK = {
        api_qc: {
            accent: "teal",
            tag: "LLM-QAuto 核心",
            features: ["配置助手：cURL → YAML", "帮写 / Listing / 生图场景", "批量运行与 HTML 报告"],
        },
        case_design: {
            accent: "blue",
            tag: "需求 → 用例",
            features: ["用例助手：多轮对话", "评审图 + Mermaid 覆盖树", "服务端保存与 CSV 导出"],
        },
        ui_automation: {
            accent: "violet",
            tag: "Playwright",
            features: ["脚本助手：多轮对话", "本机一键运行", "GitHub Actions CI 模板"],
        },
    };

    function getModuleCardMeta(m) {
        const card = m.card || {};
        const fallback = MODULE_EXTRAS_FALLBACK[m.id] || {};
        return {
            accent: card.accent || fallback.accent || "teal",
            tag: card.tag || fallback.tag || "模块",
            features: card.features || fallback.features || [],
        };
    }

    async function loadPlatformModules() {
        try {
            const { data } = await apiFetch("/api/platform/modules");
            platformMeta = data.platform || {};
            platformModules = data.modules || [];
        } catch (e) {
            platformModules = [
                {
                    id: "api_qc",
                    name: "API 质检",
                    description: "LLM API 批量评判",
                    icon: "api",
                    skill_id: "qauto-from-curl",
                    default_section: "assistant",
                    sections: [],
                },
            ];
        }
        updateBrand();
    }

    function updateBrand() {
        const nameEl = document.querySelector(".brand-name");
        const tagEl = document.querySelector(".brand-tagline");
        if (nameEl && platformMeta.name) nameEl.textContent = platformMeta.name;
        if (tagEl && platformMeta.tagline) tagEl.textContent = platformMeta.tagline;
    }

    function getModule(id) {
        return platformModules.find((m) => m.id === id);
    }

    const MODULE_CHROME = {
        api_qc: { tag: "API 质检", showStats: true },
        case_design: { tag: "用例设计", showStats: false },
        ui_automation: { tag: "UI 自动化", showStats: false },
        api_contract: { tag: "接口契约", showStats: false },
        perf_test: { tag: "性能测试", showStats: false },
        mock_data: { tag: "Mock 造数", showStats: false },
    };

    const WORKBENCH_MODULE_IDS = ["api_contract", "perf_test", "mock_data"];

    function renderModulePageHead(title, lead, actionsHtml) {
        return `<header class="module-page-head">
  <div class="module-page-head-main">
    <h1 class="module-page-title">${escapeHtml(title)}</h1>
    ${lead ? `<p class="module-page-lead">${lead}</p>` : ""}
  </div>
  ${actionsHtml ? `<div class="module-page-actions">${actionsHtml}</div>` : ""}
</header>`;
    }

    function updateModuleChrome(moduleId, sectionLabel) {
        document.body.classList.remove("module-api_qc", "module-case_design", "module-ui_automation");
        if (moduleId) document.body.classList.add(`module-${moduleId}`);

        const statsBar = document.getElementById("stats-bar");
        const chrome = moduleId ? MODULE_CHROME[moduleId] : null;
        if (statsBar) {
            statsBar.style.display = chrome?.showStats ? "" : "none";
        }

        const ctx = document.getElementById("header-context");
        const badge = document.getElementById("header-badge");
        const tagline = document.querySelector(".brand-tagline");

        if (!moduleId) {
            if (ctx) ctx.innerHTML = "";
            if (badge) {
                badge.textContent = "Quality Assurance";
                badge.style.display = "";
            }
            if (tagline) tagline.textContent = platformMeta.tagline || "Skill 与 Web 同步的多功能测试平台";
            return;
        }

        const mod = getModule(moduleId);
        if (ctx && mod) {
            ctx.innerHTML = sectionLabel
                ? `<span class="header-ctx-module">${escapeHtml(mod.name)}</span><span class="header-ctx-sep">/</span><span class="header-ctx-section">${escapeHtml(sectionLabel)}</span>`
                : `<span class="header-ctx-module">${escapeHtml(mod.name)}</span>`;
        }
        if (badge && chrome) badge.textContent = chrome.tag;
        if (tagline && mod) tagline.textContent = mod.description || platformMeta.tagline || "";
    }

    function setShellLayout(mode, moduleId) {
        const layout = document.getElementById("main-layout");
        const statsBar = document.getElementById("stats-bar");
        document.body.classList.toggle("shell-home", mode === "home");
        document.body.classList.toggle("shell-module", mode === "module");
        if (layout) {
            layout.classList.toggle("main-grid--home", mode === "home");
            layout.classList.toggle("main-grid--module", mode === "module");
            if (mode === "home") {
                layout.style.gridTemplateColumns = "1fr";
            } else if (typeof window.applyMainNavGridColumns === "function") {
                window.applyMainNavGridColumns();
            }
        }
        if (mode === "home") {
            if (statsBar) statsBar.style.display = "none";
            updateModuleChrome(null);
        } else if (moduleId) {
            updateModuleChrome(moduleId);
        }
    }

    function renderModuleCard(m) {
        const icon = MODULE_ICONS[m.icon] || MODULE_ICONS.api;
        const extra = getModuleCardMeta(m);
        const skillOnly = m.skill_only && !WORKBENCH_MODULE_IDS.includes(m.id) ? '<span class="module-card-badge">Cursor Skill</span>' : "";
        const features = (extra.features || [])
            .map((f) => `<li>${escapeHtml(f)}</li>`)
            .join("");
        return `<article class="module-card module-card--${extra.accent}">
  <div class="module-card-top">
    <div class="module-card-icon">${icon}</div>
    <span class="module-card-tag">${escapeHtml(extra.tag)}</span>
    ${skillOnly}
  </div>
  <h3 class="module-card-title">${escapeHtml(m.name)}</h3>
  <p class="module-card-desc">${escapeHtml(m.description || "")}</p>
  <ul class="module-card-features">${features}</ul>
  <div class="module-card-foot">
    <code class="module-card-skill">@${escapeHtml(m.skill_id || "skill")}</code>
    <span class="module-card-cta">进入模块 <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="9 18 15 12 9 6"/></svg></span>
  </div>
  <button type="button" class="module-card-hit" onclick="enterModule('${m.id}')" aria-label="进入 ${escapeHtml(m.name)}"></button>
</article>`;
    }

    function renderPlatformHome() {
        currentModule = null;
        setShellLayout("home");

        const sidebar = document.getElementById("sidebar-module-nav");
        const apiActions = document.getElementById("sidebar-api-actions");
        if (sidebar) sidebar.innerHTML = "";
        if (apiActions) apiActions.style.display = "none";
        const backBtn = document.getElementById("sidebar-back-home");
        if (backBtn) backBtn.style.display = "none";

        const content = document.getElementById("main-content");
        if (!content) return;

        const cards = platformModules.map(renderModuleCard).join("");

        content.innerHTML = `
<div class="platform-home">
  <section class="platform-hero">
    <p class="platform-hero-eyebrow">Quality Assurance Platform</p>
    <h1 class="platform-hero-title">选择能力模块，开始测试工作</h1>
    <p class="platform-hero-lead">Web 控制台与 Cursor Skill 共用同一份 manifest，在浏览器或 IDE 中无缝切换。</p>
  </section>

  <section class="platform-section">
    <div class="platform-section-head">
      <h2>能力模块</h2>
      <p>点击进入；API 质检为 LLM-QAuto 核心引擎，其余模块可独立使用。</p>
    </div>
    <div class="module-grid">${cards}</div>
  </section>
</div>`;
    }

    function renderModuleSidebar(moduleId) {
        setShellLayout("module", moduleId);
        const mod = getModule(moduleId);
        const sidebar = document.getElementById("sidebar-module-nav");
        const apiActions = document.getElementById("sidebar-api-actions");
        const backBtn = document.getElementById("sidebar-back-home");
        if (backBtn) backBtn.style.display = "flex";
        if (!sidebar || !mod) return;

        if (moduleId === "api_qc" && apiActions) {
            apiActions.style.display = "block";
        } else if (apiActions) {
            apiActions.style.display = "none";
        }

        const sections = mod.sections || [];
        sidebar.innerHTML = `
<div class="sidebar-module-head">
  <span class="sidebar-module-name">${escapeHtml(mod.name)}</span>
  <p class="sidebar-module-desc">${escapeHtml(mod.description || "")}</p>
</div>
<div class="sidebar-label">功能导航</div>
<div class="nav-menu">
${sections
    .map(
        (s) => `<div class="nav-item" onclick="showModuleSection('${moduleId}','${s.id}')" id="nav-${moduleId}-${s.id}">
  <span>${escapeHtml(s.label)}</span>
</div>`
    )
    .join("")}
</div>`;
    }

    function enterModule(moduleId, sectionId) {
        const mod = getModule(moduleId);
        if (!mod) return;
        currentModule = moduleId;
        renderModuleSidebar(moduleId);
        const section = sectionId || mod.default_section || (mod.sections && mod.sections[0] && mod.sections[0].id) || "workspace";
        showModuleSection(moduleId, section);
    }

    function showModuleSection(moduleId, sectionId) {
        currentModule = moduleId;
        setShellLayout("module", moduleId);
        const mod = getModule(moduleId);
        const sec = (mod?.sections || []).find((s) => s.id === sectionId);
        updateModuleChrome(moduleId, sec?.label || sectionId);

        document.querySelectorAll("#sidebar-module-nav .nav-item").forEach((el) => el.classList.remove("active"));
        const nav = document.getElementById(`nav-${moduleId}-${sectionId}`);
        if (nav) nav.classList.add("active");

        if (moduleId === "api_qc") {
            if (typeof showApiQcSection === "function") showApiQcSection(sectionId);
        } else if (moduleId === "case_design") {
            if (typeof loadCaseDesign === "function") loadCaseDesign(sectionId);
        } else if (moduleId === "ui_automation") {
            if (typeof loadUiAuto === "function") loadUiAuto(sectionId);
        } else if (WORKBENCH_MODULE_IDS.includes(moduleId)) {
            if (typeof loadSkillWorkbench === "function") loadSkillWorkbench(moduleId, sectionId);
        } else if (mod?.skill_only) {
            renderSkillOnlyModule(mod);
        }
    }

    function renderSkillOnlyModule(mod) {
        const content = document.getElementById("main-content");
        if (!content || !mod) return;
        const extra = getModuleCardMeta(mod);
        const features = (extra.features || [])
            .map((f) => `<li>${escapeHtml(f)}</li>`)
            .join("");
        const head = renderModulePageHead(
            mod.name,
            mod.description || "",
            `<button type="button" class="btn btn-secondary btn-sm" onclick="showModuleHome()">返回首页</button>`
        );
        content.innerHTML = `
<div class="module-page">
${head}
<div class="module-page-body skill-only-panel">
  <div class="skill-only-card">
    <p class="skill-only-eyebrow">Cursor Skill · 暂无 Web 工作台</p>
    <h2>在 Cursor 对话中使用</h2>
    <p class="skill-only-cmd"><code>@${escapeHtml(mod.skill_id || "skill")}</code></p>
    <p class="hint">粘贴 OpenAPI、性能场景或发布说明，Skill 会按项目规范生成产物。完整 Web 界面可后续接入 <code>modules.yaml</code>。</p>
    <ul class="skill-only-features">${features}</ul>
    <p class="hint">扩展新模块：编辑 <code>src/llm_qauto/platform/modules.yaml</code> 并在 <code>.cursor/skills/</code> 添加 SKILL.md。</p>
  </div>
</div>
</div>`;
    }

    function showModuleHome() {
        renderPlatformHome();
    }

    function getCurrentModule() {
        return currentModule;
    }

    window.renderModulePageHead = renderModulePageHead;
    window.updateModuleChrome = updateModuleChrome;
    window.loadPlatformModules = loadPlatformModules;
    window.renderPlatformHome = renderPlatformHome;
    window.enterModule = enterModule;
    window.showModuleSection = showModuleSection;
    window.showModuleHome = showModuleHome;
    window.getCurrentModule = getCurrentModule;
    window.getPlatformModules = () => platformModules;
})();
