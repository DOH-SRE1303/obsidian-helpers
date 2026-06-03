from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vault_tools.config import ExtensionRequirements


@dataclass(frozen=True)
class VaultExtensions:
    core_plugins: list[str] = field(default_factory=list)
    community_plugins: list[str] = field(default_factory=list)
    obsidian_dir: Path | None = None

    def has_core(self, plugin_id: str) -> bool:
        return plugin_id in self.core_plugins

    def has_community(self, plugin_id: str) -> bool:
        return plugin_id in self.community_plugins


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def enabled_plugins(obsidian_dir: Path) -> tuple[list[str], list[str]]:
    core_raw = read_json(obsidian_dir / "core-plugins.json")
    community_raw = read_json(obsidian_dir / "community-plugins.json")

    core: list[str] = []
    community: list[str] = []

    if isinstance(core_raw, list):
        core = [str(item) for item in core_raw]
    elif isinstance(core_raw, dict):
        core = [str(key) for key, enabled in core_raw.items() if enabled]

    if isinstance(community_raw, list):
        community = [str(item) for item in community_raw]

    return sorted(core), sorted(community)


def inspect_extensions(vault_path: Path) -> VaultExtensions:
    obsidian_dir = vault_path / ".obsidian"
    if not obsidian_dir.exists():
        return VaultExtensions(obsidian_dir=obsidian_dir)
    core_plugins, community_plugins = enabled_plugins(obsidian_dir)
    return VaultExtensions(
        core_plugins=core_plugins,
        community_plugins=community_plugins,
        obsidian_dir=obsidian_dir,
    )


def missing_extensions(vault_path: Path, required: ExtensionRequirements) -> list[str]:
    extensions = inspect_extensions(vault_path)
    missing: list[str] = []
    for plugin_id in required.core:
        if not extensions.has_core(plugin_id):
            missing.append(f"core:{plugin_id}")
    for plugin_id in required.community:
        if not extensions.has_community(plugin_id):
            missing.append(f"community:{plugin_id}")
    return missing


def merge_requirements(*requirements: ExtensionRequirements) -> ExtensionRequirements:
    core: set[str] = set()
    community: set[str] = set()
    for requirement in requirements:
        core.update(requirement.core)
        community.update(requirement.community)
    return ExtensionRequirements(core=sorted(core), community=sorted(community))
