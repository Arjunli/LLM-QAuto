"""HTML报告生成器 - 美观、现代、可交互的网页报告。

单文件、零依赖、零构建（内联 CSS + 原生 JS）。
暗色模式跟随系统并可手动切换；静态 CSS/JS 以普通字符串常量维护，
动态数据通过 f-string 注入模板，避免转义花括号。
"""
import html
import json
from typing import Any, Dict, List
from ..models import TestReport, TestStatus, ReportCaseRollup
from . import BaseReporter
from .labels import dimension_display_label, dimension_names_from_report, format_dimension_labels

# 静态 CSS（普通字符串，无需转义花括号）
_CSS = """
:root{--bg:#f4f5f7;--surface:#fff;--surface-2:#f7f8fa;--surface-3:#eef0f3;--border:#e2e5ea;--border-strong:#cdd2da;--text:#11181c;--text-2:#475059;--muted:#7a838d;--accent:#0d5c56;--accent-2:#0f766e;--accent-soft:rgba(13,92,86,.10);--pass:#0f9d58;--pass-soft:rgba(15,157,88,.12);--fail:#e23b3b;--fail-soft:rgba(226,59,59,.12);--warn:#e08600;--warn-soft:rgba(224,134,0,.12);--shadow:0 1px 2px rgba(17,24,28,.06),0 4px 12px rgba(17,24,28,.05);--shadow-lg:0 8px 30px rgba(17,24,28,.10);--radius:14px;--radius-sm:10px}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f1419;--surface:#171c22;--surface-2:#1d232b;--surface-3:#232a33;--border:#2a323c;--border-strong:#36404c;--text:#e7ecef;--text-2:#aab2bd;--muted:#7c8590;--accent:#2dd4bf;--accent-2:#14b8a6;--accent-soft:rgba(45,212,191,.14);--pass:#34d399;--pass-soft:rgba(52,211,153,.16);--fail:#f87171;--fail-soft:rgba(248,113,113,.16);--warn:#fbbf24;--warn-soft:rgba(251,191,36,.16);--shadow:0 1px 2px rgba(0,0,0,.4),0 4px 12px rgba(0,0,0,.35);--shadow-lg:0 10px 30px rgba(0,0,0,.5)}}
:root[data-theme="dark"]{--bg:#0f1419;--surface:#171c22;--surface-2:#1d232b;--surface-3:#232a33;--border:#2a323c;--border-strong:#36404c;--text:#e7ecef;--text-2:#aab2bd;--muted:#7c8590;--accent:#2dd4bf;--accent-2:#14b8a6;--accent-soft:rgba(45,212,191,.14);--pass:#34d399;--pass-soft:rgba(52,211,153,.16);--fail:#f87171;--fail-soft:rgba(248,113,113,.16);--warn:#fbbf24;--warn-soft:rgba(251,191,36,.16);--shadow:0 1px 2px rgba(0,0,0,.4),0 4px 12px rgba(0,0,0,.35);--shadow-lg:0 10px 30px rgba(0,0,0,.5)}
*{margin:0;padding:0;box-sizing:border-box}html{scroll-behavior:smooth}
body{font-family:"Source Sans 3",-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;line-height:1.6;color:var(--text);background:var(--bg);font-size:15px;-webkit-font-smoothing:antialiased}
code,pre,.mono{font-family:ui-monospace,"SF Mono",Consolas,"Cascadia Code",monospace}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1120px;margin:0 auto;padding:28px 20px 64px}
.hero{position:relative;overflow:hidden;border-radius:var(--radius);padding:30px 32px 28px;margin-bottom:22px;color:#fff;background:linear-gradient(135deg,#0d5c56 0%,#0f766e 45%,#14b8a6 100%);box-shadow:var(--shadow-lg)}
.hero::after{content:"";position:absolute;right:-60px;top:-60px;width:240px;height:240px;border-radius:50%;background:rgba(255,255,255,.10);pointer-events:none}
.hero::before{content:"";position:absolute;right:60px;bottom:-90px;width:180px;height:180px;border-radius:50%;background:rgba(255,255,255,.06);pointer-events:none}
.hero-row{display:flex;flex-wrap:wrap;align-items:flex-start;justify-content:space-between;gap:18px;position:relative;z-index:1}
.hero-eyebrow{font-size:12px;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:rgba(255,255,255,.78);margin-bottom:8px}
.hero-title{font-size:1.85rem;font-weight:800;letter-spacing:-.02em;margin-bottom:8px}
.hero-sub{font-size:14px;color:rgba(255,255,255,.82)}
.hero-sub .code{font-family:ui-monospace,Consolas,monospace;font-size:12px;background:rgba(255,255,255,.16);padding:2px 8px;border-radius:6px}
.hero-meta{display:flex;flex-wrap:wrap;gap:10px 22px;margin-top:16px;font-size:13px;color:rgba(255,255,255,.85);position:relative;z-index:1}
.hero-meta b{font-weight:600;color:#fff}
.status-badge{display:inline-flex;align-items:center;gap:8px;padding:9px 16px;border-radius:999px;font-size:13px;font-weight:700;background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.30)}
.status-badge .dot{width:9px;height:9px;border-radius:50%;background:#fff;box-shadow:0 0 0 3px rgba(255,255,255,.25)}
.theme-btn{position:absolute;right:18px;top:18px;z-index:3;width:38px;height:38px;border-radius:50%;border:1px solid rgba(255,255,255,.30);background:rgba(255,255,255,.16);color:#fff;cursor:pointer;display:flex;align-items:center;justify-content:center;transition:background .2s}
.theme-btn:hover{background:rgba(255,255,255,.28)}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:22px}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-sm);padding:16px 18px;box-shadow:var(--shadow)}
.kpi h3{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:8px}
.kpi .val{font-size:1.9rem;font-weight:800;letter-spacing:-.02em;line-height:1.1}
.kpi .det{font-size:12px;color:var(--muted);margin-top:6px}
.kpi .pass-c{color:var(--pass)}.kpi .fail-c{color:var(--fail)}
.bar{height:7px;background:var(--surface-3);border-radius:999px;overflow:hidden;margin-top:10px}
.bar>i{display:block;height:100%;border-radius:999px;background:linear-gradient(90deg,var(--accent),var(--accent-2));transition:width .5s ease}
@media(max-width:900px){.kpis{grid-template-columns:repeat(2,1fr)}}@media(max-width:520px){.kpis{grid-template-columns:1fr}}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:22px 24px 24px;margin-bottom:16px;box-shadow:var(--shadow)}
.panel-title{display:flex;align-items:center;gap:10px;font-size:1.1rem;font-weight:700;margin-bottom:16px;padding-bottom:12px;border-bottom:1px solid var(--border);letter-spacing:-.01em}
.panel-title .count{font-size:13px;font-weight:600;color:var(--muted);background:var(--surface-3);padding:2px 10px;border-radius:999px}
.panel-intro{color:var(--text-2);font-size:14px;margin-bottom:14px}
table.tbl{width:100%;border-collapse:collapse;font-size:14px}
.tbl th,.tbl td{text-align:left;padding:11px 13px;border-bottom:1px solid var(--border);vertical-align:top}
.tbl th{font-weight:600;color:var(--text-2);background:var(--surface-2);font-size:12px}
.tbl tbody tr:hover{background:var(--accent-soft)}
.tag{display:inline-block;padding:3px 10px;background:var(--surface-3);border:1px solid var(--border);border-radius:6px;font-size:12px}
.pass{color:var(--pass);font-weight:600}.fail{color:var(--fail);font-weight:600}.warn{color:var(--warn);font-weight:600}
.pill{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:600}
.pill-pass{background:var(--pass-soft);color:var(--pass)}.pill-fail{background:var(--fail-soft);color:var(--fail)}.pill-warn{background:var(--warn-soft);color:var(--warn)}
.overview{display:grid;grid-template-columns:220px 1fr;gap:28px;align-items:center}
@media(max-width:720px){.overview{grid-template-columns:1fr}}
.donut-wrap{display:flex;flex-direction:column;align-items:center;gap:8px}
.donut{position:relative;width:180px;height:180px}.donut svg{transform:rotate(-90deg)}
.donut .center{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center}
.donut .center .pct{font-size:2rem;font-weight:800;line-height:1}.donut .center .lbl{font-size:12px;color:var(--muted);margin-top:2px}
.dim-bars{display:flex;flex-direction:column;gap:16px}
.dim-bar h4{font-size:14px;font-weight:600;margin-bottom:6px;display:flex;justify-content:space-between;align-items:baseline}
.dim-bar h4 .sc{color:var(--muted);font-size:12px;font-weight:500}
.dim-bar .track{height:26px;background:var(--surface-3);border-radius:8px;overflow:hidden;position:relative}
.dim-bar .fill{height:100%;border-radius:8px;display:flex;align-items:center;justify-content:flex-end;padding-right:10px;color:#fff;font-size:12px;font-weight:700;transition:width .5s ease}
.fill-ok{background:linear-gradient(90deg,#0f9d58,#34d399)}.fill-mid{background:linear-gradient(90deg,#e08600,#fbbf24)}.fill-bad{background:linear-gradient(90deg,#e23b3b,#f87171)}
.case-toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:14px}
.search-input{flex:1;min-width:200px;padding:9px 14px;border:1px solid var(--border-strong);border-radius:8px;background:var(--surface);color:var(--text);font-size:14px;transition:border-color .2s,box-shadow .2s}
.search-input:focus{outline:none;border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft)}
.filter-chip{padding:7px 14px;border-radius:999px;border:1px solid var(--border-strong);background:var(--surface);color:var(--text-2);font-size:13px;cursor:pointer;transition:all .15s}
.filter-chip.active{background:var(--accent);color:#fff;border-color:var(--accent)}.filter-chip:hover:not(.active){border-color:var(--accent)}
.case-card{border:1px solid var(--border);border-radius:var(--radius-sm);margin-bottom:14px;overflow:hidden;background:var(--surface);transition:box-shadow .2s}
.case-card:hover{box-shadow:var(--shadow)}.case-card.hidden{display:none}
.case-head{display:flex;flex-wrap:wrap;align-items:center;gap:12px;padding:13px 16px;background:var(--surface-2);border-bottom:1px solid var(--border);cursor:pointer;user-select:none}
.case-head .cid{font-weight:700;font-family:ui-monospace,Consolas,monospace;font-size:13px}
.case-head .meta{color:var(--muted);font-size:13px}
.case-toggle{margin-left:auto;color:var(--muted);transition:transform .2s;font-size:12px}
.case-card.open .case-toggle{transform:rotate(180deg)}
.case-body{display:none;padding:16px}.case-card.open .case-body{display:block}
.case-err{background:var(--fail-soft);border:1px solid var(--fail);border-radius:8px;padding:10px 14px;margin-bottom:12px;color:var(--fail);font-size:13px}
.case-dim-line{font-size:13px;color:var(--text-2);margin-top:12px;padding-top:12px;border-top:1px dashed var(--border)}
.cmp-grid{display:grid;grid-template-columns:1fr 1fr;gap:0;border:1px solid var(--border);border-radius:8px;overflow:hidden;margin-top:12px}
@media(max-width:820px){.cmp-grid{grid-template-columns:1fr}}
.cmp-col{padding:14px 16px;border-bottom:1px solid var(--border);min-width:0}
.cmp-grid .cmp-col:first-child{border-right:1px solid var(--border)}
@media(max-width:820px){.cmp-grid .cmp-col:first-child{border-right:none}}
.cmp-col h4{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:10px}
.fv{font-family:ui-monospace,Consolas,monospace;font-size:12px;white-space:pre-wrap;word-break:break-word;max-height:140px;overflow-y:auto;background:var(--surface-2);border:1px solid var(--border);border-radius:6px;padding:8px 10px}
.empty{color:var(--muted);font-style:italic;font-size:13px}
.in-judge{color:var(--accent);font-weight:600;font-size:12px}.not-in-judge{color:var(--muted);font-size:12px}
.pre-block{background:var(--surface-2);border:1px solid var(--border);padding:10px 12px;border-radius:8px;overflow:auto;font-size:11.5px;line-height:1.6;font-family:ui-monospace,Consolas,monospace;max-height:340px;margin-top:8px;white-space:pre-wrap;word-break:break-word}
.fv-summary{cursor:pointer;font-size:12px;color:var(--accent);font-weight:600;list-style:none;padding:3px 0}.fv-summary::-webkit-details-marker{display:none}.fv-summary::before{content:"▸ "}.fv-details[open]>.fv-summary::before{content:"▾ "}
.fv-details>.fv{margin-top:6px}
.tbl code{font-size:12px;color:var(--accent-2);background:var(--accent-soft);padding:1px 6px;border-radius:5px}
details>summary{cursor:pointer;font-size:13px;font-weight:600;color:var(--accent);margin-top:8px;list-style:none}
details>summary::-webkit-details-marker{display:none}
details>summary::before{content:"▸ "}
details[open]>summary::before{content:"▾ "}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;margin-top:8px}
.gal-card{border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--surface-2);overflow:hidden;transition:transform .15s,box-shadow .15s}
.gal-card:hover{transform:translateY(-2px);box-shadow:var(--shadow-lg)}
.gal-card img{width:100%;height:170px;object-fit:contain;background:var(--surface);display:block}
.gal-meta{padding:9px 11px;font-size:12px;color:var(--muted)}
.gal-meta strong{color:var(--text)}
.rec{background:var(--accent-soft);border-left:3px solid var(--accent);padding:11px 15px;margin:8px 0;border-radius:0 8px 8px 0;font-size:14px}
.fail-ex{background:var(--fail-soft);border:1px solid var(--fail);border-radius:8px;padding:14px 16px;margin:12px 0}
.fail-ex pre{background:var(--surface-2);border:1px solid var(--border);padding:10px 12px;border-radius:8px;overflow-x:auto;font-size:12px;margin-top:8px;font-family:ui-monospace,Consolas,monospace}
footer.foot{text-align:center;padding:28px 12px 8px;color:var(--muted);font-size:12px}
.no-result{padding:24px;text-align:center;color:var(--muted);font-size:14px}
@media print{.hero{box-shadow:none}.theme-btn,.case-toolbar{display:none}.panel{box-shadow:none;break-inside:avoid}.case-card{break-inside:avoid}.case-body{display:block!important}}
"""

