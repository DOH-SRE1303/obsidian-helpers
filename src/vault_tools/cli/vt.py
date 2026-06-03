from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from vault_tools.config import (
    example_config,
    find_config_path,
    user_config_path,
    load_config,
    normalize_config,
    remove_vault_profile,
    resolve_profile_selector,
    save_config,
    set_default_vault,
    set_vault_profile,
    validate_config,
)
from vault_tools.extensions import inspect_extensions, missing_extensions
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

app = typer.Typer(no_args_is_help=True, help="Audit, index, and manage Obsidian vaults.")
audit_app = typer.Typer(no_args_is_help=True, help="Run targeted vault audits.")
vault_app = typer.Typer(no_args_is_help=True, help="Manage named vault profiles.")
app.add_typer(audit_app, name="audit")
app.add_typer(vault_app, name="vault")
console = Console()

VaultArg = Annotated[
    Path | None,
    typer.Argument(
        help="Path to the Obsidian vault root. Omit when using --profile or a current vault.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
]

ProfileOpt = Annotated[
    str | None,
    typer.Option("--profile", "-p", help="Vault profile key, display name, or nickname."),
]

ConfigOpt = Annotated[
    Path | None,
    typer.Option(
        "--config",
        help="Optional config path. Otherwise use VAULT_TOOLS_CONFIG, local discovery, or user config.",
    ),
]


class ResolvedVault:
    def __init__(self, path: Path, profile_key: str | None = None) -> None:
        self.path = path
        self.profile_key = profile_key


def _check_format(value: str, allowed: set[str]) -> str:
    value = value.lower().strip()
    if value not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise typer.BadParameter(f"Expected one of: {allowed_text}")
    return value


def _resolve_vault(vault: Path | None, profile: str | None, config_path: Path | None) -> ResolvedVault:
    if vault is not None and profile is not None:
        raise typer.BadParameter("Pass either a vault path or --profile, not both.")

    if vault is not None:
        return ResolvedVault(resolve_vault(vault))

    config = load_config(config_path)
    try:
        selected_profile = resolve_profile_selector(profile, config)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    if selected_profile is None:
        available = ", ".join(sorted(config.vaults)) or "none"
        if profile:
            raise typer.BadParameter(f"Unknown vault profile '{profile}'. Available profiles: {available}")
        raise typer.BadParameter(
            "No vault path/profile provided and no current vault is configured. "
            "Run `vt vault init` and `vt vault add NAME PATH --default`, or pass a vault path."
        )

    vault_path = resolve_vault(selected_profile.path)
    missing = missing_extensions(vault_path, selected_profile.required_extensions)
    if missing:
        missing_text = ", ".join(missing)
        raise typer.BadParameter(
            f"Vault profile '{selected_profile.key}' is missing required Obsidian extensions: {missing_text}. "
            f"Checked {vault_path / '.obsidian'}."
        )
    return ResolvedVault(vault_path, selected_profile.key)


def _resolve_vault_input(vault: Path | None, profile: str | None, config_path: Path | None) -> Path:
    return _resolve_vault(vault, profile, config_path).path


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


def _add_profile(
    name: str,
    path: Path,
    role: str,
    description: str,
    display_name: str | None,
    nicknames: list[str] | None,
    make_default: bool,
    config_path: Path | None,
) -> None:
    saved = set_vault_profile(
        name,
        path,
        role=role,
        description=description,
        display_name=display_name,
        nicknames=nicknames,
        make_default=make_default,
        config_path=config_path,
    )
    console.print(f"Saved profile [bold]{name}[/bold] in [bold]{saved}[/bold]")


def _set_current_vault(name: str, config_path: Path | None) -> None:
    try:
        saved = set_default_vault(name, config_path=config_path)
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc
    console.print(f"Set current vault to [bold]{name}[/bold] in [bold]{saved}[/bold]")


def _print_profile_table(config_path: Path | None) -> None:
    config = load_config(config_path)
    table = Table(title=f"Vault profiles ({config.path})")
    table.add_column("Current")
    table.add_column("Key")
    table.add_column("Name")
    table.add_column("Nicknames")
    table.add_column("Role")
    table.add_column("Path")
    table.add_column("Description")

    for name, profile in sorted(config.vaults.items()):
        table.add_row(
            "*" if name == config.current_vault else "",
            name,
            profile.display_name or "",
            ", ".join(profile.nicknames),
            profile.role,
            str(profile.path),
            profile.description,
        )
    console.print(table)


def _print_status(config_path: Path | None, profile: str | None = None) -> None:
    config = load_config(config_path)
    selected = resolve_profile_selector(profile, config)
    if selected is None:
        raise typer.BadParameter("No current vault is configured." if profile is None else f"Unknown vault: {profile}")

    table = Table(title=f"Vault status: {selected.key}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("Config", str(config.path))
    table.add_row("Current", "yes" if selected.key == config.current_vault else "no")
    table.add_row("Key", selected.key)
    table.add_row("Name", selected.display_name or "")
    table.add_row("Nicknames", ", ".join(selected.nicknames))
    table.add_row("Role", selected.role)
    table.add_row("Path", str(selected.path))
    table.add_row("Path exists", "yes" if selected.path.exists() else "no")
    table.add_row("Required core", ", ".join(selected.required_extensions.core))
    table.add_row("Required community", ", ".join(selected.required_extensions.community))

    if selected.path.exists():
        extensions = inspect_extensions(selected.path)
        table.add_row("Enabled core", ", ".join(extensions.core_plugins))
        table.add_row("Enabled community", ", ".join(extensions.community_plugins))
    console.print(table)


@vault_app.command("init")
def vault_init(
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Config path to create.")] = None,
    example: Annotated[
        bool,
        typer.Option("--example/--empty", help="Write example profiles or an empty config."),
    ] = True,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing config.")] = False,
    user: Annotated[bool, typer.Option("--user", help="Create the per-user config instead of a local config.")] = False,
) -> None:
    """Create a vault-tools config file."""
    path = out or (user_config_path() if user else find_config_path() or Path.cwd() / "vault-tools.yml")
    if path.exists() and not force:
        raise typer.BadParameter(f"Config already exists: {path}. Use --force to overwrite.")
    data = example_config() if example else {"current_vault": None, "vaults": {}}
    saved = save_config(data, path)
    console.print(f"Wrote [bold]{saved}[/bold]")


@vault_app.command("list")
def vault_list(config_path: ConfigOpt = None) -> None:
    """List configured vault profiles."""
    _print_profile_table(config_path)


@vault_app.command("add")
def vault_add(
    name: Annotated[str, typer.Argument(help="Profile key, such as old, new, work, or migration.")],
    path: Annotated[
        Path,
        typer.Argument(
            help="Vault path. Relative paths are stored as entered and resolved relative to the config file.",
            file_okay=False,
            dir_okay=True,
            resolve_path=False,
        ),
    ],
    nickname: Annotated[list[str] | None, typer.Option("--nickname", help="Reusable alias for this vault.")] = None,
    display_name: Annotated[str | None, typer.Option("--name", help="Human-readable vault name.")] = None,
    role: Annotated[str, typer.Option("--role", help="Profile role, such as source, target, or archive.")] = "vault",
    description: Annotated[str, typer.Option("--description", "-d", help="Optional description.")] = "",
    make_default: Annotated[bool, typer.Option("--default", help="Set this profile as the current vault.")] = False,
    config_path: ConfigOpt = None,
) -> None:
    """Add or update a named vault profile."""
    _add_profile(name, path, role, description, display_name, nickname, make_default, config_path)


@vault_app.command("remove")
def vault_remove(
    name: Annotated[str, typer.Argument(help="Profile name to remove.")],
    config_path: ConfigOpt = None,
) -> None:
    """Remove a vault profile from the local config."""
    saved = remove_vault_profile(name, config_path=config_path)
    console.print(f"Removed profile [bold]{name}[/bold] from [bold]{saved}[/bold]")


@vault_app.command("set")
def vault_set(
    name: Annotated[str, typer.Argument(help="Profile key, display name, or nickname to make current.")],
    config_path: ConfigOpt = None,
) -> None:
    """Set the current vault profile."""
    _set_current_vault(name, config_path)


@vault_app.command("default")
def vault_default(
    name: Annotated[str | None, typer.Argument(help="Profile name to set as current. Omit to show current.")] = None,
    config_path: ConfigOpt = None,
) -> None:
    """Show or set the current vault profile. Deprecated alias for `vault set`."""
    config = load_config(config_path)
    if name is None:
        console.print(config.current_vault or "No current vault configured.")
        return
    _set_current_vault(name, config_path)


@vault_app.command("show")
def vault_show(
    name: Annotated[str | None, typer.Argument(help="Profile selector to show. Omit to show current.")] = None,
    config_path: ConfigOpt = None,
) -> None:
    """Show details for one vault profile."""
    _print_status(config_path, name)


@vault_app.command("status")
def vault_status(
    name: Annotated[str | None, typer.Argument(help="Profile selector to show. Omit to show current.")] = None,
    config_path: ConfigOpt = None,
) -> None:
    """Show current vault, config, path, and extension state."""
    _print_status(config_path, name)


@vault_app.command("doctor")
def vault_doctor(config_path: ConfigOpt = None) -> None:
    """Validate profile config and report likely problems."""
    config = load_config(config_path)
    issues = validate_config(config)
    if not issues:
        console.print(f"[green]No config issues found.[/green] ({config.path})")
        return
    table = Table(title=f"Config issues ({config.path})")
    table.add_column("Level")
    table.add_column("Message")
    for issue in issues:
        table.add_row(issue.level, issue.message)
    console.print(table)


@vault_app.command("normalize")
def vault_normalize(config_path: ConfigOpt = None) -> None:
    """Rewrite config using the canonical schema."""
    saved = normalize_config(config_path)
    console.print(f"Normalized [bold]{saved}[/bold]")


@app.command()
def info(
    vault: VaultArg = None,
    profile: ProfileOpt = None,
    config_path: ConfigOpt = None,
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
    vault_path = _resolve_vault_input(vault, profile, config_path)
    scan = scan_vault(vault_path, include_obsidian=include_obsidian)

    if fmt == "json":
        output = out or Path("reports/vault-info.json")
        write_json(output, scan.to_dict())
    else:
        output = out or Path("reports/vault-info.md")
        report = render_info_markdown(scan, vault_path=vault_path, max_depth=max_depth, include_obsidian=include_obsidian)
        write_text(output, report)

    console.print(f"Wrote [bold]{output}[/bold]")


@app.command("tree")
def tree_command(
    vault: VaultArg = None,
    profile: ProfileOpt = None,
    config_path: ConfigOpt = None,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Optional output path.")] = None,
    max_depth: Annotated[int, typer.Option(help="Folder tree depth.")] = 3,
    include_obsidian: Annotated[
        bool,
        typer.Option("--include-obsidian/--no-include-obsidian", help="Include .obsidian folder."),
    ] = False,
) -> None:
    """Export a Markdown folder tree for the vault."""
    vault_path = _resolve_vault_input(vault, profile, config_path)
    text = "```text\n" + folder_tree(vault_path, max_depth=max_depth, include_obsidian=include_obsidian) + "\n```\n"

    if out:
        write_text(out, text)
        console.print(f"Wrote [bold]{out}[/bold]")
    else:
        console.print(text)


@app.command()
def manifest(
    vault: VaultArg = None,
    profile: ProfileOpt = None,
    config_path: ConfigOpt = None,
    out: Annotated[Path, typer.Option("--out", "-o", help="Output JSON path.")] = Path("exports/vault-manifest.json"),
    include_obsidian: Annotated[
        bool,
        typer.Option("--include-obsidian/--no-include-obsidian", help="Include .obsidian files in the scan."),
    ] = False,
) -> None:
    """Export the full JSON scan used by other commands."""
    vault_path = _resolve_vault_input(vault, profile, config_path)
    scan = scan_vault(vault_path, include_obsidian=include_obsidian)
    write_json(out, scan.to_dict())
    console.print(f"Wrote [bold]{out}[/bold]")


@audit_app.command("no-tags")
def audit_no_tags(
    vault: VaultArg = None,
    profile: ProfileOpt = None,
    config_path: ConfigOpt = None,
    out: Annotated[Path, typer.Option("--out", "-o", help="Output path.")] = Path("reports/audit-no-tags.md"),
    fmt: Annotated[str, typer.Option("--format", help="Output format: md, json, or csv.")] = "md",
    under: Annotated[str | None, typer.Option("--under", help="Optional vault-relative folder prefix.")] = None,
) -> None:
    """Find notes that have neither frontmatter tags nor inline hashtags."""
    vault_path = _resolve_vault_input(vault, profile, config_path)
    scan = scan_vault(vault_path)
    rows = note_rows(find_untagged_notes(scan, under=under))
    _write_rows(rows, out, fmt, "Notes without tags")


@audit_app.command("broken-links")
def audit_broken_links(
    vault: VaultArg = None,
    profile: ProfileOpt = None,
    config_path: ConfigOpt = None,
    out: Annotated[Path, typer.Option("--out", "-o", help="Output path.")] = Path("reports/audit-broken-links.md"),
    fmt: Annotated[str, typer.Option("--format", help="Output format: md, json, or csv.")] = "md",
) -> None:
    """Find wikilinks that do not resolve to a scanned Markdown note."""
    vault_path = _resolve_vault_input(vault, profile, config_path)
    scan = scan_vault(vault_path)
    _write_rows(find_broken_wikilinks(scan), out, fmt, "Broken wikilinks")


@audit_app.command("orphan-attachments")
def audit_orphan_attachments(
    vault: VaultArg = None,
    profile: ProfileOpt = None,
    config_path: ConfigOpt = None,
    out: Annotated[Path, typer.Option("--out", "-o", help="Output path.")] = Path("reports/audit-orphan-attachments.md"),
    fmt: Annotated[str, typer.Option("--format", help="Output format: md, json, or csv.")] = "md",
) -> None:
    """Find common attachment files that are not referenced by embeds or markdown links."""
    vault_path = _resolve_vault_input(vault, profile, config_path)
    scan = scan_vault(vault_path)
    rows = [{"path": path} for path in find_orphan_attachments(vault_path, scan)]
    _write_rows(rows, out, fmt, "Orphan attachments")


@app.command()
def stats(vault: VaultArg = None, profile: ProfileOpt = None, config_path: ConfigOpt = None) -> None:
    """Print a compact summary to the terminal."""
    vault_path = _resolve_vault_input(vault, profile, config_path)
    scan = scan_vault(vault_path)

    notes_with_tags = sum(1 for note in scan.notes if note.tags)
    notes_without_tags = len(scan.notes) - notes_with_tags

    table = Table(title=f"Vault stats: {vault_path.name}")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_row("Path", str(vault_path))
    table.add_row("Notes", str(len(scan.notes)))
    table.add_row("Total files", str(scan.total_files))
    table.add_row("Notes with tags", str(notes_with_tags))
    table.add_row("Notes without tags", str(notes_without_tags))
    table.add_row("Templates folder", scan.templates_folder or "")

    console.print(table)


if __name__ == "__main__":
    app()
