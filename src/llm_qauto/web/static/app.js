/**
 * LLM-QAuto Web 前端：统一 API 请求与可见的状态提示
 */

let currentSection = "assistant";
let currentProjectId = null;
let ws = null;
let selectedRunId = null;
let detailPollTimer = null;
/** 最近一次已渲染的运行详情快照，用于 WS 高频推送时跳过无变化的重绘（避免滚动被重置） */
let lastRunDetailFingerprint = "";
let lastDetailWasRunning = false;

const UI_ICONS = {
    folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
    template: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>',
    clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>',
    play: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="5 3 19 12 5 21 5 3"/></svg>',
    trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>',
    empty: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/><line x1="9" y1="14" x2="15" y2="14"/></svg>',
};

function emptyStateHtml(title, aux) {
    return `
        <div class="empty-state">
            <div class="empty-visual" aria-hidden="true">${UI_ICONS.empty}</div>
            <p>${title}</p>
            <p class="aux">${aux}</p>
        </div>`;
}

function projectCardHtml(p) {
    const idEsc = p.id.replace(/'/g, "\\'");
    const isExample = !!p.is_example;
    const cardClass = `project-card${isExample ? " project-card--example" : ""}`;
    const icon = isExample ? UI_ICONS.template : UI_ICONS.folder;
    const badge = isExample ? '<span class="badge badge--example">示例</span>' : "";
    const created = p.created_at ? new Date(p.created_at).toLocaleString() : "-";
    const exampleRunBtn = isExample
        ? `<button type="button" class="btn btn-run" onclick="event.stopPropagation(); runExampleDirect('${idEsc}')">${UI_ICONS.play}直接运行</button>`
        : "";
    const delBtn = !isExample
        ? `<button type="button" class="btn btn-ghost btn-delete-project" title="删除此项目配置" onclick="event.stopPropagation(); deleteProject('${idEsc}')">${UI_ICONS.trash}删除</button>`
        : "";
    return `
        <div class="${cardClass}">
            <div class="project-card-inner">
                <div class="project-card-icon" aria-hidden="true">
                    <div class="project-card-icon-inner">${icon}</div>
                </div>
                <div class="project-card-body" onclick="viewProject('${idEsc}')">
                    <div class="name">${escapeHtml(p.name)}</div>
                    <div class="desc">${escapeHtml(p.description || "暂无描述")}</div>
                    <div class="meta">
                        ${badge}
                        <span class="meta-item">${UI_ICONS.clock}${created}</span>
                    </div>
                </div>
                <div class="project-card-actions">${exampleRunBtn}${delBtn}</div>
            </div>
        </div>`;
}

/** 底部状态条：method url -> status ms */
function setApiStatus(message, kind = "info", detail = "") {
    const bar = document.getElementById("api-status-bar");
    const text = document.getElementById("api-status-text");
    const sub = document.getElementById("api-status-detail");
    if (!bar || !text) return;
    bar.classList.remove("ok", "err", "loading");
    if (kind === "ok") bar.classList.add("ok");
    else if (kind === "err") bar.classList.add("err");
    else if (kind === "loading") bar.classList.add("loading");
    text.textContent = message;
    sub.textContent = detail || "";
    console.log("[API]", message, detail);
}

/**
 * 带界面提示的 fetch
 * @param {string} url
 * @param {object} options - fetch options + { silent?: boolean } 轮询类请求设 true 跳过 toast
 * @returns {{ response: Response, data: any } | { error: Error, response?: Response }}
 */
async function apiFetch(url, options = {}) {
    const silent = options && options.silent;
    const method = (options.method || "GET").toUpperCase();
    const started = performance.now();
    const label = `${method} ${url}`;
    setApiStatus(`正在请求: ${label}`, "loading");

    let response;
    try {
        response = await fetch(url, options);
    } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        setApiStatus(`网络错误: ${label}`, "err", msg);
        if (!silent && typeof showToast === "function") {
            showToast(`网络错误：${msg}`, "error");
        }
        throw e;
    }

    const ms = Math.round(performance.now() - started);
    const ct = response.headers.get("content-type") || "";

    let data = null;
    try {
        if (ct.includes("application/json")) {
            data = await response.json();
        } else if (response.status !== 204) {
            data = await response.text();
        }
    } catch (e) {
        setApiStatus(`解析响应失败: ${label}`, "err", response.status + " " + response.statusText);
        if (!silent && typeof showToast === "function") {
            showToast(`解析响应失败：${response.status}`, "error");
        }
        throw e;
    }

    if (response.ok) {
        setApiStatus(`完成 ${response.status} ${label} (${ms}ms)`, "ok");
        return { response, data };
    }

    const detail =
        data && typeof data === "object" && data.detail != null
            ? String(data.detail)
            : typeof data === "string"
              ? data.slice(0, 200)
              : response.statusText;
    setApiStatus(`失败 ${response.status} ${label} (${ms}ms)`, "err", detail);
    if (!silent && typeof showToast === "function") {
        showToast(`请求失败 ${response.status}：${detail}`, "error");
    }
    const err = new Error(detail);
    err.response = response;
    err.data = data;
    throw err;
}

document.addEventListener("DOMContentLoaded", async () => {
    document.querySelectorAll(".modal-overlay").forEach((el) => {
        el.setAttribute("aria-hidden", el.classList.contains("active") ? "false" : "true");
    });
    setApiStatus(
        `就绪 · 同源 ${window.location.origin} · 打开开发者工具 Network 可看全部请求`,
        "info"
    );
    if (typeof initConfigForms === "function") initConfigForms();
    if (typeof loadPlatformModules === "function") await loadPlatformModules();
    if (typeof renderPlatformHome === "function") {
        await renderPlatformHome();
    } else {
        showApiQcSection("assistant");
    }
    loadStats();
    initWebSocket();
    initMainNavSplitter();
    window.addEventListener("resize", () => {
        const ds = document.getElementById("detail-split");
        if (ds && window.innerWidth <= 1100) ds.style.gridTemplateColumns = "";
        const rg = document.getElementById("report-panes-grid");
        if (rg && window.innerWidth <= 880) rg.style.gridTemplateColumns = "";
    });
    setInterval(loadStats, 5000);
});

function initWebSocket() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    try {
        ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
    } catch (e) {
        setApiStatus("WebSocket 无法连接", "err", String(e));
        return;
    }

    ws.onopen = () => setApiStatus("WebSocket 已连接 (/ws)", "ok");

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            updateRunningTests(data.running_tests || []);
        } catch (e) {
            console.warn("WS parse error", e);
        }
    };

    ws.onclose = () => {
        setApiStatus("WebSocket 已断开，3s 后重试…", "info");
        setTimeout(initWebSocket, 3000);
    };

    ws.onerror = () => setApiStatus("WebSocket 错误", "err");
}

async function loadStats() {
    const statsBar = document.getElementById("stats-bar");
    if (!statsBar || statsBar.style.display === "none") return;
    try {
        const { data } = await apiFetch("/api/stats", { silent: true });
        const rate = Number(data.success_rate ?? 0);
        document.getElementById("stat-projects").textContent = data.total_projects ?? 0;
        document.getElementById("stat-tests").textContent = data.total_tests ?? 0;
        document.getElementById("stat-rate").textContent = rate.toFixed(1) + "%";
        document.getElementById("stat-running").textContent = data.running_tests ?? 0;
    } catch (e) {
        document.getElementById("stat-rate").textContent = "--";
    }
}

function showSection(section) {
    if (typeof enterModule === "function") {
        enterModule("api_qc", section);
    } else {
        showApiQcSection(section);
    }
}

function showApiQcSection(section) {
    currentSection = section;

    document.querySelectorAll("#sidebar-module-nav .nav-item").forEach((item) => item.classList.remove("active"));
    const nav = document.getElementById(`nav-api_qc-${section}`);
    if (nav) nav.classList.add("active");

    if (section !== "runs") {
        clearDetailPoll();
    }

    switch (section) {
        case "projects":
            loadProjects();
            break;
        case "runs":
            loadRuns();
            break;
        case "examples":
            loadExamples();
            break;
        case "assistant":
            if (typeof loadAssistant === "function") loadAssistant();
            break;
        default:
            setApiStatus(`未知板块: ${section}`, "err");
    }
}

