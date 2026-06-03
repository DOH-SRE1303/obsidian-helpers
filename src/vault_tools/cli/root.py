from __future__ import annotations

import typer
from rich.console import Console

from vault_tools.cli import vc, vt

app = typer.Typer(
    no_args_is_help=True,
    help=(
        "Umbrella CLI for Obsidian vault helpers. Use `vt` for vault audits, profiles, "
        "and manipulation helpers. Use `vc` for future vault chat/local LLM workflows."
    ),
)
console = Console()
app.add_typer(vt.app, name="vt", help="Vault tooling: profiles, audits, reports, and future manipulations.")
app.add_typer(vc.app, name="vc", help="Vault chat: future indexing and local LLM question answering.")


@app.command("completion-info")
def completion_info() -> None:
    """Print shell completion commands for each executable."""
    console.print("Install completion for the commands you use directly:")
    console.print("  vt --install-completion")
    console.print("  vc --install-completion")
    console.print("  vault-tools --install-completion")
    console.print("Preview shell scripts with --show-completion, for example: vt --show-completion")


if __name__ == "__main__":
    app()
