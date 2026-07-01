/**
 * 用例设计 — Mermaid 图渲染（评审概览 + 覆盖树）
 * 自动将无效 mindmap 转为 flowchart，避免 Parse error。
 */
(function () {
    const MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.min.js";
    let loadPromise = null;
    let renderSeq = 0;

    const STYLE_BLOCK = [
        "classDef root fill:#0284c7,stroke:#0369a1,color:#fff,stroke-width:2px",
        "classDef mod fill:#e0f2fe,stroke:#38bdf8,color:#0c4a6e,stroke-width:1.5px",
        "classDef tc fill:#fff,stroke:#cbd5e1,color:#334155,stroke-width:1px",
        "classDef nf fill:#fef9c3,stroke:#eab308,color:#713f12,stroke-width:1px",
        "classDef p0 fill:#fee2e2,stroke:#ef4444,color:#991b1b,stroke-width:1.5px",
    ].join("\n");

    function esc(s) {
        return String(s || "")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    function escapeLabel(text, maxLen) {
        maxLen = maxLen || 40;
        let s = String(text || "")
            .replace(/["#[\](){}<>|]/g, " ")
            .replace(/\s+/g, " ")
            .trim();
        if (s.length > maxLen) s = s.slice(0, maxLen - 1) + "…";
        return s || "节点";
    }

    function nodeId(tcId) {
        return String(tcId || "TC").replace(/[^A-Za-z0-9]/g, "") || "TC";
    }

    function mindmapToFlowchart(source, rootTitle) {
        const text = (source || "").trim();
        if (!/^mindmap\b/im.test(text)) return text;

        let rootLabel = rootTitle || "测试范围";
        const modules = [];
        let currentMod = "用例覆盖";
        let bucket = [];

        function flush() {
            if (bucket.length) {
                modules.push({ name: currentMod, items: bucket.slice() });
                bucket = [];
            }
        }

        text.split("\n")
            .slice(1)
            .forEach((line) => {
                const stripped = line.trim();
                if (!stripped) return;

                const rootM = stripped.match(/root\s*\(\((.+?)\)\)|root\s*\((.+?)\)/i);
                if (rootM) {
                    rootLabel = (rootM[1] || rootM[2] || "").trim() || rootLabel;
                    return;
                }

                const tcM = stripped.match(/^\[?(TC-\d+)\]?\s*(.*)$/i);
                if (tcM) {
                    bucket.push({ id: tcM[1].toUpperCase(), desc: tcM[2].trim() });
                    return;
                }

                if (!/TC-\d+/i.test(stripped) && stripped.length <= 24) {
                    flush();
                    currentMod = stripped;
                }
            });
        flush();

        if (!modules.length) {
            return "flowchart TB\n  R([\"" + escapeLabel(rootLabel) + "\"]):::root\n" + STYLE_BLOCK;
        }

        const lines = ["flowchart TB", '  R(["' + escapeLabel(rootLabel) + '"]):::root'];
        modules.forEach((mod, i) => {
            const gid = "G" + (i + 1);
            const mid = "M" + (i + 1);
            const modLabel = escapeLabel(mod.name, 14);
            lines.push('  subgraph ' + gid + '["' + modLabel + '"]');
            lines.push("    direction TB");
            lines.push('    ' + mid + '["' + modLabel + '"]:::mod');
            mod.items.forEach((item) => {
                const nid = nodeId(item.id);
                const label = escapeLabel(item.id + " " + item.desc, 38);
                lines.push('    ' + nid + '["' + label + '"]:::tc');
                lines.push("    " + mid + " --> " + nid);
            });
            lines.push("  end");
            lines.push("  R --> " + mid);
        });
        lines.push(STYLE_BLOCK);
        return lines.join("\n");
    }

    function flowchartFromTable(caseTable, title) {
        const rows = [];
        (caseTable || "").split("\n").forEach((line) => {
            const t = line.trim();
            if (!t.startsWith("|") || /^\|\s*[-:]+\s*\|/.test(t)) return;
            const cells = t
                .replace(/^\|/, "")
                .replace(/\|$/, "")
                .split("|")
                .map((c) => c.trim());
            if (cells.length < 2 || !/^TC-\d+$/i.test(cells[0])) return;
            rows.push({
                id: cells[0].toUpperCase(),
                module: cells[1] || "用例",
                hint: (cells[3] || "").slice(0, 20),
            });
        });

        const root = title || "测试范围";
        if (!rows.length) {
            return 'flowchart TB\n  R(["' + escapeLabel(root) + '"]):::root\n' + STYLE_BLOCK;
        }

        const byMod = {};
        rows.forEach((r) => {
            if (!byMod[r.module]) byMod[r.module] = [];
            byMod[r.module].push(r);
        });

        const lines = ["flowchart TB", '  R(["' + escapeLabel(root) + '"]):::root'];
        Object.keys(byMod).forEach((modName, i) => {
            const gid = "G" + (i + 1);
            const mid = "M" + (i + 1);
            const modLabel = escapeLabel(modName, 14);
            lines.push('  subgraph ' + gid + '["' + modLabel + '"]');
            lines.push("    direction TB");
            lines.push('    ' + mid + '["' + modLabel + '"]:::mod');
            byMod[modName].forEach((item) => {
                const nid = nodeId(item.id);
                const label = escapeLabel(item.id + " " + item.hint, 38);
                lines.push('    ' + nid + '["' + label + '"]:::tc');
                lines.push("    " + mid + " --> " + nid);
            });
            lines.push("  end");
            lines.push("  R --> " + mid);
        });
        lines.push(STYLE_BLOCK);
        return lines.join("\n");
    }

    function prepareMermaidSource(source, opts) {
        opts = opts || {};
        let src = (source || "").trim();
        if (!src) {
            if (opts.caseTable) {
                return { src: flowchartFromTable(opts.caseTable, opts.title), converted: false };
            }
            return { src: "", converted: false };
        }

        let converted = false;
        if (/^mindmap\b/im.test(src)) {
            src = mindmapToFlowchart(src, opts.title);
            converted = true;
        }

        if (!/^(flowchart|graph)\b/im.test(src) && opts.caseTable) {
            src = flowchartFromTable(opts.caseTable, opts.title);
            converted = true;
        }

        if (!/classDef\s+root/i.test(src)) {
            src = src + "\n" + STYLE_BLOCK;
        }

        return { src, converted };
    }

    function loadMermaid() {
        if (window.mermaid) return Promise.resolve(window.mermaid);
        if (loadPromise) return loadPromise;
        loadPromise = new Promise((resolve, reject) => {
            const existing = document.querySelector('script[data-case-mermaid="1"]');
            if (existing) {
                existing.addEventListener("load", () => resolve(window.mermaid));
                existing.addEventListener("error", () => reject(new Error("Mermaid 加载失败")));
                return;
            }
            const s = document.createElement("script");
            s.src = MERMAID_URL;
            s.async = true;
            s.dataset.caseMermaid = "1";
            s.onload = () => {
                window.mermaid.initialize({
                    startOnLoad: false,
                    theme: "base",
                    themeVariables: {
                        fontFamily: '"Segoe UI", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif',
                        fontSize: "13px",
                        primaryColor: "#e0f2fe",
                        primaryTextColor: "#0f172a",
                        primaryBorderColor: "#38bdf8",
                        secondaryColor: "#f1f5f9",
                        secondaryTextColor: "#334155",
                        secondaryBorderColor: "#cbd5e1",
                        tertiaryColor: "#f8fafc",
                        lineColor: "#94a3b8",
                        textColor: "#334155",
                        mainBkg: "#ffffff",
                        nodeBorder: "#cbd5e1",
                        clusterBkg: "#f8fafc",
                        clusterBorder: "#e2e8f0",
                        titleColor: "#0f172a",
                        edgeLabelBackground: "#ffffff",
                    },
                    securityLevel: "strict",
                    flowchart: {
                        useMaxWidth: true,
                        htmlLabels: true,
                        curve: "basis",
                        padding: 18,
                        nodeSpacing: 32,
                        rankSpacing: 44,
                    },
                });
                resolve(window.mermaid);
            };
            s.onerror = () => reject(new Error("Mermaid 加载失败"));
            document.head.appendChild(s);
        });
        return loadPromise;
    }

    async function renderDiagram(container, source, opts) {
        if (!container) return;
        const raw = (source || "").trim();
        const loadingClass = (opts && opts.loadingClass) || "case-mermaid-loading";
        const kind = (opts && opts.kind) || "review";
        if (!raw && !(opts && opts.caseTable)) {
            container.innerHTML = "";
            container.style.display = "none";
            return;
        }
        container.style.display = "";
        container.innerHTML = '<div class="' + loadingClass + '">渲染图表…</div>';

        const mermaid = await loadMermaid();
        let { src, converted } = prepareMermaidSource(raw, opts);
        const id = "case-mmd-" + ++renderSeq + "-" + Date.now();

        async function tryRender(code, suffix) {
            return mermaid.render(id + (suffix || ""), code);
        }

        try {
            let result = await tryRender(src, "");
            let note = converted
                ? '<p class="case-mermaid-legacy-hint">已自动将 mindmap 转为 flowchart 以便正常显示</p>'
                : "";
            container.innerHTML =
                '<div class="case-mermaid-diagram case-mermaid-diagram--' +
                kind +
                '">' +
                result.svg +
                "</div>" +
                note;
        } catch (e1) {
            try {
                const fixed = mindmapToFlowchart(raw, (opts && opts.title) || "测试范围");
                if (fixed !== raw) {
                    const result = await tryRender(fixed, "-fix");
                    container.innerHTML =
                        '<div class="case-mermaid-diagram case-mermaid-diagram--' +
                        kind +
                        '">' +
                        result.svg +
                        '</div><p class="case-mermaid-legacy-hint">原 Mermaid 语法有误，已自动修复并渲染</p>';
                    return;
                }
                if (opts && opts.caseTable) {
                    const fromTable = flowchartFromTable(opts.caseTable, opts.title);
                    const result = await tryRender(fromTable, "-table");
                    container.innerHTML =
                        '<div class="case-mermaid-diagram case-mermaid-diagram--' +
                        kind +
                        '">' +
                        result.svg +
                        '</div><p class="case-mermaid-legacy-hint">图表源码无法解析，已根据用例表自动生成覆盖树</p>';
                    return;
                }
            } catch (e2) {
                /* fall through */
            }
            container.innerHTML =
                '<pre class="case-mermaid-src">' +
                esc(raw) +
                "</pre>" +
                '<p class="hint case-mermaid-err">图表渲染失败（' +
                esc(e1.message || e1) +
                "）</p>";
        }
    }

    async function renderCaseDiagrams(reviewEl, treeEl, reviewSrc, treeSrc, meta) {
        meta = meta || {};
        const opts = { title: meta.title, caseTable: meta.caseTable };
        await Promise.all([
            renderDiagram(reviewEl, reviewSrc, Object.assign({ kind: "review" }, opts)),
            renderDiagram(treeEl, treeSrc, Object.assign({ kind: "tree" }, opts)),
        ]);
    }

    window.CaseMermaid = {
        loadMermaid,
        renderDiagram,
        renderCaseDiagrams,
        prepareMermaidSource,
        mindmapToFlowchart,
        flowchartFromTable,
    };
})();
