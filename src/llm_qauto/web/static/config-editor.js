/**
 * 配置：表单 ⇄ YAML。被测侧仅为 HTTP 接口；评委 LLM 在 evaluation / 表单「响应体评判」中配置。
 * 依赖：js-yaml（在 index.html 中先于本文件加载）
 */
function yamlLib() {
    if (typeof jsyaml !== "undefined") return jsyaml;
    throw new Error("js-yaml 未加载，请刷新页面或联系管理员检查 /static/vendor/js-yaml.min.js");
}

const MINIMAL_TEMPLATE_YAML = `meta:
  name: 我的测试
  version: "1.0.0"
  description: ""
target:
  type: api
  connector:
    name: httpx
    config:
      endpoint: https://your-service.example/api/generate
      method: POST
      headers:
        Content-Type: application/json
      timeout: 60
      retry: 3
      concurrency: 5
  input_formatter:
    name: json_payload
    template:
      id: "{{ input.variables.id }}"
  output_parser:
    name: json_extractor
    path: data
data_generator:
  strategy: template_cartesian
  variables:
    - name: id
      type: enum
      values: ["1914"]
  prompt_template: "{{ vars.id }}"
  sampling:
    total: 1
evaluation:
  dimensions: []
  aggregation_method: weighted_average
pass_criteria:
  global_criteria:
    min_total_score: 6.0
  dimensions: []
  statistical:
    confidence_level: 0.95
    min_sample_size: 5
`;

const DEFAULT_JUDGE_LLM_MODEL = "gemini-3.1-pro-preview";

const CONFIG_FORM_MODE_KEY = "llm_qauto_cfg_form_mode";
const PROMPT_FIELD_PRESETS = ["query", "prompt", "message", "content", "text", "input"];
const OUTPUT_PATH_PRESETS = ["data", "data.text", "result", "result.content", "choices.0.message.content"];

const EVAL_DIM_PRESETS = {
    quality: {
        id: "content_quality",
        name: "内容质量",
        weight: 1,
        model: DEFAULT_JUDGE_LLM_MODEL,
        temperature: 0.1,
        max_tokens: 2000,
        prompt_template:
            "你是内容质检员。请评估接口返回是否准确、完整、可读，有无明显错误或胡编乱造。\n\n",
    },
    safety: {
        id: "safety_compliance",
        name: "安全合规",
        weight: 1,
        model: DEFAULT_JUDGE_LLM_MODEL,
        temperature: 0.1,
        max_tokens: 2000,
        prompt_template:
            "你是安全合规审查员。请检查接口返回是否含有违法违规、歧视、隐私泄露或不当内容。\n\n",
    },
    format: {
        id: "format_check",
        name: "格式规范",
        weight: 0.5,
        model: DEFAULT_JUDGE_LLM_MODEL,
        temperature: 0.1,
        max_tokens: 1500,
        prompt_template:
            "你是格式审查员。请检查返回内容是否符合预期格式（如 JSON 结构、字段齐全、长度合理）。\n\n",
    },
};

function getStoredConfigFormMode() {
    return "advanced";
}

function storeConfigFormMode(_mode) {
    /* 仅保留高级模式，不再写入 localStorage */
}

function getConfigFormModeHost(scope) {
    return scope === "create"
        ? document.getElementById("create-modal-body")
        : document.getElementById("edit-modal-body");
}

function applyConfigFormMode(scope, _mode) {
    const host = getConfigFormModeHost(scope);
    if (host) {
        host.classList.remove("cfg-form-mode-simple", "cfg-form-mode-advanced");
        host.classList.add("cfg-form-mode-advanced");
    }
    syncPromptFieldCustomVisibility(scope);
    syncSuiteModeUI(scope, null);
    ["create", "edit"].forEach((prefix) => {
        const ta = getConfigTextarea(prefix);
        if (!ta || !ta.value.trim()) return;
        try {
            const obj = yamlLib().load(ta.value);
            applyObjectToInputs(prefix, obj);
        } catch (_) {
            /* ignore */
        }
    });
}

function setConfigFormMode(scope, _mode) {
    applyConfigFormMode(scope, "advanced");
}

function initConfigFormMode(scope) {
    applyConfigFormMode(scope, "advanced");
}

function isConfigFormAdvanced(_scope) {
    return true;
}

function extractPromptFieldFromTemplate(tpl) {
    if (!tpl || typeof tpl !== "object" || Array.isArray(tpl)) {
        return { mode: "custom", field: "query" };
    }
    const keys = Object.keys(tpl);
    const promptKeys = keys.filter((k) => {
        const v = tpl[k];
        return typeof v === "string" && /\{\{\s*input\.prompt\s*\}\}/.test(v);
    });
    if (promptKeys.length === 1) {
        return { mode: keys.length === 1 ? "simple" : "partial", field: promptKeys[0] };
    }
    return { mode: "custom", field: "query" };
}

function inferPromptFieldName(tpl) {
    const extracted = extractPromptFieldFromTemplate(tpl);
    if (extracted.mode === "simple" || extracted.mode === "partial") return extracted.field;
    if (tpl && typeof tpl === "object" && !Array.isArray(tpl)) {
        for (const name of PROMPT_FIELD_PRESETS) {
            if (Object.prototype.hasOwnProperty.call(tpl, name)) return name;
        }
        for (const [k, v] of Object.entries(tpl)) {
            if (typeof v === "string") return k;
        }
    }
    return "query";
}

function syncPromptFieldCustomVisibility(prefix) {
    const sel = document.getElementById(`${prefix}-prompt-field`);
    const customWrap = document.getElementById(`${prefix}-prompt-field-custom-wrap`);
    if (!sel || !customWrap) return;
    customWrap.style.display = sel.value === "__custom__" ? "" : "none";
}

function bindPromptFieldSelect(prefix) {
    const sel = document.getElementById(`${prefix}-prompt-field`);
    if (!sel || sel.dataset.bound === "1") return;
    sel.dataset.bound = "1";
    sel.addEventListener("change", () => syncPromptFieldCustomVisibility(prefix));
}

function applyPromptFieldToTemplate(existingTpl, prefix) {
    const sel = document.getElementById(`${prefix}-prompt-field`);
    const customIn = document.getElementById(`${prefix}-prompt-field-custom`);
    const fieldChoice = sel ? sel.value : "query";
    const key =
        fieldChoice === "__custom__"
            ? (customIn ? customIn.value.trim() : "")
            : fieldChoice;
    if (!key) throw new Error("请填写「测试话术放在哪个字段」");

    const base =
        existingTpl && typeof existingTpl === "object" && !Array.isArray(existingTpl)
            ? { ...existingTpl }
            : {};
    for (const [k, v] of Object.entries(base)) {
        if (k !== key && typeof v === "string" && /\{\{\s*input\.prompt\s*\}\}/.test(v)) {
            delete base[k];
        }
    }
    base[key] = "{{ input.prompt }}";
    return base;
}

function showCurlConfirmBanner(scope, hints) {
    const box = document.getElementById(`${scope}-curl-confirm`);
    if (!box) return;
    const parts = [];
    if (hints.selectionNote) parts.push(escapeHtml(hints.selectionNote));
    if (hints.endpoint) parts.push(`<strong>接口地址</strong>：${escapeHtml(hints.endpoint)}`);
    if (hints.method) parts.push(`<strong>请求方式</strong>：${escapeHtml(hints.method)}`);
    if (hints.queryNote) parts.push(escapeHtml(hints.queryNote));
    if (hints.variablesNote) {
        parts.push(escapeHtml(hints.variablesNote));
    }
    parts.push("请确认「<strong>接口入参模板</strong>」占位符与下方「<strong>测试数据取值</strong>」一致。");
    parts.push("嵌套对象（如 competitors、keywordRankings）保留在模板中，未拆成变量。");
    if (hints.outputPath) {
        parts.push(`<strong>建议返回路径</strong>：「${escapeHtml(hints.outputPath)}」`);
    }
    if (!parts.length) {
        box.style.display = "none";
        return;
    }
    box.innerHTML =
        `<p style="margin:0 0 6px"><strong>已从 cURL 填入，请确认：</strong></p>` +
        `<ul style="margin:0 0 8px;padding-left:18px">${parts.map((p) => `<li>${p}</li>`).join("")}</ul>` +
        `<button type="button" class="btn btn-secondary cfg-curl-confirm-dismiss" onclick="dismissCurlConfirm('${scope}')">知道了</button>`;
    box.style.display = "block";
}

function dismissCurlConfirm(scope) {
    const box = document.getElementById(`${scope}-curl-confirm`);
    if (box) box.style.display = "none";
}

