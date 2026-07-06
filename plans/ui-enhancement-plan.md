# UI 视觉与交互完善实施计划

> 目标：在不引入构建工具的前提下，为现有 vanilla JS + 单页 index.html 前端增加暗色模式、Toast 通知、加载骨架屏、键盘快捷键四项能力。

## 现状基线

| 维度 | 现状 |
|------|------|
| HTML | [`index.html`](src/llm_qauto/web/static/index.html:1) 单文件 4846 行，~4200 行内联 CSS |
| CSS 变量 | 已在 [`:root`](src/llm_qauto/web/static/index.html:11) 定义全套设计 token（`--bg/--surface/--text/--accent` 等），暗色模式只需覆盖变量 |
| JS | 13 个全局脚本，核心 [`app.js`](src/llm_qauto/web/static/app.js:1) 1749 行；请求统一走 [`apiFetch`](src/llm_qauto/web/static/app.js:83) |
| 状态提示 | 仅底部 [`api-status-bar`](src/llm_qauto/web/static/index.html:4825)，无浮层 toast |
| 模态框 | `showModal`/`hideModal` 全局函数，4 个 modal-overlay |
| 图表 | 已引入 `/static/vendor/chart.umd.min.js` |

## 实施原则

1. **零构建工具** — 全部手写 CSS/JS，沿用现有全局脚本风格
2. **不破坏现有功能** — 增量注入，`apiFetch`/`setApiStatus` 保持签名兼容
3. **新代码集中** — 新建 [`theme.js`](src/llm_qauto/web/static/theme.js:1) 与 [`ui-kit.js`](src/llm_qauto/web/static/ui-kit.js:1) 两个文件，减少对巨型 index.html 的改动
4. **CSS 走 `<style>` 追加** — 在 index.html 现有 `<style>` 块末尾追加新规则，避免改动行号错位

---

## 阶段 1：暗色模式

### 1.1 CSS 变量覆盖

在 index.html 现有 `:root` 块之后追加 `body.theme-dark { ... }`，覆盖全套语义 token：

```css
body.theme-dark {
    --bg: #0b1120;
    --bg-accent: radial-gradient(..., #0b1120);
    --surface: #0f172a;
    --surface-2: #1e293b;
    --border: #334155;
    --border-strong: #475569;
    --text: #f1f5f9;
    --text-muted: #94a3b8;
    --sidebar: linear-gradient(180deg, #020617 0%, #0b1120 100%);
    --shadow-sm: 0 1px 2px rgba(0,0,0,0.3);
    --shadow-md: 0 4px 16px rgba(0,0,0,0.4);
}
```

需覆盖的硬编码色值（散落在现有 CSS 中）：
- `.header` 背景 `rgba(255,255,255,0.82)` → `rgba(15,23,42,0.82)`
- `.modal` / `.stat-card` / `.meta-tile` 白底 → `var(--surface-2)`
- `.event-log` `#fafafa` → `#0b1120`
- `.code-editor` 系列（已是深色，暗色下保持）
- 各 `phase-chip` 的 rgba 背景在暗色下降低透明度

### 1.2 主题切换按钮

在 header-right 区域（[`header-context`](src/llm_qauto/web/static/index.html:4603) 旁）插入主题切换按钮：

```html
<button type="button" id="theme-toggle" class="header-icon-btn" aria-label="切换主题">
  <svg class="icon-sun">...</svg>
  <svg class="icon-moon">...</svg>
</button>
```

### 1.3 theme.js 逻辑

```js
// theme.js
(function () {
    const KEY = "qauto-theme";
    function apply(theme) {
        document.body.classList.toggle("theme-dark", theme === "dark");
        localStorage.setItem(KEY, theme);
        // 更新按钮图标可见性
    }
    function init() {
        const saved = localStorage.getItem(KEY);
        const prefersDark = matchMedia("(prefers-color-scheme: dark)").matches;
        apply(saved || (prefersDark ? "dark" : "light"));
        document.getElementById("theme-toggle")?.addEventListener("click", () => {
            apply(document.body.classList.contains("theme-dark") ? "light" : "dark");
        });
    }
    document.addEventListener("DOMContentLoaded", init);
})();
```

**交付物**：index.html CSS 变量块 + 切换按钮 + [`theme.js`](src/llm_qauto/web/static/theme.js:1)

---

## 阶段 2：Toast 通知系统

### 2.1 容器与样式

在 `<body>` 末尾（`api-status-bar` 前）插入：

```html
<div id="toast-container" class="toast-container" aria-live="assertive"></div>
```

CSS：右上角堆叠，4 种类型（success/error/info/warning），自动消失动画。

### 2.2 showToast API（ui-kit.js）

```js
function showToast(message, type = "info", opts = {}) {
    const container = document.getElementById("toast-container");
    const el = document.createElement("div");
    el.className = `toast toast--${type}`;
    el.innerHTML = `<span class="toast-icon">${ICONS[type]}</span><span class="toast-msg">${escapeHtml(message)}</span>`;
    container.appendChild(el);
    requestAnimationFrame(() => el.classList.add("toast--show"));
    const duration = opts.duration ?? (type === "error" ? 6000 : 3500);
    setTimeout(() => {
        el.classList.remove("toast--show");
        el.addEventListener("transitionend", () => el.remove(), { once: true });
    }, duration);
    return el;
}
```

