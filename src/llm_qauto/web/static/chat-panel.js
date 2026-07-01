/**
 * 共享聊天/Toast/本地会话工具（配置助手、用例设计等复用）
 */
(function (global) {
    function showToast(message, isError, toastId) {
        const id = toastId || "platform-toast";
        let el = document.getElementById(id);
        if (!el) {
            el = document.createElement("div");
            el.id = id;
            el.className = "assistant-toast platform-toast";
            document.body.appendChild(el);
        }
        el.textContent = message;
        el.classList.toggle("assistant-toast--err", !!isError);
        el.classList.add("is-visible");
        clearTimeout(el._hideTimer);
        el._hideTimer = setTimeout(() => el.classList.remove("is-visible"), 2800);
    }

    function createSessionStore(storageKey) {
        return {
            load() {
                try {
                    const raw = localStorage.getItem(storageKey);
                    return raw ? JSON.parse(raw) : null;
                } catch (e) {
                    localStorage.removeItem(storageKey);
                    return null;
                }
            },
            save(payload) {
                try {
                    if (!payload || !payload.messages || !payload.messages.length) {
                        localStorage.removeItem(storageKey);
                        return;
                    }
                    payload.updatedAt = Date.now();
                    localStorage.setItem(storageKey, JSON.stringify(payload));
                } catch (e) {
                    showToast("本地存储失败，内容可能过大", true);
                }
            },
            clear() {
                localStorage.removeItem(storageKey);
            },
        };
    }

    function renderMarkdownLite(text) {
        let html = (typeof escapeHtml === "function" ? escapeHtml(text || "") : String(text || ""));
        html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
        html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
        html = html.replace(/\n/g, "<br>");
        return html;
    }

    function scrollToBottom(el) {
        if (!el) return;
        requestAnimationFrame(() => {
            el.scrollTop = el.scrollHeight;
        });
    }

    function scrollToBottom(el) {
        if (!el) return;
        requestAnimationFrame(() => {
            el.scrollTop = el.scrollHeight;
        });
    }

    const ICON_IMAGE =
        '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>';

    function readFileAsDataUrl(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(String(reader.result || ""));
            reader.onerror = () => reject(reader.error || new Error("读取文件失败"));
            reader.readAsDataURL(file);
        });
    }

    function renderMessageImagesHtml(items, forStorage) {
        if (!items || !items.length) return "";
        if (forStorage) {
            return `<div class="assistant-msg-image-badge">📎 ${items.length} 张截图</div>`;
        }
        const imgs = items
            .map((it) => {
                const src = it.data || it.thumb || "";
                if (!src) return "";
                const alt = escapeHtmlLite(it.name || "截图");
                return `<img class="assistant-msg-image" src="${src}" alt="${alt}" loading="lazy" />`;
            })
            .filter(Boolean)
            .join("");
        return imgs ? `<div class="assistant-msg-images">${imgs}</div>` : "";
    }

    function escapeHtmlLite(s) {
        if (typeof global.escapeHtml === "function") return global.escapeHtml(s);
        return String(s || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    /**
     * 聊天输入框截图附件（粘贴 / 上传）
     * opts: { previewId, fileInputId, imageBtnId, inputId, maxImages, maxBytes, onChange }
     */
    function createComposeAttachments(opts) {
        const maxImages = opts.maxImages || 4;
        const maxBytes = opts.maxBytes || 4 * 1024 * 1024;
        let items = [];

        function renderPreview() {
            const box = document.getElementById(opts.previewId);
            if (!box) return;
            box.innerHTML = items
                .map(
                    (it, idx) => `<div class="assistant-attach-chip">
<img src="${it.data}" alt="${escapeHtmlLite(it.name)}" />
<button type="button" class="assistant-attach-remove" data-idx="${idx}" aria-label="移除">×</button>
</div>`
                )
                .join("");
            box.querySelectorAll(".assistant-attach-remove").forEach((btn) => {
                btn.onclick = () => {
                    items.splice(Number(btn.dataset.idx), 1);
                    renderPreview();
                    if (opts.onChange) opts.onChange(items);
                };
            });
        }

        async function addImageFile(file) {
            if (!file || !String(file.type || "").startsWith("image/")) {
                showToast("请选择图片文件", true);
                return false;
            }
            if (file.size > maxBytes) {
                showToast(`图片过大（>${Math.round(maxBytes / 1024 / 1024)}MB）`, true);
                return false;
            }
            if (items.length >= maxImages) {
                showToast(`最多 ${maxImages} 张截图`, true);
                return false;
            }
            try {
                const data = await readFileAsDataUrl(file);
                items.push({ type: "image", data, name: file.name || "截图.png" });
                renderPreview();
                if (opts.onChange) opts.onChange(items);
                return true;
            } catch (e) {
                showToast(e.message || "读取图片失败", true);
                return false;
            }
        }

        return {
            getItems() {
                return items.slice();
            },
            getPayload() {
                return items.map((it) => ({ type: "image", data: it.data, name: it.name }));
            },
            clear() {
                items = [];
                renderPreview();
            },
            bind() {
                const input = document.getElementById(opts.inputId);
                const fileInput = document.getElementById(opts.fileInputId);
                const imageBtn = document.getElementById(opts.imageBtnId);

                if (imageBtn && fileInput) {
                    imageBtn.onclick = () => fileInput.click();
                    fileInput.onchange = async () => {
                        const files = fileInput.files ? Array.from(fileInput.files) : [];
                        for (const f of files) {
                            await addImageFile(f);
                        }
                        fileInput.value = "";
                    };
                }

                if (input) {
                    input.addEventListener("paste", async (e) => {
                        const clip = e.clipboardData;
                        if (!clip) return;
                        const imageFiles = [];
                        for (const item of clip.items || []) {
                            if (item.type && item.type.startsWith("image/")) {
                                const f = item.getAsFile();
                                if (f) imageFiles.push(f);
                            }
                        }
                        if (!imageFiles.length) return;
                        e.preventDefault();
                        for (const f of imageFiles) {
                            await addImageFile(f);
                        }
                        showToast("已添加截图");
                    });
                }
            },
        };
    }

    global.PlatformChat = {
        showToast,
        createSessionStore,
        renderMarkdownLite,
        scrollToBottom,
        createComposeAttachments,
        renderMessageImagesHtml,
        ICON_IMAGE,
    };
})(window);