async function loadProjects() {
    const content = document.getElementById("main-content");
    const head =
        typeof renderModulePageHead === "function"
            ? renderModulePageHead("测试项目", "管理 YAML 套件，创建后可在本页或「测试运行」中发起批量评判。", "")
            : '<div class="section-title">测试项目</div>';
    const _skeleton = (typeof skeletonProjectCards === "function") ? skeletonProjectCards(4) : "加载中…";
    content.innerHTML = `<div class="module-page">${head}<div class="module-page-body project-list" id="project-list">${_skeleton}</div></div>`;

    try {
        const { data } = await apiFetch("/api/projects");
        const list = document.getElementById("project-list");
        const projects = data.projects || [];

        if (projects.length === 0) {
            list.innerHTML = emptyStateHtml(
                "当前没有测试项目",
                "使用左侧「从 cURL 快速创建」粘贴浏览器请求，或在「示例配置」中从模板开始。"
            );
            return;
        }

        list.innerHTML = projects.map((p) => projectCardHtml(p)).join("");
    } catch (e) {
        content.innerHTML = `<div class="error">加载失败: ${escapeHtml(e.message)}</div>`;
    }
}

function escapeHtml(s) {
    return String(s)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function dimensionNamesFromReport(data) {
    const meta = data && data.suite_meta;
    if (meta && meta.dimension_display_names && typeof meta.dimension_display_names === "object") {
        return meta.dimension_display_names;
    }
    const out = {};
    (data?.dimension_stats || []).forEach((s) => {
        if (s && s.dimension_id) {
            out[s.dimension_id] = s.dimension_name || s.dimension_id;
        }
    });
    return out;
}

function dimensionDisplayLabel(names, dimId) {
    if (!dimId) return dimId;
    const label = names && names[dimId];
    return label && String(label).trim() ? String(label).trim() : dimId;
}

function formatDimensionLabels(names, dimIds) {
    if (!dimIds) return "—";
    const list = Array.isArray(dimIds) ? dimIds : [dimIds];
    if (!list.length) return "—";
    return list.map((id) => dimensionDisplayLabel(names, id)).join(", ");
}

/** 报告状态是否为「通过」（兼容枚举对象或字符串） */
function reportStatusPassed(status) {
    if (status == null) return false;
    const v = typeof status === "object" && status !== null && "value" in status ? status.value : status;
    return String(v).toLowerCase() === "passed";
}

/** 将典型后端异常转写为界面可读说明；原文保留在折叠区 */
function humanizeError(msg) {
    const m = String(msg || "");
    if (m.includes("datetime") && m.includes("JSON serializable")) {
        return "保存运行产物时数据序列化失败。此类问题已在当前版本修复，请重新执行一次任务。";
    }
    if (m.includes("API key") || m.includes("api_key")) {
        return "缺少或无效的模型 API 密钥。请检查项目根目录 .env 或环境变量后重试。";
    }
    return m.length > 160 ? m.slice(0, 160) + "…" : m;
}

/** 被测接口 / 连接器报错 → 产品可读短句（完整原文见折叠区） */
function humanizeConnectorError(msg) {
    const m = String(msg || "");
    if (!m.trim()) return "未返回具体原因，可请技术同事对照下方「技术明细」与后台日志。";
    if (m.includes("不支持将 HTTP 方法设为 OPTIONS") || (m.includes("OPTIONS") && m.includes("CORS"))) {
        return "配置问题：接口 HTTP 方法被设成了 OPTIONS（多用于浏览器预检）。请在 YAML 里改为与接口文档一致的 GET 或 POST。";
    }
    if (/HTTP\s*502|502/.test(m)) {
        return "上游返回 502：多为网关或服务短暂不可用，可稍后重试或由后端查看服务状态。";
    }
    if (/HTTP\s*503|503/.test(m)) return "服务返回 503：可能过载或正在维护。";
    if (/HTTP\s*504|504/.test(m)) return "网关超时（504）：对方处理过慢或链路异常。";
    if (/HTTP\s*401|401/.test(m)) return "鉴权失败（401）：请检查 Token、Header 是否与现场环境一致。";
    if (/HTTP\s*403|403/.test(m)) return "无权限（403）：账号或 IP 可能被拒绝。";
    if (/HTTP\s*404|404/.test(m)) return "路径不存在（404）：请核对 URL 是否与后端路由一致。";
    if (/HTTP\s*500|500/.test(m)) return "服务端内部错误（500）：需业务后端查日志。";
    if (/JSON|不是合法 JSON|JSONDecodeError/i.test(m)) return "返回内容不是合法 JSON，请确认接口确实返回 JSON（有时是 HTML 报错页）。";
    if (/ConnectError|Connection refused|ECONNREFUSED/i.test(m)) return "无法连上目标地址（连接被拒绝）：请检查 IP、端口、防火墙。";
    if (/timed out|Timeout|超时/i.test(m)) return "等待响应超时：可能网络慢、服务卡死或超时时间过短。";
    if (/certificate|SSL|TLS/i.test(m)) return "HTTPS 证书或 TLS 问题：检查证书是否有效、系统时间是否正确。";
    return m.length > 200 ? m.slice(0, 198) + "…" : m;
}

function formatActivityClock(ts) {
    if (!ts) return "—";
    const s = String(ts);
    const m = s.match(/T(\d{2}:\d{2}:\d{2})/);
    if (m) return m[1];
    return s.length >= 19 ? s.slice(11, 19) : s;
}

/** 用例编号 → 口头称呼 */
function friendlyCaseRef(caseId) {
    const s = String(caseId ?? "").trim();
    if (!s) return "本条样本";
    const m = s.match(/^case_(\d+)$/i);
    if (m) return `第 ${parseInt(m[1], 10)} 条样本`;
    return `样本「${s}」`;
}

const ACTIVITY_KIND_LABEL = {
    lifecycle: "阶段",
    invoke: "调用接口",
    evaluate: "智能评判",
    error: "异常",
};

const LIFECYCLE_FRIENDLY = {
    ready: { title: "测试环境就绪", hint: "连接器、抽样与评判器已加载。" },
    inputs_ready: { title: "已生成待测样本", hint: "" },
    probing: { title: "正在检查接口是否可达", hint: "先发送探测请求，避免整批任务白跑。" },
    connectivity_failed: { title: "接口不可达，任务已中止", hint: "" },
    invoking: { title: "正在请求被测服务", hint: "" },
    invoke_wait: { title: "额外等待 Listing", hint: "仅在配置了 max_wait_sec 时出现。" },
    invoke_poll: { title: "等待 Listing 生成", hint: "" },
    evaluating: { title: "正在进行智能评判", hint: "" },
    aggregating: { title: "正在汇总统计与门禁", hint: "" },
    completed: { title: "本轮执行结束", hint: "" },
};

function friendlyLifecycleLine(ev) {
    const ph = String(ev.phase || "").toLowerCase();
    const preset = LIFECYCLE_FRIENDLY[ph];
    const rawMsg = String(ev.message || "").trim();
    let title = preset ? preset.title : "进度更新";
    let hint = preset && preset.hint ? preset.hint : "";

    if (ph === "inputs_ready" && ev.total != null) {
        hint = `系统已根据变量组合生成 ${ev.total} 条样本，即将逐条调用接口。`;
    } else if (ph === "completed") {
        if (ev.passed_cases != null && ev.total_cases != null) {
            hint = `共处理 ${ev.total_cases} 条样本，其中 ${ev.passed_cases} 条达到通过标准。`;
        } else {
            hint = rawMsg || hint;
        }
    } else if (ph === "connectivity_failed") {
        hint = humanizeConnectorError(rawMsg);
    } else if ((ph === "invoke_wait" || ph === "invoke_poll") && rawMsg) {
        hint = rawMsg;
    } else if (!hint && rawMsg) {
        hint = rawMsg;
    }
    return { title, hint };
}

/** 供折叠区展示的原始一行（保留原逻辑） */
function formatEventBodyTechnical(ev) {
    const k = ev.kind || "";
    if (k === "lifecycle")
        return `${ev.phase || "—"} · ${String(ev.message || "").trim() || "—"}`;
    if (k === "invoke") {
        const err = ev.error ? ` · error` : "";
        return `${ev.case_id} · ${ev.latency_ms ?? ""}ms · ${ev.output_chars ?? ""} chars${err}`;
    }
    if (k === "evaluate")
        return `${ev.case_id} · ${ev.passed ? "通过" : "未通过"}${ev.skipped_judge ? " · skipped_judge" : ""}${ev.llm_called ? " · llm_called=1" : ""}`;
    if (k === "error") return String(ev.message || "");
    try {
        return JSON.stringify(ev).slice(0, 400);
    } catch {
        return "—";
    }
}

function buildActivityItemHtml(ev) {
    const kind = ev.kind || "";
    const clock = formatActivityClock(ev.ts);
    const badge = ACTIVITY_KIND_LABEL[kind] || kind || "记录";
    let rowClass = "activity-item";
    let title = "";
    let hint = "";
    const tech = formatEventBodyTechnical(ev);

    if (kind === "lifecycle") {
        const fl = friendlyLifecycleLine(ev);
        title = fl.title;
        hint = fl.hint;
        const ph = String(ev.phase || "").toLowerCase();
        if (ph === "connectivity_failed") rowClass += " activity-item--bad";
        else if (ph === "completed") rowClass += " activity-item--ok";
    } else if (kind === "invoke") {
        const ref = friendlyCaseRef(ev.case_id);
        if (ev.error) {
            title = `${ref}：接口调用未成功`;
            hint = humanizeConnectorError(ev.error);
            rowClass += " activity-item--bad";
        } else {
            const ms = ev.latency_ms != null ? Number(ev.latency_ms) : null;
            const sec = ms != null ? (ms / 1000).toFixed(ms >= 10000 ? 1 : 2) : null;
            const chars =
                ev.output_chars != null
                    ? Number(ev.output_chars) === 0
                        ? "返回正文为空。"
                        : `返回内容约 ${ev.output_chars} 个字符。`
                    : "";
            title = `${ref}：接口已返回`;
            hint = sec != null ? `耗时约 ${sec} 秒。${chars}` : chars || "调用已完成。";
            rowClass += " activity-item--ok";
        }
    } else if (kind === "evaluate") {
        const ref = friendlyCaseRef(ev.case_id);
        if (ev.skipped_judge) {
            title = `${ref}：未执行 AI 打分`;
            hint =
                ev.llm_configured === true
                    ? "接口返回失败或无效，本次已跳过配置的「大模型评委」，不会产生模型调用。"
                    : "本条未进入评委流程（或未配置 LLM 评委）。";
            rowClass += " activity-item--warn";
        } else if (ev.passed) {
            title = `${ref}：评判为达标`;
            hint =
                ev.llm_called === true
                    ? ev.batch_llm
                        ? "单次全评（batch_llm）已调用并完成多维度打分；结果满足阈值与规则。"
                        : "大模型评委已调用并完成打分；结果满足阈值与规则。"
                    : "已按规则评判为达标（当前维度未启用 LLM 评委）。";
            rowClass += " activity-item--ok";
        } else {
            title = `${ref}：评判为未达标`;
            hint =
                ev.llm_called === true
                    ? ev.batch_llm
                        ? "单次全评已完成但未达通过标准，可在报告中查看各维得分与 issues。"
                        : "大模型已完成打分但未达通过标准，可在报告或明细中查看原因。"
                    : "未满足配置的评分规则（或未走 LLM 评委）。";
            rowClass += " activity-item--warn";
        }
    } else if (kind === "error") {
        title = "运行过程出现异常";
        hint = humanizeError(ev.message);
        rowClass += " activity-item--bad";
    } else {
        title = "其它事件";
        hint = formatEventBodyTechnical(ev);
    }

    const hintBlock = hint
        ? `<div class="activity-hint">${escapeHtml(hint)}</div>`
        : "";

    return `
    <div class="${rowClass}" role="listitem">
      <div class="activity-item-top">
        <span class="activity-clock">${escapeHtml(clock)}</span>
        <span class="activity-pill">${escapeHtml(badge)}</span>
      </div>
      <div class="activity-line-title">${escapeHtml(title)}</div>
      ${hintBlock}
      <details class="activity-tech">
        <summary>技术明细（排障用）</summary>
        <pre>${escapeHtml(tech)}</pre>
      </details>
    </div>`;
}

function computeRunDetailFingerprint(data) {
    if (!data || !data.run_id) return "";
    const ev = (data.events && data.events[data.events.length - 1]) || null;
    const lastSig = ev
        ? `${ev.kind}|${ev.ts}|${ev.phase ?? ""}|${String(ev.message ?? "").slice(0, 120)}|${ev.case_id ?? ""}|${ev.passed}|${ev.llm_called}|${ev.skipped_judge}|${String(ev.error ?? "").slice(0, 100)}`
        : "";
    return [
        data.run_id,
        data.status ?? "",
        data.progress ?? "",
        data.phase ?? "",
        data.current_step ?? "",
        data.invoke_completed ?? "",
        data.evaluate_completed ?? "",
        data.planned_cases ?? "",
        data.error ?? "",
        lastSig,
    ].join("\u0001");
}

/** 整块 innerHTML 重绘前记录滚动位置（活动说明区 + 用例表容器） */
function captureRunDetailScroll(panel) {
    if (!panel) return null;
    const act = panel.querySelector(".event-log--friendly");
    const tbl = panel.querySelector(".cases-table-wrap");
    return {
        activity: act ? act.scrollTop : undefined,
        cases: tbl ? tbl.scrollTop : undefined,
    };
}

function restoreRunDetailScroll(panel, saved) {
    if (!panel || !saved) return;
    const apply = () => {
        const act = panel.querySelector(".event-log--friendly");
        if (act && saved.activity != null) {
            const max = Math.max(0, act.scrollHeight - act.clientHeight);
            act.scrollTop = Math.min(Math.max(0, saved.activity), max);
        }
        const tbl = panel.querySelector(".cases-table-wrap");
        if (tbl && saved.cases != null) {
            const max = Math.max(0, tbl.scrollHeight - tbl.clientHeight);
            tbl.scrollTop = Math.min(Math.max(0, saved.cases), max);
        }
    };
    apply();
    requestAnimationFrame(() => {
        apply();
        requestAnimationFrame(apply);
    });
}

function buildActivityFeedHtml(events, emptyText) {
    if (!events || !events.length) {
        return `<p class="activity-feed-empty">${escapeHtml(emptyText)}</p>`;
    }
    return `<div class="activity-feed" role="list">${events.map(buildActivityItemHtml).join("")}</div>`;
}

function clearDetailPoll() {
    if (detailPollTimer) {
        clearTimeout(detailPollTimer);
        detailPollTimer = null;
    }
}

function scheduleDetailPoll() {
    clearDetailPoll();
    if (!selectedRunId || currentSection !== "runs" || !lastDetailWasRunning) return;
    detailPollTimer = setTimeout(async () => {
        if (!selectedRunId || currentSection !== "runs") return;
        try {
            const r = await fetch(`/api/runs/${encodeURIComponent(selectedRunId)}/detail`);
            if (r.ok) {
                const data = await r.json();
                renderRunDetail(data);
            }
        } catch (e) {
            console.warn("detail poll", e);
        }
        scheduleDetailPoll();
    }, 2200);
}

function phaseChipClass(phase) {
    const p = String(phase || "").toLowerCase();
    if (p === "evaluating") return "phase-chip evaluating";
    if (p === "invoking") return "phase-chip invoking";
    if (p === "completed") return "phase-chip completed";
    if (p === "failed" || p === "connectivity_failed") return "phase-chip failed";
    return "phase-chip";
}

function runIsFailed(r) {
    const s = String(r.status || r.report_status || "").toLowerCase();
    if (s === "failed") return true;
    if (s === "completed" && r.failed_cases != null && Number(r.failed_cases) > 0 && Number(r.pass_rate) === 0)
        return true;
    return false;
}

function runListActionsHtml(r) {
    const ridEsc = String(r.run_id || "").replace(/'/g, "\\'");
    const delBtn = `<button type="button" class="btn btn-danger" onclick="event.stopPropagation(); deleteRunRecord('${ridEsc}')">删除</button>`;
    if (r.status === "running" || r.status === "starting") {
        return `<button type="button" class="btn btn-danger" onclick="event.stopPropagation(); stopRun('${ridEsc}')">停止</button>`;
    }
    if (runIsFailed(r) || r.status === "failed") {
        return `<button type="button" class="btn btn-secondary" onclick="event.stopPropagation(); viewReport('${ridEsc}')">报告</button>${delBtn}`;
    }
    if (r.status === "completed" || r.status === "passed") {
        return `<button type="button" class="btn btn-secondary" onclick="event.stopPropagation(); viewReport('${ridEsc}')">报告</button>${delBtn}`;
    }
    if (r.status === "stopped") {
        return `<button type="button" class="btn btn-secondary" onclick="event.stopPropagation(); viewReport('${ridEsc}')">详情</button>${delBtn}`;
    }
    return `<button type="button" class="btn btn-secondary" onclick="event.stopPropagation(); viewReport('${ridEsc}')">详情</button>${delBtn}`;
}

/** 列表里过长 run_id 中间省略，完整 id 放在 title */
function truncateRunIdForList(id, max = 48) {
    if (!id) return "";
    if (id.length <= max) return escapeHtml(id);
    const head = Math.ceil(max * 0.52);
    const tail = max - head - 1;
    return `${escapeHtml(id.slice(0, head))}…${escapeHtml(id.slice(-tail))}`;
}

function runListStatusChip(r) {
    if (r.is_running) {
        const ph = r.phase ? String(r.phase) : "运行中";
        return `<span class="${phaseChipClass(r.phase)} run-list-chip">${escapeHtml(phaseLabelForPm(ph))}</span>`;
    }
    if (runIsFailed(r)) {
        return `<span class="phase-chip failed run-list-chip">未通过</span>`;
    }
    const s = String(r.status || "").toLowerCase();
    if (s === "passed") {
        return `<span class="phase-chip completed run-list-chip">通过</span>`;
    }
    if (s === "completed") {
        return `<span class="phase-chip completed run-list-chip">已完成</span>`;
    }
    if (s === "failed") {
        return `<span class="phase-chip failed run-list-chip">未通过</span>`;
    }
    if (s === "stopped") {
        return `<span class="phase-chip run-list-chip run-list-chip--stopped">已停止</span>`;
    }
    return `<span class="phase-chip run-list-chip">${escapeHtml(r.status || "—")}</span>`;
}

function detailPhaseLabel(data) {
    if (data.is_running) return phaseLabelForPm(data.phase);
    if (runIsFailed(data) || String(data.report_summary?.status || "").toLowerCase() === "failed")
        return "未通过";
    const s = String(data.status || "").toLowerCase();
    if (s === "passed") return "通过";
    if (s === "completed") return "已完成";
    if (s === "failed") return "未通过";
    if (s === "stopped") return "已停止";
    const p = String(data.phase || "").toLowerCase();
    if (p === "connectivity_failed") return "接口不可达";
    if (p === "failed") return "未通过";
    if (p === "completed") return "已完成";
    return phaseLabelForPm(data.phase) || String(data.status || "—");
}

function detailPhaseChipClass(data) {
    if (data.is_running) return phaseChipClass(data.phase);
    if (runIsFailed(data) || String(data.report_summary?.status || "").toLowerCase() === "failed")
        return "phase-chip failed";
    const s = String(data.status || "").toLowerCase();
    if (s === "passed" || s === "completed") return "phase-chip completed";
    if (s === "failed") return "phase-chip failed";
    if (s === "stopped") return "phase-chip";
    return phaseChipClass(data.phase);
}

/** 左侧详情 / 报告里「阶段」代码 → 口头用语 */
function phaseLabelForPm(phase) {
    const p = String(phase || "").toLowerCase();
    const map = {
        starting: "启动中",
        ready: "就绪",
        probing: "探测接口",
        invoking: "调用被测接口",
        evaluating: "智能评判",
        aggregating: "汇总统计",
        completed: "已完成",
        connectivity_failed: "接口不可达",
        failed: "失败",
    };
    return map[p] || (phase ? String(phase) : "—");
}

function renderRunDetail(data) {
    const panel = document.getElementById("run-detail");
    if (!panel) return;

    lastDetailWasRunning = !!data.is_running;

    if (!data || !data.run_id) {
        lastRunDetailFingerprint = "";
        panel.innerHTML =
            '<div class="run-detail-placeholder">无法加载运行详情</div>';
        scheduleDetailPoll();
        return;
    }

    const savedScroll = captureRunDetailScroll(panel);
    const phaseLabel = detailPhaseLabel(data);
    const phaseChip = detailPhaseChipClass(data);
    const cfg = data.config_path ? escapeHtml(data.config_path) : "—";
    const invokeErr = (data.recent_cases || []).find((c) => c.error)?.error;
    const runFailed =
        runIsFailed(data) || String(data.report_summary?.status || "").toLowerCase() === "failed";
    const errBlock =
        data.error && data.status === "failed"
            ? `<div class="user-alert user-alert--bad" role="alert">
                 <h4>本次运行未能完成</h4>
                 <p>${escapeHtml(humanizeError(data.error))}</p>
                 <details>
                   <summary>技术详情（排障用）</summary>
                   <pre>${escapeHtml(data.error)}</pre>
                 </details>
               </div>`
            : runFailed
              ? `<div class="user-alert user-alert--bad" role="alert">
                 <h4>本轮未通过</h4>
                 <p>${escapeHtml(
                     invokeErr
                         ? humanizeConnectorError(invokeErr)
                         : data.current_step || "部分或全部用例未达通过标准，详见下方活动日志与报告。"
                 )}</p>
               </div>`
              : "";

    let summaryKpi = "";
    if (data.report_summary) {
        const rs = data.report_summary;
        summaryKpi = `
      <div class="meta-grid" style="margin-bottom:12px">
        <div class="meta-tile"><div class="label">总样本</div><div class="val">${escapeHtml(String(rs.total_cases ?? "—"))}</div></div>
        <div class="meta-tile"><div class="label">通过</div><div class="val pass-ok">${escapeHtml(String(rs.passed_cases ?? "—"))}</div></div>
        <div class="meta-tile"><div class="label">失败</div><div class="val pass-no">${escapeHtml(String(rs.failed_cases ?? "—"))}</div></div>
        <div class="meta-tile"><div class="label">通过率</div><div class="val">${escapeHtml(Number(rs.pass_rate ?? 0).toFixed(1))}%</div></div>
      </div>`;
    }

    const events = data.events || [];
    const eventsHtml = buildActivityFeedHtml(
        events,
        "暂无活动记录（已结束的任务通常不保留过程日志）。"
    );

    const cases = data.recent_cases || [];
    const caseRows = cases.length
        ? cases
              .map((c) => {
                  const pid = escapeHtml(String(c.case_id ?? "—"));
                  const lat = c.latency_ms != null ? escapeHtml(String(c.latency_ms)) : "—";
                  const ch = c.output_chars != null ? escapeHtml(String(c.output_chars)) : "—";
                  const er = c.error ? `<span class="pass-no">有</span>` : "—";
                  let pv = "—";
                  if (c.passed === true) pv = '<span class="pass-ok">通过</span>';
                  else if (c.passed === false) pv = '<span class="pass-no">未通过</span>';
                  const dimNames = dimensionNamesFromReport(data);
                  const fds = escapeHtml(formatDimensionLabels(dimNames, c.failed_dimensions));
                  return `<tr><td>${pid}</td><td>${lat}</td><td>${ch}</td><td>${er}</td><td>${pv}</td><td>${fds}</td></tr>`;
              })
              .join("")
        : '<tr><td colspan="6" style="color:#9ca3af">暂无用例行（运行开始后会出现实时轨迹）</td></tr>';

    panel.innerHTML = `
      <div class="run-detail-inner">
        <div class="detail-head">
          <div>
            <h3>${escapeHtml(data.project_name || "—")} <span class="${phaseChip}">${escapeHtml(phaseLabel)}</span></h3>
            <div class="sub">${escapeHtml(data.run_id)}</div>
            <div class="sub" style="margin-top:4px">配置: ${cfg}</div>
          </div>
          <div class="detail-toolbar">
            <button type="button" class="btn btn-secondary" onclick="refreshRunDetail()">刷新详情</button>
            ${
                data.is_running
                    ? ""
                    : `<button type="button" class="btn btn-primary" onclick="viewReport('${String(data.run_id).replace(/'/g, "\\'")}')">完整报告</button>`
            }
          </div>
        </div>
        ${errBlock}
        ${summaryKpi}
        <div class="meta-grid">
          <div class="meta-tile"><div class="label">进度</div><div class="val">${escapeHtml(String(data.progress ?? 0))}%</div></div>
          <div class="meta-tile"><div class="label">计划用例</div><div class="val">${escapeHtml(String(data.planned_cases ?? 0))}</div></div>
          <div class="meta-tile"><div class="label">调用完成</div><div class="val">${escapeHtml(String(data.invoke_completed ?? 0))}</div></div>
          <div class="meta-tile"><div class="label">评判完成</div><div class="val">${escapeHtml(String(data.evaluate_completed ?? 0))}</div></div>
        </div>
        <p style="font-size:13px;color:#4b5563;margin-bottom:14px">${escapeHtml(data.current_step || "")}</p>
        <div class="detail-split" id="detail-split">
          <div class="detail-split-col detail-block" id="detail-col-left">
            <h4>运行过程（通俗说明）</h4>
            <p class="activity-intro">按时间顺序展示当前跑在做什么。看不懂代码没关系，展开「技术明细」可对照原始日志。</p>
            <div class="event-log event-log--friendly">${eventsHtml}</div>
          </div>
          <button type="button" class="detail-splitter" id="detail-splitter" aria-label="拖动调整日志与用例区宽度" title="左右拖动调整"></button>
          <div class="detail-split-col detail-block" id="detail-col-right">
            <h4>用例轨迹</h4>
            <div class="cases-table-wrap">
              <table class="cases-table">
                <thead><tr><th>用例</th><th>延迟</th><th>字符数</th><th title="被测接口调用是否报错；— 表示无报错（不是大模型调用次数）">接口报错</th><th title="LLM 评委等评判结果">评判</th><th>失败维度</th></tr></thead>
                <tbody>${caseRows}</tbody>
              </table>
            </div>
          </div>
        </div>
      </div>`;

    lastRunDetailFingerprint = computeRunDetailFingerprint(data);

    initDetailSplit();
    restoreRunDetailScroll(panel, savedScroll);
    scheduleDetailPoll();
}

async function selectRunForDetail(runId) {
    selectedRunId = runId;
    lastRunDetailFingerprint = "";
    document.querySelectorAll(".run-item").forEach((el) => {
        el.classList.toggle("selected", el.getAttribute("data-run-id") === runId);
    });
    await refreshRunDetail();
}

async function refreshRunDetail() {
    if (!selectedRunId) return;
    const panel = document.getElementById("run-detail");
    if (!panel) return;
    try {
        const r = await fetch(`/api/runs/${encodeURIComponent(selectedRunId)}/detail`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        renderRunDetail(data);
    } catch (e) {
        panel.innerHTML = `<div class="run-detail-placeholder">加载详情失败: ${escapeHtml(e.message || String(e))}</div>`;
    }
}

async function viewProject(projectId) {
    currentProjectId = projectId;

    try {
        const { data } = await apiFetch(`/api/projects/${encodeURIComponent(projectId)}`);
        const yamlText = data.config_yaml || "";
        document.getElementById("edit-config").value = yamlText;
        if (typeof setConfigEditorMode === "function") {
            setConfigEditorMode("edit", "form");
        } else {
            document.getElementById("edit-tab-form").classList.add("active");
            document.getElementById("edit-tab-yaml").classList.remove("active");
            document.getElementById("edit-panel-form").style.display = "block";
            document.getElementById("edit-panel-yaml").style.display = "none";
            if (typeof refreshFormFromYaml === "function") {
                try {
                    refreshFormFromYaml("edit");
                    if (typeof setConfigFormSubtab === "function") {
                        setConfigFormSubtab("edit", "http");
                    }
                    if (typeof configUsesBatchLlm === "function" && typeof jsyaml !== "undefined") {
                        try {
                            const cfgObj = jsyaml.load(yamlText);
                            if (configUsesBatchLlm(cfgObj) && typeof setApiStatus === "function") {
                                setApiStatus(
                                    "请在「被测接口」下方填测试数据取值；全评提示词在「打分与放行」",
                                    "ok"
                                );
                            }
                        } catch (_) {
                            /* ignore */
                        }
                    }
                } catch (e) {
                    console.warn(e);
                    if (typeof openConfigEditorYaml === "function") {
                        openConfigEditorYaml("edit", "YAML 无法解析为表单，已切换到 YAML 原文");
                    }
                }
            }
            if (typeof initConfigFormMode === "function") initConfigFormMode("edit");
        }
        if (typeof dismissCurlConfirm === "function") dismissCurlConfirm("edit");
        document.getElementById("edit-modal").classList.add("active");
    } catch (e) {
        alert("加载配置失败: " + e.message);
    }
}

async function saveProject() {
    let config;
    try {
        if (typeof getMergedYamlForSubmit === "function") {
            config = getMergedYamlForSubmit("edit");
        } else {
            config = document.getElementById("edit-config").value.trim();
        }
    } catch (e) {
        alert(e.message || String(e));
        return;
    }

    try {
        await apiFetch(`/api/projects/${encodeURIComponent(currentProjectId)}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                name: currentProjectId,
                config_yaml: config,
            }),
        });

        const { data: projectData } = await apiFetch(
            `/api/projects/${encodeURIComponent(currentProjectId)}`
        );

        const { data: runData } = await apiFetch("/api/runs", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ config_path: projectData.config_path }),
        });

        if (runData.success) {
            hideModal("edit-modal");
            showSection("runs");
            alert("测试已启动！请到「测试运行」查看进度；底部状态条会显示每次 API。");
        }
    } catch (e) {
        alert("操作失败: " + e.message);
    }
}

