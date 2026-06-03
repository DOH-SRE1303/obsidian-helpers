from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import yaml

from vault_tools.extensions import enabled_plugins, read_json

CODE_FENCE_RE = re.compile(r"```.*?```", re.S)
INLINE_CODE_RE = re.compile(r"`[^`]*`")
URL_RE = re.compile(r"https?://\S+")
INLINE_TAG_RE = re.compile(r"(?<![\w/])#(?!\s)([A-Za-z0-9/_-]{1,80})")
WIKILINK_RE = re.compile(r"!?(?:\[\[)([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?(?:\]\])")
EMBED_RE = re.compile(r"!\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]")
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")

DEFAULT_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
}
ATTACHMENT_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".csv",
    ".tsv",
    ".zip",
}


@dataclass(frozen=True)
class NoteRecord:
    path: str
    title: str
    extension: str
    size_bytes: int
    modified_time: str
    word_count: int
    has_frontmatter: bool
    frontmatter_keys: list[str]
    tags: list[str]
    wikilinks: list[str]
    embeds: list[str]
    markdown_links: list[str]
    headings: list[str]


@dataclass(frozen=True)
class VaultScan:
    vault: str
    scanned_at: str
    notes: list[NoteRecord]
    file_type_counts: dict[str, int]
    total_files: int
    file_paths: list[str]
    templates_folder: str | None
    core_plugins: list[str]
    community_plugins: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "vault": self.vault,
            "scanned_at": self.scanned_at,
            "notes": [asdict(n) for n in self.notes],
            "file_type_counts": self.file_type_counts,
            "total_files": self.total_files,
            "file_paths": self.file_paths,
            "templates_folder": self.templates_folder,
            "core_plugins": self.core_plugins,
            "community_plugins": self.community_plugins,
        }


def resolve_vault(path: Path) -> Path:
    path = Path(os.path.expanduser(os.path.expandvars(str(path)))).resolve()
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError(f"Vault path not found or not a directory: {path}")
    return path


def detect_templates_folder(vault: Path) -> str | None:
    app_json = read_json(vault / ".obsidian" / "app.json") or {}
    if isinstance(app_json, dict):
        template_folder = (
            (app_json.get("userData", {}) or {}).get("templatesFolder")
            or (app_json.get("app", {}) or {}).get("templatesFolder")
        )
        if template_folder:
            return str(template_folder)

    templater_data = read_json(vault / ".obsidian" / "plugins" / "templater-obsidian" / "data.json")
    if isinstance(templater_data, dict) and templater_data.get("templates_folder"):
        return str(templater_data["templates_folder"])

    core_template_data = read_json(vault / ".obsidian" / "plugins" / "obsidian-templates" / "data.json")
    if isinstance(core_template_data, dict) and core_template_data.get("templateFolder"):
        return str(core_template_data["templateFolder"])

    return None


def iter_files(vault: Path, include_obsidian: bool = False) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(vault, topdown=True):
        dirnames[:] = [
            dirname
            for dirname in dirnames
            if dirname not in DEFAULT_SKIP_DIRS
            and (not dirname.startswith(".") or (include_obsidian and dirname == ".obsidian"))
        ]
        for filename in filenames:
            if filename.startswith("~$"):
                continue
            yield Path(dirpath) / filename


