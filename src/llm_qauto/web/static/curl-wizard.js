/**
 * cURL 向导：粘贴 curl → 选场景 → 补全追问 → 生成测试项目 YAML
 */
(function () {
    const SCENES = {
        prompt_rewrite_qc: {
            label: "帮写 Prompt 优化（L1 文本质检）",
            description: "评帮写后的正向/反向提示词是否保真、解耦、合规",
            exampleId: null,
        },
        listing_qc: {
            label: "Listing 文案七维质检",
            description: "基于 CDQ 七维单次全评（复用示例模板）",
            exampleId: "example_de_copyinfo_regenerate_listing_qc_rubric_batch",
        },
        image_gen: {
            label: "生图质量测评",
            description: "图片交付 + 视觉 LLM 评委",
            exampleId: null,
        },
        generic: {
            label: "通用接口质检",
            description: "内容质量 / 安全 / 格式 三维单次全评",
            exampleId: null,
        },
    };

    const PROMPT_REWRITE_DIMS = [
        { id: "intent_fidelity", name: "意图保真", weight: 0.25, criteria: "原始诉求完整保留、无曲解遗漏" },
        { id: "pos_neg_decouple", name: "正反向解耦", weight: 0.2, criteria: "正向无否定词，反向无肯定诉求；比例类诉求转正向构图" },
        { id: "format_compliance", name: "格式规范", weight: 0.1, criteria: "含「正向提示词」「反向提示词」结构或约定格式" },
        { id: "professional_rewrite", name: "专业化改写", weight: 0.15, criteria: "口语转商业摄影/构图/光影等专业表达" },
        { id: "compliance_coverage", name: "电商合规", weight: 0.15, criteria: "覆盖无文字/Logo/水印/促销标签等合规要求" },
        { id: "no_hallucination", name: "无臆造", weight: 0.15, criteria: "不臆造颜色/材质/数量/会改变产品本质的元素" },
    ];

    const GENERIC_DIMS = [
        { id: "content_quality", name: "内容质量", weight: 0.4, criteria: "准确、完整、可读，无明显错误或胡编" },
        { id: "safety_compliance", name: "安全合规", weight: 0.35, criteria: "无违法违规、歧视、隐私泄露或不当内容" },
        { id: "format_check", name: "格式规范", weight: 0.25, criteria: "符合预期格式与字段齐全" },
    ];

    let wizardStep = 1;
    let wizardAnswers = {};

    function parseIdValues(text) {
        const t = String(text || "").trim();
        if (!t) return ["1914"];
        const range = t.match(/^(\d+)\s*[-–—]\s*(\d+)$/);
        if (range) {
            const a = parseInt(range[1], 10);
            const b = parseInt(range[2], 10);
            if (a <= b && b - a <= 500) {
                const out = [];
                for (let i = a; i <= b; i++) out.push(String(i));
                return out;
            }
        }
        return t.split(/[\n,;|\s]+/).map((s) => s.trim()).filter(Boolean);
    }

    function applyCurlToObj(obj, curlText) {
        const parsed = window.parseBrowserCurl(curlText);
        let urlObj;
        try {
            urlObj = new URL(parsed.url);
        } catch {
            urlObj = null;
        }
        const upperMethod = (parsed.method || "GET").toUpperCase();
        let endpoint;
        let curlVarsApplied = false;

        if (upperMethod === "GET" && urlObj && urlObj.search && urlObj.search.length > 1) {
            endpoint = urlObj.origin + urlObj.pathname;
            const queryObj = {};
            new URLSearchParams(urlObj.search).forEach((v, k) => {
                queryObj[k] = v;
            });
            curlVarsApplied = window.applyCurlPrimitivesAsTemplateAndVariables(obj, queryObj);
            if (!curlVarsApplied) obj.target.input_formatter.template = queryObj;
        } else {
            if (urlObj) endpoint = urlObj.origin + urlObj.pathname + urlObj.search;
            else endpoint = parsed.url.split("#")[0];
            if (parsed.body != null && String(parsed.body).trim() !== "") {
                const rawB = String(parsed.body).trim();
                if (rawB.startsWith("@")) throw new Error("不支持 @ 文件请求体，请粘贴 JSON");
                let bodyObj;
                try {
                    bodyObj = JSON.parse(rawB);
                } catch (e) {
                    throw new Error("请求体不是合法 JSON：" + (e.message || String(e)));
                }
                curlVarsApplied = window.applyCurlPrimitivesAsTemplateAndVariables(obj, bodyObj);
                if (!curlVarsApplied) obj.target.input_formatter.template = bodyObj;
            } else if (upperMethod === "GET") {
                obj.target.input_formatter.template = {};
            }
        }

        obj.target.connector.config.endpoint = endpoint;
        obj.target.connector.config.method = upperMethod;
        obj.target.connector.config.headers = window.filterCurlHeaders(parsed.headers);
        return { curlVarsApplied, selectionNote: parsed.selectionNote || "" };
    }

    function applyEnvHeaders(obj, useEnv) {
        const h = obj.target.connector.config.headers || {};
        if (useEnv) {
            h.Authorization = "Bearer ${ZHIYUAN_BEARER_TOKEN}";
            if (!Object.keys(h).some((k) => k.toLowerCase() === "tenant-id")) {
                h["tenant-id"] = "${TENANT_ID}";
            }
        }
        obj.target.connector.config.headers = h;
    }

    function buildBatchPromptBody(intro, dims, extraBeforeOutput) {
        const lines = dims.map((d, i) => `${i + 1}. ${d.id}（${d.name}，权重 ${Math.round(d.weight * 100)}%）：${d.criteria}`);
        let body = `${intro}\n\n【各维检查要点】\n${lines.join("\n")}`;
        if (extraBeforeOutput) body += `\n\n${extraBeforeOutput}`;
        const ids = dims.map((d) => d.id);
        return `${body}\n\n${window.buildBatchLlmPromptTail(ids)}`;
    }

    function freshConfigObj() {
        const obj = { target: { type: "api" } };
        window.ensureConfigSkeleton(obj);
        return obj;
    }

    function buildPromptRewriteConfig(answers, curlMeta) {
        const obj = freshConfigObj();
        applyCurlToObj(obj, answers.targetCurl);
        applyEnvHeaders(obj, answers.useEnvToken === true);

        const rawField = answers.rawPromptField || "rawPrompt";
        const imageTypeField = answers.imageTypeField || "imageType";
        const rawVar = rawField.replace(/^input\.variables\./, "");
        const imgVar = imageTypeField.replace(/^input\.variables\./, "");
        const tpl = obj.target.input_formatter.template;
        if (tpl && typeof tpl === "object" && !Array.isArray(tpl)) {
            if (!(rawVar in tpl)) tpl[rawField.includes(".") ? rawField : rawVar] = `{{ input.variables.${rawVar} }}`;
            if (!(imgVar in tpl)) tpl[imageTypeField.includes(".") ? imageTypeField : imgVar] = `{{ input.variables.${imgVar} }}`;
            if (!("site" in tpl)) tpl.site = "{{ input.variables.site }}";
        }

        obj.meta.name = answers.suiteName || "prompt-rewrite-qc";
        obj.meta.version = "1.0.0";
        obj.meta.description = answers.suiteDesc || "帮写 Prompt L1 文本质检";

        obj.target.output_parser.path = answers.outputPath || "data";
        if (answers.outputKeys) {
            obj.target.output_parser.keys = answers.outputKeys.split(/[,，\s]+/).filter(Boolean);
        }

        const idValues = parseIdValues(answers.idValues);

        const vars = [{ name: "id", type: "enum", values: idValues }];
        if (!obj.data_generator.variables.some((v) => v.name === rawVar)) {
            vars.push({
                name: rawVar,
                type: "enum",
                values: [answers.sampleRawPrompt || "要欧美模特，不要文字"],
            });
        }
        if (!obj.data_generator.variables.some((v) => v.name === imgVar)) {
            vars.push({ name: imgVar, type: "enum", values: [answers.sampleImageType || "场景图"] });
        }
        if (!obj.data_generator.variables.some((v) => v.name === "site")) {
            vars.push({ name: "site", type: "enum", values: [answers.sampleSite || "DE"] });
        }
        if (answers.includeProductName) {
            vars.push({
                name: "productName",
                type: "enum",
                values: [answers.sampleProductName || "锚点产品名"],
            });
        }

        obj.data_generator.strategy = "template_cartesian";
        obj.data_generator.variables = mergeVariables(obj.data_generator.variables, vars);
        obj.data_generator.prompt_template = "{{ vars.id }}";
        obj.data_generator.sampling = { total: idValues.length };

        const anchorLines = [`【原始口语】{{ ${rawVar} }}`, `【图类型】{{ ${imgVar} }}`, `【站点】{{ site }}`];
        if (answers.includeProductName) anchorLines.push(`【产品锚点】{{ productName }}`);
        const intro = `你是 AI 帮写 Prompt 质检员。对比【原始口语】与【帮写 API 返回】，按维度 0～10 打分。
硬门槛：intent_fidelity≥8.0、no_hallucination≥8.0、pos_neg_decouple≥7.5。

${anchorLines.join("\n")}`;

        const dimension_ids = PROMPT_REWRITE_DIMS.map((d) => d.id);
        obj.evaluation.aggregation_method = "weighted_average";
        obj.evaluation.batch_llm = {
            model: "deepseek-v4-pro",
            temperature: 0.08,
            max_tokens: 4000,
            max_judge_input_chars: 14000,
            use_cache: true,
            dimension_ids,
            prompt_template: buildBatchPromptBody(intro, PROMPT_REWRITE_DIMS, null),
        };
        obj.evaluation.dimensions = PROMPT_REWRITE_DIMS.map((d) => ({
            id: d.id,
            name: d.name,
            description: d.criteria,
            weight: d.weight,
            evaluators: [],
        }));

        obj.pass_criteria = {
            global_criteria: { min_total_score: Number(answers.minTotalScore) || 7.0 },
            dimensions: [
                { id: "intent_fidelity", min_avg_score: 8.0 },
                { id: "no_hallucination", min_avg_score: 8.0 },
                { id: "pos_neg_decouple", min_avg_score: 7.5 },
            ],
            statistical: { confidence_level: 0.95, min_sample_size: 1 },
        };

        obj.target.connector.config.timeout = 120;
        obj.target.connector.config.retry = 2;
        obj.target.connector.config.concurrency = 2;
        return obj;
    }

    function mergeVariables(existing, incoming) {
        const map = new Map((existing || []).map((v) => [v.name, v]));
        incoming.forEach((v) => {
            if (map.has(v.name)) {
                const prev = map.get(v.name);
                map.set(v.name, { ...prev, values: v.values });
            } else {
                map.set(v.name, v);
            }
        });
        return Array.from(map.values());
    }

    async function buildListingConfig(answers) {
        const scene = SCENES.listing_qc;
        const { data } = await apiFetch(`/api/projects/${encodeURIComponent(scene.exampleId)}`);
        const obj = window.yamlLib().load(data.config_yaml);
        applyCurlToObj(obj, answers.targetCurl);
        applyEnvHeaders(obj, answers.useEnvToken === true);

        obj.meta.name = answers.suiteName || obj.meta.name;
        obj.meta.description = answers.suiteDesc || obj.meta.description;

        if (answers.idValues) {
            const idValues = parseIdValues(answers.idValues);
            const vars = obj.data_generator.variables || [];
            const idVar = vars.find((v) => v.name === "id");
            if (idVar) idVar.values = idValues;
            else vars.unshift({ name: "id", type: "enum", values: idValues });
            obj.data_generator.variables = vars;
            obj.data_generator.sampling = { total: idValues.length };
        }

        if (answers.asyncPoll === "yes" && answers.pollCurl) {
            try {
                const poll = window.parseBrowserCurl(answers.pollCurl);
                let pollUrl;
                try {
                    pollUrl = new URL(poll.url);
                } catch {
                    pollUrl = null;
                }
                obj.target.connector.config.invoke_poll = {
                    enabled: true,
                    endpoint: pollUrl ? pollUrl.origin + pollUrl.pathname : poll.url.split("?")[0],
                    method: (poll.method || "GET").toUpperCase(),
                    query: { id: "{{ input.variables.id }}" },
                    ready_path: answers.readyPath || "data.title",
                    timeout: 30,
                };
            } catch (e) {
                throw new Error("Poll cURL 解析失败：" + e.message);
            }
        }

        return obj;
    }

    function buildImageGenConfig(answers) {
        const obj = freshConfigObj();
        applyCurlToObj(obj, answers.targetCurl);
        applyEnvHeaders(obj, answers.useEnvToken === true);

        obj.meta.name = answers.suiteName || "image-gen-qc";
        obj.meta.version = "1.0.0";
        obj.meta.description = answers.suiteDesc || "生图质量测评";

        obj.target.output_parser.path = answers.outputPath || "data";
        obj.target.output_parser.content_mode = "image";
        obj.target.output_parser.media = {
            urls_path: answers.mediaUrlsPath || "0.url",
            download: true,
            max_images: 4,
        };
        if (answers.outputKeys) {
            obj.target.output_parser.keys = answers.outputKeys.split(/[,，\s]+/).filter(Boolean);
        }

        const idValues = parseIdValues(answers.idValues);
        obj.data_generator.variables = mergeVariables(obj.data_generator.variables, [
            { name: "id", type: "enum", values: idValues },
        ]);
        obj.data_generator.sampling = { total: idValues.length };

        obj.evaluation.dimensions = [
            {
                id: "image_delivery",
                name: "图片交付",
                weight: 0.3,
                evaluators: [
                    {
                        type: "image_rule",
                        rules: [
                            { name: "至少一张图", condition: "media_count >= 1", severity: "error" },
                            { name: "图片落盘", condition: "all_images_ok", severity: "error" },
                        ],
                    },
                ],
            },
            {
                id: "vision_quality",
                name: "画面质量与一致",
                weight: 0.7,
                evaluators: [
                    {
                        type: "vision_llm",
                        model: "gpt-4o",
                        temperature: 0.1,
                        max_tokens: 1800,
                        prompt_template:
                            "你是视觉质检员。根据用户 prompt 与生成图片，评估图文一致性、画面质量、电商合规（无文字水印）。\n\n用户 prompt：{{ prompt }}\n\n接口返回摘要：{{ output }}\n\n返回 JSON：{\"score\":0-10,\"categories\":[],\"issues\":[],\"evidence\":\"\"}",
                    },
                ],
            },
        ];
        obj.pass_criteria = {
            global_criteria: { min_total_score: 6.0 },
            dimensions: [{ id: "vision_quality", min_avg_score: 6.0 }],
            statistical: { confidence_level: 0.95, min_sample_size: 1 },
        };
        return obj;
    }

    function buildGenericConfig(answers) {
        const obj = freshConfigObj();
        applyCurlToObj(obj, answers.targetCurl);
        applyEnvHeaders(obj, answers.useEnvToken === true);

        obj.meta.name = answers.suiteName || "generic-api-qc";
        obj.meta.version = "1.0.0";
        obj.meta.description = answers.suiteDesc || "通用接口质检";

        obj.target.output_parser.path = answers.outputPath || "data";
        const idValues = parseIdValues(answers.idValues);
        obj.data_generator.variables = mergeVariables(obj.data_generator.variables, [
            { name: "id", type: "enum", values: idValues },
        ]);
        obj.data_generator.sampling = { total: idValues.length };

        const dimension_ids = GENERIC_DIMS.map((d) => d.id);
        obj.evaluation.batch_llm = {
            model: "deepseek-v4-pro",
            temperature: 0.1,
            max_tokens: 3000,
            max_judge_input_chars: 14000,
            use_cache: true,
            dimension_ids,
            prompt_template: buildBatchPromptBody(
                "你是内容质检员。请根据接口返回，一次性完成下列全部维度的评分（0～10）。",
                GENERIC_DIMS,
                null
            ),
        };
        obj.evaluation.dimensions = GENERIC_DIMS.map((d) => ({
            id: d.id,
            name: d.name,
            description: d.criteria,
            weight: d.weight,
            evaluators: [],
        }));
        obj.pass_criteria = {
            global_criteria: { min_total_score: Number(answers.minTotalScore) || 6.0 },
            dimensions: [],
            statistical: { confidence_level: 0.95, min_sample_size: 1 },
        };
        return obj;
    }

    async function generateConfigFromWizard(answers) {
        let curlMeta = {};
        const scene = answers.scene;
        if (!answers.targetCurl || !answers.targetCurl.trim()) {
            throw new Error("请粘贴被测接口 cURL");
        }
        if (scene === "listing_qc") return buildListingConfig(answers);
        if (scene === "prompt_rewrite_qc") {
            const obj = buildPromptRewriteConfig(answers, curlMeta);
            return obj;
        }
        if (scene === "image_gen") return buildImageGenConfig(answers);
        return buildGenericConfig(answers);
    }

    function collectWizardAnswers() {
        const g = (id) => document.getElementById(id)?.value?.trim() ?? "";
        const scene = g("wizard-scene") || wizardAnswers.scene;
        return {
            scene,
            targetCurl: g("wizard-target-curl"),
            pageCurl: g("wizard-page-curl"),
            suiteName: g("wizard-suite-name"),
            suiteDesc: g("wizard-suite-desc"),
            outputPath: g("wizard-output-path") || "data",
            outputKeys: g("wizard-output-keys"),
            idValues: g("wizard-id-values") || "1914",
            useEnvToken: document.getElementById("wizard-use-env")?.checked === true,
            rawPromptField: g("wizard-raw-field") || "rawPrompt",
            imageTypeField: g("wizard-image-type-field") || "imageType",
            sampleRawPrompt: g("wizard-sample-raw"),
            sampleImageType: g("wizard-sample-image-type"),
            sampleSite: g("wizard-sample-site") || "DE",
            sampleProductName: g("wizard-sample-product"),
            includeProductName: document.getElementById("wizard-include-product")?.checked,
            minTotalScore: g("wizard-min-score") || "7.0",
            asyncPoll: g("wizard-async-poll"),
            pollCurl: g("wizard-poll-curl"),
            readyPath: g("wizard-ready-path") || "data.title",
            mediaUrlsPath: g("wizard-media-path") || "0.url",
        };
    }

    function renderWizardFollowUp(scene) {
        const box = document.getElementById("wizard-followup-fields");
        if (!box) return;
        const common = `
<div class="form-group"><label>响应 JSON 根路径</label>
<input type="text" id="wizard-output-path" value="data" placeholder="data" /></div>
<div class="form-group"><label>测试 id（换行 / 逗号 / 范围 8001-8050）</label>
<input type="text" id="wizard-id-values" placeholder="1914 或 8001-8050" /></div>
<div class="form-group"><label class="cfg-wizard-check"><input type="checkbox" id="wizard-use-env" /> Token 改用 .env（\${ZHIYUAN_BEARER_TOKEN} / \${TENANT_ID}）</label></div>`;

        let extra = "";
        if (scene === "prompt_rewrite_qc") {
            extra = `
<div class="form-group"><label>原始口语字段名（body 里）</label><input type="text" id="wizard-raw-field" value="rawPrompt" /></div>
<div class="form-group"><label>图类型字段名</label><input type="text" id="wizard-image-type-field" value="imageType" /></div>
<div class="form-group"><label>示例原始口语</label><input type="text" id="wizard-sample-raw" value="要欧美模特，不要文字，产品小一点" /></div>
<div class="form-group"><label>示例图类型</label><input type="text" id="wizard-sample-image-type" value="场景图" /></div>
<div class="form-group"><label class="cfg-wizard-check"><input type="checkbox" id="wizard-include-product" /> 增加 productName 锚点变量</label></div>
<div class="form-group wizard-optional-product" style="display:none"><label>示例 productName</label><input type="text" id="wizard-sample-product" placeholder="锚点产品名" /></div>
<div class="form-group"><label>整批平均分下限</label><input type="text" id="wizard-min-score" value="7.0" /></div>`;
        } else if (scene === "listing_qc") {
            extra = `
<div class="form-group"><label>是否异步（regenerate 后 GET 拉结果）</label>
<select id="wizard-async-poll"><option value="no">否 / 同步返回</option><option value="yes">是，粘贴 poll GET cURL</option></select></div>
<div class="form-group wizard-poll-block" style="display:none"><label>Poll GET cURL</label>
<textarea id="wizard-poll-curl" class="cfg-curl-textarea" rows="3" placeholder="copy-info/get?id=…"></textarea></div>
<div class="form-group wizard-poll-block" style="display:none"><label>就绪判定路径</label>
<input type="text" id="wizard-ready-path" value="data.title" /></div>`;
        } else if (scene === "image_gen") {
            extra = `
<div class="form-group"><label>图片 URL 相对 path</label><input type="text" id="wizard-media-path" value="0.url" /></div>
<div class="form-group"><label>文本字段 keys（可选，逗号分隔）</label><input type="text" id="wizard-output-keys" placeholder="revised_prompt" /></div>`;
        } else {
            extra = `<div class="form-group"><label>整批平均分下限</label><input type="text" id="wizard-min-score" value="6.0" /></div>`;
        }

        box.innerHTML = common + extra;

        document.getElementById("wizard-include-product")?.addEventListener("change", (e) => {
            const w = document.querySelector(".wizard-optional-product");
            if (w) w.style.display = e.target.checked ? "block" : "none";
        });
        document.getElementById("wizard-async-poll")?.addEventListener("change", (e) => {
            document.querySelectorAll(".wizard-poll-block").forEach((el) => {
                el.style.display = e.target.value === "yes" ? "block" : "none";
            });
        });
    }

    function renderWizardSummary(answers) {
        const pre = document.getElementById("wizard-summary-pre");
        if (!pre) return;
        const sceneLabel = SCENES[answers.scene]?.label || answers.scene;
        pre.textContent = [
            `场景：${sceneLabel}`,
            `套件名：${answers.suiteName || "（自动生成）"}`,
            `测试条数：约 ${parseIdValues(answers.idValues).length} 条`,
            `输出 path：${answers.outputPath}`,
            answers.useEnvToken === true ? "鉴权：使用 .env 占位符" : "鉴权：保留 cURL 内 Token",
            "",
            "点击「生成并编辑」后进入表单，可再微调评委与测试数据。",
        ].join("\n");
    }

    function setWizardStep(step) {
        wizardStep = step;
        document.querySelectorAll(".cfg-wizard-step-panel").forEach((el) => {
            el.style.display = el.dataset.step === String(step) ? "block" : "none";
        });
        document.querySelectorAll(".cfg-wizard-step-dot").forEach((el) => {
            const n = Number(el.dataset.step);
            el.classList.toggle("active", n === step);
            el.classList.toggle("done", n < step);
        });
        const prevBtn = document.getElementById("wizard-btn-prev");
        const nextBtn = document.getElementById("wizard-btn-next");
        const genBtn = document.getElementById("wizard-btn-generate");
        const createBtn = document.getElementById("wizard-btn-create");
        if (prevBtn) prevBtn.style.display = step > 1 ? "inline-flex" : "none";
        if (nextBtn) nextBtn.style.display = step < 4 ? "inline-flex" : "none";
        if (genBtn) genBtn.style.display = step === 4 ? "inline-flex" : "none";
        if (createBtn) createBtn.style.display = step === 4 ? "inline-flex" : "none";
    }

    function validateWizardStep(step) {
        if (step === 1) {
            const curl = document.getElementById("wizard-target-curl")?.value?.trim();
            if (!curl) {
                alert("请粘贴被测接口 cURL");
                return false;
            }
            try {
                window.parseBrowserCurl(curl);
            } catch (e) {
                alert(e.message || String(e));
                return false;
            }
        }
        if (step === 2) {
            const scene = document.getElementById("wizard-scene")?.value;
            const name = document.getElementById("wizard-suite-name")?.value?.trim();
            if (!scene) {
                alert("请选择测评场景");
                return false;
            }
            if (!name) {
                alert("请填写套件名称");
                return false;
            }
            wizardAnswers.scene = scene;
            renderWizardFollowUp(scene);
        }
        if (step === 3) {
            wizardAnswers = collectWizardAnswers();
        }
        return true;
    }

    function wizardNext() {
        if (!validateWizardStep(wizardStep)) return;
        if (wizardStep === 3) {
            wizardAnswers = collectWizardAnswers();
            renderWizardSummary(wizardAnswers);
        }
        setWizardStep(Math.min(4, wizardStep + 1));
    }

    function wizardPrev() {
        setWizardStep(Math.max(1, wizardStep - 1));
    }

    async function wizardGenerate(andCreate) {
        wizardAnswers = collectWizardAnswers();
        try {
            const obj = await generateConfigFromWizard(wizardAnswers);
            const yamlText = window.yamlLib().dump(obj, { lineWidth: 120, noRefs: true });
            hideModal("curl-wizard-modal");

            if (andCreate) {
                const name = wizardAnswers.suiteName || obj.meta.name;
                const { data } = await apiFetch("/api/projects", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ name, config_yaml: yamlText }),
                });
                if (data.success) {
                    showSection("projects");
                    loadProjects();
                    alert("测试项目已创建！");
                }
                return;
            }

            if (typeof resetCreateConfigEditor === "function") resetCreateConfigEditor();
            document.getElementById("new-project-config").value = yamlText;
            if (typeof refreshFormFromYaml === "function") {
                refreshFormFromYaml("create");
                setConfigFormSubtab("create", "http");
            }
            showModal("create-modal");
            if (typeof setApiStatus === "function") {
                setApiStatus("cURL 向导已生成配置", "ok");
            }
        } catch (e) {
            alert("生成失败：" + (e.message || String(e)));
        }
    }

    function showCurlWizardModal() {
        wizardStep = 1;
        wizardAnswers = {};
        const ta = document.getElementById("wizard-target-curl");
        if (ta) ta.value = "";
        const pageTa = document.getElementById("wizard-page-curl");
        if (pageTa) pageTa.value = "";
        document.getElementById("wizard-suite-name").value = "";
        document.getElementById("wizard-suite-desc").value = "";
        const sceneSel = document.getElementById("wizard-scene");
        if (sceneSel) {
            sceneSel.value = "prompt_rewrite_qc";
            sceneSel.onchange = () => {
                const hint = document.getElementById("wizard-scene-hint");
                if (hint) hint.textContent = SCENES[sceneSel.value]?.description || "";
            };
            sceneSel.dispatchEvent(new Event("change"));
        }
        setWizardStep(1);
        showModal("curl-wizard-modal");
    }

    window.showCurlWizardModal = showCurlWizardModal;
    window.wizardNext = wizardNext;
    window.wizardPrev = wizardPrev;
    window.wizardGenerate = wizardGenerate;
})();
