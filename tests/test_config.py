from pathlib import Path

from vault_tools.config import load_config, resolve_profile_selector, set_default_vault, validate_config


def test_profile_selector_supports_nickname_and_current_vault(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    config_path = tmp_path / "vault-tools.yml"
    config_path.write_text(
        f"""
current_vault: work
vaults:
  work:
    path: {vault.as_posix()}
    name: Work Vault
    nicknames: [main, daily]
    role: target
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.current_vault == "work"
    assert resolve_profile_selector(None, config).key == "work"
    assert resolve_profile_selector("main", config).key == "work"
    assert resolve_profile_selector("Work Vault", config).key == "work"
    assert validate_config(config) == []


def test_set_default_vault_accepts_nickname(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    config_path = tmp_path / "vault-tools.yml"
    config_path.write_text(
        f"""
current_vault: null
vaults:
  work:
    path: {vault.as_posix()}
    nicknames: [main]
""".strip(),
        encoding="utf-8",
    )

    set_default_vault("main", config_path)

    config = load_config(config_path)
    assert config.current_vault == "work"