function applyMainNavGridColumns() {
    const layout = document.getElementById("main-layout");
    if (!layout) return;
    if (document.body.classList.contains("shell-home")) {
        layout.style.gridTemplateColumns = "1fr";
        return;
    }
    if (window.innerWidth <= 840) {
        layout.style.gridTemplateColumns = "";
        return;
    }
    const saved = localStorage.getItem("mainNavSplitPx");
    const w = saved ? Math.min(420, Math.max(160, parseInt(saved, 10) || 240)) : 240;
    layout.style.gridTemplateColumns = `${w}px 8px 1fr`;
}

function initMainNavSplitter() {
    const layout = document.getElementById("main-layout");
    const splitter = document.getElementById("main-nav-splitter");
    const sidebar = document.getElementById("main-sidebar");
    if (!layout || !splitter || !sidebar) return;

    window.applyMainNavGridColumns = applyMainNavGridColumns;

    function applySaved() {
        applyMainNavGridColumns();
    }
    applySaved();
    window.addEventListener("resize", applySaved);

    splitter.addEventListener("mousedown", (e) => {
        e.preventDefault();
        if (window.innerWidth <= 840 || document.body.classList.contains("shell-home")) return;
        const startX = e.clientX;
        const startW = sidebar.getBoundingClientRect().width;
        function onMove(ev) {
            const w = Math.min(420, Math.max(160, startW + ev.clientX - startX));
            layout.style.gridTemplateColumns = `${Math.round(w)}px 8px 1fr`;
        }
        function onUp() {
            localStorage.setItem("mainNavSplitPx", String(Math.round(sidebar.getBoundingClientRect().width)));
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
        }
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
    });
}

