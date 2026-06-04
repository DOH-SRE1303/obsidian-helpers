from __future__ import annotations

from collections import Counter, defaultdict
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
from vault_tools.manifests import (
    build_manifests,
    load_scan_from_manifest,
    orphan_attachments_from_manifest,
    read_manifest,
)
from vault_tools.reports import (
    markdown_table,
    note_rows,
    render_info_markdown,
    write_csv,
    write_json,
    write_text,
)
from vault_tools.scanner import (
    ATTACHMENT_EXTENSIONS,
    find_broken_wikilinks,
    find_orphan_attachments,
    find_untagged_notes,
    folder_tree,
    iter_files,
    resolve_vault,
    scan_vault,
    VaultScan,
)

CLICK_KEEP_FORMATTING = "\b"

BANNER = """██╗   ██╗ █████╗ ██╗   ██╗██╗  ████████╗
██║   ██║██╔══██╗██║   ██║██║  ╚══██╔══╝
██║   ██║███████║██║   ██║██║     ██║
╚██╗ ██╔╝██╔══██║██║   ██║██║     ██║
 ╚████╔╝ ██║  ██║╚██████╔╝███████╗██║
  ╚═══╝  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝╚═╝

████████╗ ██████╗  ██████╗ ██╗     ███████╗
╚══██╔══╝██╔═══██╗██╔═══██╗██║     ██╔════╝
   ██║   ██║   ██║██║   ██║██║     ███████╗
   ██║   ██║   ██║██║   ██║██║     ╚════██║
   ██║   ╚██████╔╝╚██████╔╝███████╗███████║
   ╚═╝    ╚═════╝  ╚═════╝ ╚══════╝╚══════╝"""

VT_HELP = f"""{CLICK_KEEP_FORMATTING}
{BANNER}

Audit, index, and manage Obsidian vaults.

Common vault commands:
  vt info [VAULT] --profile PROFILE --out reports/vault-info.md
  vt stats [VAULT] --profile PROFILE
  vt tree [VAULT] --profile PROFILE --max-depth 3
  vt manifest build [VAULT] --profile PROFILE --out exports/scans/PROFILE/latest

Profile setup workflow:
  vt vault init --empty
  vt vault add work /path/to/vault --name "Work Vault" --nickname main --default
  vt vault list
  vt vault status

Primary audit workflows:
  vt audit tags [VAULT] --profile PROFILE --untagged --sus --used-once
  vt audit attachment [VAULT] --profile PROFILE --locations --sprawl --duplicates
  vt audit folders [VAULT] --profile PROFILE --drift --duplicates
  vt audit no-tags --profile PROFILE --from-manifest exports/scans/PROFILE/latest

Legacy report audits:
  vt audit no-tags --profile PROFILE --from-manifest exports/scans/PROFILE/latest --out reports/audit-no-tags.md
  vt audit broken-links --profile PROFILE --from-manifest exports/scans/PROFILE/latest --format csv --out reports/broken-links.csv
  vt audit orphan-attachments --profile PROFILE --from-manifest exports/scans/PROFILE/latest --format json --out reports/orphan-attachments.json
  vt audit suspicious-tags --profile PROFILE --from-manifest exports/scans/PROFILE/latest --out reports/suspicious-tags.md

Vault resolution: pass [VAULT], pass --profile/-p, or configure a current vault with vt vault add --default.
"""

AUDIT_HELP = f"""{CLICK_KEEP_FORMATTING}
Run targeted vault audits.

Primary audit commands:
  vt audit tags [VAULT] --untagged --sus --used-once
  vt audit attachment [VAULT] --locations --sprawl --duplicates
  vt audit folders [VAULT] --drift --duplicates

Existing report commands remain available for file output:
  vt audit no-tags --from-manifest exports/scans/old/latest --out reports/audit-no-tags.md
  vt audit broken-links --from-manifest exports/scans/old/latest --format csv --out reports/broken-links.csv
  vt audit orphan-attachments --from-manifest exports/scans/old/latest --format json --out reports/orphan-attachments.json
  vt audit suspicious-tags --from-manifest exports/scans/old/latest --out reports/suspicious-tags.md
"""

