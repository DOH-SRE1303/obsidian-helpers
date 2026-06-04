from __future__ import annotations

import typer
from rich.console import Console

from vault_tools.cli import vc, vt

ROOT_HELP = f"""{vt.CLICK_KEEP_FORMATTING}
{vt.BANNER}

Umbrella CLI for Obsidian vault helpers. Use `vt` for vault audits, profiles, and manipulation helpers. Use `vc` for future vault chat/local LLM workflows.

Start with vault profiles:
  vault-tools vt vault init --empty
  vault-tools vt vault add work /path/to/vault --nickname main --default
  vault-tools vt vault status

Common vt commands:
  vault-tools vt manifest build [VAULT] --profile PROFILE --out exports/scans/PROFILE/latest
  vault-tools vt info [VAULT] --profile PROFILE
  vault-tools vt audit tags --profile PROFILE --untagged --sus --used-once
  vault-tools vt audit attachment --profile PROFILE --locations --sprawl --duplicates
  vault-tools vt audit folders --profile PROFILE --drift --duplicates

Direct executables are also installed: vt, vc.
"""

app = typer.Typer(no_args_is_help=True, help=ROOT_HELP)
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
