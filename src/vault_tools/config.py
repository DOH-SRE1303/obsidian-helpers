from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CONFIG_ENV_VAR = "VAULT_TOOLS_CONFIG"
CONFIG_FILENAMES = ("vault-tools.yml", "vault-tools.yaml", ".vault-tools.yml", ".vault-tools.yaml")


@dataclass(frozen=True)
class ExtensionRequirements:
    core: list[str] = field(default_factory=list)
    community: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        return {
            "core": sorted(set(self.core)),
            "community": sorted(set(self.community)),
        }


@dataclass(frozen=True)
class VaultProfile:
    key: str
    path: Path
    role: str = "vault"
    description: str = ""
    display_name: str | None = None
    nicknames: list[str] = field(default_factory=list)
    required_extensions: ExtensionRequirements = field(default_factory=ExtensionRequirements)

    @property
    def name(self) -> str:
        """Backward-compatible profile identifier."""
        return self.key

    def selectors(self) -> set[str]:
        values = {self.key, *self.nicknames}
        if self.display_name:
            values.add(self.display_name)
        return {value for value in values if value}


@dataclass(frozen=True)
class VaultToolsConfig:
    path: Path
    current_vault: str | None
    vaults: dict[str, VaultProfile]
    raw: dict[str, Any]

    @property
    def default_vault(self) -> str | None:
        """Backward-compatible alias for older callers and configs."""
        return self.current_vault


def user_config_path() -> Path:
    """Return the per-user fallback config path for this platform."""
    if sys.platform.startswith("win"):
        base = os.getenv("APPDATA")
        if base:
            return Path(base) / "vault-tools" / "config.yml"
    return Path.home() / ".config" / "vault-tools" / "config.yml"