function initDetailSplit() {
    const layout = document.getElementById("detail-split");
    const splitter = document.getElementById("detail-splitter");
    const left = document.getElementById("detail-col-left");
    if (!layout || !splitter || !left) return;

    function applySaved() {
        if (window.innerWidth <= 1100) {
            layout.style.gridTemplateColumns = "";
            return;
        }
        const saved = localStorage.getItem("detailSplitLeftPx");
        if (!saved) return;
        const w = Math.min(900, Math.max(220, parseInt(saved, 10) || 320));
        layout.style.gridTemplateColumns = `${w}px 8px 1fr`;
    }
    applySaved();

    splitter.addEventListener("mousedown", (e) => {
        e.preventDefault();
        if (window.innerWidth <= 1100) return;
        const startX = e.clientX;
        const startW = left.getBoundingClientRect().width;
        const layoutEl = layout;
        function onMove(ev) {
            const maxW = layoutEl.getBoundingClientRect().width - 240;
            const w = Math.min(maxW, Math.max(220, startW + ev.clientX - startX));
            layoutEl.style.gridTemplateColumns = `${Math.round(w)}px 8px 1fr`;
        }
        function onUp() {
            localStorage.setItem("detailSplitLeftPx", String(Math.round(left.getBoundingClientRect().width)));
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
        }
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
    });
}

