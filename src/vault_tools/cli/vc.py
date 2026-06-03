from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from vault_tools.config import load_config, resolve_profile_selector
from vault_tools.extensions import inspect_extensions, missing_extensions
from vault_tools.scanner import resolve_vault

app = typer.Typer(
    no_args_is_help=True,
    help="Chat with an Obsidian vault using a future local LLM/indexing workflow.",
)
console = Console()

ProfileOpt = Annotated[
    str | None,
    typer.Option("--profile", "-p", help="Vault profile key, display name, or nickname."),
]
ConfigOpt = Annotated[
    Path | None,
    typer.Option("--config", help="Optional config path."),
]


def _resolve_chat_vault(profile: str | None, config_path: Path | None) -> tuple[Path, str]:
    config = load_config(config_path)
    selected = resolve_profile_selector(profile, config)
    if selected is None:
        raise typer.BadParameter("No vault profile selected and no current vault is configured.")
    vault_path = resolve_vault(selected.path)
    missing = missing_extensions(vault_path, selected.required_extensions)
    if missing:
        raise typer.BadParameter(
            f"Vault profile '{selected.key}' is missing required Obsidian extensions: {', '.join(missing)}."
        )
    return vault_path, selected.key


@app.command()
def index(
    profile: ProfileOpt = None,
    config_path: ConfigOpt = None,
) -> None:
    """Show the planned indexing target for the selected vault."""
    vault_path, profile_key = _resolve_chat_vault(profile, config_path)
    console.print(
        f"[yellow]Indexing is not implemented yet.[/yellow] Would index profile [bold]{profile_key}[/bold] at {vault_path}."
    )


@app.command()
def ask(
    query: Annotated[str, typer.Argument(help="Question to ask about the selected vault.")],
    profile: ProfileOpt = None,
    config_path: ConfigOpt = None,
) -> None:
    """Ask a question about the selected vault once chat indexing is implemented."""
    vault_path, profile_key = _resolve_chat_vault(profile, config_path)
    console.print(f"[bold]Vault:[/bold] {profile_key} ({vault_path})")
    console.print(f"[bold]Question:[/bold] {query}")
    console.print("[yellow]Vault chat is scaffolded, but local LLM querying is not implemented yet.[/yellow]")


@app.command()
def sources(
    query: Annotated[str, typer.Argument(help="Search phrase for future source retrieval.")],
    profile: ProfileOpt = None,
    config_path: ConfigOpt = None,
) -> None:
    """Preview source retrieval for a future vault chat answer."""
    vault_path, profile_key = _resolve_chat_vault(profile, config_path)
    console.print(
        f"[yellow]Source retrieval is not implemented yet.[/yellow] Would search {profile_key} ({vault_path}) for: {query}"
    )


@app.command()
def doctor(profile: ProfileOpt = None, config_path: ConfigOpt = None) -> None:
    """Check whether the selected vault is ready for future chat/index commands."""
    vault_path, profile_key = _resolve_chat_vault(profile, config_path)
    extensions = inspect_extensions(vault_path)
    table = Table(title=f"Vault chat doctor: {profile_key}")
    table.add_column("Check")
    table.add_column("Value")
    table.add_row("Vault path", str(vault_path))
    table.add_row("Path exists", "yes")
    table.add_row("Enabled core plugins", ", ".join(extensions.core_plugins))
    table.add_row("Enabled community plugins", ", ".join(extensions.community_plugins))
    table.add_row("Chat index", "not implemented")
    console.print(table)


@app.command()
def models() -> None:
    """List planned model configuration hooks for vault chat."""
    console.print("[yellow]Model discovery is not implemented yet.[/yellow]")
    console.print("Planned providers include local LLM backends such as Ollama.")


if __name__ == "__main__":
    app()