# 静态 JS（普通字符串，无需转义花括号）
_JS = """
function toggleCase(head){head.parentElement.classList.toggle('open')}
function filterCases(filter){
  var q=document.getElementById('case-search').value.toLowerCase();
  var cards=document.querySelectorAll('.case-card');
  var shown=0;
  cards.forEach(function(c){
    var st=c.getAttribute('data-status');
    var matchFilter=(filter==='all')||(st===filter);
    var matchQ=!q||c.getAttribute('data-cid').toLowerCase().indexOf(q)>=0
      ||c.textContent.toLowerCase().indexOf(q)>=0;
    if(matchFilter&&matchQ){c.classList.remove('hidden');shown++}
    else{c.classList.add('hidden')}
  });
  var nr=document.getElementById('no-result');
  if(nr){nr.style.display=shown?'none':'block'}
}
document.addEventListener('DOMContentLoaded',function(){
  var chips=document.querySelectorAll('.filter-chip');
  chips.forEach(function(chip){
    chip.addEventListener('click',function(){
      chips.forEach(function(c){c.classList.remove('active')});
      chip.classList.add('active');
      filterCases(chip.getAttribute('data-filter'));
    });
  });
  var si=document.getElementById('case-search');
  if(si){si.addEventListener('input',function(){
    var active=document.querySelector('.filter-chip.active');
    filterCases(active?active.getAttribute('data-filter'):'all');
  })}
  var tb=document.getElementById('theme-toggle');
  if(tb){tb.addEventListener('click',function(){
    var cur=document.documentElement.getAttribute('data-theme');
    var next=cur==='dark'?'light':'dark';
    document.documentElement.setAttribute('data-theme',next);
    try{localStorage.setItem('qauto-report-theme',next)}catch(e){}
  })}
  try{
    var saved=localStorage.getItem('qauto-report-theme');
    if(saved){document.documentElement.setAttribute('data-theme',saved)}
  }catch(e){}
});
"""

