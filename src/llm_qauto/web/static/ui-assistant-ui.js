/**
 * UI 自动化助手 — 多轮聊天生成 Playwright 脚本
 */
(function () {
    const STORAGE_KEY = "llm-qauto-ui-assistant-v1";
    const FIX_PENDING_KEY = "llm-qauto-ui-fix-pending";
    const CHAT_API = "/api/ui-auto/chat";
    const PROBE_API = "/api/ui-auto/probe";

    let messages = [];
    let collected = {};
    let lastResponse = null;
    let pendingSpec = null;
    let sending = false;
    let probing = false;
    let composeAttachments = null;

    const FIELD_LABELS = {
        url: "目标 URL",
        description: "流程描述",
        assertions: "关键断言",
        spec_name: "脚本文件名",
    };

    const AVATAR_BOT =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>';
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

    function saveState() {
        try {
            if (!messages.length) {
                localStorage.removeItem(STORAGE_KEY);
                return;
            }
            localStorage.setItem(
                STORAGE_KEY,
                JSON.stringify({ version: 1, messages: messages.map((m) => ({ role: m.role, content: m.content, image_count: m.image_count || 0 })), collected, lastResponse, pendingSpec, updatedAt: Date.now() })
            );
            renderHistoryMeta();
        } catch (e) {
            toast("聊天记录过大", true);
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
            pendingSpec = data.pendingSpec || null;
            return true;
        } catch (e) {
            localStorage.removeItem(STORAGE_KEY);
            return false;
        }
    }

    function scrollBottom() {
        const el = document.getElementById("ui-asst-messages");
        if (el) PlatformChat.scrollToBottom(el);
    }

    function setBusy(busy) {
        sending = busy;
        document.querySelector(".ui-asst-compose")?.classList.toggle("is-busy", busy);
        const input = document.getElementById("ui-asst-input");
        const btn = document.getElementById("ui-asst-send");
        if (input) input.disabled = busy;
        if (btn) btn.disabled = busy;
    }

    function showTyping() {
        const wrap = document.getElementById("ui-asst-messages");
        if (!wrap || document.getElementById("ui-asst-typing")) return;
        const row = document.createElement("div");
        row.id = "ui-asst-typing";
        row.className = "assistant-typing";
        row.innerHTML = `<div class="assistant-avatar assistant-avatar--bot">${AVATAR_BOT}</div><div class="assistant-typing-dots"><span></span><span></span><span></span></div>`;
        wrap.appendChild(row);
        scrollBottom();
    }

    function hideTyping() {
        document.getElementById("ui-asst-typing")?.remove();
    }

    function formatUserContent(text, images, imageCount) {
        let html = escapeHtml(text || "").replace(/\n/g, "<br>");
        if (images?.length && PlatformChat) html += PlatformChat.renderMessageImagesHtml(images, false);
        else if (imageCount > 0) html += `<div class="assistant-msg-image-badge">📎 ${imageCount} 张截图</div>`;
        return html;
    }

    function appendBubble(role, content, extras) {
        const wrap = document.getElementById("ui-asst-messages");
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
                    btn.onclick = () => sendUiAssistantMessage(q);
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
        if (data.phase === "ready" && data.spec_content) {
            pendingSpec = { name: data.spec_name, content: data.spec_content };
            actions.push({
                label: collected.fix_context ? "保存修复后的脚本" : "保存到脚本库",
                primary: true,
                onClick: saveUiAssistantSpec,
            });
            actions.push({ label: "打开脚本管理", onClick: () => showModuleSection("ui_automation", "specs") });
        }
        return { quickReplies: data.quick_replies || [], actions };
    }

    function updateProgress(data) {
        const panel = document.getElementById("ui-asst-panel");
        if (!panel) return;
        const phase = data?.phase || lastResponse?.phase || "collecting";
        const missing = data?.missing || lastResponse?.missing || [];
        const hasDesc = !!(collected.description || "").trim();
        const hasUrl = !!collected.url;
        const ready = phase === "ready" && pendingSpec?.content;

        const steps = [
            { label: "描述测试流程", detail: hasDesc ? truncate(collected.description, 36) : "步骤与断言", done: hasDesc, active: !hasDesc },
            { label: "确认 URL / 登录", detail: hasUrl ? collected.url : "可选", done: hasUrl || hasDesc, active: hasDesc && !ready },
            { label: "生成 Playwright 脚本", detail: ready ? pendingSpec.name : "回复「生成脚本」", done: ready, active: ready },
        ];

        const stepsHtml = steps
            .map((s, i) => {
                const cls = [s.done ? "is-done" : "", s.active && !s.done ? "is-active" : "", !s.done && !s.active ? "is-pending" : ""].filter(Boolean).join(" ");
                return `<li class="assistant-step ${cls}"><div class="assistant-step-marker">${s.done ? "✓" : i + 1}</div><div class="assistant-step-body"><div class="assistant-step-label">${escapeHtml(s.label)}</div><div class="assistant-step-detail">${escapeHtml(s.detail)}</div></div></li>`;
            })
            .join("");

        const rows = ["url", "description", "spec_name"]
            .map((key) => {
                const val = collected[key];
                const label = FIELD_LABELS[key] || key;
                let display = "待填写";
                let cls = "is-miss";
                if (val) {
                    display = key === "description" ? truncate(String(val), 32) : String(val);
                    cls = "is-ok";
                } else if (missing.includes(key)) display = "仍缺";
                return `<div class="assistant-collected-row"><span class="assistant-collected-key">${escapeHtml(label)}</span><span class="assistant-collected-val ${cls}">${escapeHtml(display)}</span></div>`;
            })
            .join("");

        const probe = collected.page_probe;
        const probeErr = collected.page_probe_error;
        let probeExtra = "";
        if (hasUrl) {
            let probeDisplay = probing ? "解析中…" : probe ? `已探测 ${probe.element_count || 0} 个元素` : probeErr ? truncate(probeErr, 28) : "生成前自动解析";
            const probeCls = probe ? "is-ok" : probeErr ? "is-miss" : "";
            probeExtra = `<div class="assistant-collected-row"><span class="assistant-collected-key">页面结构</span><span class="assistant-collected-val ${probeCls}">${escapeHtml(probeDisplay)}</span></div>`;
            if (!ready) {
                probeExtra += `<button type="button" class="btn btn-secondary btn-sm ui-asst-probe-btn" onclick="probeUiAssistantPage()" ${probing ? "disabled" : ""}>${probing ? "解析中…" : "解析页面结构"}</button>`;
            }
        }

        let preview = "";
        if (ready) {
            preview = `<div class="case-asst-preview"><h4>脚本预览</h4><pre class="cfg-wizard-summary ui-asst-spec-preview">${escapeHtml(pendingSpec.content)}</pre></div>`;
        }

        const banner = ready
            ? `<div class="assistant-ready-banner">${ICON_CHECK}<span>脚本已生成，可保存或运行</span></div>`
            : collected.fix_context
              ? `<div class="assistant-ready-banner assistant-ready-banner--fix">🔧 失败修复模式 · ${escapeHtml(collected.fix_context.run_id || "")}</div>`
              : "";

        panel.innerHTML = `<div class="assistant-progress-title">脚本进度</div><ul class="assistant-steps">${stepsHtml}</ul>${banner}<div class="assistant-collected-card"><h4>已收集</h4>${rows}${probeExtra}</div>${preview}<div id="ui-asst-history-meta" class="assistant-history-meta"></div>`;
        renderHistoryMeta();
    }

    function renderHistoryMeta() {
        const el = document.getElementById("ui-asst-history-meta");
        if (!el) return;
        let savedAt = null;
        try {
            const raw = localStorage.getItem(STORAGE_KEY);
            if (raw) savedAt = JSON.parse(raw)?.updatedAt;
        } catch (e) {
            savedAt = null;
        }
        const count = messages.length;
        el.innerHTML = count
            ? `<span class="assistant-history-meta-text">${count} 条消息</span><button type="button" class="assistant-history-delete" onclick="deleteUiAssistantHistory()">删除记录</button>`
            : `<span class="assistant-history-meta-text">暂无本地记录</span>`;
    }

    function handleResponse(data) {
        lastResponse = data;
        collected = data.collected || collected;
        if (data.phase === "ready" && data.spec_content) {
            pendingSpec = { name: data.spec_name, content: data.spec_content };
        }
        messages.push({ role: "assistant", content: data.message });
        appendBubble("assistant", data.message, buildExtras(data));
        updateProgress(data);
        saveState();
    }

    async function probeUiAssistantPage() {
        const url = (collected.url || "").trim();
        if (!url || probing) return;
        probing = true;
        updateProgress(lastResponse || { collected, phase: "collecting" });
        toast("正在解析页面…");
        try {
            const { data } = await apiFetch(PROBE_API, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ url }),
            });
            collected = { ...collected, page_probe: data.page_probe };
            delete collected.page_probe_error;
            const n = data.page_probe?.element_count || 0;
            toast(`已解析 ${n} 个可交互元素`);
            updateProgress(lastResponse || { collected, phase: "collecting" });
            saveState();
        } catch (e) {
            collected = { ...collected, page_probe_error: e.message || String(e) };
            toast("页面解析失败", true);
            updateProgress(lastResponse || { collected, phase: "collecting" });
            saveState();
        } finally {
            probing = false;
            updateProgress(lastResponse || { collected, phase: "collecting" });
        }
    }

    async function sendUiAssistantMessage(text, patch) {
        const input = document.getElementById("ui-asst-input");
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
        if (/https?:\/\//.test(msg) && !collected.url) {
            const m = msg.match(/https?:\/\/[^\s]+/);
            if (m) collected = { ...collected, url: m[0] };
        }
        if (msg.length >= 15 && !collected.description) collected = { ...collected, description: msg };

        messages.push({
            role: "user",
            content: msg || "[截图]",
            image_count: attachPayload.length,
            _images: attachItems,
        });
        appendBubble("user", msg || "[截图]", { images: attachItems, imageCount: attachPayload.length });
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
            appendBubble("assistant", "请求失败：" + (e.message || ""), {});
            toast("发送失败", true);
        } finally {
            setBusy(false);
            input?.focus();
        }
    }

    async function saveUiAssistantSpec() {
        if (!pendingSpec?.content) {
            toast("暂无已生成的脚本", true);
            return;
        }
        try {
            await apiFetch("/api/ui-auto/specs", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: pendingSpec.name, content: pendingSpec.content }),
            });
            toast("已保存到脚本库");
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
            appendBubble("assistant", "无法连接 UI 助手 API。\n\n" + (e.message || ""), {});
        }
    }

    function resetUiAssistant(skipConfirm) {
        if (!skipConfirm && messages.length && !confirm("清空当前对话？")) return;
        messages = [];
        collected = {};
        lastResponse = null;
        pendingSpec = null;
        localStorage.removeItem(STORAGE_KEY);
        const wrap = document.getElementById("ui-asst-messages");
        if (wrap) wrap.innerHTML = `<div class="assistant-messages-empty"><div class="assistant-welcome-card">${AVATAR_BOT}<p>正在连接…</p></div></div>`;
        loadWelcome();
    }

    function deleteUiAssistantHistory() {
        if (!confirm("确定删除本地聊天记录？")) return;
        resetUiAssistant(true);
        toast("已删除");
    }

    function blobToDataUrl(blob) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(blob);
        });
    }

    async function startUiAssistantFromRun(ctx) {
        messages = [];
        collected = { fix_context: ctx };
        if (ctx.spec_name) collected.spec_name = ctx.spec_name;
        pendingSpec = null;
        lastResponse = null;
        const wrap = document.getElementById("ui-asst-messages");
        if (wrap) wrap.innerHTML = "";

        const userMsg = `【运行失败修复】${ctx.run_id || ""}\n\n错误：${ctx.error_summary || "测试失败"}\n\n请根据失败日志修复 Playwright 脚本。`;
        messages.push({ role: "user", content: userMsg });
        appendBubble("user", userMsg);
        saveState();
        setBusy(true);
        showTyping();

        const attachments = [];
        if (ctx.has_screenshot && ctx.run_id) {
            try {
                const resp = await fetch(`/api/ui-auto/runs/${encodeURIComponent(ctx.run_id)}/screenshot`);
                if (resp.ok) {
                    const dataUrl = await blobToDataUrl(await resp.blob());
                    attachments.push({ type: "image", data: dataUrl, name: "failure.png" });
                }
            } catch (e) {
                /* ignore screenshot errors */
            }
        }

        try {
            const { data } = await apiFetch(CHAT_API, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    messages: messages.map((m) => ({ role: m.role, content: m.content })),
                    collected,
                    patch: { fix_context: ctx, auto_fix: true },
                    attachments,
                }),
            });
            hideTyping();
            handleResponse(data);
        } catch (e) {
            hideTyping();
            appendBubble("assistant", "修复请求失败：" + (e.message || ""), {});
            toast("发送失败", true);
        } finally {
            setBusy(false);
        }
    }

    function restoreMessages() {
        const wrap = document.getElementById("ui-asst-messages");
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

    function loadUiAssistant() {
        const head = typeof renderModulePageHead === "function"
            ? renderModulePageHead(
                  "脚本助手",
                  "描述页面流程与断言，生成 Playwright .spec.ts 脚本。",
                  `<button type="button" class="btn btn-secondary btn-sm" onclick="resetUiAssistant()">新对话</button>
<button type="button" class="btn btn-secondary btn-sm assistant-btn-danger" onclick="deleteUiAssistantHistory()">删除记录</button>`
              )
            : "";
        const content = document.getElementById("main-content");
        content.innerHTML = `
<div class="module-page module-page--assistant">
${head}
<div class="assistant-shell">
  <div class="assistant-layout">
    <div id="ui-asst-messages" class="assistant-messages" aria-live="polite">
      <div class="assistant-messages-empty"><div class="assistant-welcome-card">${AVATAR_BOT}<p>正在加载…</p></div></div>
    </div>
    <div class="assistant-compose-wrap">
      <div id="ui-asst-attach-preview" class="assistant-compose-attachments"></div>
      <div class="assistant-compose ui-asst-compose">
        <textarea id="ui-asst-input" class="assistant-input" rows="1" placeholder="描述流程或粘贴 UI 截图…" aria-label="UI 助手输入"></textarea>
        <div class="assistant-compose-tools">
          <input type="file" id="ui-asst-file-input" accept="image/*" multiple hidden />
          <button type="button" class="assistant-compose-icon-btn assistant-compose-icon-btn--ghost" id="ui-asst-image-btn" title="添加截图">${PlatformChat ? PlatformChat.ICON_IMAGE : "🖼"}</button>
          <button type="button" class="assistant-compose-icon-btn assistant-send-btn" id="ui-asst-send" title="发送">${ICON_SEND}</button>
        </div>
      </div>
      <div class="assistant-compose-hint"><kbd>Enter</kbd> 发送 · <kbd>Shift</kbd>+<kbd>Enter</kbd> 换行 · 可粘贴或上传截图</div>
    </div>
  </div>
  <aside id="ui-asst-panel" class="assistant-progress-panel" aria-label="脚本进度"></aside>
</div>
</div>`;

        const input = document.getElementById("ui-asst-input");
        const sendBtn = document.getElementById("ui-asst-send");
        input?.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                sendUiAssistantMessage();
            }
        });
        input?.addEventListener("input", () => {
            input.style.height = "auto";
            input.style.height = Math.min(input.scrollHeight, 160) + "px";
        });
        sendBtn?.addEventListener("click", () => sendUiAssistantMessage());

        if (PlatformChat) {
            composeAttachments = PlatformChat.createComposeAttachments({
                previewId: "ui-asst-attach-preview",
                fileInputId: "ui-asst-file-input",
                imageBtnId: "ui-asst-image-btn",
                inputId: "ui-asst-input",
            });
            composeAttachments.bind();
        }

        const pendingRaw = sessionStorage.getItem(FIX_PENDING_KEY);
        if (pendingRaw) {
            sessionStorage.removeItem(FIX_PENDING_KEY);
            try {
                startUiAssistantFromRun(JSON.parse(pendingRaw));
                return;
            } catch (e) {
                toast("载入失败信息出错", true);
            }
        }

        if (!messages.length) resetUiAssistant(true);
        else restoreMessages();
    }

    loadState();

    window.loadUiAssistant = loadUiAssistant;
    window.sendUiAssistantMessage = sendUiAssistantMessage;
    window.probeUiAssistantPage = probeUiAssistantPage;
    window.resetUiAssistant = resetUiAssistant;
    window.deleteUiAssistantHistory = deleteUiAssistantHistory;
    window.saveUiAssistantSpec = saveUiAssistantSpec;
})();