function initReportPaneSplit() {
    const grid = document.getElementById("report-panes-grid");
    const splitter = document.getElementById("report-pane-splitter");
    const aside = grid?.querySelector(".report-sidebar");
    if (!grid || !splitter || !aside) return;

    function applySaved() {
        if (window.innerWidth <= 880) {
            grid.style.gridTemplateColumns = "";
            return;
        }
        const saved = localStorage.getItem("reportModalSplitPx");
        if (!saved) return;
        const w = Math.min(480, Math.max(180, parseInt(saved, 10) || 280));
        grid.style.gridTemplateColumns = `${w}px 8px 1fr`;
    }
    applySaved();

    splitter.addEventListener("mousedown", (e) => {
        e.preventDefault();
        if (window.innerWidth <= 880) return;
        const startX = e.clientX;
        const startW = aside.getBoundingClientRect().width;
        function onMove(ev) {
            const maxW = grid.getBoundingClientRect().width - 200;
            const w = Math.min(maxW, Math.max(180, startW + ev.clientX - startX));
            grid.style.gridTemplateColumns = `${Math.round(w)}px 8px 1fr`;
        }
        function onUp() {
            localStorage.setItem("reportModalSplitPx", String(Math.round(aside.getBoundingClientRect().width)));
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
        }
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
    });
}