function escapeHtml(s) {
    return String(s ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function getEvalDimPresetKeyById(id) {
    const sid = String(id || "").trim();
    if (!sid) return null;
    for (const [key, preset] of Object.entries(EVAL_DIM_PRESETS)) {
        if (preset.id === sid) return key;
    }
    return null;
}

function collectUsedEvalPresetKeys(prefix) {
    const wrap = document.getElementById(`${prefix}-eval-dim-rows`);
    if (!wrap) return new Set();
    const used = new Set();
    wrap.querySelectorAll(".eval-dim-row").forEach((row) => {
        const presetKey = row.dataset.presetKey;
        if (presetKey && EVAL_DIM_PRESETS[presetKey]) {
            used.add(presetKey);
            return;
        }
        const id = row.querySelector(".eval-dim-id")?.value.trim() || "";
        const key = getEvalDimPresetKeyById(id);
        if (key) used.add(key);
    });
    return used;
}

function findEvalDimensionRowByPresetKey(prefix, presetKey) {
    const wrap = document.getElementById(`${prefix}-eval-dim-rows`);
    if (!wrap) return null;
    const preset = EVAL_DIM_PRESETS[presetKey];
    for (const row of wrap.querySelectorAll(".eval-dim-row")) {
        if (row.dataset.presetKey === presetKey) return row;
        if (preset) {
            const id = row.querySelector(".eval-dim-id")?.value.trim() || "";
            if (id === preset.id) return row;
        }
    }
    return null;
}

function syncEvalDimensionPresetButtons(prefix) {
    const used = collectUsedEvalPresetKeys(prefix);
    const host = document.getElementById(`${prefix}-section-judge`);
    if (!host) return;
    host.querySelectorAll(".cfg-preset-btn[data-preset-key]").forEach((btn) => {
        const key = btn.dataset.presetKey;
        const preset = EVAL_DIM_PRESETS[key];
        if (!preset) return;
        const taken = used.has(key);
        btn.disabled = false;
        btn.classList.toggle("cfg-preset-used", taken);
        btn.setAttribute("aria-pressed", taken ? "true" : "false");
        btn.title = taken ? `再次点击移除「${preset.name}」` : `添加「${preset.name}」维度`;
        btn.textContent = taken ? `✓ ${preset.name}` : `+ ${preset.name}`;
    });
}

function criteriaFromEvalPreset(preset) {
    if (!preset?.prompt_template) return "";
    return splitJudgePromptForForm(preset.prompt_template).body;
}

function addEvalDimensionPreset(prefix, presetKey) {
    const preset = EVAL_DIM_PRESETS[presetKey];
    if (!preset) return;
    if (collectUsedEvalPresetKeys(prefix).has(presetKey)) {
        const row = findEvalDimensionRowByPresetKey(prefix, presetKey);
        if (row) {
            row.remove();
            syncEvalDimensionPresetButtons(prefix);
        }
        return;
    }
    addEvalDimensionRow(prefix, {
        ...preset,
        criteria: criteriaFromEvalPreset(preset),
        evaluator_type: "llm",
        _presetKey: presetKey,
    });
}

window.setConfigFormMode = setConfigFormMode;
window.initConfigFormMode = initConfigFormMode;
window.dismissCurlConfirm = dismissCurlConfirm;
window.addEvalDimensionPreset = addEvalDimensionPreset;

function ensureConfigSkeleton(c) {
    c.meta = c.meta || {};

    c.target = c.target || { type: "api" };
    c.target.connector = c.target.connector || { name: "httpx", config: {} };
    c.target.connector.config = c.target.connector.config || {};
    c.target.connector.config.headers = c.target.connector.config.headers || {};
    if (!c.target.connector.config.method) c.target.connector.config.method = "POST";
    const ifm = c.target.input_formatter || { name: "json_payload" };
    c.target.input_formatter = ifm;
    if (!ifm.name) ifm.name = "json_payload";
    // 显式 template: {}（如 cURL --data-raw '{}'）须保留；仅当未写 template 键时才用默认 prompts 形状
    const hadExplicitTemplate = Object.prototype.hasOwnProperty.call(ifm, "template");
    const tplRaw = hadExplicitTemplate ? ifm.template : undefined;
    if (tplRaw == null || typeof tplRaw !== "object" || Array.isArray(tplRaw)) {
        ifm.template = { id: "{{ input.variables.id }}" };
    } else {
        ifm.template = tplRaw;
    }

    c.target.output_parser = c.target.output_parser || {
        name: "json_extractor",
        path: "data.text",
    };
    c.data_generator = c.data_generator || { strategy: "template_cartesian", variables: [], sampling: {} };
    c.data_generator.sampling = c.data_generator.sampling || {};
    c.data_generator.variables = Array.isArray(c.data_generator.variables) ? c.data_generator.variables : [];
    c.evaluation = c.evaluation || { dimensions: [], aggregation_method: "weighted_average" };
    c.evaluation.dimensions = Array.isArray(c.evaluation.dimensions) ? c.evaluation.dimensions : [];
    if (c.evaluation.batch_llm != null && typeof c.evaluation.batch_llm !== "object") {
        delete c.evaluation.batch_llm;
    }
    c.pass_criteria = c.pass_criteria || {
        global_criteria: { min_total_score: 6.0 },
        dimensions: [],
        statistical: { confidence_level: 0.95, min_sample_size: 5 },
    };
}

function buildFormSubtabsHtml(prefix) {
    return `
<div class="cfg-subtabs" role="tablist" aria-label="套件配置步骤">
  <button type="button" role="tab" class="cfg-subtab active" id="${prefix}-subtab-basic" aria-selected="true" onclick="setConfigFormSubtab('${prefix}','basic')">基本信息</button>
  <button type="button" role="tab" class="cfg-subtab" id="${prefix}-subtab-http" aria-selected="false" onclick="setConfigFormSubtab('${prefix}','http')">被测接口</button>
  <button type="button" role="tab" class="cfg-subtab" id="${prefix}-subtab-judge" aria-selected="false" onclick="setConfigFormSubtab('${prefix}','judge')" title="评委打分、整批平均分与放行线">打分与放行</button>
</div>`;
}

function buildFormFieldsHtml(prefix) {
    const secBasic = `
<div id="${prefix}-section-basic" class="cfg-form-section active" role="tabpanel" data-section="basic">
<div class="form-group">
  <label>套件名称</label>
  <input type="text" id="${prefix}-meta-name" placeholder="例如：订单接口返回抽检" />
</div>
<div class="form-group">
  <label>描述</label>
  <input type="text" id="${prefix}-meta-desc" placeholder="可选" />
</div>
<div class="form-group">
  <label>版本</label>
  <input type="text" id="${prefix}-meta-version" placeholder="1.0.0" />
</div>
</div>`;

    const secHttp = `
<div id="${prefix}-section-http" class="cfg-form-section cfg-http-page cfg-content-text" role="tabpanel" data-section="http">
<div class="cfg-content-kind-bar">
  <label for="${prefix}-content-kind">测评内容</label>
  <select id="${prefix}-content-kind" onchange="onContentKindChange('${prefix}')">
    <option value="text">文案（Listing / 文本 JSON）</option>
    <option value="image">生图（返回图片 URL）</option>
  </select>
  <p class="hint cfg-content-kind-hint cfg-content-text-only">步骤 1～3 调接口，步骤 4 解析 title、description 等文本给文案评委。</p>
  <p class="hint cfg-content-kind-hint cfg-content-image-only">步骤 1～3 调生图接口，步骤 4 提取图片 URL；视觉评委在「打分与放行」配置。</p>
</div>
<p class="cfg-http-lead">按下面 4 步配置。可先展开 cURL 导入自动填充。</p>

<details class="cfg-curl-fold">
  <summary>从浏览器 cURL 快速导入（可选）</summary>
  <div class="cfg-curl-wizard cfg-curl-wizard--compact">
    <p class="hint" style="margin:8px 0">F12 → 网络 → 右键请求 → 复制为 cURL(bash)，粘贴后点解析。</p>
    <textarea id="${prefix}-curl-paste" class="cfg-curl-textarea" placeholder="粘贴 cURL(bash)；若同时有 /page 与 /get?id=…，将自动选用详情接口"></textarea>
    <button type="button" class="btn btn-primary cfg-curl-btn" onclick="importCurlFromPaste('${prefix}')">解析并填入</button>
  </div>
</details>
<div id="${prefix}-curl-confirm" class="cfg-curl-confirm" style="display:none" aria-live="polite"></div>

<section class="cfg-http-step">
  <h3 class="cfg-http-step-title"><span class="cfg-http-step-num">1</span>连接</h3>
  <div class="cfg-http-step-grid">
    <div class="form-group cfg-span-full">
      <label>接口 URL</label>
      <input type="text" id="${prefix}-endpoint" placeholder="https://api.example.com/..." />
    </div>
    <div class="form-group">
      <label>HTTP 方法</label>
      <select id="${prefix}-http-method">
        <option value="POST">POST</option>
        <option value="GET">GET</option>
        <option value="PUT">PUT</option>
      </select>
    </div>
    <div class="form-group cfg-span-2">
      <label>Authorization（可选）</label>
      <input type="text" id="${prefix}-auth-header" placeholder="Bearer 你的Token" />
      <p class="hint">其它请求头（如 tenant-id）在「YAML 原文」里改。</p>
    </div>
  </div>
  <div class="cfg-api-probe-wrap">
    <button type="button" class="btn btn-secondary cfg-api-probe-btn" style="width:auto;margin:0" onclick="probeConfigApi('${prefix}')">测试连通性</button>
    <div id="${prefix}-api-probe-result" class="cfg-api-probe-result" style="display:none" aria-live="polite"></div>
  </div>
</section>

<section class="cfg-http-step cfg-invoke-template">
  <h3 class="cfg-http-step-title"><span class="cfg-http-step-num">2</span>入参模板</h3>
  <p class="hint cfg-http-step-hint cfg-content-text-only">写字段 + 占位符 <code>{{ input.variables.xxx }}</code>，不要写具体 id。嵌套结构（competitors 等）可保留原样。</p>
  <p class="hint cfg-http-step-hint cfg-content-image-only">生图 prompt / 尺寸等参数，同样用 <code>{{ input.variables.xxx }}</code> 引用步骤 3 取值。</p>
  <textarea id="${prefix}-generic-body-yaml" rows="8" placeholder='id: "{{ input.variables.id | int }}"
sku: "{{ input.variables.sku }}"' class="cfg-body-yaml-ta"></textarea>
</section>

<section class="cfg-http-step" id="${prefix}-simple-test-data">
  <h3 class="cfg-http-step-title"><span class="cfg-http-step-num">3</span>测试取值</h3>
  <p class="hint cfg-http-step-hint cfg-fetch-only">与步骤 2 占位符对应：同一参数多个 id 在「取值」框换行填写，或写范围如 <code>8001-8050</code>（共 50 条用例）。「+ 添加参数」是增加另一个参数名（如 sku），不是再加一条 id。</p>
  <p class="hint cfg-http-step-hint cfg-generate-only">多情境组合测试：情境名 + 可选值。</p>
  <div class="form-group variables-ui" style="margin:0">
    <input type="hidden" id="${prefix}-fetch-param-name" aria-hidden="true" />
    <div class="fetch-batch-mode cfg-fetch-only cfg-fetch-batch-fold">
      <select id="${prefix}-fetch-batch-mode" aria-label="批量方式">
        <option value="param">参数名 + 取值</option>
        <option value="json">每条完整 JSON</option>
      </select>
    </div>
    <div class="var-row-head cfg-fetch-only cfg-fetch-param-rows" aria-hidden="true">
      <span>参数名</span>
      <span>取值</span>
      <span></span>
    </div>
    <div class="fetch-json-batch cfg-fetch-only" style="display:none">
      <div id="${prefix}-fetch-json-rows" class="fetch-json-rows"></div>
      <button type="button" class="btn btn-secondary" style="width:auto;margin:0" onclick="addFetchJsonRow('${prefix}')">+ 添加一条 JSON</button>
    </div>
    <div class="var-row-head cfg-generate-only" aria-hidden="true">
      <span>情境</span>
      <span>可选值</span>
      <span></span>
    </div>
    <div class="var-rows" id="${prefix}-variables-rows"></div>
    <button type="button" class="btn btn-secondary cfg-generate-only" style="width:auto;margin:0" onclick="addVariableRow('${prefix}')">+ 添加情境</button>
    <button type="button" class="btn btn-secondary cfg-fetch-only cfg-fetch-param-rows" style="width:auto;margin:0" onclick="addVariableRow('${prefix}')">+ 添加参数</button>
  </div>
  <div class="form-group cfg-generate-only" style="margin-top:12px">
    <label>话术前缀（可选）</label>
    <input type="text" id="${prefix}-prompt-prefix" placeholder="如：请根据以下信息生成文案" />
  </div>
</section>

<section class="cfg-http-step cfg-step4-wrap">
  <h3 class="cfg-http-step-title">
    <span class="cfg-http-step-num">4</span>
    <span class="cfg-step4-title-text">文案返回解析</span>
    <span class="cfg-step4-title-image">生图返回解析</span>
  </h3>
  <div class="form-group cfg-step4-common" style="margin:0">
    <label class="cfg-output-path-label-text">待评文本的 JSON 路径</label>
    <label class="cfg-output-path-label-image">响应 body 路径（可选）</label>
    <input type="text" id="${prefix}-output-path" list="${prefix}-output-path-presets" placeholder="如 data（留空=整段 body）" />
    <datalist id="${prefix}-output-path-presets">
      ${OUTPUT_PATH_PRESETS.map((p) => `<option value="${p}"></option>`).join("")}
    </datalist>
  </div>
  <details class="cfg-http-subfold cfg-step4-text-only" style="margin-top:10px">
    <summary>只取部分字段（title、description…）</summary>
    <div class="form-group" style="margin-top:8px">
      <textarea id="${prefix}-output-keys" rows="4" placeholder="title&#10;description&#10;bulletPoints1" class="cfg-body-yaml-ta cfg-body-yaml-ta--short"></textarea>
      <p class="hint">一行一个字段名 → <code>output_parser.keys</code></p>
    </div>
  </details>
  <div class="cfg-step4-image-only">
    <div class="form-group" style="margin-top:10px">
      <label>图片 URL 的 JSON 路径</label>
      <input type="text" id="${prefix}-media-urls-path" placeholder="如 data.images 或 0.url" />
      <p class="hint">相对上方 body 路径所指节点；系统会下载图片供视觉评委使用。</p>
    </div>
    <div class="form-group" style="margin-top:8px">
      <label><input type="checkbox" id="${prefix}-media-download" checked /> 下载图片到 artifacts</label>
    </div>
  </div>
</section>

<div class="form-group cfg-generate-only">
  <label>用户话术字段</label>
  <select id="${prefix}-prompt-field">
    ${PROMPT_FIELD_PRESETS.map((f) => `<option value="${f}">${f}</option>`).join("")}
    <option value="__custom__">自定义…</option>
  </select>
</div>
<div class="form-group cfg-generate-only" id="${prefix}-prompt-field-custom-wrap" style="display:none">
  <label>自定义字段名</label>
  <input type="text" id="${prefix}-prompt-field-custom" placeholder="userMessage" />
</div>

<input type="hidden" id="${prefix}-content-mode" value="auto" />

<details class="cfg-advanced-details cfg-advanced-only">
  <summary>更多选项（连接器、超时、并发）</summary>
  <div class="cfg-http-step-grid" style="margin-top:12px">
    <div class="form-group">
      <label>连接器</label>
      <select id="${prefix}-connector-name">
        <option value="httpx">httpx</option>
        <option value="http_json">http_json</option>
      </select>
    </div>
    <div class="form-group">
      <label>超时（秒）</label>
      <input type="number" id="${prefix}-timeout" />
    </div>
    <div class="form-group">
      <label>并发</label>
      <input type="number" id="${prefix}-concurrency" />
    </div>
  </div>
</details>
</div>`;

    const secJudge = `
<div id="${prefix}-section-judge" class="cfg-form-section cfg-judge-page" role="tabpanel" data-section="judge">
<p class="hint cfg-judge-image-hint">生图测评：视觉评委（<code>vision_llm</code>）请在 YAML 里配置；文案全评不适用于图片。</p>

<section class="cfg-judge-block cfg-judge-pass">
  <h3 class="cfg-judge-block-title">放行线</h3>
  <div class="form-group cfg-judge-pass-field">
    <label class="field-label">整批平均分下限</label>
    <input type="number" step="0.1" id="${prefix}-min-total-score" placeholder="例如 6" />
    <p class="hint">全部用例综合分的算术平均不得低于此值（建议量程 0～10 分）。</p>
  </div>
</section>

<section class="cfg-judge-block cfg-judge-unified" id="${prefix}-judge-unified">
  <h3 class="cfg-judge-block-title">评委配置</h3>
  <p class="hint cfg-judge-static-hint">每项维度各评一次；每行填 ID、名称、权重与评判标准。<code>{{ output }}</code> 与 JSON 格式由系统自动拼接。</p>
  <p class="hint cfg-judge-batch-notice" id="${prefix}-judge-batch-notice" hidden>当前为<strong>一次全评</strong>（省 token），由 YAML 或「Listing 七维」模板启用。</p>
  <div class="cfg-field-grid cfg-judge-shared">
    <div class="form-group" style="margin:0">
      <label class="field-label">评委模型</label>
      <input type="text" id="${prefix}-judge-llm-model" placeholder="${DEFAULT_JUDGE_LLM_MODEL}" />
    </div>
    <div class="form-group" style="margin:0">
      <label class="field-label">温度</label>
      <input type="number" step="0.05" id="${prefix}-judge-llm-temp" placeholder="0.1" />
    </div>
    <div class="form-group" style="margin:0">
      <label class="field-label">max_tokens</label>
      <input type="number" id="${prefix}-judge-llm-maxtok" placeholder="2000" />
    </div>
    <div class="form-group cfg-judge-batch-only" id="${prefix}-judge-max-chars-wrap" style="margin:0">
      <label class="field-label">评委输入上限（字符）</label>
      <input type="number" id="${prefix}-judge-max-chars" placeholder="14000" />
    </div>
  </div>
  <div class="cfg-judge-presets">
    <span class="cfg-judge-presets-label">快速添加</span>
    <div class="cfg-preset-btns">
      <button type="button" class="btn btn-secondary cfg-preset-btn" data-preset-key="quality" onclick="addEvalDimensionPreset('${prefix}','quality')">+ 内容质量</button>
      <button type="button" class="btn btn-secondary cfg-preset-btn" data-preset-key="safety" onclick="addEvalDimensionPreset('${prefix}','safety')">+ 安全合规</button>
      <button type="button" class="btn btn-secondary cfg-preset-btn" data-preset-key="format" onclick="addEvalDimensionPreset('${prefix}','format')">+ 格式规范</button>
      <button type="button" class="btn btn-secondary cfg-preset-btn cfg-preset-btn--template" onclick="applyListingBatchPreset('${prefix}')">Listing 七维</button>
    </div>
  </div>
  <div class="cfg-judge-table-wrap">
    <div class="eval-per-dim-head" aria-hidden="true">
      <span>维度 ID</span><span>显示名称</span><span>权重</span><span>评判标准</span><span></span>
    </div>
    <div id="${prefix}-eval-dim-rows" class="eval-dim-rows"></div>
  </div>
  <button type="button" class="btn btn-secondary cfg-judge-add-row" onclick="addEvalDimensionRow('${prefix}')">+ 添加维度行</button>
</section>

<section class="cfg-judge-block cfg-judge-block--muted cat-target-ui">
  <h3 class="cfg-judge-block-title">类别占比 <span class="cfg-optional-tag">可选</span></h3>
  <p class="hint cfg-judge-block-hint">约束第一行维度返回的类别标签占比区间；标签名须与评委 JSON 中 <code>categories</code> 完全一致。</p>
  <div class="cat-target-rows" id="${prefix}-cat-target-rows"></div>
  <button type="button" class="btn btn-secondary cfg-judge-add-row" onclick="addCatTargetRow('${prefix}')">+ 添加类别区间</button>
</section>
</div>`;

    return secBasic + secHttp + secJudge;
}

function getConfigFormSubtabIds(prefix) {
    return ["basic", "http", "judge"];
}

function scrollToTestDataValues(prefix) {
    setConfigFormSubtab(prefix, "http");
    const el = document.getElementById(`${prefix}-simple-test-data`);
    if (el) {
        requestAnimationFrame(() => {
            el.scrollIntoView({ behavior: "smooth", block: "start" });
        });
    }
}

window.scrollToTestDataValues = scrollToTestDataValues;

function setConfigFormSubtab(prefix, tab) {
    let t = tab === "data" ? "http" : tab;
    const ids = getConfigFormSubtabIds(prefix);
    if (!ids.includes(t)) t = "basic";
    ids.forEach((id) => {
        const btn = document.getElementById(`${prefix}-subtab-${id}`);
        const sec = document.getElementById(`${prefix}-section-${id}`);
        const on = id === t;
        if (btn) {
            btn.classList.toggle("active", on);
            btn.setAttribute("aria-selected", on ? "true" : "false");
        }
        if (sec) {
            sec.classList.toggle("active", on);
        }
    });
}

const DEFAULT_FETCH_VARIABLE_EXAMPLES = [{ label: "id", name: "id", values: ["1914"] }];
const DEFAULT_GENERATE_VARIABLE_EXAMPLES = [
    { label: "类目", values: ["男装", "数码"] },
    { label: "语气", values: ["正式", "活泼"] },
];

function getConfigHttpMethod(prefix, obj) {
    if (obj?.target?.connector?.config?.method) {
        return String(obj.target.connector.config.method).toUpperCase();
    }
    const el = document.getElementById(`${prefix}-http-method`);
    return (el?.value || "POST").toUpperCase();
}

function getInputTemplateFromObj(obj) {
    return obj?.target?.input_formatter?.template;
}

/** fetch=拉取/评测业务详情；generate=对话式生成接口 */
function getConfigSuiteMode(prefix, obj) {
    const method = getConfigHttpMethod(prefix, obj);
    const template = obj ? getInputTemplateFromObj(obj) : undefined;
    if (method === "GET") return "fetch";
    if (template && typeof template === "object" && !Array.isArray(template)) {
        for (const v of Object.values(template)) {
            if (typeof v === "string" && /\{\{\s*input\.prompt\s*\}\}/.test(v)) return "generate";
        }
        for (const v of Object.values(template)) {
            if (typeof v === "string" && /\{\{\s*input\.variables\./.test(v)) return "fetch";
        }
    }
    return "fetch";
}

function syncSuiteModeUI(prefix, obj) {
    const mode = getConfigSuiteMode(prefix, obj);
    const hosts = [
        getConfigFormModeHost(prefix),
        document.getElementById(`${prefix}-section-http`),
        document.getElementById(`${prefix}-simple-test-data`),
    ];
    hosts.forEach((host) => {
        if (!host) return;
        host.classList.remove("cfg-suite-fetch", "cfg-suite-generate");
        host.classList.add(mode === "generate" ? "cfg-suite-generate" : "cfg-suite-fetch");
    });
}

/** 从请求体/Query 模板递归收集 {{ input.variables.xxx }} 字段名 */
function listInputVariableNamesFromTemplate(tpl, out) {
    const names = out || new Set();
    if (tpl == null) return [...names];
    if (typeof tpl === "string") {
        const re = /\{\{\s*input\.variables\.([a-zA-Z_][a-zA-Z0-9_]*)/g;
        let m;
        while ((m = re.exec(tpl))) names.add(m[1]);
        return [...names];
    }
    if (Array.isArray(tpl)) {
        tpl.forEach((item) => listInputVariableNamesFromTemplate(item, names));
        return [...names];
    }
    if (typeof tpl === "object") {
        Object.values(tpl).forEach((v) => listInputVariableNamesFromTemplate(v, names));
    }
    return [...names];
}

function countFetchInputVariables(obj) {
    if (!obj || typeof obj !== "object") return 0;
    const fromTpl = listInputVariableNamesFromTemplate(getInputTemplateFromObj(obj));
    const dgVars = obj.data_generator?.variables;
    const fromDg = Array.isArray(dgVars) ? dgVars.map((v) => v?.name).filter(Boolean) : [];
    return new Set([...fromTpl, ...fromDg]).size;
}

function isFetchParamRowsMode(prefix, obj) {
    if (getConfigSuiteMode(prefix, obj) !== "fetch") return false;
    if (isFetchJsonBatchMode(prefix)) return false;
    return true;
}

/** @deprecated 统一为按参数名+取值行编辑 */
function isFetchMultiVariableMode(prefix, obj) {
    return isFetchParamRowsMode(prefix, obj);
}

function ensureDataGeneratorVariablesFromTemplate(obj) {
    if (!obj || typeof obj !== "object") return;
    const names = listInputVariableNamesFromTemplate(getInputTemplateFromObj(obj));
    if (!names.length) return;
    obj.data_generator = obj.data_generator || { strategy: "template_cartesian", variables: [] };
    if (!Array.isArray(obj.data_generator.variables)) obj.data_generator.variables = [];
    const existing = new Set(obj.data_generator.variables.map((v) => v?.name).filter(Boolean));
    names.forEach((name) => {
        if (!existing.has(name)) {
            obj.data_generator.variables.push({ name, type: "enum", values: [] });
            existing.add(name);
        }
    });
}

function syncFetchMultiVarUI(prefix, obj) {
    const sec = document.getElementById(`${prefix}-simple-test-data`);
    if (!sec) return;
    sec.classList.toggle("cfg-fetch-param-rows-active", isFetchParamRowsMode(prefix, obj));
}

function isFetchSimpleListMode(prefix, obj) {
    return false;
}

function isFetchJsonBatchMode(prefix) {
    if (getConfigSuiteMode(prefix, null) !== "fetch") return false;
    const sel = document.getElementById(`${prefix}-fetch-batch-mode`);
    if (sel) return sel.value === "json";
    if (isConfigFormAdvanced(prefix)) {
        const wrap = document.getElementById(`${prefix}-fetch-json-rows`);
        return !!(wrap && wrap.querySelector(".fetch-json-row"));
    }
    return false;
}

function shouldUseFetchJsonBatch(obj) {
    if (!obj || typeof obj !== "object") return false;
    const dg = obj.data_generator;
    if (dg?.strategy === "fixed_rows" && Array.isArray(dg.rows) && dg.rows.length > 0) return true;
    return false;
}

function setFetchBatchMode(prefix, mode, syncUi = true) {
    const sel = document.getElementById(`${prefix}-fetch-batch-mode`);
    if (sel) sel.value = mode === "json" ? "json" : "param";
    if (syncUi) syncFetchBatchModeUI(prefix);
}

function syncFetchBatchModeUI(prefix, obj) {
    const sec = document.getElementById(`${prefix}-simple-test-data`);
    if (!sec) return;
    const suiteFetch = getConfigSuiteMode(prefix, obj) === "fetch";
    const batchMode = suiteFetch && isFetchJsonBatchMode(prefix) ? "json" : "param";
    sec.classList.toggle("cfg-fetch-batch-json", suiteFetch && batchMode === "json");
    sec.classList.toggle("cfg-fetch-batch-param", suiteFetch && batchMode !== "json");
    syncFetchMultiVarUI(prefix, obj || null);
}

function bindFetchBatchModeSelect(prefix) {
    const sel = document.getElementById(`${prefix}-fetch-batch-mode`);
    if (!sel || sel.dataset.bound === "1") return;
    sel.dataset.bound = "1";
    sel.addEventListener("change", () => {
        if (sel.value === "json") {
            const wrap = document.getElementById(`${prefix}-fetch-json-rows`);
            if (wrap && !wrap.querySelector(".fetch-json-row")) addFetchJsonRow(prefix);
        } else {
            const varWrap = document.getElementById(`${prefix}-variables-rows`);
            if (varWrap && !varWrap.querySelector(".var-row")) {
                addVariableRow(prefix, { name: "id", values: ["1914"] });
            }
        }
        syncFetchBatchModeUI(prefix, null);
    });
}

function isComplexFetchBody(tpl) {
    if (!tpl || typeof tpl !== "object" || Array.isArray(tpl)) return false;
    let prim = 0;
    for (const v of Object.values(tpl)) {
        if (v === null || typeof v !== "object") prim++;
    }
    return prim > 1;
}

function extractRowVarsFromBody(bodyObj) {
    const row = {};
    if (!bodyObj || typeof bodyObj !== "object" || Array.isArray(bodyObj)) return row;
    for (const [k, v] of Object.entries(bodyObj)) {
        if (v === null || typeof v !== "object") row[k] = v;
    }
    return row;
}

function curlVarPlaceholder(name, value) {
    if (name === "id" && (typeof value === "number" || /^\d+$/.test(String(value)))) {
        return "{{ input.variables.id | int }}";
    }
    return `{{ input.variables.${name} }}`;
}

function normalizeCurlVarValue(value) {
    if (value === null || value === undefined) return "";
    if (typeof value === "boolean" || typeof value === "number") return value;
    const s = String(value);
    if (/^\d+$/.test(s)) return Number(s);
    return s;
}

/** cURL 顶层标量字段 → 模板占位符 + data_generator.variables 取值 */
function applyCurlPrimitivesAsTemplateAndVariables(obj, bodyTpl) {
    if (!bodyTpl || typeof bodyTpl !== "object" || Array.isArray(bodyTpl)) return false;
    const rowVars = extractRowVarsFromBody(bodyTpl);
    const keys = Object.keys(rowVars);
    if (!keys.length) return false;

    const template = JSON.parse(JSON.stringify(bodyTpl));
    keys.forEach((k) => {
        template[k] = curlVarPlaceholder(k, rowVars[k]);
    });

    obj.target.input_formatter.template = template;
    obj.data_generator = obj.data_generator || { strategy: "template_cartesian", variables: [] };
    obj.data_generator.strategy = "template_cartesian";
    obj.data_generator.variables = keys.map((name) => ({
        name,
        type: "enum",
        values: [normalizeCurlVarValue(rowVars[name])],
    }));
    obj.data_generator.prompt_template =
        keys.length === 1
            ? `{{ vars.${keys[0]} }}`
            : keys.map((k) => `{{ vars.${k} }}`).join(" / ");
    delete obj.data_generator.rows;
    return true;
}

function buildRequestTemplateFromJsonRows(rows, existingTpl) {
    const base =
        existingTpl && typeof existingTpl === "object" && !Array.isArray(existingTpl)
            ? JSON.parse(JSON.stringify(existingTpl))
            : {};
    const varKeys = new Set();
    (rows || []).forEach((r) => {
        if (r && typeof r === "object") Object.keys(r).forEach((k) => varKeys.add(k));
    });
    varKeys.forEach((k) => {
        base[k] = `{{ input.variables.${k} }}`;
    });
    return base;
}

function buildMetaPromptFromRows(rows) {
    if (!Array.isArray(rows) || !rows.length) return "";
    const keys = Object.keys(rows[0] || {});
    if (!keys.length) return "";
    return keys.map((k) => `{{ vars.${k} }}`).join(" / ");
}

function clearFetchJsonRows(prefix) {
    const wrap = document.getElementById(`${prefix}-fetch-json-rows`);
    if (wrap) wrap.innerHTML = "";
}

function addFetchJsonRow(prefix, rowObj) {
    const wrap = document.getElementById(`${prefix}-fetch-json-rows`);
    if (!wrap) return;
    const idx = wrap.querySelectorAll(".fetch-json-row").length + 1;
    const row = document.createElement("div");
    row.className = "fetch-json-row";

    const label = document.createElement("label");
    label.textContent = `第 ${idx} 条请求参数 JSON`;

    const ta = document.createElement("textarea");
    ta.className = "fetch-json-value";
    ta.rows = 6;
    ta.placeholder = '{\n  "id": 1914,\n  "sku": "260406CHA12-BXG08PGFDE2",\n  "site": "DE"\n}';
    if (rowObj && typeof rowObj === "object") {
        try {
            ta.value = JSON.stringify(rowObj, null, 2);
        } catch (_) {
            ta.value = String(rowObj);
        }
    }

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-secondary btn-fetch-json-remove";
    btn.textContent = "删掉";
    btn.addEventListener("click", () => removeFetchJsonRow(btn));

    row.appendChild(label);
    row.appendChild(ta);
    row.appendChild(btn);
    wrap.appendChild(row);
    renumberFetchJsonRows(prefix);
    syncFetchBatchModeUI(prefix);
}

function renumberFetchJsonRows(prefix) {
    const wrap = document.getElementById(`${prefix}-fetch-json-rows`);
    if (!wrap) return;
    wrap.querySelectorAll(".fetch-json-row").forEach((row, i) => {
        const label = row.querySelector("label");
        if (label) label.textContent = `第 ${i + 1} 条请求参数 JSON`;
    });
}

function removeFetchJsonRow(btn) {
    const row = btn.closest(".fetch-json-row");
    if (!row) return;
    const wrap = row.parentElement;
    const prefix = (wrap?.id || "").replace(/-fetch-json-rows$/, "") || "edit";
    row.remove();
    renumberFetchJsonRows(prefix);
    syncFetchBatchModeUI(prefix);
}

function renderFetchJsonRows(prefix, rows) {
    clearFetchJsonRows(prefix);
    const list = Array.isArray(rows) ? rows : [];
    if (list.length === 0) {
        addFetchJsonRow(prefix, null);
        return;
    }
    list.forEach((r) => addFetchJsonRow(prefix, r));
}

function tryCollectFetchJsonRows(prefix) {
    const wrap = document.getElementById(`${prefix}-fetch-json-rows`);
    if (!wrap) return [];
    const rows = [];
    wrap.querySelectorAll(".fetch-json-row .fetch-json-value").forEach((ta) => {
        const raw = ta.value.trim();
        if (!raw) return;
        try {
            const obj = JSON.parse(raw);
            if (obj && typeof obj === "object" && !Array.isArray(obj)) rows.push(obj);
        } catch (_) {
            /* skip invalid while typing */
        }
    });
    return rows;
}

function collectFetchJsonRows(prefix) {
    const wrap = document.getElementById(`${prefix}-fetch-json-rows`);
    if (!wrap) return [];
    const rows = [];
    const items = wrap.querySelectorAll(".fetch-json-row .fetch-json-value");
    items.forEach((ta, i) => {
        const raw = ta.value.trim();
        if (!raw) return;
        try {
            const obj = JSON.parse(raw);
            if (obj && typeof obj === "object" && !Array.isArray(obj)) rows.push(obj);
        } catch (e) {
            throw new Error(`第 ${i + 1} 条请求参数不是合法 JSON：${e.message || String(e)}`);
        }
    });
    return rows;
}

window.addFetchJsonRow = addFetchJsonRow;

function inferFetchParamName(obj) {
    if (!obj || typeof obj !== "object") return "id";
    const tpl = obj.target?.input_formatter?.template;
    if (tpl && typeof tpl === "object" && !Array.isArray(tpl)) {
        for (const [k, v] of Object.entries(tpl)) {
            if (typeof v === "string") {
                const m = v.match(/\{\{\s*input\.variables\.([a-zA-Z_][a-zA-Z0-9_]*)/);
                if (m) return m[1];
            }
        }
        const keys = Object.keys(tpl);
        if (keys.length === 1) return keys[0];
    }
    const ep = obj.target?.connector?.config?.endpoint || "";
    try {
        const u = new URL(ep);
        const qKeys = [...new URLSearchParams(u.search).keys()];
        if (qKeys.length === 1) return qKeys[0];
    } catch (_) {
        /* ignore */
    }
    const vars = obj.data_generator?.variables;
    if (Array.isArray(vars) && vars.length === 1 && vars[0]?.name) return vars[0].name;
    return "id";
}

function getFetchParamName(prefix, obj) {
    const el = document.getElementById(`${prefix}-fetch-param-name`);
    const manual = el?.value.trim();
    if (manual) return manual;
    if (obj) return inferFetchParamName(obj);
    const ep = document.getElementById(`${prefix}-endpoint`)?.value.trim() || "";
    try {
        const u = new URL(ep);
        const qKeys = [...new URLSearchParams(u.search).keys()];
        if (qKeys.length === 1) return qKeys[0];
    } catch (_) {
        /* ignore */
    }
    return "id";
}

function syncFetchParamNameUI(prefix, obj) {
    const el = document.getElementById(`${prefix}-fetch-param-name`);
    if (!el) return;
    if (!el.value.trim() && obj) {
        el.value = inferFetchParamName(obj);
    }
    const name = getFetchParamName(prefix, obj);
    const head = document.getElementById(`${prefix}-fetch-value-head`);
    if (head) head.textContent = `取值（${name}）`;
    document.querySelectorAll(`#${prefix}-variables-rows .fetch-case-value`).forEach((inp) => {
        inp.placeholder = `填写 ${name}，如 1914`;
    });
}

function bindFetchParamNameInput(prefix) {
    const el = document.getElementById(`${prefix}-fetch-param-name`);
    if (!el || el.dataset.bound === "1") return;
    el.dataset.bound = "1";
    el.addEventListener("input", () => {
        syncFetchParamNameUI(prefix, null);
    });
}

function addFetchCaseRow(prefix, value) {
    const wrap = document.getElementById(`${prefix}-variables-rows`);
    if (!wrap) return;
    const row = document.createElement("div");
    row.className = "var-row fetch-case-row";
    row.dataset.fetchCase = "1";

    const valIn = document.createElement("input");
    valIn.type = "text";
    valIn.className = "var-values fetch-case-value";
    valIn.placeholder = "填写取值，如 1914";
    if (value != null && value !== "") valIn.value = String(value);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-secondary btn-var-remove";
    btn.textContent = "删掉";
    btn.addEventListener("click", () => removeVariableRow(btn));

    row.appendChild(valIn);
    row.appendChild(btn);
    wrap.appendChild(row);
    syncFetchParamNameUI(prefix, null);
}

window.addFetchCaseRow = addFetchCaseRow;

function addDefaultVariableExamples(prefix, obj) {
    const mode = getConfigSuiteMode(prefix, obj);
    if (mode === "generate") {
        DEFAULT_GENERATE_VARIABLE_EXAMPLES.forEach((preset) => addVariableRow(prefix, preset));
    } else if (isFetchJsonBatchMode(prefix) || shouldUseFetchJsonBatch(obj)) {
        addFetchJsonRow(prefix, null);
    } else if (isFetchParamRowsMode(prefix, obj)) {
        if (obj && countFetchInputVariables(obj) > 0) {
            listInputVariableNamesFromTemplate(getInputTemplateFromObj(obj)).forEach((name) => {
                const v = (obj.data_generator?.variables || []).find((x) => x && x.name === name);
                addVariableRow(prefix, {
                    name,
                    values: Array.isArray(v?.values) ? v.values : [],
                });
            });
        } else {
            addVariableRow(prefix, { name: "id", values: ["1914"] });
        }
    } else {
        DEFAULT_FETCH_VARIABLE_EXAMPLES.forEach((preset) => addVariableRow(prefix, preset));
    }
}

function buildRequestTemplateFromVariables(prefix, existingTpl) {
    syncAllVarRowNames(prefix);
    const vars = collectVariableRows(prefix);
    const base =
        existingTpl && typeof existingTpl === "object" && !Array.isArray(existingTpl)
            ? JSON.parse(JSON.stringify(existingTpl))
            : {};
    for (const [k, v] of Object.entries(base)) {
        if (typeof v === "string" && /\{\{\s*input\.(variables\.|prompt)/.test(v)) {
            delete base[k];
        }
    }
    vars.forEach((v) => {
        base[v.name] = `{{ input.variables.${v.name} }}`;
    });
    return base;
}

function buildAutoMetaPromptTemplate(prefix) {
    const vars = collectVariableRows(prefix);
    if (!vars.length) return "";
    if (vars.length === 1) return `{{ vars.${vars[0].name} }}`;
    return vars.map((v) => `{{ vars.${v.name} }}`).join(" / ");
}

function getVarRowPrefix(row) {
    const sec = row?.closest("[id$='-section-http']");
    return (sec?.id || "").replace(/-section-http$/, "") || "edit";
}

const AUTO_PROMPT_VAR_LINE = /^(.+?)：\{\{\s*vars\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}\s*$/;

function slugVarName(label, index, usedNames) {
    const raw = String(label || "").trim();
    let base = "";
    if (/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(raw)) {
        base = raw;
    } else {
        base = raw
            .toLowerCase()
            .replace(/[^\w]+/g, "_")
            .replace(/^_|_$/g, "");
        if (!base || !/^[a-zA-Z_]/.test(base)) {
            base = `var_${index + 1}`;
        }
    }
    let name = base;
    let n = 2;
    while (usedNames.has(name)) {
        name = `${base}_${n++}`;
    }
    usedNames.add(name);
    return name;
}

function parseAutoPromptTemplate(template, variables) {
    const t = String(template ?? "").trim();
    if (!t) return { prefix: "", labelsByName: {}, custom: false };

    const singleVar = t.match(/^\{\{\s*vars\.([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}$/);
    if (singleVar) {
        const name = singleVar[1];
        const v = (variables || []).find((x) => x && x.name === name);
        return {
            prefix: "",
            labelsByName: { [name]: v?.label || name },
            custom: false,
        };
    }

    const lines = t.replace(/\r\n/g, "\n").split("\n");
    const labelsByName = {};
    const prefixLines = [];
    let sawVarLine = false;

    for (const line of lines) {
        const m = line.match(AUTO_PROMPT_VAR_LINE);
        if (m) {
            labelsByName[m[2]] = m[1];
            sawVarLine = true;
            continue;
        }
        if (!sawVarLine) {
            prefixLines.push(line);
            continue;
        }
        return { prefix: "", labelsByName: {}, custom: true };
    }

    if (sawVarLine) {
        return { prefix: prefixLines.join("\n"), labelsByName, custom: false };
    }

    if (!(variables || []).length) {
        return { prefix: t, labelsByName: {}, custom: false };
    }
    return { prefix: "", labelsByName: {}, custom: true };
}

function buildAutoPromptTemplate(prefix) {
    syncAllVarRowNames(prefix);
    const prefixText = document.getElementById(`${prefix}-prompt-prefix`)?.value.trim() || "";
    const rows = collectVariableRows(prefix);
    if (rows.length === 0) {
        return prefixText || "测试输入";
    }
    if (rows.length === 1 && !prefixText) {
        return `{{ vars.${rows[0].name} }}`;
    }
    const lines = [];
    if (prefixText) lines.push(prefixText);
    rows.forEach((v) => {
        lines.push(`${v.label || v.name}：{{ vars.${v.name} }}`);
    });
    return lines.join("\n");
}

function syncVarRowName(row) {
    if (!row) return;
    const prefix = getVarRowPrefix(row);
    if (isConfigFormAdvanced(prefix) || getConfigSuiteMode(prefix, null) === "fetch") return;
    const labelIn = row.querySelector(".var-label");
    const nameIn = row.querySelector(".var-name");
    if (!labelIn || !nameIn) return;
    const wrap = row.parentElement;
    const used = new Set();
    wrap.querySelectorAll(".var-row").forEach((r) => {
        if (r === row) return;
        const n = r.querySelector(".var-name")?.value.trim();
        if (n) used.add(n);
    });
    const idx = Array.from(wrap.querySelectorAll(".var-row")).indexOf(row);
    nameIn.value = slugVarName(labelIn.value.trim(), idx, used);
}

function syncAllVarRowNames(prefix) {
    const wrap = document.getElementById(`${prefix}-variables-rows`);
    if (!wrap || isConfigFormAdvanced(prefix)) return;
    wrap.querySelectorAll(".var-row").forEach((row) => syncVarRowName(row));
}

function removeVariableRow(btn) {
    const row = btn.closest(".var-row");
    if (!row) return;
    const prefix = getVarRowPrefix(row);
    row.remove();
}

function addVariableRow(prefix, preset) {
    const wrap = document.getElementById(`${prefix}-variables-rows`);
    if (!wrap) return;
    const isFetch = getConfigSuiteMode(prefix, null) === "fetch" && !isFetchJsonBatchMode(prefix);
    const row = document.createElement("div");
    row.className = "var-row";
    const labelIn = document.createElement("input");
    labelIn.type = "text";
    labelIn.className = isFetch ? "var-label cfg-generate-only" : "var-label cfg-simple-only";
    labelIn.placeholder = "情境名称，如：类目";
    if (!isFetch) {
        if (preset && preset.label) labelIn.value = String(preset.label);
        else if (preset && preset.name && !isConfigFormAdvanced(prefix)) labelIn.value = String(preset.name);
    }

    const nameIn = document.createElement("input");
    nameIn.type = "text";
    nameIn.className = isFetch ? "var-name cfg-fetch-only" : "var-name cfg-advanced-only";
    nameIn.placeholder = isFetch ? "参数名，如 id、sku、productName" : "英文名，如 id";
    if (preset && preset.name) nameIn.value = String(preset.name);
    else if (!isFetch && preset && preset.label && /^[a-zA-Z_][a-zA-Z0-9_]*$/.test(String(preset.label))) {
        nameIn.value = String(preset.label);
    }

    const ta = document.createElement("textarea");
    ta.className = "var-values";
    ta.placeholder = "取值：换行多个 id，或写范围 8001-8050（50 条用例）";
    if (preset && Array.isArray(preset.values) && preset.values.length) {
        ta.value = preset.values.map((x) => String(x)).join("\n");
    }
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-secondary btn-var-remove";
    btn.textContent = "删掉";
    btn.addEventListener("click", () => removeVariableRow(btn));
    if (!isFetch) {
        labelIn.addEventListener("input", () => {
            syncVarRowName(row);
        });
    }
    row.appendChild(labelIn);
    row.appendChild(nameIn);
    row.appendChild(ta);
    row.appendChild(btn);
    wrap.appendChild(row);
    if (!isFetch) syncVarRowName(row);
}

function clearVariableRows(prefix) {
    const wrap = document.getElementById(`${prefix}-variables-rows`);
    if (wrap) wrap.innerHTML = "";
}

function renderVariableRows(prefix, variables, labelsByName, obj) {
    clearVariableRows(prefix);
    const list = Array.isArray(variables) ? variables : [];
    const labels = labelsByName && typeof labelsByName === "object" ? labelsByName : {};
    if (list.length === 0) {
        addDefaultVariableExamples(prefix, obj || null);
        return;
    }
    list.forEach((v) => {
        const values = v.values != null ? v.values : [];
        addVariableRow(prefix, {
            name: v.name || "",
            label: labels[v.name] || v.label || v.name || "",
            values: Array.isArray(values) ? values : [],
        });
    });
}

function parseVarValuesFromRaw(raw) {
    const tokens = String(raw || "")
        .split(/[\n,，、]+/)
        .map((s) => s.trim())
        .filter(Boolean);
    const out = [];
    const MAX_RANGE = 500;
    for (const tok of tokens) {
        const rangeMatch = tok.match(/^(\d+)\s*(?:\.\.|[-–—~～])\s*(\d+)$/);
        if (rangeMatch) {
            let a = parseInt(rangeMatch[1], 10);
            let b = parseInt(rangeMatch[2], 10);
            if (Number.isNaN(a) || Number.isNaN(b)) {
                out.push(tok);
                continue;
            }
            if (a > b) [a, b] = [b, a];
            const len = b - a + 1;
            if (len > MAX_RANGE) {
                throw new Error(`范围 ${a}-${b} 共 ${len} 条，超过单次上限 ${MAX_RANGE}，请缩小范围或分批运行`);
            }
            for (let i = a; i <= b; i++) out.push(String(i));
            continue;
        }
        out.push(tok.replace(/^["']|["']$/g, ""));
    }
    return out;
}

function collectVariableRows(prefix) {
    const wrap = document.getElementById(`${prefix}-variables-rows`);
    if (!wrap) return [];

    const out = [];
    const used = new Set();
    wrap.querySelectorAll(".var-row").forEach((row, index) => {
        const nameRaw = row.querySelector(".var-name")?.value.trim() || "";
        const labelRaw = row.querySelector(".var-label")?.value.trim() || "";
        const raw = row.querySelector(".var-values")?.value.trim() || "";
        if (!nameRaw && !labelRaw && !raw) return;
        let name = nameRaw;
        if (!name) name = slugVarName(labelRaw, index, used);
        else used.add(name);
        const label = labelRaw || nameRaw || name;
        const values = parseVarValuesFromRaw(raw);
        out.push({ name, label, type: "enum", values });
    });
    return out;
}

const DEFAULT_FORM_EVAL_DIM_ID = "content_mix";

/** 自动拼接时在「前半段质检说明」后追加的输出块起始（拆分已存 YAML 必须与之一致）。 */
const JUDGE_PROMPT_TAIL_BLOCK = `待评价的接口输出如下（已按配置截取；可能是 JSON 或其它文本，或可含完整 code/data）：\n{{ output }}\n\n只输出一个 JSON 对象（不要 Markdown、不要夹杂其它说明）。必须使用这些键：\n- score：数字，建议量程 0～10（本条在该维度上系统按 ≥6 计为及格）；\n- categories：字符串数组（质检标签，没有则 [])；\n- issues：字符串数组（具体问题，没有则 [])；\n- evidence：字符串（一句简明依据）；\n\n除该 JSON 外不要输出其它任何字符。`;

/** 简易模式只读预览（与 JUDGE_PROMPT_TAIL_BLOCK 语义一致，便于用户理解无需手写部分） */
const JUDGE_PROMPT_TAIL_PREVIEW = `待评价的接口输出如下（来自「被测接口」里配置的返回路径）：\n{{ output }}\n\n只输出一个 JSON 对象：\n{"score":0-10,"categories":["..."], "issues":[], "evidence":""}`;

const DEFAULT_LLM_PROMPT_FALLBACK = `请根据你的角色与上文要求综合评价接口返回。\n\n${JUDGE_PROMPT_TAIL_BLOCK}`;

/** 判断是否由表单自动拼了标准输出段；加载空串视为「前半段可由用户填写 + 默认接尾」。 */
function splitJudgePromptForForm(stored) {
    const t = String(stored ?? "").replace(/\r\n/g, "\n");
    const needle = `\n\n${JUDGE_PROMPT_TAIL_BLOCK}`;
    const idx = t.indexOf(needle);
    if (idx !== -1) {
        return { handwritten: false, body: t.slice(0, idx).trimEnd() };
    }
    const tt = t.trim();
    if (tt === "") {
        return { handwritten: false, body: "" };
    }
    return { handwritten: true, body: t };
}

/** 默认拼接模式下用户若仍贴了「接口输出 / 只输出 JSON」等段落，会与自动尾段冲突；保存前删掉这些重复文末。 */
function stripLikelyManualJsonTail(s0) {
    const s = String(s0 ?? "").replace(/\r\n/g, "\n");
    let cut = -1;

    const mark = (re) => {
        const m = s.match(re);
        if (m && m.index !== undefined && m.index !== null) cut = cut === -1 ? m.index : Math.min(cut, m.index);
    };

    // 「接口输出…{{ output }}」（同行）；或两行：接口输出 + 下一行 {{ output }}
    mark(/\n+[ \t]*(?:接口输出|被测(?:接口)?输出|输出正文|输出片段)[^\n]{0,80}\{\{\s*output\s*\}\}/i);
    mark(/\n+[ \t]*(?:接口输出|输出)[^\n]{0,48}?[：:]?\s*\n[ \t]*\{\{\s*output\s*\}\}[ \t]*/i);

    // 单独一行占位符 {{ output }}
    mark(/\n+[ \t]*\{\{\s*output\s*\}\}[ \t]*(?=\n|$)/);

    mark(/\n+[ \t]*只输出(?:一个\s*)?JSON[^\n]{0,64}[：:]?/);

    mark(/\n+[ \t]*\{\s*"score"\s*:/);

    if (cut === -1) return s.trimEnd();

    return s.slice(0, cut).trimEnd();
}

/** 勾选「不写 JSON 骨架」时用前半段说明 + 统一尾段生成完整评委提示词。 */
function assembleJudgePromptFromParts(bodyTrimmed, handwritten) {
    let b = String(bodyTrimmed ?? "").trim();
    if (handwritten) return b;
    b = stripLikelyManualJsonTail(b);
    if (!b) return DEFAULT_LLM_PROMPT_FALLBACK;
    return `${b}\n\n${JUDGE_PROMPT_TAIL_BLOCK}`;
}

function judgePromptShowsDuplicateRisk(text) {
    const s = String(text ?? "").replace(/\r\n/g, "\n");
    if (!s.trim()) return false;
    if (/\{\{\s*output\s*\}\}/.test(s)) return true;
    if (/只输出(?:一个\s*)?JSON/i.test(s)) return true;
    return false;
}

function dimensionHasLlmEvaluator(d) {
    return !!(d && Array.isArray(d.evaluators) && d.evaluators.some((e) => e && e.type === "llm"));
}

/** 表单可编辑的评委：文本 llm + 视觉 vision_llm */
function dimensionHasFormEvaluator(d) {
    return !!(
        d &&
        Array.isArray(d.evaluators) &&
        d.evaluators.some((e) => e && (e.type === "llm" || e.type === "vision_llm"))
    );
}

function getFormEvaluator(d) {
    if (!d || !Array.isArray(d.evaluators)) return null;
    return (
        d.evaluators.find((e) => e && e.type === "vision_llm") ||
        d.evaluators.find((e) => e && e.type === "llm") ||
        null
    );
}

/** 生图 / 混合模态套件：表单无法完整表达时应默认打开 YAML */
function evaluationUsesBatchLlm(obj) {
    const b = obj?.evaluation?.batch_llm;
    return !!(b && typeof b === "object" && (b.prompt_template || (b.dimension_ids && b.dimension_ids.length)));
}

function getContentKindFromObj(obj) {
    const op = obj?.target?.output_parser;
    if (!op) return "text";
    const mode = String(op.content_mode || "").toLowerCase();
    if (mode === "image" || mode === "mixed") return "image";
    if (op.media && (op.media.urls_path || op.media.download != null)) return "image";
    return "text";
}

function syncContentKindUI(prefix, kind) {
    const k =
        kind ||
        document.getElementById(`${prefix}-content-kind`)?.value ||
        "text";
    const isImage = k === "image";
    const cls = isImage ? "cfg-content-image" : "cfg-content-text";
    [`${prefix}-section-http`, `${prefix}-form-fields`].forEach((id) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.classList.remove("cfg-content-text", "cfg-content-image");
        el.classList.add(cls);
    });
    const cm = document.getElementById(`${prefix}-content-mode`);
    if (cm) cm.value = isImage ? "image" : "auto";
}

function onContentKindChange(prefix) {
    syncContentKindUI(prefix);
}

function configUsesMultimodal(obj) {
    if (!obj || typeof obj !== "object") return false;
    if (getContentKindFromObj(obj) === "image") return true;
    const op = obj.target?.output_parser;
    if (op && (op.content_mode === "image" || op.content_mode === "mixed" || op.media)) {
        return true;
    }
    const dims = obj.evaluation?.dimensions;
    if (!Array.isArray(dims)) return false;
    return dims.some(
        (d) =>
            d &&
            Array.isArray(d.evaluators) &&
            d.evaluators.some((e) => e && (e.type === "vision_llm" || e.type === "image_rule"))
    );
}

function configUsesBatchLlm(obj) {
    return evaluationUsesBatchLlm(obj);
}

window.configUsesMultimodal = configUsesMultimodal;
window.configUsesBatchLlm = configUsesBatchLlm;
window.evaluationUsesBatchLlm = evaluationUsesBatchLlm;
window.onContentKindChange = onContentKindChange;

const DEFAULT_JUDGE_DIMENSIONS = [
    {
        id: "content_quality",
        name: "内容质量",
        weight: 1,
        criteria: "准确性、完整性、可读性，有无明显错误或胡编乱造",
    },
    {
        id: "safety_compliance",
        name: "安全合规",
        weight: 1,
        criteria: "违法违规、歧视、隐私泄露或不当内容",
    },
    {
        id: "format_check",
        name: "格式规范",
        weight: 0.5,
        criteria: "返回格式是否符合预期（如 JSON 结构、字段齐全、长度合理）",
    },
];

const LISTING_BATCH_DIMENSIONS = [
    {
        id: "fact_consistency",
        name: "事实一致性",
        weight: 0.2,
        criteria: "CDQ Ch4：数量/材质/尺寸/用途与锚点一致；各字段规格不矛盾；禁捏造认证。",
    },
    {
        id: "keyword_strategy",
        name: "关键词策略",
        weight: 0.25,
        criteria: "CDQ Ch5+Ch12：标题 150～200 字、前 80 字含核心词；keywordRanking 嵌入；searchTerms 不堆砌。",
    },
    {
        id: "competitor_signal",
        name: "竞品信号利用",
        weight: 0.15,
        criteria: "CDQ Ch9/Ch16：吸收竞品买家任务；差异化清晰；不抄袭、不违背锚点。",
    },
    {
        id: "conversion_copy",
        name: "转化文案质量",
        weight: 0.15,
        criteria: "CDQ Ch9+Ch17：Bullet benefit-first、150～500 字；#1-2 前置差异化；COSMO 场景/搭配。",
    },
    {
        id: "description_structure",
        name: "Description 结构",
        weight: 0.1,
        criteria: "结构可读非复读；CDQ Ch20 Rufus 可回答性 ≥4/5。",
    },
    {
        id: "compliance_risk",
        name: "合规与风险提示",
        weight: 0.1,
        criteria: "CDQ Ch18：禁夸大/绝对化；不含配件须标注；P0-P3 风险分级。",
    },
    {
        id: "user_special_notes",
        name: "用户特殊说明",
        weight: 0.05,
        criteria: "锚点 productParameters 等特殊要求须体现；无则中性偏上。",
    },
];

const BATCH_LLM_OUTPUT_MARKER = "【待评接口返回】";

function buildBatchLlmPromptTail(dimensionIds) {
    const ids = (dimensionIds || []).filter(Boolean);
    const skeleton = ids
        .map((id) => `"${id}":{"score":0-10,"categories":[],"issues":[],"evidence":""}`)
        .join(",");
    return `${BATCH_LLM_OUTPUT_MARKER}（已按配置截取，可能是 JSON 或纯文本）\n{{ output }}\n\n只输出一个 JSON 对象（不要 markdown 代码块）：\n{"dimensions":{${skeleton}},"summary":{"overall_comment":"","risk_flags":[]}}`;
}

function splitBatchPromptForForm(stored, dimensionIds) {
    const t = String(stored ?? "").replace(/\r\n/g, "\n");
    const marker = `\n\n${BATCH_LLM_OUTPUT_MARKER}`;
    const idx = t.indexOf(marker);
    if (idx !== -1) {
        return { handwritten: false, body: t.slice(0, idx).trimEnd() };
    }
    const tt = t.trim();
    if (!tt) return { handwritten: false, body: "" };
    if (/\{\{\s*listing_excerpt\s*\}\}/.test(tt) || /"dimensions"\s*:\s*\{/.test(tt)) {
        return { handwritten: true, body: t };
    }
    return { handwritten: true, body: t };
}

function assembleBatchPromptFromParts(bodyTrimmed, dimensionIds, handwritten) {
    if (handwritten) return String(bodyTrimmed ?? "").trim();
    let b = stripLikelyManualJsonTail(bodyTrimmed);
    if (!b) b = "你是内容质检员。请根据接口返回，一次性完成下列全部维度的评分（0～10）。";
    const ids = (dimensionIds || []).filter(Boolean);
    if (!ids.length) return b;
    return `${b}\n\n${buildBatchLlmPromptTail(ids)}`;
}

const preservedBatchPrompts = {};

function setJudgeBatchMode(prefix, enabled) {
    const host = document.getElementById(`${prefix}-judge-unified`);
    if (!host) return;
    if (enabled) host.dataset.batchMode = "1";
    else {
        delete host.dataset.batchMode;
        delete host.dataset.listingBatch;
    }
    syncJudgeModeUI(prefix, null);
}

function applyListingBatchPreset(prefix) {
    setJudgeBatchMode(prefix, true);
    const host = document.getElementById(`${prefix}-judge-unified`);
    if (host) host.dataset.listingBatch = "1";
    clearEvalDimensionRows(prefix);
    LISTING_BATCH_DIMENSIONS.forEach((d) => addEvalDimensionRow(prefix, d));
    applyJudgeSharedFieldsToForm(prefix, null, { batch: true, listing: true });
    delete preservedBatchPrompts[prefix];
}

window.applyListingBatchPreset = applyListingBatchPreset;

function syncJudgeModeUI(prefix, obj) {
    const host = document.getElementById(`${prefix}-judge-unified`);
    if (!host) return;

    let useBatch = isBatchLlmFormEnabled(prefix);
    if (obj && evaluationUsesBatchLlm(obj)) {
        useBatch = true;
        host.dataset.batchMode = "1";
    }

    host.classList.toggle("cfg-judge-unified--batch", useBatch);

    const notice = document.getElementById(`${prefix}-judge-batch-notice`);
    if (notice) {
        notice.hidden = !useBatch;
        if (useBatch && preservedBatchPrompts[prefix]) {
            notice.innerHTML =
                '当前为<strong>一次全评</strong>（CDQ 等完整 prompt 在 <strong>YAML 原文</strong> 标签页；下方表格仅显示维度摘要，保存表单不会覆盖 YAML 内长 prompt）。';
        } else if (useBatch) {
            notice.innerHTML =
                '当前为<strong>一次全评</strong>（省 token），由 YAML 或「Listing 七维」模板启用。';
        }
    }

    const catHint = document.querySelector(`#${prefix}-section-judge .cat-target-ui .hint`);
    if (catHint) {
        catHint.innerHTML = useBatch
            ? "可选。全评时绑定<strong>第一行维度</strong>的 ID；类别名须与全评 JSON 中该维 <code>categories</code> 一致。"
            : "当您希望「优秀 / 需注意 / 严重问题」之类标签在本次测试中的<strong>出现比例落在区间里</strong>时用。只对<strong>上面列表第一行维度</strong>生效；名字要和评委返回的类别<strong>完全一致</strong>。<strong>每一行从左到右</strong>：标签名 → 占比下限 → 占比上限（百分数）。";
    }
}

function getFirstFormEvaluatorFromDimensions(dimensions) {
    const list = Array.isArray(dimensions) ? dimensions : [];
    for (const d of list) {
        const ev = getFormEvaluator(d);
        if (ev) return ev;
    }
    return null;
}

function applyJudgeSharedFieldsToForm(prefix, dimensions, opts) {
    const dims = dimensions || [];
    const batch = opts?.batch ?? isBatchLlmFormEnabled(prefix);
    const batchCfg = opts?.batchCfg || null;
    const ev = getFirstFormEvaluatorFromDimensions(dims);
    const src = batchCfg || ev;
    const set = (id, val) => {
        const el = document.getElementById(`${prefix}-${id}`);
        if (el) el.value = val != null && val !== undefined ? String(val) : "";
    };
    set("judge-llm-model", src?.model || DEFAULT_JUDGE_LLM_MODEL);
    set(
        "judge-llm-temp",
        src?.temperature != null ? src.temperature : batch ? 0.08 : 0.1
    );
    set(
        "judge-llm-maxtok",
        src?.max_tokens != null ? src.max_tokens : batch ? 4500 : 2000
    );
    set(
        "judge-max-chars",
        batchCfg?.max_judge_input_chars != null ? batchCfg.max_judge_input_chars : 14000
    );
    if (opts?.listing) {
        set("judge-llm-temp", 0.08);
        set("judge-llm-maxtok", 4500);
        set("judge-max-chars", 14000);
    }
}

function collectJudgeSharedFields(prefix) {
    const g = (id) => document.getElementById(`${prefix}-${id}`)?.value.trim() ?? "";
    const tempRaw = g("judge-llm-temp");
    const maxTokRaw = g("judge-llm-maxtok");
    const maxCharsRaw = g("judge-max-chars");
    const batch = isBatchLlmFormEnabled(prefix);
    return {
        model: g("judge-llm-model") || DEFAULT_JUDGE_LLM_MODEL,
        temperature: tempRaw !== "" && !Number.isNaN(Number(tempRaw)) ? Number(tempRaw) : batch ? 0.08 : 0.1,
        max_tokens:
            maxTokRaw !== "" && !Number.isNaN(Number(maxTokRaw)) ? Number(maxTokRaw) : batch ? 4500 : 2000,
        max_judge_input_chars:
            maxCharsRaw !== "" && !Number.isNaN(Number(maxCharsRaw)) ? Number(maxCharsRaw) : 14000,
    };
}

function buildBatchPromptFromJudgeRows(rows, listingMode) {
    const ids = rows.map((r) => r.id).filter(Boolean);
    const lines = rows.map((r, i) => {
        const crit = String(r.criteria || "").trim() || r.name || r.id;
        return `${i + 1}. ${r.id}（${r.name}，权重 ${r.weight}）：${crit}`;
    });
    let intro = "你是内容质检员。请根据接口返回，一次性完成下列全部维度的评分（0～10）。";
    if (listingMode) {
        intro = `你是亚马逊 DE 站 Listing 七维质检员。根据【锚点】与【待评 Listing 摘录】一次性完成全部维度评分。
系统分制 0～10。硬门槛参考：事实一致性≥8.0、关键词策略≥7.2、合规≥8.0。

【锚点】site={{ site }}，sku={{ sku }}，productName={{ productName }}，productParameters={{ productParameters }}`;
    }
    const body = `${intro}\n\n【各维检查要点】\n${lines.join("\n")}`;
    let prompt = assembleBatchPromptFromParts(body, ids, false);
    if (listingMode) {
        prompt = prompt.replace(
            buildBatchLlmPromptTail(ids),
            `【待评 Listing 摘录】\n{{ listing_excerpt }}\n\n${buildBatchLlmPromptTail(ids)}`
        );
    }
    return prompt;
}

function mergeBatchLlmIntoObj(obj, prefix) {
    ensureConfigSkeleton(obj);
    const prev = obj.evaluation?.batch_llm || {};
    const rows = collectJudgeDimensionRows(prefix);
    const shared = collectJudgeSharedFields(prefix);
    const dimension_ids = rows.map((r) => r.id);
    if (!dimension_ids.length) {
        throw new Error("全评模式须至少配置一个维度");
    }
    const listingMode = document.getElementById(`${prefix}-judge-unified`)?.dataset.listingBatch === "1";
    let prompt_template = preservedBatchPrompts[prefix];
    if (!prompt_template) {
        prompt_template = buildBatchPromptFromJudgeRows(rows, listingMode);
    }
    const batch = {
        model: shared.model,
        temperature: shared.temperature,
        max_tokens: shared.max_tokens,
        max_judge_input_chars: shared.max_judge_input_chars,
        use_cache: true,
        dimension_ids,
        prompt_template,
    };
    if (prev.excerpt_mode) batch.excerpt_mode = prev.excerpt_mode;
    else if (listingMode) batch.excerpt_mode = "listing";
    if (prev.excerpt_keys) batch.excerpt_keys = prev.excerpt_keys;
    obj.evaluation.batch_llm = batch;

    const existing = Array.isArray(obj.evaluation.dimensions) ? obj.evaluation.dimensions : [];
    const merged = [];
    for (const row of rows) {
        const prevDim = existing.find((d) => d && d.id === row.id);
        merged.push({
            id: row.id,
            name: row.name || row.id,
            description: row.criteria || (prevDim && prevDim.description) || "",
            weight: row.weight,
            fail_fast: !!(prevDim && prevDim.fail_fast),
            evaluators: [],
        });
    }
    obj.evaluation.dimensions = merged;
}

function isBatchLlmFormEnabled(prefix) {
    const host = document.getElementById(`${prefix}-judge-unified`);
    return host?.dataset.batchMode === "1";
}

function removeEvalDimensionRow(btn) {
    const row = btn.closest(".eval-dim-row");
    if (!row) return;
    const sec = row.closest(".cfg-form-section[data-section='judge']");
    const prefix = (sec?.id || "").replace(/-section-judge$/, "") || "edit";
    row.remove();
    syncEvalDimensionPresetButtons(prefix);
}

function addEvalDimensionRow(prefix, preset) {
    const wrap = document.getElementById(`${prefix}-eval-dim-rows`);
    if (!wrap) return;
    const row = document.createElement("div");
    row.className = "eval-dim-row eval-per-dim-row";

    const judgeType = preset && preset.evaluator_type === "vision_llm" ? "vision_llm" : "llm";
    if (judgeType === "vision_llm") row.dataset.judgeType = "vision_llm";

    const isVision = judgeType === "vision_llm";
    const parsed = isVision
        ? {
              handwritten: true,
              body: preset && preset.prompt_template != null ? String(preset.prompt_template) : "",
          }
        : splitJudgePromptForForm(preset && preset.prompt_template != null ? preset.prompt_template : "");
    if (parsed.handwritten) row.dataset.handwritten = "1";

    const idIn = document.createElement("input");
    idIn.type = "text";
    idIn.className = "eval-dim-id cfg-judge-cell-input";
    idIn.placeholder = "维度 ID";
    if (preset && preset.id) idIn.value = String(preset.id);

    const nameIn = document.createElement("input");
    nameIn.type = "text";
    nameIn.className = "eval-dim-name cfg-judge-cell-input";
    nameIn.placeholder = "显示名称";
    if (preset && preset.name) nameIn.value = String(preset.name);

    const wIn = document.createElement("input");
    wIn.type = "number";
    wIn.step = "0.01";
    wIn.className = "eval-dim-weight cfg-judge-cell-input cfg-judge-cell-weight";
    wIn.placeholder = "1";
    wIn.value =
        preset && preset.weight != null && preset.weight !== "" ? String(preset.weight) : "1";

    const ta = document.createElement("textarea");
    ta.className = "eval-prompt cfg-judge-cell-input cfg-judge-cell-criteria";
    ta.rows = 2;
    ta.placeholder = "例：检查返回内容是否事实准确、无夸大宣传……";
    if (preset && preset.criteria != null && String(preset.criteria).trim()) {
        ta.value = String(preset.criteria);
    } else {
        ta.value = parsed.body;
    }

    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "btn btn-secondary cfg-judge-row-remove";
    rm.textContent = "移除";
    rm.addEventListener("click", () => removeEvalDimensionRow(rm));

    [idIn, nameIn, wIn, ta].forEach((el) => {
        el.addEventListener("input", () => {
            delete preservedBatchPrompts[prefix];
            const host = document.getElementById(`${prefix}-judge-unified`);
            if (host) delete host.dataset.listingBatch;
            /* 保持 batchMode：编辑行后仍按全评保存，仅重生成提示词 */
        });
    });

    row.appendChild(idIn);
    row.appendChild(nameIn);
    row.appendChild(wIn);
    row.appendChild(ta);
    row.appendChild(rm);

    if (preset && preset._presetKey) {
        row.dataset.presetKey = preset._presetKey;
    } else if (preset && preset.id) {
        const pk = getEvalDimPresetKeyById(preset.id);
        if (pk) row.dataset.presetKey = pk;
    }

    wrap.appendChild(row);
    syncEvalDimensionPresetButtons(prefix);
}

function clearEvalDimensionRows(prefix) {
    const wrap = document.getElementById(`${prefix}-eval-dim-rows`);
    if (wrap) wrap.innerHTML = "";
}

function renderEvalDimensionRows(prefix, dimensions, opts) {
    clearEvalDimensionRows(prefix);
    const batchMode = opts?.batchMode ?? isBatchLlmFormEnabled(prefix);
    const dims = Array.isArray(dimensions) ? dimensions : [];
    const idOrder = Array.isArray(opts?.dimensionIds) ? opts.dimensionIds : [];
    let list = batchMode ? dims.filter((d) => d && d.id) : dims.filter(dimensionHasFormEvaluator);
    if (batchMode && idOrder.length) {
        const ordered = [];
        const seen = new Set();
        idOrder.forEach((id) => {
            const d = list.find((x) => x && x.id === id);
            if (d) {
                ordered.push(d);
                seen.add(id);
            }
        });
        list.forEach((d) => {
            if (d && d.id && !seen.has(d.id)) ordered.push(d);
        });
        list = ordered;
    }
    if (list.length === 0) {
        syncEvalDimensionPresetButtons(prefix);
        return;
    }
    list.forEach((d) => {
        const ev = getFormEvaluator(d);
        const pk = getEvalDimPresetKeyById(d.id);
        let criteria = d.description || "";
        if (!batchMode && ev?.prompt_template) {
            criteria = splitJudgePromptForForm(ev.prompt_template).body;
        }
        addEvalDimensionRow(prefix, {
            id: d.id || "",
            name: d.name || "",
            weight: d.weight,
            criteria,
            prompt_template: ev?.prompt_template,
            evaluator_type: ev?.type || "llm",
            _presetKey: pk || undefined,
        });
    });
    syncEvalDimensionPresetButtons(prefix);
}

function collectJudgeDimensionRows(prefix) {
    const wrap = document.getElementById(`${prefix}-eval-dim-rows`);
    if (!wrap) return [];
    const out = [];
    wrap.querySelectorAll(".eval-dim-row").forEach((row) => {
        let id = row.querySelector(".eval-dim-id")?.value.trim() || "";
        const name = row.querySelector(".eval-dim-name")?.value.trim() || "";
        if (!id && name) {
            const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
            id = slug || `dim_${out.length + 1}`;
        }
        if (!id) return;
        const wRaw = row.querySelector(".eval-dim-weight")?.value.trim() || "";
        const criteria = row.querySelector(".eval-prompt")?.value.trim() || "";
        out.push({
            id,
            name: name || id,
            weight: wRaw !== "" && !Number.isNaN(Number(wRaw)) ? Number(wRaw) : 1,
            criteria,
            judgeType: row.dataset.judgeType === "vision_llm" ? "vision_llm" : "llm",
            handwritten: row.dataset.handwritten === "1",
        });
    });
    return out;
}

function collectEvalDimensionRows(prefix) {
    const shared = collectJudgeSharedFields(prefix);
    return collectJudgeDimensionRows(prefix).map((row) => {
        const prompt =
            row.judgeType === "vision_llm"
                ? row.criteria
                : assembleJudgePromptFromParts(row.criteria, row.handwritten);
        return {
            id: row.id,
            name: row.name,
            description: row.criteria,
            weight: row.weight,
            model: shared.model,
            prompt_template: prompt,
            temperature: shared.temperature,
            max_tokens: shared.max_tokens,
            evaluator_name: "",
            evaluator_type: row.judgeType,
        };
    });
}

function upsertDimensionFromRow(prevDim, row) {
    const id = row.id;
    let base;
    if (prevDim && typeof prevDim === "object") {
        base = JSON.parse(JSON.stringify(prevDim));
    } else {
        base = {
            id,
            name: row.name || id,
            description: row.description || "",
            weight:
                row.weight != null && row.weight !== "" && !Number.isNaN(Number(row.weight))
                    ? Number(row.weight)
                    : 1.0,
            fail_fast: false,
            evaluators: [],
        };
    }
    base.id = id;
    base.name = row.name || base.name || id;
    if (row.description !== undefined && row.description !== "") base.description = row.description;
    else if (base.description === undefined) base.description = "";
    base.weight =
        row.weight != null && row.weight !== "" && !Number.isNaN(Number(row.weight))
            ? Number(row.weight)
            : base.weight != null && !Number.isNaN(Number(base.weight))
              ? Number(base.weight)
              : 1.0;
    if (base.fail_fast === undefined) base.fail_fast = false;

    const judgeType = row.evaluator_type === "vision_llm" ? "vision_llm" : "llm";
    const evs = Array.isArray(base.evaluators) ? [...base.evaluators] : [];
    const lidx = evs.findIndex((e) => e && (e.type === "llm" || e.type === "vision_llm"));
    const prevEv = lidx >= 0 ? evs[lidx] : {};
    const pt =
        row.prompt_template && String(row.prompt_template).trim()
            ? String(row.prompt_template)
            : prevEv.prompt_template && String(prevEv.prompt_template).trim()
              ? String(prevEv.prompt_template)
              : judgeType === "vision_llm"
                ? ""
                : DEFAULT_LLM_PROMPT_FALLBACK;

    let temperature = 0.1;
    if (row.temperature != null && row.temperature !== "" && !Number.isNaN(Number(row.temperature))) {
        temperature = Number(row.temperature);
    } else if (prevEv.temperature != null && !Number.isNaN(Number(prevEv.temperature))) {
        temperature = Number(prevEv.temperature);
    }

    let max_tokens = judgeType === "vision_llm" ? 1800 : 2000;
    if (row.max_tokens != null && row.max_tokens !== "" && !Number.isNaN(Number(row.max_tokens))) {
        max_tokens = Number(row.max_tokens);
    } else if (prevEv.max_tokens != null && !Number.isNaN(Number(prevEv.max_tokens))) {
        max_tokens = Number(prevEv.max_tokens);
    }

    const defaultModel = judgeType === "vision_llm" ? "gpt-4o" : DEFAULT_JUDGE_LLM_MODEL;
    const formEval = {
        type: judgeType,
        name:
            row.evaluator_name && String(row.evaluator_name).trim()
                ? String(row.evaluator_name).trim()
                : prevEv.name || (judgeType === "vision_llm" ? "vision_judge" : "llm_judge"),
        dimension_id: id,
        model:
            row.model && String(row.model).trim()
                ? String(row.model).trim()
                : prevEv.model || defaultModel,
        prompt_template: pt,
        temperature,
        max_tokens,
    };
    if (judgeType === "llm") {
        formEval.output_schema =
            prevEv.output_schema && typeof prevEv.output_schema === "object" ? prevEv.output_schema : {};
        formEval.context = prevEv.context && typeof prevEv.context === "object" ? prevEv.context : {};
    } else {
        formEval.max_images = prevEv.max_images != null ? prevEv.max_images : 1;
    }
    if (lidx >= 0) evs[lidx] = formEval;
    else evs.push(formEval);
    base.evaluators = evs;
    return base;
}

function mergeEvaluationRowsIntoObj(obj, rows) {
    ensureConfigSkeleton(obj);
    const filteredRows = (rows || []).filter((r) => r && r.id);
    // 没有任何有效维度 ID 时不改写 evaluation（避免误清空 YAML 里的多维度评委）
    if (filteredRows.length === 0) {
        return;
    }
    const existing = Array.isArray(obj.evaluation.dimensions) ? obj.evaluation.dimensions : [];
    const rowIds = new Set(filteredRows.map((r) => r.id));

    const mergedDims = [];
    for (const row of filteredRows) {
        const prev = existing.find((d) => d && d.id === row.id);
        mergedDims.push(upsertDimensionFromRow(prev || null, row));
    }

    const preserved = existing.filter((d) => {
        if (!d || !d.id) return false;
        if (rowIds.has(d.id)) return false;
        return !dimensionHasFormEvaluator(d);
    });

    obj.evaluation.dimensions = [...mergedDims, ...preserved];
}

function removeCatTargetRow(btn) {
    const row = btn.closest(".cat-target-row");
    if (row) row.remove();
}

function addCatTargetRow(prefix, preset) {
    const wrap = document.getElementById(`${prefix}-cat-target-rows`);
    if (!wrap) return;
    const row = document.createElement("div");
    row.className = "cat-target-row";
    const catIn = document.createElement("input");
    catIn.type = "text";
    catIn.className = "cat-target-name";
    catIn.placeholder = "标签名（须与评委返回的类别一字不差）";
    if (preset && preset.category) catIn.value = String(preset.category);
    const minIn = document.createElement("input");
    minIn.type = "number";
    minIn.className = "cat-target-min";
    minIn.placeholder = "占比下限 %";
    minIn.step = "0.1";
    if (preset && preset.min_percent != null && preset.min_percent !== "") minIn.value = String(preset.min_percent);
    const maxIn = document.createElement("input");
    maxIn.type = "number";
    maxIn.className = "cat-target-max";
    maxIn.placeholder = "占比上限 %";
    maxIn.step = "0.1";
    if (preset && preset.max_percent != null && preset.max_percent !== "") maxIn.value = String(preset.max_percent);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn btn-secondary cfg-judge-row-remove";
    btn.textContent = "移除";
    btn.addEventListener("click", () => removeCatTargetRow(btn));
    row.appendChild(catIn);
    row.appendChild(minIn);
    row.appendChild(maxIn);
    row.appendChild(btn);
    wrap.appendChild(row);
}

function clearCatTargetRows(prefix) {
    const wrap = document.getElementById(`${prefix}-cat-target-rows`);
    if (wrap) wrap.innerHTML = "";
}

function renderCatTargetRows(prefix, targets) {
    clearCatTargetRows(prefix);
    const list = Array.isArray(targets) ? targets : [];
    if (list.length === 0) {
        addCatTargetRow(prefix, null);
        return;
    }
    list.forEach((t) =>
        addCatTargetRow(prefix, {
            category: t.category || "",
            min_percent: t.min_percent,
            max_percent: t.max_percent,
        })
    );
}

function collectCatTargetRows(prefix) {
    const wrap = document.getElementById(`${prefix}-cat-target-rows`);
    if (!wrap) return [];
    const out = [];
    wrap.querySelectorAll(".cat-target-row").forEach((row) => {
        const category = row.querySelector(".cat-target-name")?.value.trim() || "";
        const minRaw = row.querySelector(".cat-target-min")?.value.trim() || "";
        const maxRaw = row.querySelector(".cat-target-max")?.value.trim() || "";
        if (!category) return;
        const item = { category };
        if (minRaw !== "") item.min_percent = Number(minRaw);
        if (maxRaw !== "") item.max_percent = Number(maxRaw);
        out.push(item);
    });
    return out;
}

function upsertPassCriteriaCategoryDistribution(obj, dimId, targets) {
    ensureConfigSkeleton(obj);
    obj.pass_criteria = obj.pass_criteria || {};
    obj.pass_criteria.dimensions = Array.isArray(obj.pass_criteria.dimensions) ? obj.pass_criteria.dimensions : [];
    const dims = obj.pass_criteria.dimensions;
    const idx = dims.findIndex((d) => d && d.id === dimId);
    const dist = targets.map((t) => {
        const x = { category: t.category };
        if (t.min_percent != null && !Number.isNaN(t.min_percent)) x.min_percent = t.min_percent;
        if (t.max_percent != null && !Number.isNaN(t.max_percent)) x.max_percent = t.max_percent;
        return x;
    });
    if (idx >= 0) {
        dims[idx] = { ...dims[idx], id: dimId, category_distribution: dist };
    } else if (dist.length > 0) {
        dims.push({
            id: dimId,
            min_avg_score: 6.0,
            max_fail_rate: 0.3,
            category_distribution: dist,
        });
    }
}

function initConfigForms() {
    ["create", "edit"].forEach((prefix) => {
        const subHost = document.getElementById(`${prefix}-cfg-subtabs`);
        const fields = document.getElementById(`${prefix}-form-fields`);
        if (subHost) subHost.innerHTML = buildFormSubtabsHtml(prefix);
        if (fields) fields.innerHTML = buildFormFieldsHtml(prefix);
        bindPromptFieldSelect(prefix);
        bindFetchParamNameInput(prefix);
        bindFetchBatchModeSelect(prefix);
        initConfigFormMode(prefix);
    });
    ["create", "edit"].forEach((prefix) => {
        const w = document.getElementById(`${prefix}-variables-rows`);
        if (w && !w.querySelector(".var-row")) addDefaultVariableExamples(prefix, null);
        const ctr = document.getElementById(`${prefix}-cat-target-rows`);
        if (ctr && !ctr.querySelector(".cat-target-row")) addCatTargetRow(prefix, null);
        renderEvalDimensionRows(prefix, []);
        applyJudgeSharedFieldsToForm(prefix, null, {});
        setConfigFormSubtab(prefix, "basic");
        syncSuiteModeUI(prefix, null);
        syncContentKindUI(prefix, "text");
    });
}

function getConfigTextarea(scope) {
    return scope === "create"
        ? document.getElementById("new-project-config")
        : document.getElementById("edit-config");
}

/** 合并前同步当前界面到 YAML（若在表单页则先 flush） */
function getConfigObjectForMerge(scope) {
    yamlLib();
    const yamlPanel = document.getElementById(`${scope}-panel-yaml`);
    const onYamlOnly = yamlPanel && yamlPanel.style.display !== "none";
    if (!onYamlOnly) flushFormToYaml(scope);
    const ta = getConfigTextarea(scope);
    const t = ta.value.trim();
    if (!t) return {};
    return yamlLib().load(t) || {};
}

const CURL_HOP_BY_HOP = new Set(["content-length", "host", "connection", "accept-encoding"]);

/** 浏览器 cURL 里常见但 REST 客户端/网关不接受的头（含 priority 会导致 nginx 400） */
const CURL_SKIP_HEADERS = new Set([
    ...CURL_HOP_BY_HOP,
    "priority",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "cache-control",
    "pragma",
]);

function filterCurlHeaders(rawHeaders) {
    const out = {};
    let authValue = null;
    for (const [k, v] of Object.entries(rawHeaders || {})) {
        const lk = String(k).toLowerCase();
        if (CURL_SKIP_HEADERS.has(lk)) continue;
        if (lk === "authorization") {
            authValue = v;
            continue;
        }
        if (lk === "content-type") continue;
        out[k] = v;
    }
    if (authValue != null && String(authValue).trim() !== "") {
        const a = String(authValue).trim();
        out.Authorization = /^bearer\s+/i.test(a) ? a : `Bearer ${a}`;
    }
    return out;
}

function normalizeCurlPaste(text) {
    if (!text || typeof text !== "string") return "";
    return text
        .replace(/\r\n/g, "\n")
        .replace(/\\\n/g, "")
        .replace(/[\uFEFF\u200B]/g, "")
        .trim();
}

function tokenizeShellQuoted(input) {
    const tokens = [];
    let i = 0;
    const n = input.length;
    while (i < n) {
        while (i < n && /\s/.test(input[i])) i++;
        if (i >= n) break;
        const c = input[i];
        if (c === "'") {
            i++;
            let buf = "";
            while (i < n && input[i] !== "'") buf += input[i++];
            if (i < n && input[i] === "'") i++;
            tokens.push(buf);
            continue;
        }
        if (c === '"') {
            i++;
            let buf = "";
            while (i < n) {
                if (input[i] === "\\" && i + 1 < n) {
                    buf += input[i + 1];
                    i += 2;
                    continue;
                }
                if (input[i] === '"') {
                    i++;
                    break;
                }
                buf += input[i++];
            }
            tokens.push(buf);
            continue;
        }
        let buf = "";
        while (i < n && !/\s/.test(input[i])) buf += input[i++];
        tokens.push(buf);
    }
    return tokens;
}

/**
 * 将粘贴内容拆成多条 curl（DevTools 复制多条时常用 `;` 分隔）。
 */
function splitCurlCommands(text) {
    const t = normalizeCurlPaste(text);
    if (!t) return [];
    if (!/\;\s*curl\b/i.test(t)) {
        const one = t.replace(/;\s*$/, "").trim();
        return one && /^\s*curl\b/i.test(one) ? [one] : [];
    }
    return t
        .split(/\;\s*(?=curl\b)/i)
        .map((p) => p.trim().replace(/;\s*$/, "").trim())
        .filter((p) => /^\s*curl\b/i.test(p));
}

/** 多条 curl 时优先详情/get（含 id），降低 page/list 分页接口权重 */
function scoreCurlCommand(parsed) {
    const url = (parsed.url || "").toLowerCase();
    if (/^wss:\/\//.test(url)) return -1000;
    let score = 0;
    try {
        const u = new URL(parsed.url);
        const path = u.pathname.toLowerCase();
        if (path.endsWith("/get") || /\/get(?:\/|$)/.test(path)) score += 50;
        if (path.endsWith("/page") || /\/page(?:\/|$)/.test(path)) score -= 40;
        if (path.endsWith("/list") || /\/list(?:\/|$)/.test(path)) score -= 30;
        if (u.searchParams.has("id")) score += 45;
        const keys = [...u.searchParams.keys()];
        if (keys.length === 1 && u.searchParams.has("id")) score += 25;
        if (
            u.searchParams.has("pageNo") ||
            u.searchParams.has("pageSize") ||
            u.searchParams.has("page")
        ) {
            score -= 25;
        }
    } catch (_) {
        /* ignore */
    }
    return score;
}

/**
 * 多条 curl 时选用最适合「被测接口」的一条；单条则原样返回。
 */
function pickBestCurlFromPaste(rawText) {
    const commands = splitCurlCommands(rawText);
    if (!commands.length) {
        const t = normalizeCurlPaste(rawText);
        if (!t) throw new Error("内容为空");
        if (!/^\s*curl\b/i.test(t)) {
            throw new Error(
                '请粘贴以 curl 开头的命令（浏览器：开发者工具 → 网络 → 复制为 cURL(bash)）'
            );
        }
        return { text: t.replace(/;\s*$/, "").trim(), note: "" };
    }
    if (commands.length === 1) {
        return { text: commands[0], note: "" };
    }

    let bestIdx = 0;
    let bestScore = -Infinity;
    const candidates = [];
    for (let i = 0; i < commands.length; i++) {
        try {
            const parsed = parseBrowserCurlSingle(commands[i]);
            const s = scoreCurlCommand(parsed);
            candidates.push({ i, s, url: parsed.url });
            if (s > bestScore) {
                bestScore = s;
                bestIdx = i;
            }
        } catch (_) {
            candidates.push({ i, s: -999, url: "" });
        }
    }

    const picked = candidates.find((c) => c.i === bestIdx);
    const pickedUrl = picked && picked.url ? picked.url : "";
    let note = `检测到 ${commands.length} 条 cURL，已自动选用被测详情接口：${pickedUrl || "（见下方地址）"}`;
    const ignored = candidates.filter((c) => c.i !== bestIdx && c.url);
    if (ignored.length) {
        note += `；已忽略：${ignored.map((c) => c.url).join("、")}`;
    }
    note += "。若不对，请只粘贴需要测评的那一条。";
    return { text: commands[bestIdx], note };
}

/**
 * DevTools 常同时复制多条 curl：HTTPS API + wss(WebSocket)。
 * 已由 pickBestCurlFromPaste 处理多 HTTP 场景；此函数保留供单条截断 wss 后缀。
 */
function takeOnlyFirstCurlCommand(text) {
    const t = text.trim();
    if (!t) return t;
    const m = t.match(/\;\s*\n\s*curl\b/i);
    if (m && m.index != null) {
        return t
            .slice(0, m.index)
            .trim()
            .replace(/;\s*$/, "")
            .trim();
    }
    const n = t.search(/\;\s*curl\b/i);
    if (n >= 0) {
        return t
            .slice(0, n)
            .trim()
            .replace(/;\s*$/, "")
            .trim();
    }
    return t.replace(/;\s*$/, "").trim();
}

/**
 * 解析单条 curl 命令（不含多选逻辑）。
 */
function parseBrowserCurlSingle(text) {
    if (!/^\s*curl\b/i.test(text)) {
        throw new Error("不是有效的 curl 命令");
    }
    const rest = text.replace(/^\s*curl(\.exe)?\s+/i, "").trim();
    const tokens = tokenizeShellQuoted(rest);
    let method = null;
    let body = null;
    const headers = {};
    let url = null;

    for (let ti = 0; ti < tokens.length; ti++) {
        const t = tokens[ti];
        if (t === "-X" || t === "--request") {
            method = (tokens[++ti] || "GET").toUpperCase();
            continue;
        }
        if (t === "-H" || t === "--header") {
            const hv = tokens[++ti] || "";
            const idx = hv.indexOf(":");
            if (idx > 0) headers[hv.slice(0, idx).trim()] = hv.slice(idx + 1).trim();
            continue;
        }
        if (t === "--data-raw" || t === "--data" || t === "--data-binary" || t === "-d") {
            body = tokens[++ti];
            continue;
        }
        if (t === "--json") {
            body = tokens[++ti];
            if (!method) method = "POST";
            continue;
        }
        if (t === "-G" || t === "--get") {
            method = "GET";
            continue;
        }
        if (t.startsWith("-")) continue;
        if (/^https?:\/\//i.test(t)) url = t;
    }

    if (!url) throw new Error("未解析到 URL");
    if (!method) method = body ? "POST" : "GET";
    return { url, method, headers, body };
}

/**
 * 解析 Chrome / Edge「复制为 cURL(bash)」常见格式（POST + JSON、GET + query）。
 * 粘贴多条时优先选用 /get?id=… 类详情接口，而非 /page 列表接口。
 */
function parseBrowserCurl(rawText) {
    let text = normalizeCurlPaste(rawText);
    if (!text) throw new Error("内容为空");

    let selectionNote = "";
    if (/\;\s*curl\b/i.test(text)) {
        const picked = pickBestCurlFromPaste(text);
        text = picked.text;
        selectionNote = picked.note || "";
    } else {
        text = takeOnlyFirstCurlCommand(text);
    }

    if (!/^\s*curl\b/i.test(text)) {
        throw new Error(
            '请粘贴以 curl 开头的命令（浏览器：开发者工具 → 网络 → 复制为 cURL(bash)）。若内含多条 curl，请删除后续的 wss(WebSocket)，或仅粘贴 HTTPS 这一条'
        );
    }
    const parsed = parseBrowserCurlSingle(text);
    parsed.selectionNote = selectionNote;
    return parsed;
}

function applyCurlTextToConfig(scope, curlText) {
    yamlLib();
    const parsed = parseBrowserCurl(curlText);
    const obj = getConfigObjectForMerge(scope);
    ensureConfigSkeleton(obj);

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
        curlVarsApplied = applyCurlPrimitivesAsTemplateAndVariables(obj, queryObj);
        if (!curlVarsApplied) {
            obj.target.input_formatter.template = queryObj;
        }
    } else {
        if (urlObj) endpoint = urlObj.origin + urlObj.pathname + urlObj.search;
        else endpoint = parsed.url.split("#")[0];

        if (parsed.body != null && String(parsed.body).trim() !== "") {
            const rawB = String(parsed.body).trim();
            if (rawB.startsWith("@")) {
                throw new Error("暂不支持 cURL 中以 @ 文件形式指定的请求体，请粘贴原始 JSON 或用手写 YAML");
            }
            let bodyObj;
            try {
                bodyObj = JSON.parse(rawB);
            } catch (e) {
                throw new Error("请求体不是合法 JSON：" + (e.message || String(e)));
            }
            curlVarsApplied = applyCurlPrimitivesAsTemplateAndVariables(obj, bodyObj);
            if (!curlVarsApplied) {
                obj.target.input_formatter.template = bodyObj;
            }
        } else if (upperMethod === "GET") {
            obj.target.input_formatter.template = {};
        }
    }

    obj.target.connector.config.endpoint = endpoint;
    obj.target.connector.config.method = upperMethod;
    // 覆盖旧 headers，避免与历史 Authorization/authorization 叠加导致 nginx 400
    obj.target.connector.config.headers = filterCurlHeaders(parsed.headers);

    const ta = getConfigTextarea(scope);
    ta.value = yamlLib().dump(obj, { lineWidth: 120, noRefs: true });

    const formTab = document.getElementById(`${scope}-tab-form`);
    const yamlTab = document.getElementById(`${scope}-tab-yaml`);
    const formPanel = document.getElementById(`${scope}-panel-form`);
    const yamlPanel = document.getElementById(`${scope}-panel-yaml`);
    if (formTab) formTab.classList.add("active");
    if (yamlTab) yamlTab.classList.remove("active");
    if (formPanel) formPanel.style.display = "block";
    if (yamlPanel) yamlPanel.style.display = "none";
    refreshFormFromYaml(scope);
    setConfigFormSubtab(scope, "http");

    const tpl = obj.target.input_formatter.template;
    const promptField = inferPromptFieldName(tpl);
    const pfSel = document.getElementById(`${scope}-prompt-field`);
    if (pfSel) {
        if (PROMPT_FIELD_PRESETS.includes(promptField)) {
            pfSel.value = promptField;
        } else {
            pfSel.value = "__custom__";
            const customIn = document.getElementById(`${scope}-prompt-field-custom`);
            if (customIn) customIn.value = promptField;
        }
        syncPromptFieldCustomVisibility(scope);
    }

    const extracted = extractPromptFieldFromTemplate(tpl);
    const varNames = (obj.data_generator?.variables || []).map((v) => v?.name).filter(Boolean);
    const curlHints = {
        endpoint: obj.target.connector.config.endpoint,
        method: obj.target.connector.config.method,
        promptField,
        outputPath: obj.target.output_parser.path || "",
        complexBody: extracted.mode === "partial",
        selectionNote: parsed.selectionNote || "",
        variablesNote: curlVarsApplied
            ? `顶层参数已拆成模板占位符 + 测试数据取值：${varNames.join(", ")}`
            : "",
    };
    if (upperMethod === "GET" && urlObj && urlObj.search && urlObj.search.length > 1) {
        const qs = new URLSearchParams(urlObj.search).toString();
        curlHints.queryNote = `URL 查询参数已写入「接口入参模板」${curlVarsApplied ? "（占位符）" : ""}：${qs}`;
    }
    showCurlConfirmBanner(scope, curlHints);
    syncSuiteModeUI(scope, obj);
    syncFetchParamNameUI(scope, obj);
    setFetchBatchMode(scope, "param", true);
}

function importCurlFromPaste(scope) {
    try {
        yamlLib();
        const curlTa = document.getElementById(`${scope}-curl-paste`);
        const raw = curlTa && curlTa.value ? curlTa.value.trim() : "";
        if (!raw) {
            alert("请先把 cURL 粘贴到文本框中");
            return;
        }
        applyCurlTextToConfig(scope, raw);
        if (curlTa) curlTa.value = "";
        if (typeof setApiStatus === "function") {
            setApiStatus(
                "已从 cURL 填入接口；顶层参数已写入模板占位符与「测试数据取值」，请向下确认",
                "ok"
            );
        }
    } catch (e) {
        alert(e.message || String(e));
    }
}

function applyObjectToInputs(prefix, obj) {
    ensureConfigSkeleton(obj);
    const tpl = obj.target.input_formatter.template;

    const set = (id, v) => {
        const el = document.getElementById(`${prefix}-${id}`);
        if (el) el.value = v != null && v !== undefined ? String(v) : "";
    };

    set("meta-name", obj.meta.name);
    set("meta-desc", obj.meta.description);
    set("meta-version", obj.meta.version);

    set("connector-name", obj.target.connector.name);
    set("endpoint", obj.target.connector.config.endpoint);
    const hdr = obj.target.connector.config.headers || {};
    const authVal = hdr.Authorization != null ? hdr.Authorization : hdr.authorization;
    set("auth-header", authVal != null && authVal !== undefined ? authVal : "");
    set("output-path", obj.target.output_parser.path ?? "");
    const okTaInit = document.getElementById(`${prefix}-output-keys`);
    const opKeysInit = obj.target.output_parser.keys;
    if (okTaInit) {
        okTaInit.value = Array.isArray(opKeysInit) ? opKeysInit.join("\n") : "";
    }
    set("timeout", obj.target.connector.config.timeout);
    set("concurrency", obj.target.connector.config.concurrency);
    const ptParsed = parseAutoPromptTemplate(
        obj.data_generator.prompt_template,
        obj.data_generator.variables
    );
    if (!isConfigFormAdvanced(prefix)) {
        set("prompt-prefix", ptParsed.custom ? "" : ptParsed.prefix);
    }
    const sc = obj.pass_criteria?.global_criteria?.min_total_score;
    set("min-total-score", sc != null && sc !== "" ? sc : "");

    const kind = getContentKindFromObj(obj);
    const ck = document.getElementById(`${prefix}-content-kind`);
    if (ck) ck.value = kind;
    syncContentKindUI(prefix, kind);
    set("media-urls-path", obj.target?.output_parser?.media?.urls_path || "");
    const dl = document.getElementById(`${prefix}-media-download`);
    if (dl) dl.checked = obj.target?.output_parser?.media?.download !== false;

    const batch = obj.evaluation?.batch_llm;
    const useBatch = evaluationUsesBatchLlm(obj);
    const judgeHost = document.getElementById(`${prefix}-judge-unified`);
    if (useBatch) setJudgeBatchMode(prefix, true);
    else setJudgeBatchMode(prefix, false);
    if (useBatch && batch?.prompt_template) {
        const parsed = splitBatchPromptForForm(batch.prompt_template, batch.dimension_ids || []);
        if (parsed.handwritten) preservedBatchPrompts[prefix] = batch.prompt_template;
        else delete preservedBatchPrompts[prefix];
        if (batch.excerpt_mode === "listing") {
            if (judgeHost) judgeHost.dataset.listingBatch = "1";
        } else if (judgeHost) {
            delete judgeHost.dataset.listingBatch;
        }
    } else {
        delete preservedBatchPrompts[prefix];
    }
    applyJudgeSharedFieldsToForm(prefix, obj.evaluation.dimensions || [], {
        batch: useBatch,
        batchCfg: batch,
    });
    renderEvalDimensionRows(prefix, obj.evaluation.dimensions || [], {
        batchMode: useBatch,
        dimensionIds: batch?.dimension_ids,
    });
    syncJudgeModeUI(prefix, obj);

    const judgeRows = collectJudgeDimensionRows(prefix);
    const firstDimId = judgeRows[0]?.id ?? DEFAULT_FORM_EVAL_DIM_ID;
    const pcDim = (obj.pass_criteria?.dimensions || []).find((x) => x && x.id === firstDimId);
    renderCatTargetRows(prefix, pcDim?.category_distribution || []);

    set("http-method", obj.target.connector.config.method || "POST");

    const extracted = extractPromptFieldFromTemplate(tpl);
    const pfSel = document.getElementById(`${prefix}-prompt-field`);
    const pfCustom = document.getElementById(`${prefix}-prompt-field-custom`);
    if (pfSel) {
        if (extracted.mode === "custom" || !PROMPT_FIELD_PRESETS.includes(extracted.field)) {
            pfSel.value = PROMPT_FIELD_PRESETS.includes(extracted.field) ? extracted.field : "__custom__";
            if (pfCustom && pfSel.value === "__custom__") pfCustom.value = extracted.field;
        } else {
            pfSel.value = extracted.field;
        }
    }
    syncPromptFieldCustomVisibility(prefix);

    const genTa = document.getElementById(`${prefix}-generic-body-yaml`);
    if (genTa) {
        try {
            genTa.value = yamlLib().dump(tpl || {}, { lineWidth: 100, noRefs: true });
        } catch (_) {
            genTa.value = String(tpl || "");
        }
    }

    applyDataGeneratorFormToInputs(prefix, obj, ptParsed);
    syncSuiteModeUI(prefix, obj);
}

function applyDataGeneratorFormToInputs(prefix, obj, ptParsed) {
    const parsed =
        ptParsed ||
        parseAutoPromptTemplate(obj.data_generator?.prompt_template, obj.data_generator?.variables);
    ensureDataGeneratorVariablesFromTemplate(obj);

    const useJsonBatch =
        shouldUseFetchJsonBatch(obj) && getConfigSuiteMode(prefix, obj) === "fetch";
    setFetchBatchMode(prefix, useJsonBatch ? "json" : "param", false);
    if (useJsonBatch) {
        clearVariableRows(prefix);
        renderFetchJsonRows(prefix, obj.data_generator?.rows || []);
    } else {
        clearFetchJsonRows(prefix);
        renderVariableRows(prefix, obj.data_generator.variables, parsed.labelsByName, obj);
    }
    syncFetchParamNameUI(prefix, obj);
    syncFetchBatchModeUI(prefix, obj);
}

function mergeDataGeneratorInputsToObject(prefix, obj) {
    const g = (id) => {
        const el = document.getElementById(`${prefix}-${id}`);
        return el ? String(el.value).trim() : "";
    };
    ensureConfigSkeleton(obj);

    const fetchJsonBatch =
        isFetchJsonBatchMode(prefix) && getConfigSuiteMode(prefix, obj) === "fetch";

    if (fetchJsonBatch) {
        obj.data_generator.strategy = "fixed_rows";
    }

    if (obj.data_generator.sampling) {
        delete obj.data_generator.sampling.total;
        if (Object.keys(obj.data_generator.sampling).length === 0) {
            delete obj.data_generator.sampling;
        }
    }

    const mode = getConfigSuiteMode(prefix, obj);
    if (mode === "generate" && !isConfigFormAdvanced(prefix)) {
        const existingPt = obj.data_generator.prompt_template;
        const parsedExisting = parseAutoPromptTemplate(existingPt, collectVariableRows(prefix));
        if (parsedExisting.custom && String(existingPt || "").trim()) {
            obj.data_generator.prompt_template = existingPt;
        } else {
            obj.data_generator.prompt_template = buildAutoPromptTemplate(prefix);
        }
    } else if (isFetchJsonBatchMode(prefix)) {
        const rows = collectFetchJsonRows(prefix);
        obj.data_generator.prompt_template = buildMetaPromptFromRows(rows);
    } else if (!isConfigFormAdvanced(prefix)) {
        obj.data_generator.prompt_template = buildAutoMetaPromptTemplate(prefix);
    }

    if (fetchJsonBatch) {
        const rows = collectFetchJsonRows(prefix);
        if (!rows.length) throw new Error("请至少添加一条完整 JSON 请求参数");
        obj.data_generator.rows = rows;
        obj.data_generator.variables = [];
        if (obj.data_generator.strategy !== "fixed_rows") obj.data_generator.strategy = "fixed_rows";
    } else {
        delete obj.data_generator.rows;
        obj.data_generator.variables = collectVariableRows(prefix).map(({ name, type, values }) => ({
            name,
            type,
            values,
        }));
    }
}

function applyInputsToObject(prefix, obj) {
    const g = (id) => {
        const el = document.getElementById(`${prefix}-${id}`);
        return el ? String(el.value).trim() : "";
    };

    obj.meta = obj.meta || {};
    if (Object.prototype.hasOwnProperty.call(obj.meta, "sut_mode")) {
        delete obj.meta.sut_mode;
    }

    ensureConfigSkeleton(obj);

    const n = g("meta-name");
    if (n) obj.meta.name = n;
    const d = g("meta-desc");
    if (d !== undefined) obj.meta.description = d;
    const ver = g("meta-version");
    if (ver) obj.meta.version = ver;

    const cn = g("connector-name");
    if (cn) obj.target.connector.name = cn;

    const ep = g("endpoint");
    if (ep) obj.target.connector.config.endpoint = ep;

    const auth = g("auth-header");
    if (auth) {
        obj.target.connector.config.headers.Authorization = auth;
    }

    const to = g("timeout");
    if (to !== "") obj.target.connector.config.timeout = Number(to);
    const co = g("concurrency");
    if (co !== "") obj.target.connector.config.concurrency = Number(co);

    const bodyRaw = document.getElementById(`${prefix}-generic-body-yaml`)?.value.trim() || "";
    let bodyFromYaml = null;
    if (bodyRaw) {
        try {
            bodyFromYaml = yamlLib().load(bodyRaw);
        } catch (err) {
            throw new Error("接口入参模板（YAML）解析失败: " + err.message);
        }
    }

    if (bodyFromYaml !== null) {
        obj.target.input_formatter.template = bodyFromYaml;
    } else if (isConfigFormAdvanced(prefix)) {
        obj.target.input_formatter.template = { query: "{{ input.prompt }}" };
    } else {
        const mode = getConfigSuiteMode(prefix, obj);
        if (mode === "generate") {
            obj.target.input_formatter.template = applyPromptFieldToTemplate(
                obj.target.input_formatter.template,
                prefix
            );
        } else if (isFetchJsonBatchMode(prefix)) {
            const rows = collectFetchJsonRows(prefix);
            if (!rows.length) throw new Error("请至少添加一条完整 JSON 请求参数");
            obj.target.input_formatter.template = buildRequestTemplateFromJsonRows(
                rows,
                obj.target.input_formatter.template
            );
        } else if (isComplexFetchBody(obj.target.input_formatter.template)) {
            throw new Error(
                "接口入参含多字段，请在「接口入参模板」中编辑 YAML，或切换批量方式为「每条一组完整 JSON」"
            );
        } else {
            obj.target.input_formatter.template = buildRequestTemplateFromVariables(
                prefix,
                obj.target.input_formatter.template
            );
        }
    }
    const meth = g("http-method");
    if (meth) obj.target.connector.config.method = meth.toUpperCase();

    const op = g("output-path");
    if (op) obj.target.output_parser.path = op;

    const okTa = document.getElementById(`${prefix}-output-keys`);
    const keysRaw = okTa ? String(okTa.value).trim() : "";
    if (keysRaw) {
        obj.target.output_parser.keys = keysRaw
            .split(/\n|,/)
            .map((s) => s.trim())
            .filter(Boolean);
    } else {
        delete obj.target.output_parser.keys;
    }

    const kind = document.getElementById(`${prefix}-content-kind`)?.value || "text";
    if (kind === "image") {
        obj.target.output_parser.content_mode = "image";
        const mup = g("media-urls-path");
        const dlEl = document.getElementById(`${prefix}-media-download`);
        if (mup) {
            obj.target.output_parser.media = obj.target.output_parser.media || {};
            obj.target.output_parser.media.urls_path = mup;
            obj.target.output_parser.media.download = dlEl ? dlEl.checked : true;
        } else {
            delete obj.target.output_parser.media;
        }
        delete obj.target.output_parser.keys;
    } else {
        delete obj.target.output_parser.content_mode;
        delete obj.target.output_parser.media;
    }

    mergeDataGeneratorInputsToObject(prefix, obj);

    const mts = g("min-total-score");
    if (mts !== "") {
        obj.pass_criteria = obj.pass_criteria || {};
        obj.pass_criteria.global_criteria = obj.pass_criteria.global_criteria || {};
        obj.pass_criteria.global_criteria.min_total_score = Number(mts);
    }

    if (isBatchLlmFormEnabled(prefix)) {
        mergeBatchLlmIntoObj(obj, prefix);
    } else {
        delete obj.evaluation.batch_llm;
        const evalRows = collectEvalDimensionRows(prefix);
        mergeEvaluationRowsIntoObj(obj, evalRows);
    }
    const boundRows = collectJudgeDimensionRows(prefix);
    const catBindId = boundRows.length > 0 ? boundRows[0].id : DEFAULT_FORM_EVAL_DIM_ID;
    upsertPassCriteriaCategoryDistribution(obj, catBindId, collectCatTargetRows(prefix));
}

function flushFormToYaml(scope) {
    yamlLib();
    const ta = getConfigTextarea(scope);
    const prefix = scope;
    let obj;
    try {
        obj = ta.value.trim() ? yamlLib().load(ta.value) : {};
    } catch (e) {
        throw new Error("当前 YAML 无法解析，请先切换到 YAML 原文修正。\n" + e.message);
    }
    if (!obj || typeof obj !== "object") obj = {};
    ensureConfigSkeleton(obj);
    applyInputsToObject(prefix, obj);
    ta.value = yamlLib().dump(obj, { lineWidth: 120, noRefs: true });
    try {
        refreshFormFromYaml(scope);
    } catch (_) {
        /* 理论不应失败；兜底避免阻断保存 */
    }
}

function refreshFormFromYaml(scope) {
    yamlLib();
    const ta = getConfigTextarea(scope);
    const prefix = scope;
    let obj;
    try {
        obj = ta.value.trim() ? yamlLib().load(ta.value) : {};
    } catch (e) {
        throw e;
    }
    if (!obj || typeof obj !== "object") obj = {};
    ensureConfigSkeleton(obj);
    applyObjectToInputs(prefix, obj);
}

function openConfigEditorYaml(scope, hint) {
    setConfigEditorMode(scope, "yaml");
    if (hint && typeof setApiStatus === "function") {
        setApiStatus(hint, "ok");
    }
}

window.openConfigEditorYaml = openConfigEditorYaml;
window.setConfigEditorMode = setConfigEditorMode;

function setConfigEditorMode(scope, mode) {
    const formTab = document.getElementById(`${scope}-tab-form`);
    const yamlTab = document.getElementById(`${scope}-tab-yaml`);
    const formPanel = document.getElementById(`${scope}-panel-form`);
    const yamlPanel = document.getElementById(`${scope}-panel-yaml`);
    const subtabBar = document.getElementById(`${scope}-cfg-subtabs`);

    if (mode === "yaml") {
        try {
            flushFormToYaml(scope);
        } catch (e) {
            alert(e.message || String(e));
            return;
        }
        formTab.classList.remove("active");
        yamlTab.classList.add("active");
        formPanel.style.display = "none";
        yamlPanel.style.display = "block";
        if (subtabBar) {
            subtabBar.style.display = "none";
            subtabBar.setAttribute("aria-hidden", "true");
        }
    } else {
        try {
            refreshFormFromYaml(scope);
        } catch (e) {
            alert("YAML 解析失败: " + (e.message || String(e)));
            return;
        }
        formTab.classList.add("active");
        yamlTab.classList.remove("active");
        formPanel.style.display = "block";
        yamlPanel.style.display = "none";
        if (subtabBar) {
            subtabBar.style.display = "";
            subtabBar.setAttribute("aria-hidden", "false");
        }
        applyConfigFormMode(scope, getStoredConfigFormMode());
        setConfigFormSubtab(scope, "http");
    }
}

function importYamlFromFile(scope, input) {
    const f = input.files && input.files[0];
    if (!f) return;
    const r = new FileReader();
    r.onload = () => {
        try {
            const ta = getConfigTextarea(scope);
            ta.value = r.result;
            yamlLib().load(r.result);
            document.getElementById(`${scope}-tab-form`).classList.add("active");
            document.getElementById(`${scope}-tab-yaml`).classList.remove("active");
            document.getElementById(`${scope}-panel-form`).style.display = "block";
            document.getElementById(`${scope}-panel-yaml`).style.display = "none";
            refreshFormFromYaml(scope);
            setConfigFormSubtab(scope, "http");
            if (typeof setApiStatus === "function") {
                setApiStatus(`已导入: ${f.name}`, "ok");
            }
        } catch (e) {
            alert("导入失败: " + (e.message || String(e)));
        }
        input.value = "";
    };
    r.readAsText(f, "UTF-8");
}

function getMergedYamlForSubmit(scope) {
    yamlLib();
    const formPanel = document.getElementById(`${scope}-panel-form`);
    const onForm = formPanel && formPanel.style.display !== "none";
    if (onForm) {
        flushFormToYaml(scope);
    }
    const text = getConfigTextarea(scope).value.trim();
    if (!text) throw new Error("配置为空");
    yamlLib().load(text);
    return text;
}

function resetCreateConfigEditor() {
    const ta = getConfigTextarea("create");
    if (ta) ta.value = MINIMAL_TEMPLATE_YAML;
    document.getElementById("create-tab-form").classList.add("active");
    document.getElementById("create-tab-yaml").classList.remove("active");
    document.getElementById("create-panel-form").style.display = "block";
    document.getElementById("create-panel-yaml").style.display = "none";
    dismissCurlConfirm("create");
    try {
        refreshFormFromYaml("create");
        setConfigFormSubtab("create", "basic");
        applyConfigFormMode("create", getStoredConfigFormMode());
    } catch (_) {}
}

function renderApiProbeResult(scope, data) {
    const box = document.getElementById(`${scope}-api-probe-result`);
    if (!box) return;
    box.style.display = "block";
    const ok = !!(data && data.success);
    box.className = "cfg-api-probe-result " + (ok ? "ok" : "fail");

    const lines = [];
    if (data.message) lines.push(String(data.message));
    if (data.error) lines.push("错误: " + data.error);
    if (data.http_status != null) {
        lines.push(`HTTP ${data.http_status}` + (data.latency_ms != null ? ` · ${Math.round(data.latency_ms)}ms` : ""));
    }
    if (data.method && data.endpoint) {
        lines.push(`请求: ${data.method} ${data.endpoint}`);
    }
    if (data.variables_used && Object.keys(data.variables_used).length) {
        lines.push("入参 variables: " + JSON.stringify(data.variables_used));
    }
    if (Array.isArray(data.warnings) && data.warnings.length) {
        data.warnings.forEach((w) => lines.push("⚠ " + w));
    }
    if (data.poll && data.poll.title_preview) {
        lines.push("Listing title: " + data.poll.title_preview);
    }
    if (data.parsed_preview && data.parsed_preview.trim()) {
        lines.push("解析摘录:\n" + data.parsed_preview.slice(0, 600));
    } else if (data.response_preview && data.response_preview.trim()) {
        lines.push("响应摘录:\n" + data.response_preview.slice(0, 600));
    }

    box.textContent = lines.filter(Boolean).join("\n\n");
    if (typeof setApiStatus === "function") {
        setApiStatus(ok ? "接口探测成功" : "接口探测失败", ok ? "ok" : "err");
    }
}

async function probeConfigApi(scope) {
    yamlLib();
    try {
        flushFormToYaml(scope);
    } catch (e) {
        alert(e.message || String(e));
        return;
    }
    const yamlText = getConfigTextarea(scope).value.trim();
    if (!yamlText) {
        alert("请先填写配置");
        return;
    }

    const btn = document.querySelector(`#${scope}-section-http .cfg-api-probe-btn`);
    const box = document.getElementById(`${scope}-api-probe-result`);
    if (btn) {
        btn.disabled = true;
        btn.textContent = "探测中…";
    }
    if (box) {
        box.style.display = "block";
        box.className = "cfg-api-probe-result pending";
        box.textContent = "正在用首条测试数据请求被测接口…";
    }

    try {
        const r = await fetch("/api/config/probe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ config_yaml: yamlText }),
        });
        let data = {};
        try {
            data = await r.json();
        } catch (_) {
            data = {};
        }
        if (!r.ok) {
            const detail = data.detail;
            const msg = typeof detail === "string" ? detail : JSON.stringify(detail || r.statusText);
            renderApiProbeResult(scope, { success: false, error: msg, message: "探测未通过" });
            return;
        }
        renderApiProbeResult(scope, data);
    } catch (e) {
        renderApiProbeResult(scope, { success: false, error: e.message || String(e), message: "请求失败" });
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = "测试接口连通性";
        }
    }
}

window.probeConfigApi = probeConfigApi;
window.parseBrowserCurl = parseBrowserCurl;
window.filterCurlHeaders = filterCurlHeaders;
window.applyCurlPrimitivesAsTemplateAndVariables = applyCurlPrimitivesAsTemplateAndVariables;
window.ensureConfigSkeleton = ensureConfigSkeleton;
window.buildBatchLlmPromptTail = buildBatchLlmPromptTail;
window.yamlLib = yamlLib;
