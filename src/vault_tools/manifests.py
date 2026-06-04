from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from vault_tools.reports import write_json
from vault_tools.scanner import (
    ATTACHMENT_EXTENSIONS,
    NoteRecord,
    VaultScan,
    iter_files,
    parse_frontmatter,
    resolve_vault,
    scan_vault,
)

MANIFEST_FILES = {
    "vault": "vault_manifest.json",
    "notes": "notes_manifest.json",
    "links": "links_manifest.json",
    "tags": "tags_manifest.json",
    "frontmatter": "frontmatter_manifest.json",
    "attachments": "attachments_manifest.json",
    "classifications": "classifications.json",
}


def content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _base_row(
    *,
    scan_id: str,
    vault_profile: str | None,
    vault_path: Path,
    scanned_at: str,
    relative_path: str,
    size_bytes: int,
    modified_time: str,
    file_hash: str,
) -> dict[str, Any]:
    return {
        "scan_id": scan_id,
        "vault_profile": vault_profile,
        "vault_path": str(vault_path),
        "scanned_at": scanned_at,
        "relative_path": relative_path,
        "size_bytes": size_bytes,
        "modified_time": modified_time,
        "content_hash": file_hash,
    }


def _file_row(
    path: Path,
    vault_path: Path,
    scan_id: str,
    vault_profile: str | None,
    scanned_at: str,
) -> dict[str, Any]:
    stat = path.stat()
    relative_path = path.relative_to(vault_path).as_posix()
    row = _base_row(
        scan_id=scan_id,
        vault_profile=vault_profile,
        vault_path=vault_path,
        scanned_at=scanned_at,
        relative_path=relative_path,
        size_bytes=stat.st_size,
        modified_time=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        file_hash=content_hash(path),
    )
    row.update(
        {
            "extension": path.suffix.lower() or "(no extension)",
            "file_name": path.name,
            "folder": Path(relative_path).parent.as_posix()
            if Path(relative_path).parent.as_posix() != "."
            else "(root)",
        }
    )
    return row


def _manifest_by_path(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row["relative_path"]): row for row in rows}


