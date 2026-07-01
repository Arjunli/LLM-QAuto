"""
HTML报告生成器 - 美观的网页报告
"""

import html
import json
from datetime import datetime
from typing import Any, Dict, List, Optional
from ..models import TestReport, TestStatus, ReportCaseRollup
from . import BaseReporter
from .labels import dimension_display_label, dimension_names_from_report, format_dimension_labels


class HTMLReporter(BaseReporter):
    """生成美观的HTML报告"""
    
    @property
    def name(self) -> str:
        return "html"
    
    def generate(self, report: TestReport, output_path: str, config: Dict[str, Any]):
        """生成HTML报告"""
        
        html_content = self._render_template(report)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
    
    def _render_template(self, report: TestReport) -> str:
        """渲染HTML模板"""
        
        status_color = {
            TestStatus.PASSED: "#0d5c56",
            TestStatus.FAILED: "#a32020",
            TestStatus.PARTIAL: "#b45309",
            TestStatus.ERROR: "#b91c1c",
        }.get(report.status, "#5a5a52")
        
        status_icon = {
            TestStatus.PASSED: "✓",
            TestStatus.FAILED: "✗",
            TestStatus.PARTIAL: "⚠",
            TestStatus.ERROR: "⚡",
        }.get(report.status, "?")
        
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>测试报告 · {report.project_name}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Source+Sans+3:ital,wght@0,400;0,600;0,700;1,400&display=swap" rel="stylesheet">
    <style>
        :root {{
            --rep-bg: #e8e8e4;
            --rep-surface: #ffffff;
            --rep-surface-2: #f7f7f4;
            --rep-border: #c8c8c1;
            --rep-text: #1c1c18;
            --rep-muted: #5a5a52;
            --rep-accent: #0d5c56;
            --rep-pass: #0f766e;
            --rep-fail: #a32020;
            --rep-warn: #b45309;
        }}
        * {{
            margin: 0; padding: 0; box-sizing: border-box;
        }}
        body {{
            font-family: "Source Sans 3", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            line-height: 1.55;
            color: var(--rep-text);
            background: var(--rep-bg);
            font-size: 15px;
            -webkit-font-smoothing: antialiased;
        }}
        .rep-wrap {{
            max-width: 1040px;
            margin: 0 auto;
            padding: 28px 20px 48px;
        }}
        .rep-hero {{
            background: var(--rep-surface);
            border: 1px solid var(--rep-border);
            border-radius: 2px;
            padding: 22px 24px 20px;
            margin-bottom: 18px;
            position: relative;
            box-shadow: 0 1px 0 rgba(28, 28, 24, 0.04);
        }}
        .rep-hero::before {{
            content: "";
            position: absolute;
            left: 0; top: 0; bottom: 0;
            width: 4px;
            background: var(--rep-accent);
            border-radius: 2px 0 0 2px;
        }}
        .rep-eyebrow {{
            font-size: 11px;
            font-weight: 600;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--rep-muted);
            margin-bottom: 6px;
        }}
        .rep-title {{
            font-size: 1.55rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            margin-bottom: 6px;
            color: var(--rep-text);
        }}
        .rep-sub {{
            color: var(--rep-muted);
            font-size: 14px;
        }}
        .rep-code {{
            font-family: ui-monospace, Consolas, "Cascadia Code", monospace;
            font-size: 12px;
            background: var(--rep-surface-2);
            padding: 2px 6px;
            border: 1px solid var(--rep-border);
            border-radius: 2px;
        }}
        .rep-hero-row {{
            display: flex;
            flex-wrap: wrap;
            align-items: flex-start;
            justify-content: space-between;
            gap: 16px;
        }}
        .rep-status-pill {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            padding: 8px 14px;
            border-radius: 2px;
            font-size: 13px;
            font-weight: 700;
            letter-spacing: 0.02em;
            border: 1px solid var(--rep-border);
            background: var(--rep-surface-2);
            color: var(--rep-text);
        }}
        .rep-status-pill .rep-dot {{
            width: 8px; height: 8px;
            border-radius: 50%;
            background: {status_color};
        }}
        .rep-kpis {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            margin-bottom: 18px;
        }}
        @media (max-width: 900px) {{
            .rep-kpis {{ grid-template-columns: repeat(2, 1fr); }}
        }}
        @media (max-width: 520px) {{
            .rep-kpis {{ grid-template-columns: 1fr; }}
        }}
        .rep-kpi {{
            background: var(--rep-surface);
            border: 1px solid var(--rep-border);
            border-radius: 2px;
            padding: 14px 16px;
        }}
        .rep-kpi h3 {{
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: var(--rep-muted);
            margin-bottom: 6px;
        }}
        .rep-kpi .rep-value {{
            font-size: 1.65rem;
            font-weight: 700;
            letter-spacing: -0.02em;
            color: var(--rep-text);
            line-height: 1.2;
        }}
        .rep-kpi .rep-detail {{
            font-size: 12px;
            color: var(--rep-muted);
            margin-top: 6px;
        }}
        .rep-kpi .rep-pass {{ color: var(--rep-pass); }}
        .rep-progress {{
            height: 6px;
            background: rgba(200, 200, 193, 0.5);
            border-radius: 2px;
            overflow: hidden;
            margin-top: 10px;
        }}
        .rep-progress-fill {{
            height: 100%;
            background: var(--rep-accent);
            border-radius: 2px;
            transition: width 0.35s ease;
        }}
        .rep-panel {{
            background: var(--rep-surface);
            border: 1px solid var(--rep-border);
            border-radius: 2px;
            padding: 20px 22px 22px;
            margin-bottom: 14px;
        }}
        .rep-section-title {{
            font-size: 1.05rem;
            font-weight: 700;
            margin-bottom: 14px;
            padding-bottom: 10px;
            border-bottom: 1px solid var(--rep-border);
            color: var(--rep-text);
            letter-spacing: -0.01em;
        }}
        table.rep-table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
        }}
        .rep-table th, .rep-table td {{
            text-align: left;
            padding: 10px 12px;
            border-bottom: 1px solid #eef0eb;
            vertical-align: top;
        }}
        .rep-table th {{
            font-weight: 600;
            color: var(--rep-text);
            background: var(--rep-surface-2);
            font-size: 12px;
        }}
        .rep-table tbody tr:hover {{
            background: rgba(13, 92, 86, 0.035);
        }}
        .pass {{ color: var(--rep-pass); font-weight: 600; }}
        .fail {{ color: var(--rep-fail); font-weight: 600; }}
        .warn {{ color: var(--rep-warn); font-weight: 600; }}
        .rep-dim-block {{
            margin-bottom: 26px;
            padding-bottom: 22px;
            border-bottom: 1px dashed var(--rep-border);
        }}
        .rep-dim-block:last-child {{
            border-bottom: none;
            margin-bottom: 0;
            padding-bottom: 0;
        }}
        .rep-dim-block h3 {{
            font-size: 1rem;
            font-weight: 700;
            margin-bottom: 12px;
            color: var(--rep-text);
        }}
        .rep-dim-metrics {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            margin: 14px 0 16px;
        }}
        @media (max-width: 720px) {{
            .rep-dim-metrics {{ grid-template-columns: repeat(2, 1fr); }}
        }}
        .rep-dim-mini {{
            background: var(--rep-surface-2);
            border: 1px solid var(--rep-border);
            border-radius: 2px;
            padding: 10px 12px;
        }}
        .rep-dim-mini .lbl {{
            font-size: 11px;
            color: var(--rep-muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 4px;
        }}
        .rep-dim-mini .num {{
            font-size: 1.25rem;
            font-weight: 700;
        }}
        .rep-dim-mini .rate-ok {{ color: var(--rep-pass); }}
        .rep-dim-mini .rate-bad {{ color: var(--rep-fail); }}
        .rep-dim-block h4 {{
            font-size: 13px;
            font-weight: 600;
            margin: 18px 0 8px;
            color: var(--rep-muted);
        }}
        .fail-example {{
            background: #f8eded;
            border: 1px solid rgba(163, 32, 32, 0.25);
            border-radius: 2px;
            padding: 14px 16px;
            margin: 12px 0;
        }}
        .fail-example pre {{
            background: var(--rep-surface-2);
            border: 1px solid var(--rep-border);
            padding: 10px 12px;
            border-radius: 2px;
            overflow-x: auto;
            font-size: 12px;
            margin-top: 8px;
            font-family: ui-monospace, Consolas, monospace;
        }}
        .rep-case-card {{
            border: 1px solid var(--rep-border);
            border-radius: 2px;
            margin-bottom: 16px;
            overflow: hidden;
        }}
        .rep-case-card-head {{
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            gap: 10px;
            padding: 12px 14px;
            background: var(--rep-surface-2);
            border-bottom: 1px solid var(--rep-border);
            font-size: 14px;
        }}
        .rep-compare-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0;
        }}
        @media (max-width: 820px) {{
            .rep-compare-grid {{ grid-template-columns: 1fr; }}
        }}
        .rep-compare-col {{
            padding: 14px 16px;
            border-bottom: 1px solid var(--rep-border);
            min-width: 0;
        }}
        .rep-compare-grid .rep-compare-col:first-child {{
            border-right: 1px solid var(--rep-border);
        }}
        @media (max-width: 820px) {{
            .rep-compare-grid .rep-compare-col:first-child {{
                border-right: none;
                border-bottom: 1px solid var(--rep-border);
            }}
        }}
        .rep-compare-col h4 {{
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--rep-muted);
            margin-bottom: 10px;
        }}
        .rep-field-empty {{
            color: var(--rep-muted);
            font-style: italic;
        }}
        .rep-field-val {{
            font-family: ui-monospace, Consolas, monospace;
            font-size: 12px;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 120px;
            overflow-y: auto;
        }}
        .rep-compare-full {{
            padding: 12px 16px 16px;
            border-top: 1px dashed var(--rep-border);
        }}
        .rep-compare-full details {{
            margin-top: 8px;
        }}
        .rep-compare-full summary {{
            cursor: pointer;
            font-size: 13px;
            font-weight: 600;
            color: var(--rep-accent);
        }}
        .rep-pre-block {{
            background: var(--rep-surface-2);
            border: 1px solid var(--rep-border);
            padding: 10px 12px;
            border-radius: 2px;
            overflow-x: auto;
            font-size: 11px;
            line-height: 1.45;
            font-family: ui-monospace, Consolas, monospace;
            max-height: 280px;
            overflow-y: auto;
            margin-top: 8px;
        }}
        .rep-in-judge {{
            color: var(--rep-accent);
            font-weight: 600;
            font-size: 12px;
        }}
        .rep-not-in-judge {{
            color: var(--rep-muted);
            font-size: 12px;
        }}
        .recommendation {{
            background: rgba(13, 92, 86, 0.06);
            border-left: 3px solid var(--rep-accent);
            padding: 10px 14px;
            margin: 8px 0;
            border-radius: 0 2px 2px 0;
            font-size: 14px;
        }}
        .category-tag {{
            display: inline-block;
            padding: 3px 10px;
            background: var(--rep-surface-2);
            border: 1px solid var(--rep-border);
            border-radius: 2px;
            font-size: 12px;
        }}
        .ci-range {{
            color: var(--rep-muted);
            font-size: 13px;
        }}
        .rep-gallery {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
            gap: 14px;
            margin-top: 12px;
        }}
        .rep-gallery-card {{
            border: 1px solid var(--rep-border);
            border-radius: 2px;
            background: var(--rep-surface-2);
            overflow: hidden;
        }}
        .rep-gallery-card img {{
            width: 100%;
            height: 160px;
            object-fit: contain;
            background: #fff;
            display: block;
        }}
        .rep-gallery-meta {{
            padding: 8px 10px;
            font-size: 12px;
            color: var(--rep-muted);
        }}
        .rep-gallery-meta strong {{
            color: var(--rep-text);
        }}
        footer.rep-foot {{
            text-align: center;
            padding: 28px 12px 8px;
            color: var(--rep-muted);
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="rep-wrap">
        <header class="rep-hero">
            <div class="rep-hero-row">
                <div>
                    <p class="rep-eyebrow">LLM-QAuto · 测试报告</p>
                    <h1 class="rep-title">{report.project_name}</h1>
                    <p class="rep-sub">运行 <code class="rep-code">{report.run_id}</code></p>
                </div>
                <div class="rep-status-pill" role="status">
                    <span class="rep-dot" aria-hidden="true"></span>
                    <span>{status_icon} {report.status.value.upper()}</span>
                </div>
            </div>
        </header>

        <div class="rep-kpis">
            <div class="rep-kpi">
                <h3>总样本</h3>
                <div class="rep-value">{report.total_cases}</div>
                <div class="rep-detail">本运行纳入评测的条目数</div>
            </div>
            <div class="rep-kpi">
                <h3>通过率</h3>
                <div class="rep-value">{report.pass_rate:.1f}%</div>
                <div class="rep-progress"><div class="rep-progress-fill" style="width: min(100%, {report.pass_rate}%)"></div></div>
            </div>
            <div class="rep-kpi">
                <h3>通过 / 失败</h3>
                <div class="rep-value"><span class="rep-pass">{report.passed_cases}</span><span style="color:var(--rep-muted);font-weight:600"> / </span><span style="color:var(--rep-fail);font-weight:700">{report.failed_cases}</span></div>
                <div class="rep-detail">样本级判定汇总</div>
            </div>
            <div class="rep-kpi">
                <h3>耗时</h3>
                <div class="rep-value" style="font-size:1.35rem">{self._format_duration(report.start_time, report.end_time)}</div>
                <div class="rep-detail">{report.start_time.strftime("%Y-%m-%d %H:%M")} 开始</div>
            </div>
        </div>

        <div class="rep-panel">
            <h2 class="rep-section-title">通过标准检查</h2>
            <table class="rep-table">
                <thead>
                    <tr>
                        <th>检查项</th>
                        <th>状态</th>
                        <th>实际值</th>
                        <th>期望值</th>
                        <th>详情</th>
                    </tr>
                </thead>
                <tbody>
                    {self._render_criteria_rows(report)}
                </tbody>
            </table>
        </div>
        
        <div class="rep-panel">
            <h2 class="rep-section-title">维度统计</h2>
            {self._render_dimension_stats(report)}
        </div>
        
        {self._render_case_invoke_judge_compare(report)}

        {self._render_case_gallery(report)}

        {self._render_failed_examples(report)}
        
        {self._render_recommendations(report)}
        
        <footer class="rep-foot">
            <p>由 LLM-QAuto 生成 · {report.end_time.strftime("%Y-%m-%d %H:%M:%S") if report.end_time else ""}</p>
        </footer>
    </div>
</body>
</html>"""
        
        return html
    
    def _format_duration(self, start, end) -> str:
        """格式化持续时间"""
        if not end:
            return "-"
        duration = (end - start).total_seconds()
        if duration < 60:
            return f"{duration:.0f}秒"
        elif duration < 3600:
            return f"{duration/60:.1f}分钟"
        else:
            return f"{duration/3600:.1f}小时"
    
    def _render_criteria_rows(self, report: TestReport) -> str:
        """渲染通过标准行"""
        rows = []
        for criteria in report.criteria_results:
            status_class = "pass" if criteria.passed else "fail"
            status_text = "通过" if criteria.passed else "失败"
            
            actual_str = f"{criteria.actual_value:.2f}" if isinstance(criteria.actual_value, float) else str(criteria.actual_value)
            expected_str = f"{criteria.expected_value:.2f}" if isinstance(criteria.expected_value, float) else str(criteria.expected_value)
            
            row = f"""
                <tr>
                    <td>{criteria.description}</td>
                    <td class="{status_class}">{status_text}</td>
                    <td>{actual_str}</td>
                    <td>{expected_str}</td>
                    <td>{criteria.details}</td>
                </tr>
            """
            rows.append(row)
        return "".join(rows) if rows else "<tr><td colspan='5'>暂无数据</td></tr>"
    
    def _render_dimension_stats(self, report: TestReport) -> str:
        """渲染维度统计"""
        if not report.dimension_stats:
            return '<p style="color:var(--rep-muted);font-size:14px;">暂无维度统计</p>'
        
        html_parts = []
        dim_names = dimension_names_from_report(report)
        for stat in report.dimension_stats:
            rate_cls = "rate-ok" if stat.pass_rate >= 80 else "rate-bad"
            dim_title = stat.dimension_name or dimension_display_label(
                report, stat.dimension_id, names=dim_names
            )
            html_parts.append(f"""
                <div class="rep-dim-block">
                    <h3>{self._esc(dim_title)}</h3>
                    <div class="rep-dim-metrics">
                        <div class="rep-dim-mini">
                            <div class="lbl">通过率</div>
                            <div class="num {rate_cls}">{stat.pass_rate:.1f}%</div>
                        </div>
                        <div class="rep-dim-mini">
                            <div class="lbl">平均分</div>
                            <div class="num">{stat.avg_score:.2f}</div>
                        </div>
                        <div class="rep-dim-mini">
                            <div class="lbl">样本数</div>
                            <div class="num">{stat.total_cases}</div>
                        </div>
                        <div class="rep-dim-mini">
                            <div class="lbl">标准差</div>
                            <div class="num">{stat.std_score:.2f}</div>
                        </div>
                    </div>
                    <h4>类别分布</h4>
                    <table class="rep-table">
                        <thead>
                            <tr>
                                <th>类别</th>
                                <th>数量</th>
                                <th>占比</th>
                                <th>95%置信区间</th>
                            </tr>
                        </thead>
                        <tbody>
                            {self._render_category_rows(stat.category_distribution)}
                        </tbody>
                    </table>
                </div>
            """)
        
        return "".join(html_parts)
    
    def _render_category_rows(self, categories) -> str:
        """渲染类别行"""
        rows = []
        for cat in categories:
            ci_lower, ci_upper = cat.confidence_interval
            row = f"""
                <tr>
                    <td><span class="category-tag">{cat.category}</span></td>
                    <td>{cat.count}</td>
                    <td>{cat.percentage:.1f}%</td>
                    <td class="ci-range">[{ci_lower*100:.1f}%, {ci_upper*100:.1f}%]</td>
                </tr>
            """
            rows.append(row)
        return "".join(rows) if rows else "<tr><td colspan='4'>无类别数据</td></tr>"
    
    def _media_src(self, report: TestReport, rel_path: str) -> str:
        """HTML 报告与 artifacts 同级的相对路径。"""
        if not rel_path:
            return ""
        if report.artifacts_path:
            return f"artifacts/{rel_path.replace(chr(92), '/')}"
        return rel_path.replace(chr(92), "/")

    def _render_images_block(self, report: TestReport, media_paths: list, alt: str = "") -> str:
        if not media_paths:
            return ""
        imgs = []
        for p in media_paths[:4]:
            src = self._media_src(report, p)
            if src:
                imgs.append(
                    f'<img src="{src}" alt="{alt}" loading="lazy" '
                    f'style="max-width:200px;max-height:160px;margin:6px 8px 0 0;border:1px solid var(--rep-border)">'
                )
        return f'<div style="margin-top:8px">{"".join(imgs)}</div>' if imgs else ""

    @staticmethod
    def _esc(text: Any) -> str:
        if text is None:
            return ""
        return html.escape(str(text), quote=True)

    def _format_field_value(self, val: Any, max_len: int = 500) -> str:
        if val is None:
            return '<span class="rep-field-empty">（空）</span>'
        if isinstance(val, (dict, list)):
            text = json.dumps(val, ensure_ascii=False, indent=0)
        else:
            text = str(val).strip()
        if not text:
            return '<span class="rep-field-empty">（空）</span>'
        if len(text) > max_len:
            text = text[: max_len - 12] + "…[已截断]"
        return f'<div class="rep-field-val">{self._esc(text)}</div>'

    def _judge_excerpt_as_dict(self, excerpt: str) -> Dict[str, Any]:
        if not (excerpt or "").strip():
            return {}
        try:
            data = json.loads(excerpt)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def _render_field_compare_table(
        self,
        case: ReportCaseRollup,
        parser_keys: List[str],
    ) -> str:
        judge_data = self._judge_excerpt_as_dict(
            getattr(case, "judge_excerpt", "") or ""
        )
        keys = list(parser_keys) or list(
            dict(getattr(case, "parsed_fields", None) or {}).keys()
        )
        if not keys and judge_data:
            keys = list(judge_data.keys())
        if not keys:
            return '<p style="color:var(--rep-muted);font-size:13px">未配置 output_parser.keys，无法按字段对照。</p>'

        parsed = dict(getattr(case, "parsed_fields", None) or {})
        rows = []
        for k in keys:
            in_judge = k in judge_data
            judge_mark = (
                '<span class="rep-in-judge">是</span>'
                if in_judge
                else '<span class="rep-not-in-judge">否</span>'
            )
            rows.append(
                f"<tr>"
                f"<td><code>{self._esc(k)}</code></td>"
                f"<td>{self._format_field_value(parsed.get(k))}</td>"
                f"<td>{self._format_field_value(judge_data.get(k) if in_judge else None)}</td>"
                f"<td>{judge_mark}</td>"
                f"</tr>"
            )
        return f"""
            <table class="rep-table">
                <thead>
                    <tr>
                        <th>字段</th>
                        <th>接口解析值</th>
                        <th>评委摘录值</th>
                        <th>进入评委</th>
                    </tr>
                </thead>
                <tbody>{"".join(rows)}</tbody>
            </table>
        """

    def _render_case_invoke_judge_compare(self, report: TestReport) -> str:
        """用例级：被测接口返回 vs 提交评委字段对照。"""
        cases = list(report.cases or [])
        if not cases:
            return ""

        op = (report.suite_meta or {}).get("output_parser") or {}
        parser_keys: List[str] = list(op.get("keys") or [])
        path_hint = op.get("path") or ""
        cards = []

        for case in cases[:40]:
            status_cls = "pass" if case.passed else "fail"
            status_txt = "通过" if case.passed else "未通过"
            err = getattr(case, "output_error", None)
            err_block = (
                f'<p class="fail" style="margin:0 0 8px">接口错误：{self._esc(err)}</p>'
                if err
                else ""
            )
            table_html = self._render_field_compare_table(case, parser_keys)

            raw_prev = getattr(case, "invoke_raw_preview", "") or ""
            judge_prev = getattr(case, "judge_excerpt", "") or ""
            out_prev = case.output_preview or ""

            raw_block = (
                f'<details><summary>展开原始 HTTP 响应（摘要）</summary>'
                f'<pre class="rep-pre-block">{self._esc(raw_prev)}</pre></details>'
                if raw_prev
                else '<p class="rep-field-empty" style="font-size:13px">无原始响应记录</p>'
            )
            judge_block = (
                f'<pre class="rep-pre-block">{self._esc(judge_prev)}</pre>'
                if judge_prev
                else '<p class="rep-field-empty" style="font-size:13px">未调用评委或摘录为空</p>'
            )
            parsed_block = (
                f'<details style="margin-top:8px"><summary>展开完整解析正文</summary>'
                f'<pre class="rep-pre-block">{self._esc(out_prev)}</pre></details>'
                if out_prev
                else ""
            )

            dim_names = dimension_names_from_report(report)
            dim_bits = []
            for dim_id, dim in (case.dimensions or {}).items():
                if not dim:
                    continue
                sc = dim.get("score")
                ps = "通过" if dim.get("passed") else "未通过"
                dim_label = dimension_display_label(report, dim_id, names=dim_names)
                dim_bits.append(f"{dim_label}: {sc} ({ps})")
            dim_line = (
                f'<p style="font-size:13px;color:var(--rep-muted);margin-top:10px">'
                f'评判：{self._esc(" · ".join(dim_bits) or "—")}</p>'
            )

            cards.append(f"""
                <div class="rep-case-card">
                    <div class="rep-case-card-head">
                        <strong>{self._esc(case.case_id)}</strong>
                        <span class="{status_cls}">{status_txt}</span>
                        <span style="color:var(--rep-muted)">综合分 {case.aggregated_score:.2f}</span>
                        <span style="color:var(--rep-muted)">调用 {case.invoke_latency_ms:.0f} ms</span>
                    </div>
                    {err_block}
                    {table_html}
                    <div class="rep-compare-grid">
                        <div class="rep-compare-col">
                            <h4>被测接口</h4>
                            {raw_block}
                            {parsed_block}
                        </div>
                        <div class="rep-compare-col">
                            <h4>提交评委的摘录</h4>
                            {judge_block}
                        </div>
                    </div>
                    {dim_line}
                </div>
            """)

        path_note = (
            f'解析路径 <code>{self._esc(path_hint)}</code> · '
            f'字段 {len(parser_keys)} 个'
            if parser_keys or path_hint
            else ""
        )

        return f"""
            <div class="rep-panel">
                <h2 class="rep-section-title">接口返回与评测对照</h2>
                <p style="color:var(--rep-muted);font-size:14px;margin-bottom:12px">
                    左表对比「配置解析字段」与「评委实际看到的摘录」；下方可展开原始响应与完整解析正文。
                    {path_note}
                </p>
                {"".join(cards)}
            </div>
        """

    def _render_case_gallery(self, report: TestReport) -> str:
        """含图片的用例画廊（文本+生图混合报告）。"""
        image_cases = [
            c for c in (report.cases or [])
            if getattr(c, "media_preview_paths", None)
        ]
        if not image_cases:
            return ""

        cards = []
        for c in image_cases[:24]:
            first = c.media_preview_paths[0] if c.media_preview_paths else ""
            src = self._media_src(report, first)
            if not src:
                continue
            status_cls = "pass" if c.passed else "fail"
            cards.append(f"""
                <div class="rep-gallery-card">
                    <img src="{src}" alt="{c.case_id}">
                    <div class="rep-gallery-meta">
                        <strong>{c.case_id}</strong><br>
                        模式: {getattr(c, 'content_mode', 'text')} ·
                        <span class="{status_cls}">{'通过' if c.passed else '失败'}</span><br>
                        分: {c.aggregated_score:.1f} · 图: {getattr(c, 'media_count', 0)} 张
                    </div>
                </div>
            """)

        if not cards:
            return ""

        return f"""
            <div class="rep-panel">
                <h2 class="rep-section-title">生成图预览</h2>
                <p style="color:var(--rep-muted);font-size:14px;margin-bottom:8px">
                    共 {len(image_cases)} 条用例含图像产物（报告需与 artifacts 目录一并保存）。
                </p>
                <div class="rep-gallery">{''.join(cards)}</div>
            </div>
        """

    def _render_failed_examples(self, report: TestReport) -> str:
        """渲染失败示例"""
        if not report.failed_examples:
            return ""
        
        examples_html = []
        dim_names = dimension_names_from_report(report)
        for case in report.failed_examples[:10]:  # 最多显示10个
            failed_dims = format_dimension_labels(report, case.failed_dimensions, names=dim_names)
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
            imgs = self._render_images_block(report, media_rel, case.id)
            examples_html.append(f"""
                <div class="fail-example">
                    <strong>ID:</strong> {case.id}<br>
                    <strong>模式:</strong> {getattr(case.output, 'content_mode', 'text')}<br>
                    <strong>输入:</strong> {case.input.prompt[:200]}{'...' if len(case.input.prompt) > 200 else ''}<br>
                    <strong>输出:</strong>
                    <pre>{case.output.content[:500]}{'...' if len(case.output.content) > 500 else ''}</pre>
                    {imgs}
                    <strong>失败维度:</strong> {failed_dims}
                </div>
            """)
        
        return f"""
            <div class="rep-panel">
                <h2 class="rep-section-title">失败示例 <span style="font-weight:600;color:var(--rep-muted);font-size:0.9em">({len(report.failed_examples)} 条)</span></h2>
                {''.join(examples_html)}
            </div>
        """
    
    def _render_recommendations(self, report: TestReport) -> str:
        """渲染建议"""
        if not report.recommendations:
            return ""
        
        recs_html = []
        for rec in report.recommendations[:10]:
            recs_html.append(f'<div class="recommendation">{rec}</div>')
        
        return f"""
            <div class="rep-panel">
                <h2 class="rep-section-title">改进建议</h2>
                {''.join(recs_html)}
            </div>
        """
