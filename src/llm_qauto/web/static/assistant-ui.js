/**
 * 配置助手 — Web 聊天界面
 */
(function () {
    let assistantMessages = [];
    let assistantCollected = {};
    let pendingConfigYaml = null;
    let pendingConfigName = null;
    let assistantSending = false;
    let lastAssistantResponse = null;
    let composeAttachments = null;

    const ASSISTANT_STORAGE_KEY = "llm-qauto-assistant-v1";

    const SCENE_LABELS = {
        listing_qc: "Listing 七维质检",
        prompt_rewrite_qc: "帮写 Prompt L1",
        image_gen: "生图测评",
        generic: "通用三维质检",
    };

    const FIELD_LABELS = {
        scene: "测试场景",
        target_curl: "被测 cURL",
        suite_name: "项目名称",
        id_values: "测试 ID",
        output_path: "响应路径",
    };

    const AVATAR_BOT =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2M20 14h2M15 13v2M9 13v2"/></svg>';
    const WELCOME_BOT =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 8V4H8"/><rect x="4" y="8" width="16" height="12" rx="2"/><path d="M2 14h2M20 14h2M15 13v2M9 13v2"/></svg>';
    const AVATAR_USER =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';
    const ICON_SEND =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>';
    const ICON_CLIP =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>';
    const ICON_CHECK =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="20 6 9 17 4 12"/></svg>';

    function getAssistantPersistPayload() {
        return {
            version: 1,
            messages: assistantMessages.map((m) => ({
                role: m.role,
                content: m.content,
                image_count: m.image_count || 0,
            })),
            collected: assistantCollected,
            lastResponse: lastAssistantResponse,
            pendingConfigYaml,
            pendingConfigName,
            updatedAt: Date.now(),
        };
    }

    function saveAssistantState() {
        try {
            if (!assistantMessages.length) {
                localStorage.removeItem(ASSISTANT_STORAGE_KEY);
                return;
            }
            localStorage.setItem(ASSISTANT_STORAGE_KEY, JSON.stringify(getAssistantPersistPayload()));
            renderAssistantHistoryMeta();
        } catch (e) {
            if (typeof showAssistantToast === "function") {
                showAssistantToast("聊天记录过大，无法保存到本地", true);
            }
        }
    }

    function loadAssistantState() {
        try {
            const raw = localStorage.getItem(ASSISTANT_STORAGE_KEY);
            if (!raw) return false;
            const data = JSON.parse(raw);
            if (!data || !Array.isArray(data.messages) || !data.messages.length) return false;
            assistantMessages = data.messages;
            assistantCollected = data.collected || {};
            lastAssistantResponse = data.lastResponse || null;
            pendingConfigYaml = data.pendingConfigYaml || data.lastResponse?.config_yaml || null;
            pendingConfigName = data.pendingConfigName || data.lastResponse?.config_name || null;
            return true;
        } catch (e) {
            localStorage.removeItem(ASSISTANT_STORAGE_KEY);
            return false;
        }
    }

    function clearAssistantStorage() {
        localStorage.removeItem(ASSISTANT_STORAGE_KEY);
        renderAssistantHistoryMeta();
    }

    function formatAssistantSavedTime(ts) {
        if (!ts) return "";
        try {
            const d = new Date(ts);
            const pad = (n) => String(n).padStart(2, "0");
            return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
        } catch (e) {
            return "";
        }
    }

    function renderAssistantHistoryMeta() {
        const el = document.getElementById("assistant-history-meta");
        if (!el) return;
        let savedAt = null;
        try {
            const raw = localStorage.getItem(ASSISTANT_STORAGE_KEY);
            if (raw) savedAt = JSON.parse(raw)?.updatedAt;
        } catch (e) {
            savedAt = null;
        }
        const count = assistantMessages.length;
        if (!count && !savedAt) {
            el.innerHTML = `<span class="assistant-history-meta-text">暂无本地记录</span>`;
            return;
        }
        const timeLabel = savedAt ? formatAssistantSavedTime(savedAt) : "";
        el.innerHTML = `
<span class="assistant-history-meta-text">${count ? `${count} 条消息` : "暂无消息"}${timeLabel ? ` · 保存于 ${escapeHtml(timeLabel)}` : ""}</span>
<button type="button" class="assistant-history-delete" onclick="deleteAssistantHistory()">删除记录</button>`;
    }

    function renderMarkdownLite(text) {
        let html = escapeHtml(text || "");
        html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
        html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
        html = html.replace(/\n/g, "<br>");
        return html;
    }

    function truncate(text, max) {
        const s = String(text || "");
        if (s.length <= max) return s;
        return s.slice(0, max) + "…";
    }

    function formatUserMessageContent(text, images, imageCount) {
        const raw = String(text || "");
        let html = "";
        if (!/curl\s/i.test(raw)) {
            html = escapeHtml(raw).replace(/\n/g, "<br>");
        } else {
            const compact = raw.replace(/\s+/g, " ").trim();
            const preview = truncate(compact, 120);
            html = `<details class="assistant-curl-block"><summary>已粘贴 cURL <span class="assistant-curl-meta">${escapeHtml(preview)}</span></summary><pre class="assistant-curl-pre">${escapeHtml(raw)}</pre></details>`;
        }
        if (images?.length && window.PlatformChat) {
            html += PlatformChat.renderMessageImagesHtml(images, false);
        } else if (imageCount > 0) {
            html += `<div class="assistant-msg-image-badge">📎 ${imageCount} 张截图</div>`;
        }
        return html || escapeHtml(raw).replace(/\n/g, "<br>");
    }

    function showAssistantToast(message, isError) {
        if (window.PlatformChat) {
            PlatformChat.showToast(message, isError);
            return;
        }
        let el = document.getElementById("assistant-toast");
        if (!el) {
            el = document.createElement("div");
            el.id = "assistant-toast";
            el.className = "assistant-toast";
            document.body.appendChild(el);
        }
        el.textContent = message;
        el.classList.toggle("assistant-toast--err", !!isError);
        el.classList.add("is-visible");
        clearTimeout(showAssistantToast._timer);
        showAssistantToast._timer = setTimeout(() => el.classList.remove("is-visible"), 2800);
    }

    function scrollAssistantToBottom() {
        const wrap = document.getElementById("assistant-messages");
        if (wrap) {
            requestAnimationFrame(() => {
                wrap.scrollTop = wrap.scrollHeight;
            });
        }
    }

    function setAssistantBusy(busy) {
        assistantSending = busy;
        const compose = document.querySelector(".assistant-compose");
        const input = document.getElementById("assistant-input");
        const sendBtn = document.getElementById("assistant-send-btn");
        if (compose) compose.classList.toggle("is-busy", busy);
        if (input) input.disabled = busy;
        if (sendBtn) sendBtn.disabled = busy;
        document.querySelectorAll(".assistant-msg-option-btn, .assistant-msg-chip, .assistant-msg-btn").forEach((btn) => {
            btn.disabled = busy;
        });
    }

    function showAssistantTyping() {
        const wrap = document.getElementById("assistant-messages");
        if (!wrap || document.getElementById("assistant-typing-row")) return;
        const row = document.createElement("div");
        row.id = "assistant-typing-row";
        row.className = "assistant-typing";
        row.innerHTML = `
<div class="assistant-avatar assistant-avatar--bot" aria-hidden="true">${AVATAR_BOT}</div>
<div class="assistant-typing-dots" aria-label="助手正在输入"><span></span><span></span><span></span></div>`;
        wrap.appendChild(row);
        scrollAssistantToBottom();
    }

    function hideAssistantTyping() {
        const el = document.getElementById("assistant-typing-row");
        if (el) el.remove();
    }

    function autoResizeAssistantInput() {
        const input = document.getElementById("assistant-input");
        if (!input) return;
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 160) + "px";
    }

    function appendLabel(parent, text) {
        const label = document.createElement("div");
        label.className = "assistant-msg-label";
        label.textContent = text;
        parent.appendChild(label);
    }

    function appendActionButtons(container, actions) {
        if (!actions || !actions.length) return;
        appendLabel(container, "下一步");
        const act = document.createElement("div");
        act.className = "assistant-msg-actions";
        actions.forEach((a) => {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = a.primary
                ? "assistant-msg-btn assistant-msg-btn--primary"
                : a.ghost
                  ? "assistant-msg-btn assistant-msg-btn--ghost"
                  : "assistant-msg-btn";
            btn.textContent = a.label;
            btn.onclick = a.onClick;
            act.appendChild(btn);
        });
        container.appendChild(act);
    }

    function appendAssistantBubble(role, content, extras) {
        const wrap = document.getElementById("assistant-messages");
        if (!wrap) return;

        const empty = wrap.querySelector(".assistant-messages-empty");
        if (empty) empty.remove();

        const row = document.createElement("div");
        row.className = `assistant-msg-row assistant-msg-row--${role}`;

        const avatar = document.createElement("div");
        avatar.className = `assistant-avatar assistant-avatar--${role === "user" ? "user" : "bot"}`;
        avatar.setAttribute("aria-hidden", "true");
        avatar.innerHTML = role === "user" ? AVATAR_USER : AVATAR_BOT;
        row.appendChild(avatar);

        const col = document.createElement("div");
        col.className = "assistant-msg-col";

        const inner = document.createElement("div");
        inner.className = "assistant-msg-body";
        inner.innerHTML = role === "assistant" ? renderMarkdownLite(content) : formatUserMessageContent(content, extras?.images, extras?.imageCount);
        col.appendChild(inner);

        if (role === "assistant" && extras) {
            if (extras.sceneOptions && extras.sceneOptions.length) {
                appendLabel(col, "选择测试场景");
                const optGrid = document.createElement("div");
                optGrid.className = "assistant-msg-options";
                extras.sceneOptions.forEach((opt) => {
                    const btn = document.createElement("button");
                    btn.type = "button";
                    btn.className = "assistant-msg-option-btn";
                    btn.innerHTML = escapeHtml(opt.label) + (opt.hint ? `<span class="assistant-msg-option-hint">${escapeHtml(opt.hint)}</span>` : "");
                    btn.onclick = () => applyAssistantScene(opt);
                    optGrid.appendChild(btn);
                });
                col.appendChild(optGrid);
            }

            if (extras.quickReplies && extras.quickReplies.length) {
                appendLabel(col, "快捷回复");
                const chips = document.createElement("div");
                chips.className = "assistant-msg-chips";
                extras.quickReplies.slice(0, 6).forEach((q) => {
                    const btn = document.createElement("button");
                    btn.type = "button";
                    btn.className = "assistant-msg-chip";
                    btn.textContent = q;
                    btn.onclick = () => sendAssistantMessage(q);
                    chips.appendChild(btn);
                });
                col.appendChild(chips);
            }

            appendActionButtons(col, extras.actions);
        }

        row.appendChild(col);
        wrap.appendChild(row);
        scrollAssistantToBottom();
    }

    function buildAssistantBubbleExtras(data) {
        const actions = [];

        if (data.phase === "ready" && data.config_yaml) {
            pendingConfigYaml = data.config_yaml;
            pendingConfigName = data.config_name || assistantCollected.suite_name || "test-suite";
            actions.push({
                label: "创建测试项目",
                primary: true,
                onClick: () => createProjectFromAssistant(false),
            });
            actions.push({
                label: "生成并编辑",
                onClick: () => createProjectFromAssistant(true),
            });
        }

        const hasScene = data.scene_options && data.scene_options.length;
        return {
            sceneOptions: hasScene ? data.scene_options : [],
            quickReplies: hasScene ? [] : data.quick_replies || [],
            actions,
        };
    }

    function computeAssistantSteps(collected, phase) {
        const scene = collected.scene;
        const hasCurl = !!collected.target_curl;
        const hasName = !!collected.suite_name;
        const ready = phase === "ready" && pendingConfigYaml;

        const steps = [
            {
                id: "scene",
                label: "选择测试场景",
                detail: scene ? SCENE_LABELS[scene] || scene : "帮写 / Listing / 生图 / 通用",
                done: !!scene,
                active: !scene,
            },
            {
                id: "curl",
                label: "粘贴被测 cURL",
                detail: hasCurl ? truncate(collected.target_curl.replace(/\s+/g, " "), 48) : "从浏览器 DevTools 复制",
                done: hasCurl,
                active: !!scene && !hasCurl,
            },
            {
                id: "info",
                label: "补全测试信息",
                detail: hasName ? collected.suite_name : "项目名称、测试 ID 等",
                done: hasName && hasCurl && !!scene,
                active: !!scene && hasCurl && !ready,
            },
            {
                id: "ready",
                label: "生成并创建项目",
                detail: ready ? "配置已就绪" : "确认后一键创建",
                done: ready,
                active: ready,
            },
        ];
        return steps;
    }

    function updateAssistantProgress(data) {
        const panel = document.getElementById("assistant-progress-panel");
        if (!panel) return;

        const collected = data?.collected || assistantCollected || {};
        const phase = data?.phase || lastAssistantResponse?.phase || "collecting";
        const missing = data?.missing || lastAssistantResponse?.missing || [];
        const steps = computeAssistantSteps(collected, phase);

        const stepsHtml = steps
            .map((s, i) => {
                const cls = [s.done ? "is-done" : "", s.active && !s.done ? "is-active" : "", !s.done && !s.active ? "is-pending" : ""]
                    .filter(Boolean)
                    .join(" ");
                const marker = s.done ? "✓" : i + 1;
                return `<li class="assistant-step ${cls}">
  <div class="assistant-step-marker">${marker}</div>
  <div class="assistant-step-body">
    <div class="assistant-step-label">${escapeHtml(s.label)}</div>
    <div class="assistant-step-detail">${escapeHtml(s.detail)}</div>
  </div>
</li>`;
            })
            .join("");

        const rows = ["scene", "target_curl", "suite_name"]
            .map((key) => {
                const val = collected[key];
                const label = FIELD_LABELS[key] || key;
                let display = "待填写";
                let cls = "is-miss";
                if (key === "scene" && val) {
                    display = SCENE_LABELS[val] || val;
                    cls = "is-ok";
                } else if (key === "target_curl" && val) {
                    display = "已粘贴 (" + truncate(val.replace(/\s+/g, " "), 28) + ")";
                    cls = "is-ok";
                } else if (val) {
                    display = String(val);
                    cls = "is-ok";
                } else if (missing.includes(key)) {
                    display = "仍缺";
                }
                return `<div class="assistant-collected-row"><span class="assistant-collected-key">${escapeHtml(label)}</span><span class="assistant-collected-val ${cls}">${escapeHtml(display)}</span></div>`;
            })
            .join("");

        const readyBanner =
            phase === "ready" && pendingConfigYaml
                ? `<div class="assistant-ready-banner">${ICON_CHECK}<span>YAML 已生成，可在对话中创建项目</span></div>`
                : "";

        panel.innerHTML = `
<div class="assistant-progress-title">配置进度</div>
<ul class="assistant-steps">${stepsHtml}</ul>
${readyBanner}
<div class="assistant-collected-card">
  <h4>已收集</h4>
  ${rows}
</div>
<div id="assistant-history-meta" class="assistant-history-meta"></div>`;
        renderAssistantHistoryMeta();
    }

    async function applyAssistantScene(opt) {
        if (assistantSending || !opt) return;
        const patch = {
            scene: opt.id || opt.scene,
            suite_name: opt.suite_name || opt.id,
        };
        await sendAssistantMessage(`选择场景：${opt.label}`, patch);
    }

    function handleAssistantResponse(data) {
        lastAssistantResponse = data;
        assistantCollected = data.collected || assistantCollected;
        const bubbleExtras = buildAssistantBubbleExtras(data);
        assistantMessages.push({ role: "assistant", content: data.message, _extras: bubbleExtras });
        appendAssistantBubble("assistant", data.message, bubbleExtras);
        updateAssistantProgress(data);
        saveAssistantState();

        if (typeof setApiStatus === "function") {
            setApiStatus("配置助手已回复", "ok");
        }
    }

    async function sendAssistantMessage(text, patch) {
        const input = document.getElementById("assistant-input");
        const msg = (text != null ? String(text) : input && input.value ? input.value.trim() : "").trim();
        const attachPayload = composeAttachments ? composeAttachments.getPayload() : [];
        const attachItems = composeAttachments ? composeAttachments.getItems() : [];
        if ((!msg && !attachPayload.length) || assistantSending) return;

        setAssistantBusy(true);
        if (input && text == null) {
            input.value = "";
            autoResizeAssistantInput();
        }

        if (patch && typeof patch === "object") {
            assistantCollected = { ...assistantCollected, ...patch };
        }
        if (/curl\s/i.test(msg)) {
            const curlText = msg.trim();
            const prev = assistantCollected.target_curl;
            if (!prev || curlText.length > String(prev).length || /https?:\/\//i.test(curlText)) {
                assistantCollected = { ...assistantCollected, target_curl: curlText };
            }
        }

        assistantMessages.push({
            role: "user",
            content: msg || (attachPayload.length ? "[截图]" : ""),
            image_count: attachPayload.length,
            _images: attachItems,
        });
        appendAssistantBubble("user", msg || "[截图]", { images: attachItems, imageCount: attachPayload.length });
        updateAssistantProgress({ collected: assistantCollected, phase: "collecting" });
        saveAssistantState();
        showAssistantTyping();

        try {
            const body = {
                messages: assistantMessages.map((m) => ({ role: m.role, content: m.content })),
                collected: assistantCollected,
                attachments: attachPayload,
            };
            if (patch && typeof patch === "object") {
                body.patch = patch;
            }
            const { data } = await apiFetch("/api/assistant/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });

            hideAssistantTyping();
            handleAssistantResponse(data);
            if (composeAttachments) composeAttachments.clear();
        } catch (e) {
            hideAssistantTyping();
            assistantMessages.push({ role: "assistant", content: "请求失败：" + (e.message || String(e)) });
            appendAssistantBubble("assistant", assistantMessages[assistantMessages.length - 1].content, {
                sceneOptions: [],
                quickReplies: [],
                actions: [{ label: "重新提问", ghost: true, onClick: () => restartAssistantQuestion() }],
            });
            saveAssistantState();
            showAssistantToast("发送失败：" + (e.message || "网络错误"), true);
            if (typeof setApiStatus === "function") setApiStatus("配置助手失败", "err", e.message);
        } finally {
            setAssistantBusy(false);
            if (input) input.focus();
        }
    }

    async function pasteCurlToAssistant() {
        try {
            const text = await navigator.clipboard.readText();
            if (!text || !/curl\s/i.test(text)) {
                showAssistantToast("剪贴板中未检测到 cURL，请先复制 DevTools 的 cURL", true);
                return;
            }
            const input = document.getElementById("assistant-input");
            if (input) {
                input.value = text.trim();
                autoResizeAssistantInput();
                input.focus();
            }
            showAssistantToast("已粘贴 cURL，点击发送继续");
        } catch (e) {
            showAssistantToast("无法读取剪贴板，请手动粘贴", true);
        }
    }

    async function createProjectFromAssistant(openEditorOnly) {
        if (!pendingConfigYaml) {
            showAssistantToast("暂无已生成的配置", true);
            return;
        }
        const name = pendingConfigName || "test-suite";
        if (openEditorOnly) {
            if (typeof resetCreateConfigEditor === "function") resetCreateConfigEditor();
            document.getElementById("new-project-config").value = pendingConfigYaml;
            if (typeof refreshFormFromYaml === "function") {
                refreshFormFromYaml("create");
                setConfigFormSubtab("create", "basic");
            }
            showModal("create-modal");
            showAssistantToast("已在编辑器中打开配置");
            return;
        }
        try {
            const { data } = await apiFetch("/api/projects", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, config_yaml: pendingConfigYaml }),
            });
            if (data.success) {
                const successMsg = `项目 **${name}** 已创建。可在「测试项目」中查看并运行。`;
                assistantMessages.push({ role: "assistant", content: successMsg });
                appendAssistantBubble(
                    "assistant",
                    successMsg,
                    {
                        sceneOptions: [],
                        quickReplies: [],
                        actions: [
                            { label: "查看测试项目", primary: true, onClick: () => showSection("projects") },
                            { label: "重新提问", ghost: true, onClick: () => restartAssistantQuestion() },
                        ],
                    }
                );
                saveAssistantState();
                showAssistantToast("项目创建成功");
                showSection("projects");
            }
        } catch (e) {
            showAssistantToast("创建失败：" + e.message, true);
        }
    }

    async function loadAssistantWelcome() {
        showAssistantTyping();
        try {
            const { data } = await apiFetch("/api/assistant/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ messages: [], collected: {} }),
            });
            hideAssistantTyping();
            assistantCollected = data.collected || {};
            lastAssistantResponse = data;
            assistantMessages.push({ role: "assistant", content: data.message });
            appendAssistantBubble("assistant", data.message, buildAssistantBubbleExtras(data));
            updateAssistantProgress(data);
            saveAssistantState();
        } catch (e) {
            hideAssistantTyping();
            const errMsg = "无法连接配置助手 API。请确认 Web 服务已启动且 .env 已配置 LLM。\n\n" + (e.message || "");
            assistantMessages.push({ role: "assistant", content: errMsg });
            appendAssistantBubble(
                "assistant",
                errMsg,
                {
                    sceneOptions: [],
                    quickReplies: [],
                    actions: [{ label: "重新提问", ghost: true, onClick: () => restartAssistantQuestion() }],
                }
            );
            saveAssistantState();
        }
    }

    function resetAssistantChat(skipConfirm) {
        if (!skipConfirm && assistantMessages.length > 0) {
            if (!confirm("清空当前对话并重新开始？")) return;
        }
        assistantMessages = [];
        assistantCollected = {};
        pendingConfigYaml = null;
        pendingConfigName = null;
        lastAssistantResponse = null;
        clearAssistantStorage();
        const wrap = document.getElementById("assistant-messages");
        if (wrap) {
            wrap.innerHTML = `<div class="assistant-messages-empty"><div class="assistant-welcome-card">${WELCOME_BOT}<p>正在连接配置助手…</p></div></div>`;
        }
        const input = document.getElementById("assistant-input");
        if (input) {
            input.value = "";
            autoResizeAssistantInput();
        }
        updateAssistantProgress({ collected: {}, phase: "collecting" });
        loadAssistantWelcome();
    }

    function restartAssistantQuestion() {
        resetAssistantChat(false);
    }

    function deleteAssistantHistory() {
        const hasLocal = !!localStorage.getItem(ASSISTANT_STORAGE_KEY);
        if (!hasLocal && assistantMessages.length === 0) {
            showAssistantToast("暂无聊天记录");
            return;
        }
        if (!confirm("确定删除本地保存的聊天记录？删除后无法恢复。")) return;
        clearAssistantStorage();
        resetAssistantChat(true);
        showAssistantToast("聊天记录已删除");
    }

    function restoreAssistantMessages() {
        const wrap = document.getElementById("assistant-messages");
        if (!wrap) return;
        wrap.innerHTML = "";
        if (!assistantMessages.length) return;

        assistantMessages.forEach((m, idx) => {
            const isLastAssistant = m.role === "assistant" && idx === assistantMessages.length - 1;
            let extras = null;
            if (m.role === "user") {
                extras = { images: m._images, imageCount: m.image_count || 0 };
            } else if (isLastAssistant && lastAssistantResponse) {
                extras = buildAssistantBubbleExtras(lastAssistantResponse);
            } else if (m._extras) {
                extras = m._extras;
            }
            appendAssistantBubble(m.role, m.content, extras);
        });
        updateAssistantProgress(lastAssistantResponse || { collected: assistantCollected, phase: "collecting" });
    }

    function loadAssistant() {
        const head = typeof renderModulePageHead === "function"
            ? renderModulePageHead(
                  "配置助手",
                  "粘贴 cURL 或描述测评目标，逐步补全信息并生成 YAML 测试项目。",
                  `<button type="button" class="btn btn-secondary btn-sm" onclick="resetAssistantChat()">新对话</button>
<button type="button" class="btn btn-secondary btn-sm assistant-btn-danger" onclick="deleteAssistantHistory()">删除记录</button>
<button type="button" class="btn btn-secondary btn-sm" onclick="showCurlWizardModal()">cURL 向导</button>`
              )
            : "";
        const content = document.getElementById("main-content");
        content.innerHTML = `
<div class="module-page module-page--assistant">
${head}
<div class="assistant-shell">
  <div class="assistant-layout">
    <div id="assistant-messages" class="assistant-messages" aria-live="polite">
      <div class="assistant-messages-empty">
        <div class="assistant-welcome-card">${WELCOME_BOT}<p>正在加载…</p></div>
      </div>
    </div>
    <div class="assistant-compose-wrap">
      <div id="assistant-attach-preview" class="assistant-compose-attachments"></div>
      <div class="assistant-compose">
        <textarea id="assistant-input" class="assistant-input" rows="1" placeholder="粘贴 cURL、截图或描述测评目标…" aria-label="配置助手输入"></textarea>
        <div class="assistant-compose-tools">
          <input type="file" id="assistant-file-input" accept="image/*" multiple hidden />
          <button type="button" class="assistant-compose-icon-btn assistant-compose-icon-btn--ghost" id="assistant-image-btn" title="添加截图">${window.PlatformChat ? PlatformChat.ICON_IMAGE : "🖼"}</button>
          <button type="button" class="assistant-compose-icon-btn assistant-compose-icon-btn--ghost" id="assistant-paste-btn" title="从剪贴板粘贴 cURL">${ICON_CLIP}</button>
          <button type="button" class="assistant-compose-icon-btn assistant-send-btn" id="assistant-send-btn" title="发送">${ICON_SEND}</button>
        </div>
      </div>
      <div class="assistant-compose-hint"><kbd>Enter</kbd> 发送 · <kbd>Shift</kbd>+<kbd>Enter</kbd> 换行 · 可粘贴或上传截图</div>
    </div>
  </div>
  <aside id="assistant-progress-panel" class="assistant-progress-panel" aria-label="配置进度"></aside>
</div>
</div>`;

        const input = document.getElementById("assistant-input");
        const sendBtn = document.getElementById("assistant-send-btn");
        const pasteBtn = document.getElementById("assistant-paste-btn");

        if (input) {
            input.addEventListener("keydown", (e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    sendAssistantMessage();
                }
            });
            input.addEventListener("input", autoResizeAssistantInput);
        }
        if (sendBtn) sendBtn.onclick = () => sendAssistantMessage();
        if (pasteBtn) pasteBtn.onclick = () => pasteCurlToAssistant();

        if (window.PlatformChat) {
            composeAttachments = PlatformChat.createComposeAttachments({
                previewId: "assistant-attach-preview",
                fileInputId: "assistant-file-input",
                imageBtnId: "assistant-image-btn",
                inputId: "assistant-input",
            });
            composeAttachments.bind();
        }

        updateAssistantProgress({ collected: assistantCollected, phase: lastAssistantResponse?.phase || "collecting" });

        if (assistantMessages.length === 0) {
            resetAssistantChat(true);
        } else {
            restoreAssistantMessages();
            renderAssistantHistoryMeta();
        }
    }

    loadAssistantState();

    window.loadAssistant = loadAssistant;
    window.sendAssistantMessage = sendAssistantMessage;
    window.resetAssistantChat = resetAssistantChat;
    window.restartAssistantQuestion = restartAssistantQuestion;
    window.deleteAssistantHistory = deleteAssistantHistory;
    window.applyAssistantScene = applyAssistantScene;
})();