class HTMLReporter(BaseReporter):
    @property
    def name(self) -> str:
        return "html"

    def generate(self, report: TestReport, output_path: str, config: Dict[str, Any]):
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(self._render(report))

    # ---- 主题色映射 ----
    _STATUS_COLOR = {
        TestStatus.PASSED: "#0f9d58",
        TestStatus.FAILED: "#e23b3b",
        TestStatus.PARTIAL: "#e08600",
        TestStatus.ERROR: "#b91c1c",
    }
    _STATUS_ICON = {
        TestStatus.PASSED: "✓",
        TestStatus.FAILED: "✗",
        TestStatus.PARTIAL: "⚠",
        TestStatus.ERROR: "⚡",
    }

    @staticmethod
    def _esc(text: Any) -> str:
        return html.escape("" if text is None else str(text), quote=True)

    def _format_duration(self, start, end) -> str:
        if not end:
            return "-"
        d = (end - start).total_seconds()
        if d < 60:
            return f"{d:.0f}秒"
        if d < 3600:
            return f"{d/60:.1f}分钟"
        return f"{d/3600:.1f}小时"

    def _media_src(self, report: TestReport, rel: str) -> str:
        if not rel:
            return ""
        if report.artifacts_path:
            return f"artifacts/{rel.replace(chr(92), '/')}"
        return rel.replace(chr(92), "/")

    def _judge_dict(self, excerpt: str) -> Dict[str, Any]:
        if not (excerpt or "").strip():
            return {}
        try:
            d = json.loads(excerpt)
            return d if isinstance(d, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _fmt_field(self, val: Any, preview_len: int = 120) -> str:
        """渲染字段值：短值直接展示，长值折叠进 <details>（JSON 带缩进，便于阅读）。"""
        if val is None:
            return '<span class="empty">（空）</span>'
        if isinstance(val, (dict, list)):
            full = json.dumps(val, ensure_ascii=False, indent=2)
        else:
            full = str(val).strip()
        if not full:
            return '<span class="empty">（空）</span>'
        if len(full) <= preview_len:
            return f'<div class="fv">{self._esc(full)}</div>'
        preview = " ".join(full.split())[: preview_len - 1] + "…"
        return (
            f'<details class="fv-details"><summary class="fv-summary">{self._esc(preview)}</summary>'
            f'<div class="fv">{self._esc(full)}</div></details>'
        )

    def _pretty_json(self, raw: str, fallback_preview_len: int = 240) -> str:
        """尝试把 JSON 字符串美化缩进；非 JSON 则原样返回。用于 <pre> 块提升可读性。"""
        s = (raw or "").strip()
        if not s:
            return ""
        try:
            d = json.loads(s)
            return json.dumps(d, ensure_ascii=False, indent=2)
        except (json.JSONDecodeError, ValueError):
            return s

    def _render(self, report: TestReport) -> str:
        sc = self._STATUS_COLOR.get(report.status, "#5a5a52")
        si = self._STATUS_ICON.get(report.status, "?")
        dur = self._format_duration(report.start_time, report.end_time)
        start_str = report.start_time.strftime("%Y-%m-%d %H:%M") if report.start_time else "-"
        end_str = report.end_time.strftime("%Y-%m-%d %H:%M:%S") if report.end_time else ""
        return _HTML_TEMPLATE.format(
            css=_CSS, js=_JS,
            title=self._esc(report.project_name),
            project=self._esc(report.project_name),
            run_id=self._esc(report.run_id),
            status_icon=si, status_color=sc,
            status_label=report.status.value.upper(),
            total=report.total_cases, pass_rate=report.pass_rate,
            passed=report.passed_cases, failed=report.failed_cases,
            duration=dur, start_str=start_str, end_str=end_str,
            criteria=self._render_criteria(report),
            dimensions=self._render_dimensions(report),
            cases_html=self._render_cases(report),
            gallery=self._render_gallery(report),
            failed_examples=self._render_failed_examples(report),
            recommendations=self._render_recommendations(report),
        )

    def _render_criteria(self, report: TestReport) -> str:
        rows = []
        for c in report.criteria_results:
            cls = "pass" if c.passed else "fail"
            txt = "通过" if c.passed else "失败"
            act = f"{c.actual_value:.2f}" if isinstance(c.actual_value, float) else str(c.actual_value)
            exp = f"{c.expected_value:.2f}" if isinstance(c.expected_value, float) else str(c.expected_value)
            rows.append(
                f"<tr><td>{self._esc(c.description)}</td>"
                f'<td><span class="pill pill-{cls}">{txt}</span></td>'
                f"<td>{self._esc(act)}</td><td>{self._esc(exp)}</td>"
                f"<td>{self._esc(c.details)}</td></tr>"
            )
        body = "".join(rows) or "<tr><td colspan='5'>暂无数据</td></tr>"
        return (
            '<div class="panel"><h2 class="panel-title">通过标准检查</h2>'
            '<table class="tbl"><thead><tr><th>检查项</th><th>状态</th>'
            "<th>实际值</th><th>期望值</th><th>详情</th></tr></thead>"
            f"<tbody>{body}</tbody></table></div>"
        )

    def _render_dimensions(self, report: TestReport) -> str:
        if not report.dimension_stats:
            return ""
        names = dimension_names_from_report(report)
        pr = report.pass_rate
        circ = 2 * 3.14159 * 70
        offset = circ * (1 - pr / 100)
        sc = self._STATUS_COLOR.get(report.status, "#0d5c56")
        donut = (
            '<div class="overview"><div class="donut-wrap"><div class="donut">'
            f'<svg width="180" height="180"><circle cx="90" cy="90" r="70" '
            f'fill="none" stroke="var(--surface-3)" stroke-width="14"/>'
            f'<circle cx="90" cy="90" r="70" fill="none" stroke="{sc}" '
            f'stroke-width="14" stroke-linecap="round" stroke-dasharray="{circ:.1f}" '
            f'stroke-dashoffset="{offset:.1f}"/></svg>'
            f'<div class="center"><div class="pct">{pr:.0f}%</div>'
            '<div class="lbl">通过率</div></div></div></div>'
        )
        bars = []
        for s in report.dimension_stats:
            label = s.dimension_name or dimension_display_label(report, s.dimension_id, names=names)
            rate = s.pass_rate
            fill_cls = "fill-ok" if rate >= 80 else ("fill-mid" if rate >= 50 else "fill-bad")
            bars.append(
                f'<div class="dim-bar"><h4><span>{self._esc(label)}</span>'
                f'<span class="sc">均分 {s.avg_score:.2f} · {s.total_cases} 样本 · σ {s.std_score:.2f}</span></h4>'
                f'<div class="track"><div class="fill {fill_cls}" style="width:{min(100, rate):.1f}%">{rate:.1f}%</div></div>'
                f'{self._render_category_table(s.category_distribution)}</div>'
            )
        return (
            '<div class="panel"><h2 class="panel-title">维度统计</h2>'
            + donut + '<div class="dim-bars">' + "".join(bars) + "</div></div>"
        )

    def _render_category_table(self, cats) -> str:
        if not cats:
            return ""
        rows = []
        for c in cats:
            lo, hi = c.confidence_interval
            rows.append(
                f"<tr><td><span class='tag'>{self._esc(c.category)}</span></td>"
                f"<td>{c.count}</td><td>{c.percentage:.1f}%</td>"
                f"<td>[{lo*100:.1f}%, {hi*100:.1f}%]</td></tr>"
            )
        return (
            '<table class="tbl" style="margin-top:10px"><thead><tr>'
            "<th>类别</th><th>数量</th><th>占比</th><th>95%CI</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )

    def _field_compare_table(self, case: ReportCaseRollup, parser_keys: List[str]) -> str:
        jd = self._judge_dict(getattr(case, "judge_excerpt", "") or "")
        parsed = dict(getattr(case, "parsed_fields", None) or {})
        keys = list(parser_keys) or list(parsed.keys())
        has_parsed = bool(parsed)
        if not keys and jd:
            keys = list(jd.keys())
        if not keys:
            return '<p class="empty">未配置 output_parser.keys，无法按字段对照。</p>'
        # 字段过多时折叠：默认展示前 12 个，其余收进 <details>
        MAX_INLINE = 12
        show_keys, rest_keys = keys[:MAX_INLINE], keys[MAX_INLINE:]

        def row(k: str) -> str:
            inj = k in jd
            mark = '<span class="in-judge">是</span>' if inj else '<span class="not-in-judge">否</span>'
            if has_parsed:
                return (
                    f"<tr><td><code>{self._esc(k)}</code></td>"
                    f"<td>{self._fmt_field(parsed.get(k))}</td>"
                    f"<td>{self._fmt_field(jd.get(k) if inj else None)}</td>"
                    f"<td>{mark}</td></tr>"
                )
            # 未配置解析器（parsed_fields 为空）时省略"接口解析值"空列
            return (
                f"<tr><td><code>{self._esc(k)}</code></td>"
                f"<td>{self._fmt_field(jd.get(k) if inj else None)}</td>"
                f"<td>{mark}</td></tr>"
            )

        head = (
            '<table class="tbl"><thead><tr><th>字段</th>'
            + ("<th>接口解析值</th>" if has_parsed else "")
            + "<th>评委摘录值</th><th>进入评委</th></tr></thead><tbody>"
        )
        body = "".join(row(k) for k in show_keys)
        tail = "</tbody></table>"
        if rest_keys:
            extra = "".join(row(k) for k in rest_keys)
            return (
                head + body + tail
                + f'<details class="fv-details"><summary class="fv-summary">展开其余 {len(rest_keys)} 个字段</summary>'
                f'<table class="tbl"><tbody>{extra}</tbody></table></details>'
            )
        return head + body + tail

    def _render_cases(self, report: TestReport) -> str:
        cases = list(report.cases or [])
        if not cases:
            return ""
        op = (report.suite_meta or {}).get("output_parser") or {}
        pkeys: List[str] = list(op.get("keys") or [])
        path_hint = op.get("path") or ""
        names = dimension_names_from_report(report)
        cards = []
        for c in cases[:60]:
            status_cls = "pass" if c.passed else "fail"
            status_txt = "通过" if c.passed else "未通过"
            err = ""
            if getattr(c, "output_error", None):
                err = f'<div class="case-err">接口错误：{self._esc(c.output_error)}</div>'
            tbl = self._field_compare_table(c, pkeys)
            raw_prev = self._pretty_json(getattr(c, "invoke_raw_preview", "") or "")
            judge_prev = self._pretty_json(getattr(c, "judge_excerpt", "") or "")
            out_prev = c.output_preview or ""
            raw_blk = (
                f'<details class="fv-details"><summary class="fv-summary">展开原始 HTTP 响应（摘要）</summary>'
                f'<pre class="pre-block">{self._esc(raw_prev)}</pre></details>'
                if raw_prev else '<p class="empty">无原始响应记录</p>'
            )
            judge_blk = (
                f'<pre class="pre-block">{self._esc(judge_prev)}</pre>'
                if judge_prev else '<p class="empty">未调用评委或摘录为空</p>'
            )
            parsed_blk = (
                f'<details class="fv-details"><summary class="fv-summary">展开完整解析正文</summary>'
                f'<pre class="pre-block">{self._esc(self._pretty_json(out_prev))}</pre></details>'
                if out_prev else ""
            )
            dim_bits = []
            for did, dim in (c.dimensions or {}).items():
                if not dim:
                    continue
                sc = dim.get("score")
                ps = "通过" if dim.get("passed") else "未通过"
                dim_bits.append(f"{dimension_display_label(report, did, names=names)}: {sc} ({ps})")
            dim_line = (
                '<p class="case-dim-line">评判：'
                + self._esc(" · ".join(dim_bits) or "—") + "</p>"
            )
            cards.append(
                f'<div class="case-card" data-status="{status_cls}" data-cid="{self._esc(c.case_id)}">'
                '<div class="case-head" onclick="toggleCase(this)">'
                f'<span class="cid">{self._esc(c.case_id)}</span>'
                f'<span class="pill pill-{status_cls}">{status_txt}</span>'
                f'<span class="meta">综合分 {c.aggregated_score:.2f}</span>'
                f'<span class="meta">调用 {c.invoke_latency_ms:.0f} ms</span>'
                '<span class="case-toggle">▼</span></div>'
                f'<div class="case-body">{err}{tbl}'
                '<div class="cmp-grid"><div class="cmp-col"><h4>被测接口</h4>'
                f"{raw_blk}{parsed_blk}</div>"
                '<div class="cmp-col"><h4>提交评委的摘录</h4>'
                f"{judge_blk}</div></div>{dim_line}</div></div>"
            )
        path_note = (
            f'解析路径 <code>{self._esc(path_hint)}</code> · 字段 {len(pkeys)} 个'
            if (pkeys or path_hint) else ""
        )
        return (
            '<div class="panel"><h2 class="panel-title">接口返回与评测对照'
            f'<span class="count">{len(cases)}</span></h2>'
            '<div class="panel-intro">对比「配置解析字段」与「评委实际看到的摘录」；'
            f'点击卡片展开原始响应与完整解析正文。{path_note}</div>'
            '<div class="case-toolbar">'
            '<input id="case-search" class="search-input" placeholder="搜索用例 ID 或内容…">'
            '<button class="filter-chip active" data-filter="all">全部</button>'
            '<button class="filter-chip" data-filter="pass">通过</button>'
            '<button class="filter-chip" data-filter="fail">失败</button>'
            '</div>'
            + "".join(cards)
            + '<div id="no-result" class="no-result" style="display:none">无匹配用例</div>'
            + "</div>"
        )

    def _render_gallery(self, report: TestReport) -> str:
        image_cases = [c for c in (report.cases or []) if getattr(c, "media_preview_paths", None)]
        if not image_cases:
            return ""
        cards = []
        for c in image_cases[:24]:
            first = c.media_preview_paths[0] if c.media_preview_paths else ""
            src = self._media_src(report, first)
            if not src:
                continue
            status_cls = "pass" if c.passed else "fail"
            cards.append(
                f'<div class="gal-card"><img src="{src}" alt="{self._esc(c.case_id)}" loading="lazy">'
                '<div class="gal-meta"><strong>' + self._esc(c.case_id) + "</strong><br>"
                f"模式: {getattr(c, 'content_mode', 'text')} · "
                f'<span class="{status_cls}">{"通过" if c.passed else "失败"}</span><br>'
                f"分: {c.aggregated_score:.1f} · 图: {getattr(c, 'media_count', 0)} 张</div></div>"
            )
        if not cards:
            return ""
        return (
            '<div class="panel"><h2 class="panel-title">生成图预览</h2>'
            f'<div class="panel-intro">共 {len(image_cases)} 条用例含图像产物（报告需与 artifacts 目录一并保存）。</div>'
            f'<div class="gallery">{"".join(cards)}</div></div>'
        )

    def _render_failed_examples(self, report: TestReport) -> str:
        if not report.failed_examples:
            return ""
        parts = []
        names = dimension_names_from_report(report)
        for case in report.failed_examples[:10]:
            failed_dims = format_dimension_labels(report, case.failed_dimensions, names=names)
            media_rel = []
            if report.artifacts_path and case.output.media:
                from pathlib import Path
                art = Path(report.artifacts_path)
                for m in case.output.media:
                    if m.local_path:
                        try:
                            media_rel.append(str(Path(m.local_path).relative_to(art)))
                        except ValueError:
                            pass
            imgs = ""
            if media_rel:
                imgs = "".join(
                    f'<img src="{self._media_src(report, p)}" alt="{self._esc(case.id)}" '
                    f'loading="lazy" style="max-width:200px;max-height:160px;margin:6px 8px 0 0;'
                    f'border:1px solid var(--border);border-radius:8px">'
                    for p in media_rel[:4]
                )
                imgs = f'<div style="margin-top:8px">{imgs}</div>'
            prompt_prev = case.input.prompt[:200] + ("..." if len(case.input.prompt) > 200 else "")
            out_prev = case.output.content[:500] + ("..." if len(case.output.content) > 500 else "")
            parts.append(
                f'<div class="fail-ex"><strong>ID:</strong> {self._esc(case.id)}<br>'
                f"<strong>模式:</strong> {getattr(case.output, 'content_mode', 'text')}<br>"
                f"<strong>输入:</strong> {self._esc(prompt_prev)}<br>"
                f"<strong>输出:</strong><pre>{self._esc(out_prev)}</pre>"
                f"{imgs}<strong>失败维度:</strong> {self._esc(failed_dims)}</div>"
            )
        return (
            '<div class="panel"><h2 class="panel-title">失败示例 '
            f'<span class="count">{len(report.failed_examples)}</span></h2>'
            + "".join(parts) + "</div>"
        )

    def _render_recommendations(self, report: TestReport) -> str:
        if not report.recommendations:
            return ""
        recs = "".join(f'<div class="rec">{self._esc(r)}</div>' for r in report.recommendations[:10])
        return (
            '<div class="panel"><h2 class="panel-title">改进建议</h2>'
            + recs + "</div>"
        )

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>测试报告 · {title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <header class="hero">
    <button id="theme-toggle" class="theme-btn" title="切换明暗主题" aria-label="切换主题"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg></button>
    <div class="hero-row">
      <div>
        <p class="hero-eyebrow">LLM-QAuto · 测试报告</p>
        <h1 class="hero-title">{project}</h1>
        <p class="hero-sub">运行 <span class="code">{run_id}</span></p>
        <div class="hero-meta"><span><b>开始</b> {start_str}</span><span><b>耗时</b> {duration}</span><span><b>生成</b> {end_str}</span></div>
      </div>
      <div class="status-badge" role="status"><span class="dot" style="background:{status_color};box-shadow:0 0 0 3px rgba(255,255,255,.25)"></span><span>{status_icon} {status_label}</span></div>
    </div>
  </header>
  <div class="kpis">
    <div class="kpi"><h3>总样本</h3><div class="val">{total}</div><div class="det">纳入评测的条目数</div></div>
    <div class="kpi"><h3>通过率</h3><div class="val">{pass_rate:.1f}%</div><div class="bar"><i style="width:min(100%,{pass_rate}%)"></i></div></div>
    <div class="kpi"><h3>通过 / 失败</h3><div class="val"><span class="pass-c">{passed}</span> <span style="color:var(--muted);font-weight:600">/</span> <span class="fail-c">{failed}</span></div><div class="det">样本级判定汇总</div></div>
    <div class="kpi"><h3>耗时</h3><div class="val" style="font-size:1.4rem">{duration}</div><div class="det">{start_str} 开始</div></div>
  </div>
  {criteria}
  {dimensions}
  {cases_html}
  {gallery}
  {failed_examples}
  {recommendations}
  <footer class="foot"><p>由 LLM-QAuto 生成 · {end_str}</p></footer>
</div>
<script>{js}</script>
</body>
</html>"""