VAULT_HELP = f"""{CLICK_KEEP_FORMATTING}
Manage named vault profiles.

Profile setup quick start:
  vt vault init --empty
  vt vault add work /path/to/vault --name "Work Vault" --nickname main --default
  vt vault status

Use --config path/to/vault-tools.yml or VAULT_TOOLS_CONFIG to choose a non-default config.
"""


app = typer.Typer(no_args_is_help=True, help=VT_HELP)
manifest_app = typer.Typer(no_args_is_help=True, help="Build reusable machine-readable vault manifests.")
audit_app = typer.Typer(no_args_is_help=True, help=AUDIT_HELP)
vault_app = typer.Typer(no_args_is_help=True, help=VAULT_HELP)
app.add_typer(manifest_app, name="manifest", help="Build reusable machine-readable vault manifests.")
app.add_typer(audit_app, name="audit", help=AUDIT_HELP)
app.add_typer(vault_app, name="vault", help=VAULT_HELP)
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

FromManifestOpt = Annotated[
    Path | None,
    typer.Option(
        "--from-manifest",
        help="Read an existing manifest directory instead of rescanning the vault.",
        file_okay=False,
        dir_okay=True,
        resolve_path=True,
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


def _scan_from_inputs(
    vault: Path | None,
    profile: str | None,
    config_path: Path | None,
    from_manifest: Path | None,
    *,
    include_obsidian: bool = False,
) -> tuple[Path, VaultScan]:
    if from_manifest is not None:
        scan = load_scan_from_manifest(from_manifest)
        return Path(scan.vault), scan
    vault_path = _resolve_vault_input(vault, profile, config_path)
    return vault_path, scan_vault(vault_path, include_obsidian=include_obsidian)


def _resolved_profile_key(vault: Path | None, profile: str | None, config_path: Path | None) -> tuple[Path, str | None]:
    resolved = _resolve_vault(vault, profile, config_path)
    return resolved.path, resolved.profile_key or profile


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
    from_manifest: FromManifestOpt = None,
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Optional output path.")] = None,
    fmt: Annotated[str, typer.Option("--format", help="Output format: md or json.")] = "md",
    max_depth: Annotated[int, typer.Option(help="Folder tree depth for markdown output.")] = 2,
    include_obsidian: Annotated[
        bool,
        typer.Option(
            "--include-obsidian/--no-include-obsidian",
            help="Include .obsidian details and plugin metadata when scanning a vault.",
        ),
    ] = False,
) -> None:
    """Create a basic vault snapshot report from a vault scan or manifest."""
    fmt = _check_format(fmt, {"md", "json"})
    vault_path, scan = _scan_from_inputs(
        vault, profile, config_path, from_manifest, include_obsidian=include_obsidian
    )

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


@manifest_app.command("build")
def manifest_build(
    vault: VaultArg = None,
    profile: ProfileOpt = None,
    config_path: ConfigOpt = None,
    out: Annotated[Path, typer.Option("--out", "-o", help="Output manifest directory.")] = Path("exports/scans/latest"),
    scan_id: Annotated[str | None, typer.Option("--scan-id", help="Stable scan identifier for reproducible output paths.")] = None,
    include_obsidian: Annotated[
        bool,
        typer.Option("--include-obsidian/--no-include-obsidian", help="Include .obsidian files in manifests."),
    ] = False,
) -> None:
    """Build reusable JSON manifest files for a vault inventory snapshot."""
    vault_path, profile_key = _resolved_profile_key(vault, profile, config_path)
    outputs = build_manifests(
        vault_path,
        out,
        vault_profile=profile_key,
        scan_id=scan_id,
        include_obsidian=include_obsidian,
    )
    table = Table(title=f"Manifests written: {out}")
    table.add_column("Manifest")
    table.add_column("Path")
    for name, path in outputs.items():
        table.add_row(name, str(path))
    console.print(table)


def _format_bytes(size_bytes: int) -> str:
    units = ["B", "KiB", "MiB", "GiB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size_bytes} B"


def _attachment_records(vault_path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for path in iter_files(vault_path, include_obsidian=False):
        if path.suffix.lower() not in ATTACHMENT_EXTENSIONS:
            continue
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        relative = path.relative_to(vault_path).as_posix()
        records.append(
            {
                "path": relative,
                "name": path.name,
                "folder": Path(relative).parent.as_posix() if Path(relative).parent.as_posix() != "." else "(root)",
                "extension": path.suffix.lower(),
                "size_bytes": size,
            }
        )
    return sorted(records, key=lambda record: str(record["path"]).lower())


def _attachment_records_from_manifest(from_manifest: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for row in read_manifest(from_manifest, "attachments"):
        relative = str(row.get("relative_path") or row.get("path") or "")
        records.append(
            {
                "path": relative,
                "name": str(row.get("file_name") or Path(relative).name),
                "folder": str(row.get("folder") or Path(relative).parent.as_posix() or "(root)"),
                "extension": str(row.get("extension") or Path(relative).suffix.lower()),
                "size_bytes": int(row.get("size_bytes") or 0),
            }
        )
    return sorted(records, key=lambda record: str(record["path"]).lower())


def _print_summary(title: str, rows: list[tuple[str, object]]) -> None:
    table = Table(title=title)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for metric, value in rows:
        table.add_row(metric, str(value))
    console.print(table)


def _print_rows(title: str, rows: list[dict[str, object]], limit: int = 50) -> None:
    if not rows:
        console.print(f"[green]{title}: no records found.[/green]")
        return
    table = Table(title=title)
    for column in rows[0]:
        justify = "right" if column in {"count", "notes", "files", "size", "size_bytes"} else "left"
        table.add_column(column, justify=justify)
    for row in rows[:limit]:
        table.add_row(*(str(value) for value in row.values()))
    console.print(table)
    if len(rows) > limit:
        console.print(f"Showing {limit} of {len(rows)} rows.")


def _suspicious_tag_rows(tag_counts: Counter[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for tag, count in sorted(tag_counts.items()):
        reasons = []
        if len(tag) > 40:
            reasons.append("long")
        if "_" in tag:
            reasons.append("underscore")
        if tag.count("/") > 2:
            reasons.append("deep hierarchy")
        if tag.endswith(("-", "_", "/")) or tag.startswith(("-", "_", "/")):
            reasons.append("edge punctuation")
        if reasons:
            rows.append({"tag": f"#{tag}", "count": count, "reason": ", ".join(reasons)})
    return rows


@audit_app.command("tags")
def audit_tags(
    vault: VaultArg = None,
    profile: ProfileOpt = None,
    config_path: ConfigOpt = None,
    from_manifest: FromManifestOpt = None,
    untagged: Annotated[bool, typer.Option("--untagged", help="List notes without frontmatter tags or inline hashtags.")] = False,
    sus: Annotated[bool, typer.Option("--sus", help="List suspicious tags that may need cleanup.")] = False,
    used_once: Annotated[bool, typer.Option("--used-once", help="List tags used by exactly one note.")] = False,
) -> None:
    """Audit tag coverage, one-off tags, and suspicious tag patterns."""
    if not any([untagged, sus, used_once]):
        untagged = sus = used_once = True

    vault_path, scan = _scan_from_inputs(vault, profile, config_path, from_manifest)
    tag_counts = Counter(tag for note in scan.notes for tag in note.tags)
    untagged_notes = find_untagged_notes(scan)

    _print_summary(
        f"Tag audit: {vault_path.name}",
        [
            ("Notes", len(scan.notes)),
            ("Unique tags", len(tag_counts)),
            ("Tagged notes", len(scan.notes) - len(untagged_notes)),
            ("Untagged notes", len(untagged_notes)),
            ("Tags used once", sum(1 for count in tag_counts.values() if count == 1)),
        ],
    )

    if untagged:
        _print_rows("Untagged notes", note_rows(untagged_notes))
    if used_once:
        rows = [
            {"tag": f"#{tag}", "count": count}
            for tag, count in sorted(tag_counts.items())
            if count == 1
        ]
        _print_rows("Tags used once", rows)
    if sus:
        _print_rows("Suspicious tags", _suspicious_tag_rows(tag_counts))


@audit_app.command("suspicious-tags")
def audit_suspicious_tags(
    vault: VaultArg = None,
    profile: ProfileOpt = None,
    config_path: ConfigOpt = None,
    from_manifest: FromManifestOpt = None,
    out: Annotated[Path, typer.Option("--out", "-o", help="Output path.")] = Path("reports/audit-suspicious-tags.md"),
    fmt: Annotated[str, typer.Option("--format", help="Output format: md, json, or csv.")] = "md",
) -> None:
    """Find suspicious tag patterns that may need normalization."""
    _, scan = _scan_from_inputs(vault, profile, config_path, from_manifest)
    tag_counts = Counter(tag for note in scan.notes for tag in note.tags)
    _write_rows(_suspicious_tag_rows(tag_counts), out, fmt, "Suspicious tags")


@audit_app.command("attachment")
def audit_attachment(
    vault: VaultArg = None,
    profile: ProfileOpt = None,
    config_path: ConfigOpt = None,
    from_manifest: FromManifestOpt = None,
    locations: Annotated[bool, typer.Option("--locations", help="Summarize attachment folders and storage sizes.")] = False,
    sprawl: Annotated[bool, typer.Option("--sprawl", help="List attachments outside common attachment/media folders.")] = False,
    duplicates: Annotated[bool, typer.Option("--duplicates", help="List repeated attachment filenames.")] = False,
) -> None:
    """Audit attachment storage, locations, sprawl, and duplicate names."""
    if not any([locations, sprawl, duplicates]):
        locations = sprawl = duplicates = True

    if from_manifest is not None:
        scan = load_scan_from_manifest(from_manifest)
        vault_path = Path(scan.vault)
        records = _attachment_records_from_manifest(from_manifest)
    else:
        vault_path = _resolve_vault_input(vault, profile, config_path)
        records = _attachment_records(vault_path)
    total_size = sum(int(record["size_bytes"]) for record in records)

    _print_summary(
        f"Attachment audit: {vault_path.name}",
        [
            ("Attachments", len(records)),
            ("Storage", _format_bytes(total_size)),
            ("Folders", len({record["folder"] for record in records})),
        ],
    )

    if locations:
        by_folder: dict[str, dict[str, int]] = defaultdict(lambda: {"files": 0, "size_bytes": 0})
        for record in records:
            folder = str(record["folder"])
            by_folder[folder]["files"] += 1
            by_folder[folder]["size_bytes"] += int(record["size_bytes"])
        rows = [
            {"folder": folder, "files": data["files"], "size": _format_bytes(data["size_bytes"])}
            for folder, data in sorted(by_folder.items(), key=lambda item: (-item[1]["size_bytes"], item[0]))
        ]
        _print_rows("Attachment locations", rows)
    if sprawl:
        common_names = {"attachments", "attachment", "assets", "asset", "media", "images", "image", "files"}
        rows = [
            {"path": str(record["path"]), "size": _format_bytes(int(record["size_bytes"]))}
            for record in records
            if not any(part.lower() in common_names for part in Path(str(record["path"])).parts[:-1])
        ]
        _print_rows("Attachment sprawl", rows)
    if duplicates:
        by_name: dict[str, list[dict[str, object]]] = defaultdict(list)
        for record in records:
            by_name[str(record["name"]).lower()].append(record)
        rows = [
            {"name": name, "count": len(matches), "paths": "; ".join(str(match["path"]) for match in matches)}
            for name, matches in sorted(by_name.items())
            if len(matches) > 1
        ]
        _print_rows("Duplicate attachment names", rows)


@audit_app.command("folders")
def audit_folders(
    vault: VaultArg = None,
    profile: ProfileOpt = None,
    config_path: ConfigOpt = None,
    from_manifest: FromManifestOpt = None,
    drift: Annotated[bool, typer.Option("--drift", help="Summarize sparse top-level folders that may indicate organization drift.")] = False,
    duplicates: Annotated[bool, typer.Option("--duplicates", help="List repeated folder names in different locations.")] = False,
) -> None:
    """Audit folder distribution, organization drift, and duplicate folder names."""
    if not any([drift, duplicates]):
        drift = duplicates = True

    vault_path, scan = _scan_from_inputs(vault, profile, config_path, from_manifest)
    folder_file_counts: Counter[str] = Counter()
    folder_note_counts: Counter[str] = Counter()
    folder_names: dict[str, list[str]] = defaultdict(list)

    for file_path in scan.file_paths:
        parent = Path(file_path).parent.as_posix()
        folder = parent if parent != "." else "(root)"
        folder_file_counts[folder] += 1
        if file_path.endswith(".md"):
            folder_note_counts[folder] += 1
        for ancestor in Path(file_path).parents:
            ancestor_text = ancestor.as_posix()
            if ancestor_text in {".", ""}:
                continue
            folder_names[ancestor.name.lower()].append(ancestor_text)

    _print_summary(
        f"Folder audit: {vault_path.name}",
        [
            ("Files", scan.total_files),
            ("Notes", len(scan.notes)),
            ("Folders with files", len(folder_file_counts)),
            ("Top-level folders", len({Path(path).parts[0] for path in scan.file_paths if len(Path(path).parts) > 1})),
        ],
    )

    if drift:
        rows = []
        top_level: dict[str, dict[str, int]] = defaultdict(lambda: {"files": 0, "notes": 0})
        for folder, count in folder_file_counts.items():
            top = folder.split("/", 1)[0]
            top_level[top]["files"] += count
            top_level[top]["notes"] += folder_note_counts[folder]
        for folder, data in sorted(top_level.items(), key=lambda item: (item[1]["notes"], item[1]["files"], item[0])):
            reason = "few notes" if data["notes"] <= 1 else "file-heavy" if data["files"] > data["notes"] * 5 else "review"
            rows.append({"folder": folder, "notes": data["notes"], "files": data["files"], "reason": reason})
        _print_rows("Folder drift candidates", rows)
    if duplicates:
        rows = [
            {"name": name, "count": len(set(paths)), "paths": "; ".join(sorted(set(paths)))}
            for name, paths in sorted(folder_names.items())
            if len(set(paths)) > 1
        ]
        _print_rows("Duplicate folder names", rows)


@audit_app.command("no-tags")
def audit_no_tags(
    vault: VaultArg = None,
    profile: ProfileOpt = None,
    config_path: ConfigOpt = None,
    from_manifest: FromManifestOpt = None,
    out: Annotated[Path, typer.Option("--out", "-o", help="Output path.")] = Path("reports/audit-no-tags.md"),
    fmt: Annotated[str, typer.Option("--format", help="Output format: md, json, or csv.")] = "md",
    under: Annotated[str | None, typer.Option("--under", help="Optional vault-relative folder prefix.")] = None,
) -> None:
    """Find notes that have neither frontmatter tags nor inline hashtags."""
    _, scan = _scan_from_inputs(vault, profile, config_path, from_manifest)
    rows = note_rows(find_untagged_notes(scan, under=under))
    _write_rows(rows, out, fmt, "Notes without tags")


@audit_app.command("broken-links")
def audit_broken_links(
    vault: VaultArg = None,
    profile: ProfileOpt = None,
    config_path: ConfigOpt = None,
    from_manifest: FromManifestOpt = None,
    out: Annotated[Path, typer.Option("--out", "-o", help="Output path.")] = Path("reports/audit-broken-links.md"),
    fmt: Annotated[str, typer.Option("--format", help="Output format: md, json, or csv.")] = "md",
) -> None:
    """Find wikilinks that do not resolve to a scanned Markdown note."""
    _, scan = _scan_from_inputs(vault, profile, config_path, from_manifest)
    _write_rows(find_broken_wikilinks(scan), out, fmt, "Broken wikilinks")


@audit_app.command("orphan-attachments")
def audit_orphan_attachments(
    vault: VaultArg = None,
    profile: ProfileOpt = None,
    config_path: ConfigOpt = None,
    from_manifest: FromManifestOpt = None,
    out: Annotated[Path, typer.Option("--out", "-o", help="Output path.")] = Path("reports/audit-orphan-attachments.md"),
    fmt: Annotated[str, typer.Option("--format", help="Output format: md, json, or csv.")] = "md",
) -> None:
    """Find common attachment files that are not referenced by embeds or markdown links."""
    if from_manifest is not None:
        scan = load_scan_from_manifest(from_manifest)
        paths = orphan_attachments_from_manifest(from_manifest, scan)
    else:
        vault_path = _resolve_vault_input(vault, profile, config_path)
        scan = scan_vault(vault_path)
        paths = find_orphan_attachments(vault_path, scan)
    rows = [{"path": path} for path in paths]
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