def folder_tree(vault: Path, max_depth: int = 2, include_obsidian: bool = False) -> str:
    lines = [f"- {vault.name}/"]

    def walk(directory: Path, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = list(directory.iterdir())
        except PermissionError:
            return

        entries = [
            entry
            for entry in entries
            if not entry.name.startswith(".") or (include_obsidian and entry.name == ".obsidian")
        ]
        entries.sort(key=lambda entry: (entry.is_file(), entry.name.lower()))

        for entry in entries:
            indent = "  " * depth + "- "
            suffix = "/" if entry.is_dir() else ""
            lines.append(f"{indent}{entry.name}{suffix}")
            if entry.is_dir():
                walk(entry, depth + 1)

    walk(vault, 1)
    return "\n".join(lines)


def frontmatter_block(text: str) -> str | None:
    if not text.startswith("---"):
        return None

    lines = text.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return None

    for index in range(1, min(len(lines), 1000)):
        if lines[index].strip() == "---":
            return "\n".join(lines[1:index])

    return None


def parse_frontmatter(text: str) -> dict[str, Any]:
    block = frontmatter_block(text)
    if not block:
        return {}

    try:
        data = yaml.safe_load(block) or {}
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


def _flatten(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        if "," in value:
            return [item.strip() for item in value.split(",") if item.strip()]
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        out: list[str] = []
        for item in value:
            out.extend(_flatten(item))
        return out
    if isinstance(value, dict):
        out: list[str] = []
        for item in value.values():
            out.extend(_flatten(item))
        return out
    return []


def _looks_like_hex(value: str) -> bool:
    value = value.lstrip("#").lower()
    return len(value) in {3, 4, 6, 8} and all(char in "0123456789abcdef" for char in value)


def tags_from_frontmatter(frontmatter: dict[str, Any]) -> list[str]:
    tag_value = None
    for key, value in frontmatter.items():
        if key.lower() == "tags":
            tag_value = value
            break

    tags: list[str] = []
    for tag in _flatten(tag_value):
        tag = tag.strip().lstrip("#").lower()
        if tag:
            tags.append(tag)
    return sorted(set(tags))


def inline_tags(text: str) -> list[str]:
    cleaned = CODE_FENCE_RE.sub("", text)
    cleaned = INLINE_CODE_RE.sub("", cleaned)
    cleaned = URL_RE.sub("", cleaned)

    tags: list[str] = []
    for match in INLINE_TAG_RE.finditer(cleaned):
        tag = match.group(1).lower()
        if not _looks_like_hex(tag):
            tags.append(tag)
    return sorted(set(tags))


def extract_wikilinks(text: str) -> list[str]:
    return sorted({match.group(1).strip() for match in WIKILINK_RE.finditer(text) if match.group(1).strip()})


def extract_embeds(text: str) -> list[str]:
    return sorted({match.group(1).strip() for match in EMBED_RE.finditer(text) if match.group(1).strip()})


def extract_markdown_links(text: str) -> list[str]:
    return sorted({match.group(1).strip() for match in MARKDOWN_LINK_RE.finditer(text) if match.group(1).strip()})


def extract_headings(text: str) -> list[str]:
    headings = []
    for line in text.splitlines():
        if line.startswith("#"):
            stripped = line.lstrip("#").strip()
            if stripped:
                headings.append(stripped)
    return headings


def scan_note(path: Path, vault: Path) -> NoteRecord | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        stat = path.stat()
    except Exception:
        return None

    frontmatter = parse_frontmatter(text)
    tags = sorted(set(tags_from_frontmatter(frontmatter)) | set(inline_tags(text)))

    relative_path = path.relative_to(vault).as_posix()
    return NoteRecord(
        path=relative_path,
        title=path.stem,
        extension=path.suffix.lower(),
        size_bytes=stat.st_size,
        modified_time=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        word_count=len(re.findall(r"\b\w+\b", text)),
        has_frontmatter=bool(frontmatter),
        frontmatter_keys=sorted(frontmatter.keys()),
        tags=tags,
        wikilinks=extract_wikilinks(text),
        embeds=extract_embeds(text),
        markdown_links=extract_markdown_links(text),
        headings=extract_headings(text),
    )


def scan_vault(vault: Path, include_obsidian: bool = False) -> VaultScan:
    vault = resolve_vault(vault)
    file_type_counts: Counter[str] = Counter()
    notes: list[NoteRecord] = []

    file_paths: list[str] = []

    for path in iter_files(vault, include_obsidian=include_obsidian):
        relative_path = path.relative_to(vault).as_posix()
        file_paths.append(relative_path)
        extension = path.suffix.lower() or "(no extension)"
        file_type_counts[extension] += 1
        if extension == ".md":
            note = scan_note(path, vault)
            if note:
                notes.append(note)

    core_plugins: list[str] = []
    community_plugins: list[str] = []
    if include_obsidian and (vault / ".obsidian").exists():
        core_plugins, community_plugins = enabled_plugins(vault / ".obsidian")

    return VaultScan(
        vault=str(vault),
        scanned_at=datetime.now().isoformat(timespec="seconds"),
        notes=notes,
        file_type_counts=dict(file_type_counts.most_common()),
        total_files=sum(file_type_counts.values()),
        file_paths=sorted(file_paths),
        templates_folder=detect_templates_folder(vault),
        core_plugins=core_plugins,
        community_plugins=community_plugins,
    )


def note_lookup(scan: VaultScan) -> dict[str, set[str]]:
    """Build a lookup that approximates Obsidian wikilink/file resolution."""
    lookup: dict[str, set[str]] = {}

    for note in scan.notes:
        path = Path(note.path)
        candidates = {
            note.title,
            path.name,
            path.as_posix(),
            path.with_suffix("").as_posix(),
        }
        for candidate in candidates:
            lookup.setdefault(candidate, set()).add(note.path)

    for file_path in scan.file_paths:
        path = Path(file_path)
        candidates = {
            path.name,
            path.as_posix(),
            path.with_suffix("").as_posix(),
        }
        for candidate in candidates:
            lookup.setdefault(candidate, set()).add(file_path)

    return lookup


def find_broken_wikilinks(scan: VaultScan) -> list[dict[str, str]]:
    lookup = note_lookup(scan)
    broken: list[dict[str, str]] = []

    for note in scan.notes:
        for link in note.wikilinks:
            if link not in lookup:
                broken.append({"source": note.path, "link": link})

    return broken


def find_untagged_notes(scan: VaultScan, under: str | None = None) -> list[NoteRecord]:
    notes = [note for note in scan.notes if not note.tags]
    if under:
        prefix = under.strip("/\\")
        notes = [note for note in notes if note.path.startswith(prefix)]
    return notes


def find_orphan_attachments(vault: Path, scan: VaultScan) -> list[str]:
    vault = resolve_vault(vault)
    referenced = {embed for note in scan.notes for embed in note.embeds}
    referenced |= {
        link
        for note in scan.notes
        for link in note.markdown_links
        if not link.startswith(("http://", "https://", "mailto:"))
    }

    referenced_names = {Path(item).name for item in referenced}
    orphans: list[str] = []

    for path in iter_files(vault, include_obsidian=False):
        if path.suffix.lower() not in ATTACHMENT_EXTENSIONS:
            continue
        relative = path.relative_to(vault).as_posix()
        if relative not in referenced and path.name not in referenced_names:
            orphans.append(relative)

    return sorted(orphans)
