from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from vault_tools.scanner import NoteRecord, VaultScan, folder_tree


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str) -> Path:
    ensure_parent(path)
    path.write_text(text, encoding="utf-8")
    return path


def write_json(path: Path, data: Any) -> Path:
    ensure_parent(path)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> Path:
    ensure_parent(path)
    rows = list(rows)
    with path.open("w", newline="", encoding="utf-8") as file:
        if not rows:
            file.write("")
            return path
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    return path


def markdown_table(rows: list[dict[str, Any]], columns: list[str] | None = None) -> str:
    if not rows:
        return "_No records found._\n"

    columns = columns or list(rows[0].keys())
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join(["---"] * len(columns)) + " |"
    body = []
    for row in rows:
        values = [str(row.get(column, "")).replace("\n", " ") for column in columns]
        body.append("| " + " | ".join(values) + " |")
    return "\n".join([header, separator, *body]) + "\n"


def render_info_markdown(scan: VaultScan, vault_path: Path, max_depth: int, include_obsidian: bool) -> str:
    tag_counts = Counter(tag for note in scan.notes for tag in note.tags)
    frontmatter_counts = Counter(key for note in scan.notes for key in note.frontmatter_keys)

    lines: list[str] = []
    lines.append("# Vault Snapshot\n")
    lines.append(f"- Vault: `{scan.vault}`")
    lines.append(f"- Scanned at: `{scan.scanned_at}`")
    lines.append(f"- Notes (.md): {len(scan.notes)}")
    lines.append(f"- Total files: {scan.total_files}")
    lines.append(f"- Notes with tags: {sum(1 for note in scan.notes if note.tags)}")
    lines.append(f"- Notes without tags: {sum(1 for note in scan.notes if not note.tags)}")
    lines.append("\n## Folder tree\n")
    lines.append("```text")
    lines.append(folder_tree(vault_path, max_depth=max_depth, include_obsidian=include_obsidian))
    lines.append("```")

    lines.append("\n## File types\n")
    for extension, count in scan.file_type_counts.items():
        lines.append(f"- **{extension}**: {count}")

    if frontmatter_counts:
        lines.append("\n## Frontmatter fields\n")
        for key, count in frontmatter_counts.most_common(25):
            lines.append(f"- `{key}`: {count}")

    if tag_counts:
        lines.append("\n## Tags\n")
        for tag, count in tag_counts.most_common(50):
            lines.append(f"- `#{tag}`: {count}")

    if scan.templates_folder:
        lines.append("\n## Templates folder\n")
        lines.append(f"- `{scan.templates_folder}`")

    if include_obsidian:
        lines.append("\n## Enabled plugins\n")
        if scan.core_plugins:
            lines.append("- **Core**: " + ", ".join(scan.core_plugins))
        if scan.community_plugins:
            lines.append("- **Community**: " + ", ".join(scan.community_plugins))
        if not scan.core_plugins and not scan.community_plugins:
            lines.append("_No plugin info found._")

    return "\n".join(lines) + "\n"


def note_rows(notes: list[NoteRecord]) -> list[dict[str, Any]]:
    return [
        {
            "path": note.path,
            "word_count": note.word_count,
            "modified_time": note.modified_time,
            "frontmatter": "yes" if note.has_frontmatter else "no",
            "links": len(note.wikilinks),
            "attachments": len(note.embeds),
        }
        for note in notes
    ]