### 2.3 集成点

| 触发场景 | 位置 | 类型 |
|---------|------|------|
| 请求成功 | [`apiFetch`](src/llm_qauto/web/static/app.js:113) `response.ok` 分支 | success（仅显式操作时，轮询不弹） |
| 请求失败 | [`apiFetch`](src/llm_qauto/web/static/app.js:124) 抛错前 | error |
| 运行启动 | [`startRun`](src/llm_qauto/web/static/app.js:949) 回调 | info |
| 运行完成 | WebSocket 推送 status=completed | success/error |
| 删除项目 | [`deleteProject`](src/llm_qauto/web/static/app.js:597) | success |

**注意**：避免轮询类请求（`loadStats`、WS 心跳）触发 toast，加 `options.silent` 标志位跳过。

**交付物**：toast 容器 + CSS + [`ui-kit.js`](src/llm_qauto/web/static/ui-kit.js:1) + apiFetch 改造

---

## 阶段 3：加载骨架屏

### 3.1 通用 shimmer 组件

```css
.skeleton {
    background: linear-gradient(90deg, var(--border) 25%, var(--surface) 50%, var(--border) 75%);
    background-size: 200% 100%;
    animation: shimmer 1.4s infinite;
    border-radius: var(--radius-sm);
}
@keyframes shimmer { 0%{background-position:200% 0} 100%{background-position:-200% 0} }
```

### 3.2 应用场景

| 区域 | 骨架结构 |
|------|---------|
| 测试项目列表 | 3-4 个 `.project-card` 骨架（图标块 + 两行文本条） |
| 测试运行列表 | 3-4 个运行行骨架 |
| 用例设计会话列表 | 会话卡片骨架 |
| 工作台会话列表 | 会话卡片骨架 |
| 运行详情面板 | meta-grid 骨架 + event-log 骨架 |

### 3.3 实现方式

在 [`ui-kit.js`](src/llm_qauto/web/static/ui-kit.js:1) 提供 `skeletonList(count, templateFn)`，各列表渲染函数在 `apiFetch` 前先注入骨架，数据返回后替换。

**交付物**：skeleton CSS + `skeletonList` 工具 + 3 处列表渲染改造

---

## 阶段 4：键盘快捷键

### 4.1 快捷键映射

| 快捷键 | 动作 |
|--------|------|
| `?` | 打开快捷键帮助面板 |
| `g` `h` | 回到工作台首页 |
| `g` `p` | 跳转测试项目 |
| `g` `r` | 跳转测试运行 |
| `n` | 新建（cURL 向导） |
| `/` | 聚焦当前页搜索框 |
| `Esc` | 关闭模态框 / 帮助面板 |
| `t` | 切换主题 |
| `k` | 打开命令面板（可选，进阶） |

### 4.2 全局监听（ui-kit.js）

```js
const KEYMAP = {
    "?": () => toggleHelpPanel(),
    "gh": () => showModuleHome(),
    "gp": () => showApiQcSection("projects"),
    "gr": () => showApiQcSection("runs"),
    "n": () => showCurlWizardModal(),
    "t": () => document.getElementById("theme-toggle").click(),
    "Escape": () => closeAllModals(),
};
```

- 输入框/textarea 聚焦时禁用单字符快捷键（`?` `/` `n` `t`）
- 双键序列（`g` `h`）用 300ms 超时窗口

### 4.3 帮助面板

模态框形式，列出全部快捷键，`?` 唤出。

**交付物**：快捷键监听 + 帮助面板 modal

---

## 文件改动清单

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| [`index.html`](src/llm_qauto/web/static/index.html:1) | 追加 CSS + 插入 toast 容器/主题按钮/帮助面板 + 引入新脚本 | 集中在 `<style>` 末尾与 `<body>` 末尾 |
| [`theme.js`](src/llm_qauto/web/static/theme.js:1) | 新建 | 暗色模式逻辑 |
| [`ui-kit.js`](src/llm_qauto/web/static/ui-kit.js:1) | 新建 | showToast + skeleton + 快捷键 |
| [`app.js`](src/llm_qauto/web/static/app.js:1) | 小改 | apiFetch 集成 toast + 列表渲染注入骨架 |

## 不改动

- 后端 [`api.py`](src/llm_qauto/web/api.py:1)（纯前端增强，无需新接口）
- 现有 JS 文件（platform-shell / config-editor / *-ui.js）保持不动
- pyproject.toml / 依赖

## 验证方式

1. 启动 `python web_server.py`，访问 http://localhost:8080
2. 暗色：点击主题按钮切换，刷新后保持；检查各模块页面无白底刺眼
3. Toast：创建/删除项目、启动运行，观察右上角浮层
4. 骨架屏：切换到项目/运行列表，观察加载瞬间 shimmer
5. 快捷键：按 `?` 看帮助；`g h` 回首页；`n` 开向导；`t` 切主题
