from __future__ import annotations

import logging
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from .pipeline.engine import Pipeline, PipelineResult

console = Console()


def _setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True)],
    )


def _print_results(result: PipelineResult):
    table = Table(
        title=f"AgentSAST Results — {result.target}", show_lines=True
    )
    table.add_column("File", style="cyan", max_width=40)
    table.add_column("Line", justify="right", style="white")
    table.add_column("Tool", style="dim")
    table.add_column("CWE", style="yellow")
    table.add_column("Verdict", style="bold")
    table.add_column("Confidence", justify="right")
    table.add_column("Reason", max_width=60)

    for entry in result.results:
        anchor = entry["anchor"]
        llm = entry.get("llm")

        if llm:
            verdict = llm.get("verdict", "uncertain")
            confidence = f"{llm.get('confidence', 0):.0%}"
            reason = llm.get("reason", "")[:60]
        else:
            verdict = "skipped"
            confidence = "-"
            reason = "-"

        verdict_style = {
            "vulnerable": "[red]VULNERABLE[/red]",
            "safe": "[green]SAFE[/green]",
            "uncertain": "[yellow]UNCERTAIN[/yellow]",
            "skipped": "[dim]SKIPPED[/dim]",
        }.get(verdict, verdict)

        table.add_row(
            anchor["location"]["file"],
            str(anchor["location"]["line"]),
            anchor["tool"],
            anchor.get("cwe", ""),
            verdict_style,
            confidence,
            reason,
        )

    console.print(table)
    console.print(
        f"\n[bold]Summary:[/bold] {result.total_anchors} anchors → "
        f"[red]{result.vulnerable} vulnerable[/red], "
        f"[green]{result.safe} safe[/green], "
        f"[yellow]{result.uncertain} uncertain[/yellow]"
    )


@click.command()
@click.argument("target", type=click.Path(exists=True))
@click.option(
    "--project-root",
    type=click.Path(),
    default=None,
    help="Project root for cross-file slicing",
)
@click.option(
    "--tools",
    "-t",
    multiple=True,
    default=["semgrep", "flawfinder"],
    help="SAST tools to use",
)
@click.option(
    "--semgrep-config", default="p/c", help="Semgrep rules config"
)
@click.option(
    "--max-call-depth",
    default=2,
    type=int,
    help="Max caller/callee slicing depth",
)
@click.option("--llm-model", default="gpt-4o", help="LLM model name")
@click.option(
    "--llm-api-key",
    envvar="OPENAI_API_KEY",
    default=None,
    help="OpenAI API key",
)
@click.option(
    "--llm-base-url",
    envvar="OPENAI_BASE_URL",
    default=None,
    help="OpenAI-compatible API base URL",
)
@click.option(
    "--skip-llm",
    is_flag=True,
    help="Skip LLM judgment, only run Layer1+Layer2",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(),
    default=None,
    help="Output JSON file path",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def main(
    target: str,
    project_root: str | None,
    tools: tuple[str, ...],
    semgrep_config: str,
    max_call_depth: int,
    llm_model: str,
    llm_api_key: str | None,
    llm_base_url: str | None,
    skip_llm: bool,
    output: str | None,
    verbose: bool,
):
    _setup_logging(verbose)

    pipeline = Pipeline(
        tools=list(tools),
        semgrep_config=semgrep_config,
        max_call_depth=max_call_depth,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        llm_base_url=llm_base_url,
        skip_llm=skip_llm,
    )

    root = Path(project_root).resolve() if project_root else None
    console.rule(
        "[bold blue]AgentSAST — AI-Augmented Static Analysis[/bold blue]"
    )
    console.print(f"Target: {target}")
    console.print(f"Tools: {', '.join(tools)}")
    console.print(f"LLM: {'skipped' if skip_llm else llm_model}")
    console.print()

    result = pipeline.run(Path(target), project_root=root)

    _print_results(result)

    if output:
        out_path = Path(output)
        out_path.write_text(result.to_json())
        console.print(f"\nResults written to: {out_path}")


if __name__ == "__main__":
    main()
