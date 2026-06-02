from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

CONFIG_ENV_VAR = "VAULT_TOOLS_CONFIG"
CONFIG_FILENAMES = ("vault-tools.yml", "vault-tools.yaml", ".vault-tools.yml", ".vault-tools.yaml")


@dataclass(frozen=True)
class VaultProfile:
    name: str
    path: Path
    role: str = "vault"
    description: str = ""


@dataclass(frozen=True)
class VaultToolsConfig:
    path: Path
    default_vault: str | None
    vaults: dict[str, VaultProfile]
    raw: dict[str, Any]


def find_config_path(start: Path | None = None) -> Path | None:
    """Find a vault-tools config file.

    Resolution order:
    1. VAULT_TOOLS_CONFIG environment variable
    2. current directory and parents, looking for vault-tools.yml/yaml variants
    """
    env_path = os.getenv(CONFIG_ENV_VAR)
    if env_path:
        return Path(os.path.expanduser(os.path.expandvars(env_path))).resolve()

    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent

    for directory in (current, *current.parents):
        for filename in CONFIG_FILENAMES:
            candidate = directory / filename
            if candidate.exists():
                return candidate.resolve()
    return None


def default_config_path(start: Path | None = None) -> Path:
    """Return where a new local config should be written by default."""
    base = (start or Path.cwd()).resolve()
    if base.is_file():
        base = base.parent
    return base / "vault-tools.yml"


def _expand_profile_path(raw_path: str, config_path: Path) -> Path:
    expanded = Path(os.path.expanduser(os.path.expandvars(raw_path)))
    if not expanded.is_absolute():
        expanded = config_path.parent / expanded
    return expanded.resolve()


def load_config(config_path: Path | None = None) -> VaultToolsConfig:
    found = config_path.resolve() if config_path else find_config_path()
    if found is None:
        return VaultToolsConfig(path=default_config_path(), default_vault=None, vaults={}, raw={})
    if not found.exists():
        return VaultToolsConfig(path=found, default_vault=None, vaults={}, raw={})

    data = yaml.safe_load(found.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        data = {}

    vaults_raw = data.get("vaults") or {}
    vaults: dict[str, VaultProfile] = {}
    if isinstance(vaults_raw, dict):
        for name, value in vaults_raw.items():
            if isinstance(value, str):
                raw_path = value
                role = "vault"
                description = ""
            elif isinstance(value, dict):
                raw_path = str(value.get("path", ""))
                role = str(value.get("role", "vault"))
                description = str(value.get("description", ""))
            else:
                continue
            if raw_path:
                vaults[str(name)] = VaultProfile(
                    name=str(name),
                    path=_expand_profile_path(raw_path, found),
                    role=role,
                    description=description,
                )

    default_vault = data.get("default_vault")
    if default_vault is not None:
        default_vault = str(default_vault)

    return VaultToolsConfig(
        path=found,
        default_vault=default_vault,
        vaults=vaults,
        raw=data,
    )


def save_config(data: dict[str, Any], config_path: Path | None = None) -> Path:
    path = config_path or find_config_path() or default_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path.resolve()


def empty_config() -> dict[str, Any]:
    return {"default_vault": None, "vaults": {}}


def example_config() -> dict[str, Any]:
    return {
        "default_vault": "new",
        "vaults": {
            "old": {
                "path": "../vault-old",
                "role": "source",
                "description": "Read-only legacy vault snapshot used as migration evidence.",
            },
            "new": {
                "path": "../vault-new",
                "role": "target",
                "description": "Version-controlled working vault.",
            },
        },
    }


def set_vault_profile(
    name: str,
    path: Path,
    *,
    role: str = "vault",
    description: str = "",
    make_default: bool = False,
    config_path: Path | None = None,
) -> Path:
    config = load_config(config_path)
    data = config.raw if config.raw else empty_config()
    data.setdefault("vaults", {})
    data["vaults"][name] = {
        "path": str(path),
        "role": role,
        "description": description,
    }
    if make_default or not data.get("default_vault"):
        data["default_vault"] = name
    return save_config(data, config.path if config.path else config_path)


def remove_vault_profile(name: str, config_path: Path | None = None) -> Path:
    config = load_config(config_path)
    data = config.raw if config.raw else empty_config()
    vaults = data.setdefault("vaults", {})
    vaults.pop(name, None)
    if data.get("default_vault") == name:
        data["default_vault"] = next(iter(vaults), None)
    return save_config(data, config.path if config.path else config_path)


def set_default_vault(name: str, config_path: Path | None = None) -> Path:
    config = load_config(config_path)
    if name not in config.vaults:
        raise KeyError(f"Unknown vault profile: {name}")
    data = config.raw if config.raw else empty_config()
    data["default_vault"] = name
    return save_config(data, config.path if config.path else config_path)
