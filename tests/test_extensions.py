from pathlib import Path

from vault_tools.config import ExtensionRequirements
from vault_tools.extensions import inspect_extensions, missing_extensions


def test_inspect_extensions_reads_core_and_community_plugins(tmp_path: Path):
    obsidian = tmp_path / ".obsidian"
    obsidian.mkdir()
    (obsidian / "core-plugins.json").write_text('{"templates": true, "canvas": false}', encoding="utf-8")
    (obsidian / "community-plugins.json").write_text('["dataview"]', encoding="utf-8")

    extensions = inspect_extensions(tmp_path)

    assert extensions.core_plugins == ["templates"]
    assert extensions.community_plugins == ["dataview"]
    assert missing_extensions(
        tmp_path,
        ExtensionRequirements(core=["templates"], community=["dataview", "templater-obsidian"]),
    ) == ["community:templater-obsidian"]