/** 报告弹窗内嵌入 iframe 区域高度（横条上下拖动） */
function initReportViewerHeight() {
    const viewer = document.querySelector("#report-content .report-viewer");
    const handle = document.getElementById("report-iframe-h-resize");
    const iframe = viewer?.querySelector("iframe");
    if (!viewer || !handle || !iframe) return;

    const saved = localStorage.getItem("reportIframePx");
    if (saved) {
        const h = Math.min(900, Math.max(280, parseInt(saved, 10)));
        viewer.style.flex = "0 0 auto";
        viewer.style.height = `${h}px`;
        viewer.style.minHeight = "280px";
    }

    handle.addEventListener("mousedown", (e) => {
        e.preventDefault();
        const startY = e.clientY;
        const startH = viewer.getBoundingClientRect().height;
        function onMove(ev) {
            const nh = Math.min(900, Math.max(280, startH + ev.clientY - startY));
            viewer.style.flex = "0 0 auto";
            viewer.style.height = `${Math.round(nh)}px`;
            viewer.style.minHeight = "280px";
        }
        function onUp() {
            localStorage.setItem("reportIframePx", String(Math.round(viewer.getBoundingClientRect().height)));
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
        }
        document.body.style.cursor = "row-resize";
        document.body.style.userSelect = "none";
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
    });
}

function initRunsSplitter() {
    const layout = document.getElementById("runs-layout");
    const splitter = document.getElementById("runs-splitter");
    const listCol = document.getElementById("runs-col-list");
    if (!layout || !splitter || !listCol) return;

    if (window.innerWidth > 960) {
        const saved = localStorage.getItem("runsSplitPx");
        if (saved) {
            const w = Math.min(680, Math.max(200, parseInt(saved, 10) || 320));
            layout.style.gridTemplateColumns = `${w}px 8px 1fr`;
        }
    } else {
        layout.style.gridTemplateColumns = "";
    }

    splitter.addEventListener("mousedown", (e) => {
        e.preventDefault();
        if (window.innerWidth <= 960) return;
        const startX = e.clientX;
        const startW = listCol.getBoundingClientRect().width;
        function onMove(ev) {
            const w = Math.min(680, Math.max(200, startW + ev.clientX - startX));
            layout.style.gridTemplateColumns = `${Math.round(w)}px 8px 1fr`;
        }
        function onUp() {
            localStorage.setItem("runsSplitPx", String(Math.round(listCol.getBoundingClientRect().width)));
            document.removeEventListener("mousemove", onMove);
            document.removeEventListener("mouseup", onUp);
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
        }
        document.body.style.cursor = "col-resize";
        document.body.style.userSelect = "none";
        document.addEventListener("mousemove", onMove);
        document.addEventListener("mouseup", onUp);
    });
}

