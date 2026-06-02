from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from vault_tools.reports import (
    markdown_table,
    note_rows,
    render_info_markdown,
    write_csv,
    write_json,
    write_text,
)
from vault_tools.scanner import (
    find_broken_wikilinks,
    find_orphan_attachments,
    find_untagged_notes,
    folder_tree,
    resolve_vault,
    scan_vault,
)

app = typer.Typer(
    no_args_is_help=True,
    help="Audit and index an Obsidian vault.",
)
audit_app = typer.Typer(no_args_is_help=True, help="Run targeted vault audits.")
app.add_typer(audit_app, name="audit")
console = Console()

VaultArg = Annotated[
    Path,
    typer.Argument(
        help="Path to the Obsidian vault root.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
]


def _check_format(value: str, allowed: set[str]) -> str:
    value = value.lower().strip()
    if value not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise typer.BadParameter(f"Expected one of: {allowed_text}")
    return value


def _write_rows(rows: list[dict[str, object]], out: Path, fmt: str, title: str) -> None:
    fmt = _check_format(fmt, {"md", "json", "csv"})
    if fmt == "json":
        write_json(out, rows)
    elif fmt == "csv":
        write_csv(out, rows)
    else:
        text = f"# {title}\n\n" + markdown_table(rows)
        write_text(out, text)
    console.print(f"Wrote [bold]{out}[/bold]")


@app.command()
def info(
    vault: VaultArg,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Optional output path.")] = None,
    fmt: Annotated[str, typer.Option("--format", help="Output format: md or json.")] = "md",
    max_depth: Annotated[int, typer.Option(help="Folder tree depth for markdown output.")] = 2,
    include_obsidian: Annotated[
        bool,
        typer.Option(
            "--include-obsidian/--no-include-obsidian",
            help="Include .obsidian details and plugin metadata.",
        ),
    ] = False,
) -> None:
    """Create a basic vault snapshot report."""
    fmt = _check_format(fmt, {"md", "json"})
    vault = resolve_vault(vault)
    scan = scan_vault(vault, include_obsidian=include_obsidian)

    if fmt == "json":
        output = out or Path("reports/vault-info.json")
        write_json(output, scan.to_dict())
    else:
        output = out or Path("reports/vault-info.md")
        report = render_info_markdown(
            scan,
            vault_path=vault,
            max_depth=max_depth,
            include_obsidian=include_obsidian,
        )
        write_text(output, report)

    console.print(f"Wrote [bold]{output}[/bold]")


@app.command("tree")
def tree_command(
    vault: VaultArg,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Optional output path.")] = None,
    max_depth: Annotated[int, typer.Option(help="Folder tree depth.")] = 3,
    include_obsidian: Annotated[
        bool,
        typer.Option("--include-obsidian/--no-include-obsidian", help="Include .obsidian folder."),
    ] = False,
) -> None:
    """Export a Markdown folder tree for the vault."""
    vault = resolve_vault(vault)
    text = "```text\n" + folder_tree(vault, max_depth=max_depth, include_obsidian=include_obsidian) + "\n```\n"

    if out:
        write_text(out, text)
        console.print(f"Wrote [bold]{out}[/bold]")
    else:
        console.print(text)


@app.command()
def manifest(
    vault: VaultArg,
    out: Annotated[Path, typer.Option("--out", "-o", help="Output JSON path.")] = Path(
        "exports/vault-manifest.json"
    ),
    include_obsidian: Annotated[
        bool,
        typer.Option(
            "--include-obsidian/--no-include-obsidian",
            help="Include .obsidian files in the scan.",
        ),
    ] = False,
) -> None:
    """Export the full JSON scan used by other commands."""
    vault = resolve_vault(vault)
    scan = scan_vault(vault, include_obsidian=include_obsidian)
    write_json(out, scan.to_dict())
    console.print(f"Wrote [bold]{out}[/bold]")


@audit_app.command("no-tags")
def audit_no_tags(
    vault: VaultArg,
    out: Annotated[Path, typer.Option("--out", "-o", help="Output path.")] = Path(
        "reports/audit-no-tags.md"
    ),
    fmt: Annotated[str, typer.Option("--format", help="Output format: md, json, or csv.")] = "md",
    under: Annotated[
        str | None,
        typer.Option(
            "--under",
            help="Optional vault-relative folder prefix, such as 'Meetings' or 'Projects/WAPOP'.",
        ),
    ] = None,
) -> None:
    """Find notes that have neither frontmatter tags nor inline hashtags."""
    vault = resolve_vault(vault)
    scan = scan_vault(vault)
    notes = find_untagged_notes(scan, under=under)
    rows = note_rows(notes)
    _write_rows(rows, out, fmt, "Notes without tags")


@audit_app.command("broken-links")
def audit_broken_links(
    vault: VaultArg,
    out: Annotated[Path, typer.Option("--out", "-o", help="Output path.")] = Path(
        "reports/audit-broken-links.md"
    ),
    fmt: Annotated[str, typer.Option("--format", help="Output format: md, json, or csv.")] = "md",
) -> None:
    """Find wikilinks that do not resolve to a scanned Markdown note."""
    vault = resolve_vault(vault)
    scan = scan_vault(vault)
    rows = find_broken_wikilinks(scan)
    _write_rows(rows, out, fmt, "Broken wikilinks")


@audit_app.command("orphan-attachments")
def audit_orphan_attachments(
    vault: VaultArg,
    out: Annotated[Path, typer.Option("--out", "-o", help="Output path.")] = Path(
        "reports/audit-orphan-attachments.md"
    ),
    fmt: Annotated[str, typer.Option("--format", help="Output format: md, json, or csv.")] = "md",
) -> None:
    """Find common attachment files that are not referenced by embeds or markdown links."""
    vault = resolve_vault(vault)
    scan = scan_vault(vault)
    rows = [{"path": path} for path in find_orphan_attachments(vault, scan)]
    _write_rows(rows, out, fmt, "Orphan attachments")


@app.command()
def stats(vault: VaultArg) -> None:
    """Print a compact summary to the terminal."""
    vault = resolve_vault(vault)
    scan = scan_vault(vault)

    notes_with_tags = sum(1 for note in scan.notes if note.tags)
    notes_without_tags = len(scan.notes) - notes_with_tags

    table = Table(title="Vault stats")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Notes", str(len(scan.notes)))
    table.add_row("Total files", str(scan.total_files))
    table.add_row("Notes with tags", str(notes_with_tags))
    table.add_row("Notes without tags", str(notes_without_tags))
    table.add_row("Templates folder", scan.templates_folder or "")

    console.print(table)


if __name__ == "__main__":
    app()
