from pathlib import Path

from typer.testing import CliRunner

from vault_tools.cli import root, vt


runner = CliRunner()


def test_vt_help_includes_banner_profiles_and_audit_workflows():
    result = runner.invoke(vt.app, ["--help"])

    assert result.exit_code == 0
    assert "████████╗ ██████╗" in result.output
    assert "vt info [VAULT] --profile PROFILE" in result.output
    assert "Profile setup workflow" in result.output
    assert "vt vault add work /path/to/vault" in result.output
    assert "vt audit tags [VAULT] --profile PROFILE --untagged --sus --used-once" in result.output
    assert "vt audit attachment [VAULT] --profile PROFILE --locations --sprawl" in result.output
    assert "vt audit folders [VAULT] --profile PROFILE --drift --duplicates" in result.output
    assert "--from-manifest" in result.output
    assert "exports/scans/PROFILE/latest" in result.output


def test_vault_tools_help_includes_banner_and_profile_setup():
    result = runner.invoke(root.app, ["--help"])

    assert result.exit_code == 0
    assert "████████╗ ██████╗" in result.output
    assert "vault-tools vt vault init --empty" in result.output
    assert "vault-tools vt audit tags --profile PROFILE --untagged --sus --used-once" in result.output


def test_primary_audit_commands_run(tmp_path: Path):
    (tmp_path / "Projects").mkdir()
    (tmp_path / "Projects" / "one.md").write_text("#tag-one\n![[image.png]]", encoding="utf-8")
    (tmp_path / "Projects" / "two.md").write_text("No tags here", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"fake")
    (tmp_path / "Projects" / "image.png").write_bytes(b"fake")

    tags_result = runner.invoke(vt.app, ["audit", "tags", str(tmp_path), "--untagged", "--used-once"])
    attachment_result = runner.invoke(
        vt.app,
        ["audit", "attachment", str(tmp_path), "--locations", "--duplicates"],
    )
    folders_result = runner.invoke(vt.app, ["audit", "folders", str(tmp_path), "--drift"])

    assert tags_result.exit_code == 0
    assert "Tag audit" in tags_result.output
    assert "Untagged notes" in tags_result.output
    assert "#tag-one" in tags_result.output
    assert attachment_result.exit_code == 0
    assert "Attachment audit" in attachment_result.output
    assert "Duplicate attachment names" in attachment_result.output
    assert folders_result.exit_code == 0
    assert "Folder audit" in folders_result.output
    assert "Folder drift candidates" in folders_result.output


def test_manifest_build_and_audits_can_read_manifest(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Projects").mkdir()
    (vault / "Projects" / "one.md").write_text(
        "---\ntags: [project]\nstatus: active\n---\n[[Missing]]\n![[kept.png]]",
        encoding="utf-8",
    )
    (vault / "Projects" / "two.md").write_text("No tags here", encoding="utf-8")
    (vault / "kept.png").write_bytes(b"kept")
    (vault / "orphan.png").write_bytes(b"orphan")
    out = tmp_path / "exports" / "scans" / "old" / "latest"

    build_result = runner.invoke(vt.app, ["manifest", "build", str(vault), "--out", str(out)])
    no_tags_result = runner.invoke(
        vt.app,
        [
            "audit",
            "no-tags",
            "--from-manifest",
            str(out),
            "--out",
            str(tmp_path / "no-tags.json"),
            "--format",
            "json",
        ],
    )
    broken_links_result = runner.invoke(
        vt.app,
        [
            "audit",
            "broken-links",
            "--from-manifest",
            str(out),
            "--out",
            str(tmp_path / "broken.json"),
            "--format",
            "json",
        ],
    )
    orphan_result = runner.invoke(
        vt.app,
        [
            "audit",
            "orphan-attachments",
            "--from-manifest",
            str(out),
            "--out",
            str(tmp_path / "orphans.json"),
            "--format",
            "json",
        ],
    )
    suspicious_result = runner.invoke(
        vt.app,
        [
            "audit",
            "suspicious-tags",
            "--from-manifest",
            str(out),
            "--out",
            str(tmp_path / "suspicious.json"),
            "--format",
            "json",
        ],
    )

    assert build_result.exit_code == 0
    for name in [
        "vault_manifest.json",
        "notes_manifest.json",
        "links_manifest.json",
        "tags_manifest.json",
        "frontmatter_manifest.json",
        "attachments_manifest.json",
        "classifications.json",
    ]:
        assert (out / name).exists()
    assert "content_hash" in (out / "vault_manifest.json").read_text(encoding="utf-8")
    assert no_tags_result.exit_code == 0
    assert broken_links_result.exit_code == 0
    assert orphan_result.exit_code == 0
    assert suspicious_result.exit_code == 0
    assert "Projects/two.md" in (tmp_path / "no-tags.json").read_text(encoding="utf-8")
    assert "Missing" in (tmp_path / "broken.json").read_text(encoding="utf-8")
    assert "orphan.png" in (tmp_path / "orphans.json").read_text(encoding="utf-8")


def test_info_can_render_from_manifest_without_rescanning_vault(tmp_path: Path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "note.md").write_text("# Note", encoding="utf-8")
    out = tmp_path / "scan"

    build_result = runner.invoke(vt.app, ["manifest", "build", str(vault), "--out", str(out)])
    renamed = tmp_path / "vault-renamed"
    vault.rename(renamed)
    report_path = tmp_path / "report.md"
    info_result = runner.invoke(
        vt.app,
        ["info", "--from-manifest", str(out), "--out", str(report_path)],
    )

    assert build_result.exit_code == 0
    assert info_result.exit_code == 0
    assert "Vault Snapshot" in report_path.read_text(encoding="utf-8")
    assert "note.md" in report_path.read_text(encoding="utf-8")
