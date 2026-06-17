"""Interactive CLI for the LangGraph SQL Q&A agent."""
import sys
import os
from pathlib import Path

# Ensure project root is on PYTHONPATH
sys.path.insert(0, str(Path(__file__).parent))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.rule import Rule
from rich.prompt import Prompt
from rich.live import Live
from rich.spinner import Spinner
from rich import box
from rich.markup import escape

console = Console()

BANNER = """
[bold cyan]╔══════════════════════════════════════════════════════╗[/]
[bold cyan]║[/]  [bold white]SQL Q&A Agent[/]  [dim]powered by LangChain + LangGraph[/]  [bold cyan]║[/]
[bold cyan]╚══════════════════════════════════════════════════════╝[/]
"""

EXAMPLE_QUESTIONS = [
    "Show me the top 10 records from [your table]",
    "What is the total count grouped by [a column]?",
    "Show me data from the last 30 days",
    "Which rows have the highest value in [a column]?",
    "Generate a report of all records where [condition]",
    "What is the monthly trend for [a metric]?",
    "Show me a summary grouped by [dimension]",
    "Which entries are missing or have null values?",
]


def _check_env():
    """Warn if the LLM API key is missing."""
    from config import LLM_PROVIDER, ANTHROPIC_API_KEY, OPENAI_API_KEY
    if LLM_PROVIDER == "anthropic" and not ANTHROPIC_API_KEY:
        console.print(
            "[bold red]ANTHROPIC_API_KEY is not set.[/]\n"
            "Copy [cyan].env.example[/] to [cyan].env[/] and add your key.\n"
        )
        sys.exit(1)
    if LLM_PROVIDER == "openai" and not OPENAI_API_KEY:
        console.print(
            "[bold red]OPENAI_API_KEY is not set.[/]\n"
            "Copy [cyan].env.example[/] to [cyan].env[/] and add your key.\n"
        )
        sys.exit(1)


def _connect_db() -> list[str]:
    """Test the SQL Server connection and return discovered table names.

    Exits the program with a helpful message if the connection fails.
    """
    from config import DB_SERVER, DB_NAME
    console.print(
        f"[yellow]Connecting to SQL Server:[/] "
        f"[cyan]{DB_SERVER}[/] / [cyan]{DB_NAME}[/] ..."
    )
    from database.db_setup import test_connection
    result = test_connection()
    if not result["success"]:
        console.print(
            Panel(
                f"[bold red]Connection failed:[/]\n{result['error']}\n\n"
                "Check DB_SERVER, DB_NAME, DB_USERNAME, DB_PASSWORD and DB_DRIVER in your [cyan].env[/] file.\n"
                "Make sure the ODBC driver is installed: "
                "[link=https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server]"
                "Download ODBC Driver[/link]",
                title="SQL Server Error",
                border_style="red",
            )
        )
        sys.exit(1)

    tables = result["tables"]
    console.print(
        f"[green]Connected.[/] Found [bold]{len(tables)}[/] table(s): "
        f"[dim]{', '.join(tables[:8])}{'...' if len(tables) > 8 else ''}[/]\n"
    )
    return tables


def _render_result_table(state: dict):
    """Render query results as a Rich table (capped at 20 rows)."""
    rows    = state.get("query_results") or []
    columns = state.get("column_names") or []
    if not rows or not columns:
        return

    display = rows[:20]
    table   = Table(box=box.SIMPLE_HEAD, show_lines=False, highlight=True)
    for col in columns:
        table.add_column(str(col), style="cyan", no_wrap=True)

    for row in display:
        cells = [str(row.get(c, "")) for c in columns]
        table.add_row(*cells)

    console.print(table)
    if len(rows) > 20:
        console.print(
            f"[dim]  ... and {len(rows) - 20} more rows[/]\n"
        )


def _render_response(state: dict):
    """Print the full formatted response panel."""
    response = state.get("response", "(no response)")

    panel = Panel(
        Text(response, style="white"),
        title="[bold green] Answer[/]",
        border_style="green",
        padding=(1, 2),
    )
    console.print(panel)

    # SQL callout
    sql = state.get("sql_query")
    if sql:
        console.print(
            Panel(
                Text(sql, style="dim cyan"),
                title="[dim] SQL Query Used[/]",
                border_style="dim",
                padding=(0, 1),
            )
        )

    # Report
    if state.get("report_filename"):
        console.print(
            f"\n[bold yellow] Report ready:[/] {state['report_filename']}\n"
        )


def _show_examples():
    t = Table(title="Example Questions", box=box.ROUNDED, style="dim")
    t.add_column("#", style="cyan", width=3)
    t.add_column("Question")
    for i, q in enumerate(EXAMPLE_QUESTIONS, 1):
        t.add_row(str(i), q)
    console.print(t)
    console.print()


def main():
    console.print(BANNER)
    _check_env()
    _connect_db()

    console.print("[bold]Commands:[/]  [cyan]examples[/] • [cyan]quit[/] / [cyan]exit[/]\n")

    history: list[str] = []

    while True:
        try:
            question = Prompt.ask("[bold green]You[/]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/]")
            break

        if not question:
            continue

        lower = question.lower()

        if lower in {"quit", "exit", "q", "bye"}:
            console.print("[dim]Goodbye![/]")
            break

        if lower in {"examples", "example", "help"}:
            _show_examples()
            continue

        if lower == "history":
            if not history:
                console.print("[dim]No history yet.[/]\n")
            else:
                for i, q in enumerate(history, 1):
                    console.print(f"  [cyan]{i}.[/] {q}")
                console.print()
            continue

        history.append(question)

        # Run the agent with a spinner
        console.print()
        state = None

        with console.status("[bold yellow]Thinking...[/]", spinner="dots"):
            try:
                from agent.graph import run_agent
                state = run_agent(question)
            except Exception as exc:
                console.print(f"[bold red]Agent error:[/] {escape(str(exc))}\n")
                continue

        console.print(Rule(style="dim"))
        _render_result_table(state)
        _render_response(state)
        console.print(Rule(style="dim"))
        console.print()


if __name__ == "__main__":
    main()
