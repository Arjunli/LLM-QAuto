/**
 * 用例设计助手 — 多轮聊天 UI（与 API 质检配置助手同模式）
 */
(function () {
    const STORAGE_KEY = "llm-qauto-case-assistant-v1";
    const CHAT_API = "/api/cases/chat";

    let messages = [];
    let collected = {};
    let lastResponse = null;
    let pendingDraft = null;
    let sending = false;
    let composeAttachments = null;

    const FIELD_LABELS = {
        title: "会话标题",
        prd_text: "需求正文",
        scope: "覆盖范围",
        priority_focus: "重点优先级",
        excluded: "排除范围",
    };

    const AVATAR_BOT =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
    const AVATAR_USER =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';
    const ICON_SEND =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>';
    const ICON_CHECK =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>';

    function toast(msg, err) {
        if (window.PlatformChat) PlatformChat.showToast(msg, err);
    }

    function renderMd(text) {
        return PlatformChat ? PlatformChat.renderMarkdownLite(text) : escapeHtml(text || "");
    }

    function truncate(s, n) {
        s = String(s || "");
        return s.length <= n ? s : s.slice(0, n) + "…";
    }

    function formatUserContent(text, images, imageCount) {
        const raw = String(text || "");
        let html = "";
        if (raw.length > 300 || raw.split("\n").length > 8) {
            html = `<details class="assistant-curl-block"><summary>已粘贴需求 <span class="assistant-curl-meta">${escapeHtml(truncate(raw.replace(/\s+/g, " "), 80))}</span></summary><pre class="assistant-curl-pre">${escapeHtml(raw)}</pre></details>`;
        } else {
            html = escapeHtml(raw).replace(/\n/g, "<br>");
        }
        if (images?.length && PlatformChat) html += PlatformChat.renderMessageImagesHtml(images, false);
        else if (imageCount > 0) html += `<div class="assistant-msg-image-badge">📎 ${imageCount} 张截图</div>`;
        return html;
    }

    function saveState() {
        try {
            if (!messages.length) {
                localStorage.removeItem(STORAGE_KEY);
                return;
            }
            localStorage.setItem(
                STORAGE_KEY,
                JSON.stringify({
                    version: 1,
                    messages: messages.map((m) => ({ role: m.role, content: m.content, image_count: m.image_count || 0 })),
                    collected,
                    lastResponse,
                    pendingDraft,
                    updatedAt: Date.now(),
                })
            );
            renderHistoryMeta();
        } catch (e) {
            toast("聊天记录过大，无法保存到本地", true);
        }
    }

    function loadState() {
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (!raw) return false;
            const data = JSON.parse(raw);
            if (!data?.messages?.length) return false;
            messages = data.messages;
            collected = data.collected || {};
            lastResponse = data.lastResponse || null;
            pendingDraft = data.pendingDraft || null;
            return true;
        } catch (e) {
            localStorage.removeItem(STORAGE_KEY);
            return false;
        }
    }

    function scrollBottom() {
        const el = document.getElementById("case-asst-messages");
        if (el) PlatformChat.scrollToBottom(el);
    }

    function setBusy(busy) {
        sending = busy;
        const compose = document.querySelector(".case-asst-compose");
        const input = document.getElementById("case-asst-input");
        const btn = document.getElementById("case-asst-send");
        if (compose) compose.classList.toggle("is-busy", busy);
        if (input) input.disabled = busy;
        if (btn) btn.disabled = busy;
        document.querySelectorAll("#case-asst-messages .assistant-msg-chip, #case-asst-messages .assistant-msg-btn").forEach((b) => {
            b.disabled = busy;
        });
    }

    function showTyping() {
        const wrap = document.getElementById("case-asst-messages");
        if (!wrap || document.getElementById("case-asst-typing")) return;
        const row = document.createElement("div");
        row.id = "case-asst-typing";
        row.className = "assistant-typing";
        row.innerHTML = `<div class="assistant-avatar assistant-avatar--bot">${AVATAR_BOT}</div><div class="assistant-typing-dots"><span></span><span></span><span></span></div>`;
        wrap.appendChild(row);
        scrollBottom();
    }

    function hideTyping() {
        document.getElementById("case-asst-typing")?.remove();
    }

    function markdownTableToHtml(md) {
        const lines = (md || "").split("\n").filter((l) => l.trim().startsWith("|"));
        if (lines.length < 2) return `<pre class="cfg-wizard-summary">${escapeHtml(md || "")}</pre>`;
        let html = "<table class='case-table'><thead><tr>";
        lines[0].split("|").filter(Boolean).forEach((c) => (html += `<th>${escapeHtml(c.trim())}</th>`));
        html += "</tr></thead><tbody>";
        for (let i = 2; i < lines.length; i++) {
            const cells = lines[i].split("|").filter(Boolean).map((c) => c.trim());
            html += "<tr>" + cells.map((c) => `<td>${escapeHtml(c)}</td>`).join("") + "</tr>";
        }
        return html + "</tbody></table>";
    }

    function appendBubble(role, content, extras) {
        const wrap = document.getElementById("case-asst-messages");
        if (!wrap) return;
        wrap.querySelector(".assistant-messages-empty")?.remove();

        const row = document.createElement("div");
        row.className = `assistant-msg-row assistant-msg-row--${role}`;
        row.innerHTML = `<div class="assistant-avatar assistant-avatar--${role === "user" ? "user" : "bot"}">${role === "user" ? AVATAR_USER : AVATAR_BOT}</div>`;
        const col = document.createElement("div");
        col.className = "assistant-msg-col";
        const body = document.createElement("div");
        body.className = "assistant-msg-body";
        body.innerHTML = role === "assistant" ? renderMd(content) : formatUserContent(content, extras?.images, extras?.imageCount);
        col.appendChild(body);

        if (role === "assistant" && extras) {
            if (extras.quickReplies?.length) {
                const label = document.createElement("div");
                label.className = "assistant-msg-label";
                label.textContent = "快捷回复";
                col.appendChild(label);
                const chips = document.createElement("div");
                chips.className = "assistant-msg-chips";
                extras.quickReplies.slice(0, 6).forEach((q) => {
                    const btn = document.createElement("button");
                    btn.type = "button";
                    btn.className = "assistant-msg-chip";
                    btn.textContent = q;
                    btn.onclick = () => sendCaseAssistantMessage(q);
                    chips.appendChild(btn);
                });
                col.appendChild(chips);
            }
            if (extras.actions?.length) {
                const label = document.createElement("div");
                label.className = "assistant-msg-label";
                label.textContent = "下一步";
                col.appendChild(label);
                const act = document.createElement("div");
                act.className = "assistant-msg-actions";
                extras.actions.forEach((a) => {
                    const btn = document.createElement("button");
                    btn.type = "button";
                    btn.className = a.primary ? "assistant-msg-btn assistant-msg-btn--primary" : "assistant-msg-btn assistant-msg-btn--ghost";
                    btn.textContent = a.label;
                    btn.onclick = a.onClick;
                    act.appendChild(btn);
                });
                col.appendChild(act);
            }
        }
        row.appendChild(col);
        wrap.appendChild(row);
        scrollBottom();
    }

    function buildExtras(data) {
        const actions = [];
        if (data.phase === "ready" && data.case_table_markdown) {
            pendingDraft = {
                title: data.title || collected.title,
                input_text: collected.prd_text || "",
                assumptions: data.assumptions,
                mermaid_review: data.mermaid_review,
                mermaid_tree: data.mermaid_tree,
                case_table_markdown: data.case_table_markdown,
                message: data.message,
            };
            actions.push({ label: "保存到服务端", primary: true, onClick: saveCaseAssistantDraft });
            actions.push({ label: "查看已保存", onClick: () => showModuleSection("case_design", "sessions") });
        }
        return { quickReplies: data.quick_replies || [], actions };
    }

    function computeSteps(phase) {
        const hasPrd = !!(collected.prd_text || "").trim();
        const ready = phase === "ready" && pendingDraft?.case_table_markdown;
        return [
            { label: "粘贴 PRD / AC", detail: hasPrd ? truncate(collected.prd_text.replace(/\s+/g, " "), 40) : "需求或验收标准", done: hasPrd, active: !hasPrd },
            { label: "补全范围与优先级", detail: collected.scope || collected.priority_focus || "可选追问", done: hasPrd && userTurns() >= 1, active: hasPrd && !ready },
            { label: "生成测试树与用例表", detail: ready ? "已生成" : "回复「生成用例」", done: ready, active: ready },
        ];
    }

    function userTurns() {
        return messages.filter((m) => m.role === "user").length;
    }

    function updateProgress(data) {
        const panel = document.getElementById("case-asst-panel");
        if (!panel) return;
        const phase = data?.phase || lastResponse?.phase || "collecting";
        const missing = data?.missing || lastResponse?.missing || [];
        const steps = computeSteps(phase);

        const stepsHtml = steps
            .map((s, i) => {
                const cls = [s.done ? "is-done" : "", s.active && !s.done ? "is-active" : "", !s.done && !s.active ? "is-pending" : ""].filter(Boolean).join(" ");
                return `<li class="assistant-step ${cls}"><div class="assistant-step-marker">${s.done ? "✓" : i + 1}</div><div class="assistant-step-body"><div class="assistant-step-label">${escapeHtml(s.label)}</div><div class="assistant-step-detail">${escapeHtml(s.detail)}</div></div></li>`;
            })
            .join("");

        const rows = ["title", "prd_text", "scope"]
            .map((key) => {
                const val = collected[key];
                const label = FIELD_LABELS[key] || key;
                let display = "待填写";
                let cls = "is-miss";
                if (val) {
                    display = key === "prd_text" ? truncate(String(val).replace(/\s+/g, " "), 32) : String(val);
                    cls = "is-ok";
                } else if (missing.includes(key)) display = "仍缺";
                return `<div class="assistant-collected-row"><span class="assistant-collected-key">${escapeHtml(label)}</span><span class="assistant-collected-val ${cls}">${escapeHtml(display)}</span></div>`;
            })
            .join("");

        let preview = "";
        if (phase === "ready" && pendingDraft) {
            preview = `<div class="case-asst-preview">
<h4>用例预览</h4>
<div class="case-asst-diagrams">
  <div class="case-asst-diagram-block"><div class="case-asst-diagram-label">评审概览</div><div id="case-asst-mermaid-review" class="case-mermaid-canvas case-mermaid-canvas--compact"></div></div>
  <div class="case-asst-diagram-block"><div class="case-asst-diagram-label">覆盖树</div><div id="case-asst-mermaid-tree" class="case-mermaid-canvas case-mermaid-canvas--compact"></div></div>
</div>
<div class="case-asst-table-wrap">${markdownTableToHtml(pendingDraft.case_table_markdown || "")}</div>
</div>`;
        }

        const banner = phase === "ready" && pendingDraft ? `<div class="assistant-ready-banner">${ICON_CHECK}<span>用例已生成，可保存或导出</span></div>` : "";

        panel.innerHTML = `<div class="assistant-progress-title">设计进度</div><ul class="assistant-steps">${stepsHtml}</ul>${banner}<div class="assistant-collected-card"><h4>已收集</h4>${rows}</div>${preview}<div id="case-asst-history-meta" class="assistant-history-meta"></div>`;
        renderHistoryMeta();
        if (phase === "ready" && pendingDraft && window.CaseMermaid) {
            CaseMermaid.renderCaseDiagrams(
                document.getElementById("case-asst-mermaid-review"),
                document.getElementById("case-asst-mermaid-tree"),
                pendingDraft.mermaid_review,
                pendingDraft.mermaid_tree,
                {
                    title: pendingDraft.title,
                    caseTable: pendingDraft.case_table_markdown,
                }
            );
        }
    }

    function renderHistoryMeta() {
        const el = document.getElementById("case-asst-history-meta");
        if (!el) return;
        let savedAt = null;
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (raw) savedAt = JSON.parse(raw)?.updatedAt;
        } catch (e) {
            savedAt = null;
        }
        const count = messages.length;
        const timeLabel = savedAt ? new Date(savedAt).toLocaleString() : "";
        el.innerHTML = count
            ? `<span class="assistant-history-meta-text">${count} 条消息${timeLabel ? ` · 保存于 ${escapeHtml(timeLabel)}` : ""}</span><button type="button" class="assistant-history-delete" onclick="deleteCaseAssistantHistory()">删除记录</button>`
            : `<span class="assistant-history-meta-text">暂无本地记录</span>`;
    }

    function handleResponse(data) {
        lastResponse = data;
        collected = data.collected || collected;
        if (data.phase === "ready") {
            pendingDraft = {
                title: data.title || collected.title,
                input_text: collected.prd_text || "",
                assumptions: data.assumptions,
                mermaid_review: data.mermaid_review,
                mermaid_tree: data.mermaid_tree,
                case_table_markdown: data.case_table_markdown,
                message: data.message,
            };
        }
        messages.push({ role: "assistant", content: data.message });
        appendBubble("assistant", data.message, buildExtras(data));
        updateProgress(data);
        saveState();
    }

    async function sendCaseAssistantMessage(text, patch) {
        const input = document.getElementById("case-asst-input");
        const msg = (text != null ? String(text) : input?.value?.trim() || "").trim();
        const attachPayload = composeAttachments ? composeAttachments.getPayload() : [];
        const attachItems = composeAttachments ? composeAttachments.getItems() : [];
        if ((!msg && !attachPayload.length) || sending) return;

        setBusy(true);
        if (input && text == null) {
            input.value = "";
            input.style.height = "auto";
        }
        if (patch) collected = { ...collected, ...patch };
        if (msg.length > 80 && !collected.prd_text) collected = { ...collected, prd_text: msg };

        messages.push({
            role: "user",
            content: msg || "[截图]",
            image_count: attachPayload.length,
            _images: attachItems,
        });
        appendBubble("user", msg || "[截图]", { images: attachItems, imageCount: attachPayload.length });
        updateProgress({ collected, phase: "collecting" });
        saveState();
        showTyping();

        try {
            const body = {
                messages: messages.map((m) => ({ role: m.role, content: m.content })),
                collected,
                attachments: attachPayload,
            };
            if (patch) body.patch = patch;
            const { data } = await apiFetch(CHAT_API, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            hideTyping();
            handleResponse(data);
            if (composeAttachments) composeAttachments.clear();
        } catch (e) {
            hideTyping();
            appendBubble("assistant", "请求失败：" + (e.message || String(e)), {
                actions: [{ label: "重新提问", onClick: () => resetCaseAssistant(false) }],
            });
            toast("发送失败", true);
        } finally {
            setBusy(false);
            input?.focus();
        }
    }

    async function saveCaseAssistantDraft() {
        if (!pendingDraft?.case_table_markdown) {
            toast("暂无已生成的用例", true);
            return;
        }
        try {
            const { data } = await apiFetch("/api/cases/sessions", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(pendingDraft),
            });
            pendingDraft = data.session;
            toast("已保存");
            updateProgress(lastResponse || { phase: "ready", collected });
        } catch (e) {
            toast(e.message, true);
        }
    }

    async function loadWelcome() {
        showTyping();
        try {
            const { data } = await apiFetch(CHAT_API, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ messages: [], collected: {} }),
            });
            hideTyping();
            collected = data.collected || {};
            lastResponse = data;
            messages.push({ role: "assistant", content: data.message });
            appendBubble("assistant", data.message, buildExtras(data));
            updateProgress(data);
            saveState();
        } catch (e) {
            hideTyping();
            appendBubble("assistant", "无法连接用例助手 API。\n\n" + (e.message || ""), {});
            saveState();
        }
    }

    function resetCaseAssistant(skipConfirm) {
        if (!skipConfirm && messages.length && !confirm("清空当前对话并重新开始？")) return;
        messages = [];
        collected = {};
        lastResponse = null;
        pendingDraft = null;
        localStorage.removeItem(STORAGE_KEY);
        const wrap = document.getElementById("case-asst-messages");
        if (wrap) wrap.innerHTML = `<div class="assistant-messages-empty"><div class="assistant-welcome-card">${AVATAR_BOT}<p>正在连接…</p></div></div>`;
        updateProgress({ collected: {}, phase: "collecting" });
        loadWelcome();
    }

    function deleteCaseAssistantHistory() {
        if (!localStorage.getItem(STORAGE_KEY) && !messages.length) {
            toast("暂无聊天记录");
            return;
        }
        if (!confirm("确定删除本地保存的聊天记录？")) return;
        resetCaseAssistant(true);
        toast("聊天记录已删除");
    }

    function restoreMessages() {
        const wrap = document.getElementById("case-asst-messages");
        if (!wrap) return;
        wrap.innerHTML = "";
        messages.forEach((m, idx) => {
            const isLast = m.role === "assistant" && idx === messages.length - 1;
            appendBubble(
                m.role,
                m.content,
                m.role === "user"
                    ? { images: m._images, imageCount: m.image_count || 0 }
                    : isLast && lastResponse
                      ? buildExtras(lastResponse)
                      : null
            );
        });
        updateProgress(lastResponse || { collected, phase: "collecting" });
    }

    function loadCaseAssistant() {
        const head = typeof renderModulePageHead === "function"
            ? renderModulePageHead(
                  "用例助手",
                  "粘贴 PRD 或验收标准，追问缺口后生成 Mermaid 测试树与用例表。",
                  `<button type="button" class="btn btn-secondary btn-sm" onclick="resetCaseAssistant()">新对话</button>
<button type="button" class="btn btn-secondary btn-sm assistant-btn-danger" onclick="deleteCaseAssistantHistory()">删除记录</button>`
              )
            : "";
        const content = document.getElementById("main-content");
        content.innerHTML = `
<div class="module-page module-page--assistant">
${head}
<div class="assistant-shell">
  <div class="assistant-layout">
    <div id="case-asst-messages" class="assistant-messages" aria-live="polite">
      <div class="assistant-messages-empty"><div class="assistant-welcome-card">${AVATAR_BOT}<p>正在加载…</p></div></div>
    </div>
    <div class="assistant-compose-wrap">
      <div id="case-asst-attach-preview" class="assistant-compose-attachments"></div>
      <div class="assistant-compose case-asst-compose">
        <textarea id="case-asst-input" class="assistant-input" rows="1" placeholder="粘贴 PRD / 截图 / 验收标准…" aria-label="用例助手输入"></textarea>
        <div class="assistant-compose-tools">
          <input type="file" id="case-asst-file-input" accept="image/*" multiple hidden />
          <button type="button" class="assistant-compose-icon-btn assistant-compose-icon-btn--ghost" id="case-asst-image-btn" title="添加截图">${PlatformChat ? PlatformChat.ICON_IMAGE : "🖼"}</button>
          <button type="button" class="assistant-compose-icon-btn assistant-send-btn" id="case-asst-send" title="发送">${ICON_SEND}</button>
        </div>
      </div>
      <div class="assistant-compose-hint"><kbd>Enter</kbd> 发送 · <kbd>Shift</kbd>+<kbd>Enter</kbd> 换行 · 可粘贴或上传截图</div>
    </div>
  </div>
  <aside id="case-asst-panel" class="assistant-progress-panel" aria-label="设计进度"></aside>
</div>
</div>`;

        const input = document.getElementById("case-asst-input");
        const sendBtn = document.getElementById("case-asst-send");
        input?.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendCaseAssistantMessage();
            }
        });
        input?.addEventListener("input", () => {
            input.style.height = "auto";
            input.style.height = Math.min(input.scrollHeight, 160) + "px";
        });
        sendBtn?.addEventListener("click", () => sendCaseAssistantMessage());

        if (PlatformChat) {
            composeAttachments = PlatformChat.createComposeAttachments({
                previewId: "case-asst-attach-preview",
                fileInputId: "case-asst-file-input",
                imageBtnId: "case-asst-image-btn",
                inputId: "case-asst-input",
            });
            composeAttachments.bind();
        }

        if (!messages.length) resetCaseAssistant(true);
        else restoreMessages();
    }

    loadState();

    window.loadCaseAssistant = loadCaseAssistant;
    window.sendCaseAssistantMessage = sendCaseAssistantMessage;
    window.resetCaseAssistant = resetCaseAssistant;
    window.deleteCaseAssistantHistory = deleteCaseAssistantHistory;
    window.saveCaseAssistantDraft = saveCaseAssistantDraft;
})();