async function loadRuns() {
    const content = document.getElementById("main-content");
    const head =
        typeof renderModulePageHead === "function"
            ? renderModulePageHead("测试运行", "选中条目查看阶段、日志与用例表；结束后可打开完整报告。", "")
            : '<div class="section-title">测试运行 <span class="section-hint">选中条目查看阶段、日志与用例表</span></div>';
    content.innerHTML = `
<div class="module-page">
${head}
<div class="module-page-body runs-layout" id="runs-layout">
            <div class="runs-col-list" id="runs-col-list">
                <div class="run-list" id="run-list">${(typeof skeletonRows === "function") ? skeletonRows(4) : "加载中…"}</div>
            </div>
            <button type="button" class="runs-splitter" id="runs-splitter" aria-label="拖动调整左侧列表宽度" title="左右拖动调整宽度"></button>
            <div class="run-detail-panel" id="run-detail">
                <div class="run-detail-placeholder">在左侧选择一条运行记录，此处将显示阶段指标、活动日志与近期用例字段；结束后可打开完整报告。</div>
            </div>
        </div>
</div>`;

    try {
        const { data } = await apiFetch("/api/runs");
        const list = document.getElementById("run-list");
        const runs = data.runs || [];

        if (runs.length === 0) {
            list.innerHTML = emptyStateHtml(
                "尚无运行记录",
                "在某一项目中保存配置并发起运行后，将在此处出现队列与明细。"
            );
            document.getElementById("run-detail").innerHTML =
                '<div class="run-detail-placeholder">暂无运行记录</div>';
            initRunsSplitter();
            return;
        }

        list.innerHTML = runs
            .map((r) => {
                let statusClass = "";
                const ridEsc = r.run_id.replace(/'/g, "\\'");
                const actions = runListActionsHtml(r);

                if (r.status === "running" || r.status === "starting") {
                    statusClass = "status-running";
                } else if (runIsFailed(r) || r.status === "failed") {
                    statusClass = "status-failed";
                } else if (r.status === "stopped") {
                    statusClass = "status-stopped";
                } else if (r.status === "completed" || r.status === "passed") {
                    statusClass =
                        r.pass_rate != null && Number(r.pass_rate) < 80
                            ? "status-failed"
                            : "status-completed";
                }

                const rid = r.run_id || "";
                const ridTitle = escapeHtml(rid);
                const ridShort = truncateRunIdForList(rid);
                const chip = runListStatusChip(r);

                const detailLine = r.is_running
                    ? `${escapeHtml(r.current_step || "运行中")} · 进度 ${r.progress ?? 0}%${r.planned_cases ? ` · 计划 ${r.planned_cases} · 调用 ${r.invoke_completed ?? 0}/${r.planned_cases} · 评判 ${r.evaluate_completed ?? 0}/${r.planned_cases}` : ""}`
                    : `通过率: ${(r.pass_rate || 0).toFixed(1)}% · 样本: ${r.total_cases || 0}`;

                const sel = selectedRunId === r.run_id ? " selected" : "";

                return `
                <div class="run-item${sel}" data-run-id="${escapeHtml(r.run_id)}" onclick="selectRunForDetail('${ridEsc}')">
                    <div class="run-item-top">
                        <div class="run-status ${statusClass}"></div>
                        <div class="run-info">
                            <div class="run-title-line">${escapeHtml(r.project_name || "未命名项目")}</div>
                            <div class="run-id-line" title="${ridTitle}">${ridShort}</div>
                            <div class="run-chip-row">${chip}</div>
                            <div class="detail">${detailLine}</div>
                        </div>
                        <div class="run-actions">${actions}</div>
                    </div>
                    ${
                        r.is_running
                            ? `<div class="run-item-progress"><div class="progress-bar"><div class="progress-fill" style="width: ${r.progress || 0}%"></div></div></div>`
                            : ""
                    }
                </div>`;
            })
            .join("");

        if (selectedRunId) {
            const still = runs.some((r) => r.run_id === selectedRunId);
            if (!still) {
                selectedRunId = null;
                document.getElementById("run-detail").innerHTML =
                    '<div class="run-detail-placeholder">请选择左侧运行条目</div>';
            } else {
                document.querySelectorAll(".run-item").forEach((el) => {
                    el.classList.toggle("selected", el.getAttribute("data-run-id") === selectedRunId);
                });
                await refreshRunDetail();
            }
        }
        initRunsSplitter();
    } catch (e) {
        content.innerHTML = `<div class="error">加载失败: ${escapeHtml(e.message)}</div>`;
    }
}

function updateRunningTests(tests) {
    if (currentSection !== "runs" || !tests) return;

    tests.forEach((test) => {
        const rid = test.run_id;
        const st = test.status;
        const item = Array.from(document.querySelectorAll("[data-run-id]")).find(
            (el) => el.getAttribute("data-run-id") === rid
        );
        if (!item) return;
        const isRunning = st === "running" || st === "starting";
        const statusDiv = item.querySelector(".run-status");
        const detailDiv = item.querySelector(".run-info .detail");
        const chipRow = item.querySelector(".run-chip-row");
        const actionsDiv = item.querySelector(".run-actions");
        const progressWrap = item.querySelector(".run-item-progress");
        const progressBar = item.querySelector(".progress-fill");

        if (statusDiv) {
            statusDiv.className = "run-status ";
            if (isRunning) statusDiv.className += "status-running";
            else if (runIsFailed(test) || st === "failed") statusDiv.className += "status-failed";
            else if (st === "completed" || st === "passed") statusDiv.className += "status-completed";
            else if (st === "stopped") statusDiv.className += "status-stopped";
        }
        if (chipRow) {
            chipRow.innerHTML = runListStatusChip({ ...test, is_running: isRunning });
        }
        if (actionsDiv) {
            actionsDiv.innerHTML = runListActionsHtml({ ...test, is_running: isRunning });
        }
        if (detailDiv) {
            const plan = test.planned_cases;
            const inv = test.invoke_completed;
            const ev = test.evaluate_completed;
            if (isRunning) {
                const extra = plan
                    ? ` · 计划 ${plan} · 调用 ${inv ?? 0}/${plan} · 评判 ${ev ?? 0}/${plan}`
                    : "";
                detailDiv.textContent = `${test.current_step || ""} · 进度 ${test.progress ?? 0}%${extra}`;
            } else if (test.pass_rate != null) {
                detailDiv.textContent = `通过率: ${Number(test.pass_rate).toFixed(1)}% · 样本: ${test.total_cases || 0}`;
            } else {
                detailDiv.textContent = test.current_step || "";
            }
        }
        if (isRunning) {
            if (!progressWrap) {
                const top = item.querySelector(".run-item-top");
                if (top) {
                    const div = document.createElement("div");
                    div.className = "run-item-progress";
                    div.innerHTML =
                        '<div class="progress-bar"><div class="progress-fill" style="width:0%"></div></div>';
                    item.appendChild(div);
                }
            }
            const bar = item.querySelector(".progress-fill");
            if (bar) bar.style.width = `${test.progress ?? 0}%`;
        } else if (progressWrap) {
            progressWrap.remove();
        }
    });

    if (selectedRunId) {
        const live = tests.find((t) => t.run_id === selectedRunId);
        if (live) {
            const fp = computeRunDetailFingerprint(live);
            if (fp !== lastRunDetailFingerprint) {
                renderRunDetail(live);
            }
        }
    }
}

async function stopRun(runId) {
    if (!confirm("确定要停止这个测试吗？")) return;

    try {
        await apiFetch(`/api/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
        loadRuns();
    } catch (e) {
        alert("停止失败: " + e.message);
    }
}

async function deleteRunRecord(runId) {
    if (
        !confirm(
            "确定删除该条运行记录？将删除 web_results 下对应目录（含 HTML/JSON 报告），且不可恢复。"
        )
    ) {
        return;
    }
    try {
        await apiFetch(`/api/runs/${encodeURIComponent(runId)}/history`, { method: "DELETE" });
        if (selectedRunId === runId) {
            selectedRunId = null;
            const panel = document.getElementById("run-detail");
            if (panel) {
                panel.innerHTML =
                    '<div class="run-detail-placeholder">请选择左侧运行条目</div>';
            }
        }
        loadRuns();
        if (typeof loadStats === "function") loadStats();
    } catch (e) {
        alert("删除失败: " + e.message);
    }
}

async function viewReport(runId) {
    try {
        const { data } = await apiFetch(`/api/runs/${encodeURIComponent(runId)}/report`);
        const content = document.getElementById("report-content");

        if (data.is_running) {
            const events = data.events || [];
            const eventsHtml = buildActivityFeedHtml(events, "暂无过程记录。");
            content.innerHTML = `
                <div class="report-modal-inner">
                <div class="report-running-panel">
                <div class="detail-head" style="margin-bottom:12px">
                  <h3 style="margin:0">本次运行尚未结束</h3>
                  <div class="sub">${escapeHtml(data.run_id || runId)}</div>
                </div>
                <div class="meta-grid" style="margin-bottom:12px">
                  <div class="meta-tile"><div class="label">当前阶段</div><div class="val sm">${escapeHtml(phaseLabelForPm(data.phase))}</div></div>
                  <div class="meta-tile"><div class="label">进度</div><div class="val">${escapeHtml(String(data.progress ?? 0))}%</div></div>
                  <div class="meta-tile"><div class="label">计划条数</div><div class="val">${escapeHtml(String(data.planned_cases ?? 0))}</div></div>
                  <div class="meta-tile"><div class="label">调用 / 评判</div><div class="val sm">${escapeHtml(String(data.invoke_completed ?? 0))} / ${escapeHtml(String(data.evaluate_completed ?? 0))}</div></div>
                </div>
                <p class="report-running-step">${escapeHtml(data.current_step || "")}</p>
                <div class="detail-block">
                  <h4>运行过程（通俗说明）</h4>
                  <p class="activity-intro">面向业务同学的说明；技术人员可展开每条下方的「技术明细」。</p>
                  <div class="event-log event-log--friendly" style="max-height:340px">${eventsHtml}</div>
                </div>
                <p class="report-run-hint">在「测试运行」页选中该任务可看用例表与更多指标。</p>
                </div></div>`;
        } else {
            const passed = reportStatusPassed(data.status);
            const pillClass = passed ? "report-status-pill report-status-pill--ok" : "report-status-pill report-status-pill--bad";
            const statusLabel = passed ? "通过" : "失败";

            let html = `
                <div class="report-modal-inner">
                <div class="report-page">
                    <div class="report-hero-strip">
                        <div>
                            <p class="report-hero-label">测试摘要</p>
                            <h3 class="report-hero-project">${escapeHtml(data.project_name || "")}</h3>
                            <p class="report-hero-runid">运行 <code>${escapeHtml(String(data.run_id || runId))}</code></p>
                        </div>
                        <div class="${pillClass}" role="status">${statusLabel}</div>
                    </div>
                    <div class="report-main-grid report-container" id="report-panes-grid">
                        <aside class="report-sidebar" aria-label="指标概要">
                            <p class="report-sidebar-title">关键指标</p>
                            <ul class="report-kpi-list">
                                <li><span class="lbl">总样本</span><span class="val">${escapeHtml(String(data.total_cases ?? 0))}</span></li>
                                <li><span class="lbl">通过</span><span class="val val--ok">${escapeHtml(String(data.passed_cases ?? 0))}</span></li>
                                <li><span class="lbl">失败</span><span class="val val--bad">${escapeHtml(String(data.failed_cases ?? 0))}</span></li>
                                <li><span class="lbl">通过率</span><span class="val">${Number(data.pass_rate ?? 0).toFixed(1)}%</span></li>
                            </ul>
                        </aside>
                        <button type="button" class="report-pane-splitter" id="report-pane-splitter" aria-label="拖动调整摘要与报告区宽度" title="左右拖动调整宽度"></button>
                        <div class="report-iframe-panel">
                            <div class="report-iframe-bar">
                                <span>嵌入：完整 HTML 报告（下方横条可上下拉长）</span>
                            </div>
                            <div class="report-viewer">
                        ${
                            data.html_url
                                ? `<iframe title="测试报告" src="${escapeHtml(data.html_url)}"></iframe>`
                                : '<p style="padding:40px;text-align:center;color:var(--text-muted)">HTML 报告不可用</p>'
                        }
                            </div>
                            ${
                                data.html_url
                                    ? '<div class="report-h-resize" id="report-iframe-h-resize" role="separator" aria-orientation="horizontal" aria-label="上下拖动调整嵌入报告高度"></div>'
                                    : ""
                            }
                        </div>
                    </div>`;

            const reportDimNames = dimensionNamesFromReport(data);
            if (data.dimension_stats && data.dimension_stats.length > 0) {
                html += `<div class="report-section-block"><h3 class="report-block-title">维度统计</h3><div class="dimension-cards">`;
                data.dimension_stats.forEach((stat) => {
                    const pr = Number(stat.pass_rate ?? 0);
                    const good = pr >= 80;
                    const dimTitle = stat.dimension_name || dimensionDisplayLabel(reportDimNames, stat.dimension_id);
                    html += `
                        <div class="dim-card">
                            <h4>${escapeHtml(dimTitle)}</h4>
                            <div class="dim-metric"><span>通过率</span>
                                <span class="value" style="color: ${good ? "var(--accent)" : "var(--danger)"}">
                                    ${pr.toFixed(1)}%
                                </span>
                            </div>
                            <div class="dim-metric"><span>平均分</span><span class="value">${Number(stat.avg_score ?? 0).toFixed(2)}</span></div>
                            <div class="dim-metric"><span>样本数</span><span class="value">${escapeHtml(String(stat.total_cases ?? 0))}</span></div>
                        </div>`;
                });
                html += "</div>";
                html += `<div class="report-chart-wrap"><h3>维度通过率</h3><canvas id="dim-pass-chart" height="120"></canvas></div></div>`;
            }

            if (data.recommendations && data.recommendations.length > 0) {
                html += `<div class="report-section-block"><h3 class="report-block-title">改进建议</h3><ul class="report-rec-list">`;
                data.recommendations.forEach((r) => {
                    html += `<li>${escapeHtml(r)}</li>`;
                });
                html += "</ul></div>";
            }

            html += `</div></div>`;
            content.innerHTML = html;

            initReportPaneSplit();
            initReportViewerHeight();

            if (typeof Chart !== "undefined" && data.dimension_stats && data.dimension_stats.length > 0) {
                requestAnimationFrame(() => {
                    const canvas = document.getElementById("dim-pass-chart");
                    if (!canvas) return;
                    if (window.__dimPassChart) {
                        window.__dimPassChart.destroy();
                        window.__dimPassChart = null;
                    }
                    const labels = data.dimension_stats.map(
                        (s) => s.dimension_name || dimensionDisplayLabel(reportDimNames, s.dimension_id)
                    );
                    const rates = data.dimension_stats.map((s) => Number(s.pass_rate ?? 0));
                    const okFill = "rgba(13, 92, 86, 0.78)";
                    const badFill = "rgba(163, 32, 32, 0.72)";
                    window.__dimPassChart = new Chart(canvas, {
                        type: "bar",
                        data: {
                            labels,
                            datasets: [
                                {
                                    label: "通过率 %",
                                    data: rates,
                                    backgroundColor: rates.map((v) => (v >= 80 ? okFill : badFill)),
                                    borderColor: rates.map((v) => (v >= 80 ? "rgba(13, 92, 86, 0.95)" : "rgba(163, 32, 32, 0.9)")),
                                    borderWidth: 1,
                                },
                            ],
                        },
                        options: {
                            responsive: true,
                            plugins: { legend: { display: false } },
                            scales: {
                                y: { beginAtZero: true, max: 100 },
                            },
                        },
                    });
                });
            }
        }

        document.getElementById("report-modal").classList.add("active");
    } catch (e) {
        alert("加载报告失败: " + e.message);
    }
}

function downloadReport() {
    const iframe = document.querySelector(".report-viewer iframe");
    if (iframe && iframe.src) window.open(iframe.src, "_blank");
}

async function loadExamples() {
    const content = document.getElementById("main-content");
    const head =
        typeof renderModulePageHead === "function"
            ? renderModulePageHead("示例配置", "从仓库内置 YAML 模板快速体验，可直接运行或复制修改。", "")
            : '<div class="section-title">示例配置</div>';
    const _exSkeleton = (typeof skeletonProjectCards === "function") ? skeletonProjectCards(3) : "加载中…";
    content.innerHTML = `<div class="module-page">${head}<div class="module-page-body project-list" id="example-list">${_exSkeleton}</div></div>`;

    try {
        const { data } = await apiFetch("/api/projects");
        const examples = (data.projects || []).filter((p) => p.is_example);
        const list = document.getElementById("example-list");

        if (examples.length === 0) {
            list.innerHTML = emptyStateHtml(
                "未发现示例 YAML",
                '请在仓库中保留 <code style="font-size:12px">examples/*.yaml</code>，并从项目根目录启动服务。'
            );
            return;
        }

        list.innerHTML = examples
            .map((p) => {
                const idEsc = p.id.replace(/'/g, "\\'");
                return `
            <div class="project-card project-card--example project-card--flat">
                <div class="project-card-inner">
                    <div class="project-card-icon" aria-hidden="true">
                        <div class="project-card-icon-inner">${UI_ICONS.template}</div>
                    </div>
                    <div class="project-card-body">
                        <div class="name">${escapeHtml(p.name)}</div>
                        <div class="desc">${escapeHtml(p.description || "")}</div>
                        <div class="meta">
                            <span class="badge badge--example">示例</span>
                        </div>
                        <div class="project-card-actions">
                            <button type="button" class="btn btn-primary" style="width:auto;margin:0;padding:8px 14px;font-size:13px"
                                onclick="useExample('${idEsc}')">打开配置</button>
                            <button type="button" class="btn btn-run" onclick="runExampleDirect('${idEsc}')">${UI_ICONS.play}直接运行</button>
                        </div>
                    </div>
                </div>
            </div>`;
            })
            .join("");
    } catch (e) {
        content.innerHTML = `<div class="error">加载失败: ${escapeHtml(e.message)}</div>`;
    }
}

async function useExample(exampleId) {
    try {
        const { data } = await apiFetch(`/api/projects/${encodeURIComponent(exampleId)}`);
        const yamlText = data.config_yaml || "";
        document.getElementById("new-project-config").value = yamlText;
        if (typeof setConfigEditorMode === "function") {
            setConfigEditorMode("create", "form");
        } else {
            document.getElementById("create-tab-form").classList.add("active");
            document.getElementById("create-tab-yaml").classList.remove("active");
            document.getElementById("create-panel-form").style.display = "block";
            document.getElementById("create-panel-yaml").style.display = "none";
            if (typeof refreshFormFromYaml === "function") {
                try {
                    refreshFormFromYaml("create");
                } catch (e) {
                    alert("示例 YAML 解析失败，已切换到 YAML 原文: " + e.message);
                    if (typeof openConfigEditorYaml === "function") openConfigEditorYaml("create");
                }
            }
        }
        showModal("create-modal");
    } catch (e) {
        alert("加载示例失败: " + e.message);
    }
}

async function runExampleDirect(exampleId) {
    try {
        const { data: projectData } = await apiFetch(
            `/api/projects/${encodeURIComponent(exampleId)}`
        );
        const { data: runData } = await apiFetch("/api/runs", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ config_path: projectData.config_path }),
        });
        if (runData.success) {
            showSection("runs");
            if (typeof setApiStatus === "function") {
                setApiStatus(`示例任务已启动: ${runData.run_id}`, "ok");
            }
            alert("示例测试已启动，请到「测试运行」查看进度。");
        }
    } catch (e) {
        alert("启动示例失败: " + e.message);
    }
}

function showModal(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.add("active");
    el.setAttribute("aria-hidden", "false");
}

function hideModal(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove("active");
    el.setAttribute("aria-hidden", "true");
}

function showCreateModal() {
    if (typeof resetCreateConfigEditor === "function") resetCreateConfigEditor();
    else {
        document.getElementById("new-project-config").value = "";
    }
    showModal("create-modal");
}

async function createProject() {
    let config;
    let name = "";
    try {
        if (typeof getMergedYamlForSubmit === "function") {
            config = getMergedYamlForSubmit("create");
            const obj = yamlLib().load(config);
            if (obj && obj.meta && obj.meta.name) name = String(obj.meta.name).trim();
        } else {
            config = document.getElementById("new-project-config").value.trim();
            const obj = yamlLib().load(config);
            if (obj && obj.meta && obj.meta.name) name = String(obj.meta.name).trim();
        }
    } catch (e) {
        alert(e.message || String(e));
        return;
    }

    const nameInput = document.getElementById("create-meta-name");
    if (!name && nameInput) name = nameInput.value.trim();
    if (!name) {
        alert("请填写套件名称（表单第一项或 YAML 里 meta.name）");
        return;
    }
    if (!config) {
        alert("配置为空");
        return;
    }

    try {
        const { data } = await apiFetch("/api/projects", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, config_yaml: config }),
        });

        if (data.success) {
            hideModal("create-modal");
            showSection("projects");
            if (typeof showToast === "function") showToast("项目创建成功", "success");
            else alert("项目创建成功！");
        }
    } catch (e) {
        if (typeof showToast === "function") showToast("创建失败：" + e.message, "error");
        else alert("创建失败: " + e.message);
    }
}

async function deleteProject(projectId) {
    if (!confirm("确定要删除这个项目吗？仅删除本地保存的 YAML 配置，不会删除历史运行报告。")) return;
    try {
        await apiFetch(`/api/projects/${encodeURIComponent(projectId)}`, { method: "DELETE" });
        if (currentProjectId === projectId) {
            currentProjectId = null;
            hideModal("edit-modal");
        }
        loadProjects();
        loadStats();
        if (typeof showToast === "function") showToast("项目已删除", "success");
    } catch (e) {
        if (typeof showToast === "function") showToast("删除失败：" + e.message, "error");
        else alert("删除失败: " + e.message);
    }
}

/** 仅在遮罩上按下并松开时才关闭，避免拖选文字松手误关弹窗 */
let _modalOverlayMouseDown = false;

document.addEventListener("mousedown", (e) => {
    _modalOverlayMouseDown = !!(e.target.classList && e.target.classList.contains("modal-overlay"));
});

document.addEventListener("click", (e) => {
    if (e.target.classList && e.target.classList.contains("modal-overlay")) {
        if (_modalOverlayMouseDown) {
            e.target.classList.remove("active");
        }
    }
    _modalOverlayMouseDown = false;
});
