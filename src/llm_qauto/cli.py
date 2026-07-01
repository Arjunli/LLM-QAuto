"""
命令行入口
"""

import os
import sys
import asyncio
import click
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.panel import Panel
from rich import box

from datetime import datetime

from .config_loader import load_config, save_example_configs
from .engine import TestEngine
from .models import TestSuiteConfig
from .reporters import HTMLReporter, JSONReporter, MarkdownReporter, CSVReporter

console = Console()


@click.group()
@click.version_option(version="1.0.0")
def cli():
    """LLM-QAuto - 通用AI智能体测试平台"""
    pass


@cli.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True), help="配置文件路径")
@click.option("--output", "-o", default="./output", help="输出目录")
@click.option("--format", "-f", "report_format", default="html,json,md", help="报告格式(html,json,md,csv)")
@click.option("--save-artifacts", is_flag=True, help="保存原始数据")
@click.option("--var", "variables", multiple=True, help="模板变量(key=value)")
def run(config, output, report_format, save_artifacts, variables):
    """执行测试"""
    
    # 解析变量
    vars_dict = {}
    for var in variables:
        if "=" in var:
            key, value = var.split("=", 1)
            vars_dict[key] = value
    
    # 加载配置
    try:
        with console.status("[bold green]加载配置..."):
            suite_config = load_config(config, vars_dict)
        console.print(f"✓ 配置已加载: [cyan]{config}[/cyan]")
    except Exception as e:
        console.print(f"[red]配置加载失败: {e}[/red]")
        sys.exit(1)
    
    # 创建输出目录
    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建运行目录
    run_id = suite_config.meta.get("name", "test").replace(" ", "_") + "_" + \
             Path(config).stem + "_" + \
             datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = output_dir / run_id
    run_dir.mkdir(exist_ok=True)
    
    console.print(f"✓ 输出目录: [cyan]{run_dir}[/cyan]")
    
    # 执行测试
    async def execute():
        engine = TestEngine(suite_config)
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            
            task = progress.add_task("[green]执行测试...", total=None)
            
            def progress_callback(current, total):
                progress.update(task, description=f"[green]处理中... {current}/{total}")
            
            artifacts_path = str(run_dir / "artifacts")
            report = await engine.run(
                run_id=run_id,
                progress_callback=progress_callback,
                artifacts_dir=artifacts_path,
            )
            
            progress.update(task, completed=True, description="[green]测试完成!")
        
        return report, engine
    
    try:
        report, engine = asyncio.run(execute())
    except Exception as e:
        console.print(f"[red]测试执行失败: {e}[/red]")
        import traceback
        console.print(traceback.format_exc())
        sys.exit(1)
    
    # 保存原始数据
    if save_artifacts:
        engine.save_artifacts(str(run_dir / "artifacts"))
        console.print(f"✓ 原始数据已保存")
    
    # 生成报告
    formats = [f.strip() for f in report_format.split(",")]
    reporters = {
        "html": HTMLReporter(),
        "json": JSONReporter(),
        "md": MarkdownReporter(),
        "csv": CSVReporter(),
    }
    
    for fmt in formats:
        if fmt in reporters:
            if getattr(report, "abort_reason", None) == "connectivity" and fmt in (
                "html",
                "md",
                "csv",
            ):
                console.print(
                    f"[yellow]跳过 {fmt} 报告：被测接口首包探测失败，仅生成 JSON 说明原因。[/yellow]"
                )
                continue
            output_path = run_dir / f"report.{fmt}"
            reporters[fmt].generate(report, str(output_path), {})
            console.print(f"✓ 报告已生成: [cyan]{output_path}[/cyan]")
    
    # 显示结果摘要
    console.print()
    
    status_color = "green" if report.status.value == "passed" else "red"
    if report.status.value == "error" and getattr(report, "abort_reason", None) == "connectivity":
        status_text = "⚠ 已中止（接口不可达）"
        status_color = "yellow"
    else:
        status_text = "✓ 通过" if report.status.value == "passed" else "✗ 失败"
    
    summary_table = Table(box=box.ROUNDED, show_header=False)
    summary_table.add_column(style="bold")
    summary_table.add_column()
    summary_table.add_row("项目名称", report.project_name)
    summary_table.add_row("运行ID", report.run_id)
    summary_table.add_row("总样本数", str(report.total_cases))
    summary_table.add_row("通过数", str(report.passed_cases))
    summary_table.add_row("失败数", str(report.failed_cases))
    summary_table.add_row("通过率", f"{report.pass_rate:.1f}%")
    summary_table.add_row("最终状态", f"[{status_color}]{status_text}[/{status_color}]")
    
    console.print(Panel(summary_table, title="测试结果摘要", border_style=status_color))
    
    # 显示维度统计
    if report.dimension_stats:
        console.print()
        console.print("[bold]维度统计:[/bold]")
        
        stats_table = Table(box=box.ROUNDED)
        stats_table.add_column("维度", style="cyan")
        stats_table.add_column("通过率", justify="right")
        stats_table.add_column("平均分", justify="right")
        stats_table.add_column("样本数", justify="right")
        
        for stat in report.dimension_stats:
            pass_rate_style = "green" if stat.pass_rate >= 80 else "red"
            stats_table.add_row(
                stat.dimension_name or stat.dimension_id,
                f"[{pass_rate_style}]{stat.pass_rate:.1f}%[/{pass_rate_style}]",
                f"{stat.avg_score:.2f}",
                str(stat.total_cases)
            )
        
        console.print(stats_table)
    
    # 显示建议
    if report.recommendations:
        console.print()
        console.print("[bold yellow]改进建议:[/bold yellow]")
        for i, rec in enumerate(report.recommendations[:5], 1):
            console.print(f"  {i}. {rec}")
    
    console.print()
    console.print(f"[green]所有报告已保存到: {run_dir}[/green]")
    
    # 返回码
    sys.exit(0 if report.status.value == "passed" else 1)


@cli.command()
@click.option("--output", "-o", default="./examples", help="示例配置输出目录")
def init(output):
    """初始化示例配置"""
    save_example_configs(output)
    console.print(f"[green]✓ 示例配置已生成到: {output}[/green]")
    console.print("  - basic_example.yaml: 基础测试配置")


@cli.command()
@click.option("--config", "-c", required=True, type=click.Path(exists=True), help="配置文件路径")
def validate(config):
    """验证配置文件"""
    try:
        suite_config = load_config(config)
        console.print(f"[green]✓ 配置验证通过: {config}[/green]")
        
        # 显示配置摘要
        table = Table(box=box.ROUNDED)
        table.add_column("配置项")
        table.add_column("值")
        
        table.add_row("项目名称", suite_config.meta.get("name", "N/A"))
        table.add_row("连接器", suite_config.target.connector.name)
        table.add_row("数据生成器", suite_config.data_generator.strategy)
        table.add_row("评判维度数", str(len(suite_config.evaluation.dimensions)))
        table.add_row("计划样本数", str(suite_config.data_generator.sampling.total))
        
        console.print(table)
        
    except Exception as e:
        console.print(f"[red]✗ 配置验证失败: {e}[/red]")
        sys.exit(1)


def main():
    """主入口"""
    cli()


if __name__ == "__main__":
    main()