def build_manifests(
    vault_path: Path,
    out_dir: Path,
    *,
    vault_profile: str | None = None,
    scan_id: str | None = None,
    include_obsidian: bool = False,
) -> dict[str, Path]:
    vault_path = resolve_vault(vault_path)
    scanned_at = datetime.now().isoformat(timespec="seconds")
    scan_id = scan_id or datetime.now().strftime("%Y%m%dT%H%M%S")

    scan = scan_vault(vault_path, include_obsidian=include_obsidian)
    vault_rows = [
        _file_row(path, vault_path, scan_id, vault_profile, scanned_at)
        for path in iter_files(vault_path, include_obsidian=include_obsidian)
    ]
    file_rows = _manifest_by_path(vault_rows)

    note_rows: list[dict[str, Any]] = []
    link_rows: list[dict[str, Any]] = []
    tag_rows: list[dict[str, Any]] = []
    frontmatter_rows: list[dict[str, Any]] = []
    attachment_rows: list[dict[str, Any]] = []
    classification_rows: list[dict[str, Any]] = []

    for note in scan.notes:
        file_row = file_rows[note.path]
        note_row = {**file_row, **asdict(note), "relative_path": note.path}
        note_rows.append(note_row)

        for kind, values in (
            ("wikilink", note.wikilinks),
            ("embed", note.embeds),
            ("markdown", note.markdown_links),
        ):
            for target in values:
                link_rows.append(
                    {**file_row, "source_path": note.path, "link_type": kind, "target": target}
                )

        for tag in note.tags:
            tag_rows.append({**file_row, "note_path": note.path, "tag": tag})

        note_path = vault_path / note.path
        try:
            frontmatter = parse_frontmatter(note_path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            frontmatter = {}
        for key, value in sorted(frontmatter.items()):
            frontmatter_rows.append(
                {**file_row, "note_path": note.path, "field": str(key), "value": value}
            )

        classification_rows.append(
            {
                **file_row,
                "path": note.path,
                "note_type_guess": None,
                "domain_guess": None,
                "project_guess": None,
                "confidence": 0.0,
                "reasons": [],
                "suggested_tags": [],
                "suggested_folder": None,
                "needs_review": True,
                "review_status": "unreviewed",
            }
        )

    for row in vault_rows:
        if str(row["extension"]) in ATTACHMENT_EXTENSIONS:
            attachment_rows.append(row)

    outputs = {
        "vault": write_json(out_dir / MANIFEST_FILES["vault"], vault_rows),
        "notes": write_json(out_dir / MANIFEST_FILES["notes"], note_rows),
        "links": write_json(out_dir / MANIFEST_FILES["links"], link_rows),
        "tags": write_json(out_dir / MANIFEST_FILES["tags"], tag_rows),
        "frontmatter": write_json(out_dir / MANIFEST_FILES["frontmatter"], frontmatter_rows),
        "attachments": write_json(out_dir / MANIFEST_FILES["attachments"], attachment_rows),
        "classifications": write_json(out_dir / MANIFEST_FILES["classifications"], classification_rows),
    }
    return outputs


def read_manifest(path: Path, manifest_name: str) -> list[dict[str, Any]]:
    import json

    file_path = path / MANIFEST_FILES[manifest_name]
    if not file_path.exists():
        raise FileNotFoundError(f"Missing manifest file: {file_path}")
    data = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected a list in {file_path}")
    return data


def load_scan_from_manifest(path: Path) -> VaultScan:
    vault_rows = read_manifest(path, "vault")
    note_rows = read_manifest(path, "notes")
    file_type_counts = Counter(str(row.get("extension") or "(no extension)") for row in vault_rows)
    notes = [
        NoteRecord(
            path=str(row.get("path") or row.get("relative_path")),
            title=str(row.get("title") or Path(str(row.get("relative_path"))).stem),
            extension=str(row.get("extension") or ".md"),
            size_bytes=int(row.get("size_bytes") or 0),
            modified_time=str(row.get("modified_time") or ""),
            word_count=int(row.get("word_count") or 0),
            has_frontmatter=bool(row.get("has_frontmatter")),
            frontmatter_keys=list(row.get("frontmatter_keys") or []),
            tags=list(row.get("tags") or []),
            wikilinks=list(row.get("wikilinks") or []),
            embeds=list(row.get("embeds") or []),
            markdown_links=list(row.get("markdown_links") or []),
            headings=list(row.get("headings") or []),
        )
        for row in note_rows
    ]
    first_row = vault_rows[0] if vault_rows else (note_rows[0] if note_rows else {})
    return VaultScan(
        vault=str(first_row.get("vault_path") or path),
        scanned_at=str(first_row.get("scanned_at") or ""),
        notes=notes,
        file_type_counts=dict(file_type_counts.most_common()),
        total_files=len(vault_rows),
        file_paths=sorted(str(row.get("relative_path")) for row in vault_rows),
        templates_folder=None,
        core_plugins=[],
        community_plugins=[],
    )


def orphan_attachments_from_manifest(path: Path, scan: VaultScan) -> list[str]:
    attachment_rows = read_manifest(path, "attachments")
    referenced = {embed for note in scan.notes for embed in note.embeds}
    referenced |= {
        link
        for note in scan.notes
        for link in note.markdown_links
        if not link.startswith(("http://", "https://", "mailto:"))
    }
    referenced_names = {Path(item).name for item in referenced}
    orphans = []
    for row in attachment_rows:
        relative_path = str(row.get("relative_path"))
        if relative_path not in referenced and Path(relative_path).name not in referenced_names:
            orphans.append(relative_path)
    return sorted(orphans)