def find_local_config_path(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent

    for directory in (current, *current.parents):
        for filename in CONFIG_FILENAMES:
            candidate = directory / filename
            if candidate.exists():
                return candidate.resolve()
    return None


def find_config_path(start: Path | None = None) -> Path | None:
    """Find a vault-tools config file.

    Resolution order:
    1. VAULT_TOOLS_CONFIG environment variable
    2. current directory and parents, looking for vault-tools.yml/yaml variants
    3. per-user fallback config
    """
    env_path = os.getenv(CONFIG_ENV_VAR)
    if env_path:
        return Path(os.path.expanduser(os.path.expandvars(env_path))).resolve()

    local = find_local_config_path(start)
    if local:
        return local

    user_path = user_config_path()
    if user_path.exists():
        return user_path.resolve()
    return None


def default_config_path(start: Path | None = None, *, user: bool = False) -> Path:
    """Return where a new config should be written by default."""
    if user:
        return user_config_path()
    base = (start or Path.cwd()).resolve()
    if base.is_file():
        base = base.parent
    return base / "vault-tools.yml"


def _expand_profile_path(raw_path: str, config_path: Path) -> Path:
    expanded = Path(os.path.expanduser(os.path.expandvars(raw_path)))
    if not expanded.is_absolute():
        expanded = config_path.parent / expanded
    return expanded.resolve()


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    return []


def parse_extension_requirements(value: Any) -> ExtensionRequirements:
    if not isinstance(value, dict):
        return ExtensionRequirements()
    return ExtensionRequirements(
        core=sorted(set(_string_list(value.get("core")))),
        community=sorted(set(_string_list(value.get("community")))),
    )


def load_config(config_path: Path | None = None) -> VaultToolsConfig:
    found = config_path.resolve() if config_path else find_config_path()
    if found is None:
        return VaultToolsConfig(path=default_config_path(user=True), current_vault=None, vaults={}, raw={})
    if not found.exists():
        return VaultToolsConfig(path=found, current_vault=None, vaults={}, raw={})

    data = yaml.safe_load(found.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        data = {}

    vaults_raw = data.get("vaults") or {}
    vaults: dict[str, VaultProfile] = {}
    if isinstance(vaults_raw, dict):
        for key, value in vaults_raw.items():
            display_name: str | None = None
            nicknames: list[str] = []
            required_extensions = ExtensionRequirements()
            if isinstance(value, str):
                raw_path = value
                role = "vault"
                description = ""
            elif isinstance(value, dict):
                raw_path = str(value.get("path", ""))
                role = str(value.get("role", "vault"))
                description = str(value.get("description", ""))
                display_name = value.get("name") or value.get("display_name")
                display_name = str(display_name) if display_name else None
                nicknames = _string_list(value.get("nicknames"))
                nickname = value.get("nickname")
                if nickname:
                    nicknames.extend(_string_list(nickname))
                required_extensions = parse_extension_requirements(value.get("required_extensions"))
            else:
                continue
            if raw_path:
                vaults[str(key)] = VaultProfile(
                    key=str(key),
                    path=_expand_profile_path(raw_path, found),
                    role=role,
                    description=description,
                    display_name=display_name,
                    nicknames=sorted(set(nicknames)),
                    required_extensions=required_extensions,
                )

    current_vault = data.get("current_vault", data.get("default_vault"))
    if current_vault is not None:
        current_vault = str(current_vault)

    return VaultToolsConfig(path=found, current_vault=current_vault, vaults=vaults, raw=data)


def _canonical_config_data(config: VaultToolsConfig) -> dict[str, Any]:
    data: dict[str, Any] = {"current_vault": config.current_vault, "vaults": {}}
    for key, profile in sorted(config.vaults.items()):
        profile_data: dict[str, Any] = {"path": str(profile.path), "role": profile.role}
        if profile.display_name:
            profile_data["name"] = profile.display_name
        if profile.nicknames:
            profile_data["nicknames"] = profile.nicknames
        if profile.description:
            profile_data["description"] = profile.description
        if profile.required_extensions.core or profile.required_extensions.community:
            profile_data["required_extensions"] = profile.required_extensions.to_dict()
        data["vaults"][key] = profile_data
    return data


def save_config(data: dict[str, Any], config_path: Path | None = None) -> Path:
    path = config_path or find_config_path() or default_config_path(user=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path.resolve()


def normalize_config(config_path: Path | None = None) -> Path:
    config = load_config(config_path)
    return save_config(_canonical_config_data(config), config.path)


def empty_config() -> dict[str, Any]:
    return {"current_vault": None, "vaults": {}}


def example_config() -> dict[str, Any]:
    return {
        "current_vault": "new",
        "vaults": {
            "old": {
                "path": "../vault-old",
                "role": "source",
                "nicknames": ["legacy"],
                "description": "Read-only legacy vault snapshot used as migration evidence.",
            },
            "new": {
                "path": "../vault-new",
                "role": "target",
                "name": "Curated Vault",
                "nicknames": ["main"],
                "description": "Version-controlled working vault.",
                "required_extensions": {
                    "core": ["templates"],
                    "community": ["dataview", "templater-obsidian"],
                },
            },
        },
    }


def _data_path(config_path: Path | None, config: VaultToolsConfig) -> Path:
    return config.path if config.path else config_path or default_config_path(user=True)


def set_vault_profile(
    name: str,
    path: Path,
    *,
    role: str = "vault",
    description: str = "",
    display_name: str | None = None,
    nicknames: list[str] | None = None,
    required_extensions: ExtensionRequirements | None = None,
    make_default: bool = False,
    config_path: Path | None = None,
) -> Path:
    config = load_config(config_path)
    data = config.raw.copy() if config.raw else empty_config()
    if "default_vault" in data and "current_vault" not in data:
        data["current_vault"] = data.pop("default_vault")
    data.setdefault("vaults", {})
    profile_data: dict[str, Any] = {"path": str(path), "role": role}
    if display_name:
        profile_data["name"] = display_name
    if nicknames:
        profile_data["nicknames"] = sorted(set(nicknames))
    if description:
        profile_data["description"] = description
    if required_extensions and (required_extensions.core or required_extensions.community):
        profile_data["required_extensions"] = required_extensions.to_dict()
    data["vaults"][name] = profile_data
    if make_default or not data.get("current_vault"):
        data["current_vault"] = name
    data.pop("default_vault", None)
    return save_config(data, _data_path(config_path, config))


def remove_vault_profile(name: str, config_path: Path | None = None) -> Path:
    config = load_config(config_path)
    data = config.raw.copy() if config.raw else empty_config()
    if "default_vault" in data and "current_vault" not in data:
        data["current_vault"] = data.pop("default_vault")
    vaults = data.setdefault("vaults", {})
    vaults.pop(name, None)
    if data.get("current_vault") == name:
        data["current_vault"] = next(iter(vaults), None)
    data.pop("default_vault", None)
    return save_config(data, _data_path(config_path, config))


def resolve_profile_selector(selector: str | None, config: VaultToolsConfig) -> VaultProfile | None:
    selected = selector or config.current_vault
    if not selected:
        return None

    if selected in config.vaults:
        return config.vaults[selected]

    matches = [profile for profile in config.vaults.values() if selected in profile.selectors()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        names = ", ".join(sorted(profile.key for profile in matches))
        raise ValueError(f"Ambiguous vault selector '{selected}' matched: {names}")
    return None


def set_default_vault(name: str, config_path: Path | None = None) -> Path:
    config = load_config(config_path)
    profile = resolve_profile_selector(name, config)
    if profile is None:
        raise KeyError(f"Unknown vault profile: {name}")
    data = config.raw.copy() if config.raw else empty_config()
    if "default_vault" in data and "current_vault" not in data:
        data["current_vault"] = data.pop("default_vault")
    data["current_vault"] = profile.key
    data.pop("default_vault", None)
    return save_config(data, _data_path(config_path, config))


@dataclass(frozen=True)
class ConfigIssue:
    level: str
    message: str


def validate_config(config: VaultToolsConfig, *, check_paths: bool = True) -> list[ConfigIssue]:
    issues: list[ConfigIssue] = []
    if not config.vaults:
        issues.append(ConfigIssue("warning", "No vault profiles are configured."))

    if config.current_vault and resolve_profile_selector(config.current_vault, config) is None:
        issues.append(ConfigIssue("error", f"Current vault is unknown: {config.current_vault}"))

    selectors: dict[str, str] = {}
    for key, profile in config.vaults.items():
        for selector in profile.selectors():
            previous = selectors.get(selector)
            if previous and previous != key:
                issues.append(
                    ConfigIssue("error", f"Selector/nickname '{selector}' is shared by {previous} and {key}.")
                )
            selectors[selector] = key
        if check_paths and not profile.path.exists():
            issues.append(ConfigIssue("warning", f"Vault path for '{key}' does not exist: {profile.path}"))
        if not profile.path.name:
            issues.append(ConfigIssue("error", f"Vault path for '{key}' is empty."))
    return issues
