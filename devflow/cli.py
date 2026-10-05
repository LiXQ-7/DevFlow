"""Terminal-first CLI; state inspection does not require model credentials."""

from dataclasses import asdict
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from devflow.config import Config
from devflow.controller import DevFlowController
from devflow.session import SessionManager

app = typer.Typer(
    invoke_without_command=True, no_args_is_help=False, help="DevFlow 终端智能研发助手"
)
bench_app = typer.Typer(help="可复现评测；live 模式会调用已配置模型")
app.add_typer(bench_app, name="bench")
console = Console(highlight=False)


def show_event(name, data):
    if name == "tool_result":
        console.print(f"  工具 {data['call_id']}: {data['status']} ({data['duration_ms']:.0f} ms)")
    elif name == "context_compaction":
        console.print(f"  上下文压缩: {data['tokens_before']} → {data['tokens_after']} tokens")


@app.callback()
def main(
    ctx: typer.Context,
    root: Path = typer.Option(Path.cwd(), "--root"),
    new: bool = typer.Option(False, "--new"),
    resume: str | None = typer.Option(None, "--resume"),
    prompt: str | None = typer.Option(None, "--prompt", "-p"),
    allow_shell: bool = typer.Option(False, "--allow-shell"),
):
    """启动交互会话；--prompt 执行单轮。选项放在子命令之前。"""
    try:
        cfg = Config.load(root)
        if allow_shell:
            cfg.allow_shell = True
        if new and resume:
            raise ValueError("--new and --resume cannot be combined")
        ctx.obj = {"cfg": cfg, "resume": resume, "new": new}
        if ctx.invoked_subcommand:
            return
        controller = get_controller(ctx)
        console.print(
            f"DevFlow | {cfg.project_root}\n模型 {cfg.model} | Session {controller.session.session_id}"
        )
        console.print("工具 Read / Write / Edit / Grep / Bash / TodoWrite")
        if controller.uncertain_calls:
            console.print("检测到中断工具：结果不确定，继续时必须先核验真实状态。")
        if prompt is not None:
            result = controller.run_turn(prompt)
            console.print(result.text, markup=False)
            if result.status != "completed":
                raise typer.Exit(2)
            return
        console.print(
            "/exit 退出 · /tree 历史 · /compact 压缩 · /branch ID 分支 · /shell on 开启命令"
        )
        while True:
            try:
                text = console.input("You> ").strip()
                if text in {"/exit", "/quit"}:
                    break
                if not text:
                    continue
                if text == "/tree":
                    print_tree(controller)
                elif text == "/compact":
                    console.print(controller.compact() is not None)
                elif text.startswith("/branch "):
                    controller.branch(text.split(maxsplit=1)[1])
                    console.print("已创建会话分支；工作区文件保持当前状态。")
                elif text.startswith("/shell "):
                    controller.tools["Bash"].allowed = text == "/shell on"
                    console.print(f"命令执行: {controller.tools['Bash'].allowed}")
                else:
                    result = controller.run_turn(text)
                    console.print(result.text, markup=False)
                    usage = asdict(result.usage)
                    console.print(
                        f"状态 {result.status} | 请求 {usage['requests']} | 输入 Token {usage['input_tokens']} (API)"
                    )
            except (EOFError, KeyboardInterrupt):
                console.print("\n已保留最近持久化节点。")
                break
            except Exception as exc:
                console.print(f"失败: {type(exc).__name__}: {exc}", markup=False)
    except (ValueError, FileNotFoundError) as exc:
        console.print(str(exc), markup=False)
        raise typer.Exit(1)


def get_controller(ctx):
    if "controller" not in ctx.obj:
        ctx.obj["controller"] = DevFlowController(
            ctx.obj["cfg"], ctx.obj["resume"], ctx.obj["new"], observer=show_event
        )
    return ctx.obj["controller"]


@app.command()
def sessions(ctx: typer.Context):
    """列出当前项目的会话。"""
    for path in SessionManager.list_sessions(ctx.obj["cfg"].state_dir / "sessions"):
        console.print(path.stem)


def print_tree(controller):
    table = Table("节点 ID", "父节点", "类型", "当前分支")
    active = {e.id for e in controller.session.active_branch()}
    for entry in controller.session.entries:
        table.add_row(
            entry.id, entry.parent_id or "—", entry.type, "*" if entry.id in active else ""
        )
    console.print(table)


@app.command()
def tree(ctx: typer.Context):
    """显示当前会话树。"""
    print_tree(get_controller(ctx))


@app.command()
def branch(ctx: typer.Context, entry_id: str):
    """从历史节点创建分支；不回滚文件。"""
    get_controller(ctx).branch(entry_id)
    console.print("已创建分支。工作区文件没有回滚。")


@app.command()
def compact(ctx: typer.Context):
    """压缩旧轮次并保留完整事件历史。"""
    console.print("已压缩" if get_controller(ctx).compact() else "轮次不足，无需压缩")


@app.command()
def trace(ctx: typer.Context):
    """统计当前会话的可观察事件。"""
    from collections import Counter

    records = get_controller(ctx).trace.records()
    console.print(dict(Counter(record["event"] for record in records)))


@bench_app.command("tool")
def bench_tool(ctx: typer.Context, live: bool = False, output: Path = Path("benchmark-results")):
    from devflow.benchmarks.tool_calling import run

    console.print(str(run(ctx.obj["cfg"], output, live=live)))


@bench_app.command("context")
def bench_context(ctx: typer.Context, live: bool = False, output: Path = Path("benchmark-results")):
    from devflow.benchmarks.context_ab import run

    console.print(str(run(ctx.obj["cfg"], output, live=live)))


@bench_app.command("recovery")
def bench_recovery(ctx: typer.Context, output: Path = Path("benchmark-results")):
    from devflow.benchmarks.fault_injection import run

    console.print(str(run(output)))


@bench_app.command("report")
def bench_report(output: Path = Path("benchmark-results")):
    """从已保存的最新 CSV 汇总简历指标；跳过未测模型指标。"""
    from devflow.benchmarks.report import run

    console.print(str(run(output)))


if __name__ == "__main__":
    app()
