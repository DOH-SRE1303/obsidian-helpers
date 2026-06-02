from pathlib import Path

from vault_tools.scanner import extract_wikilinks, inline_tags, scan_vault


def test_inline_tags_ignores_code_and_urls():
    text = """
#real-tag
`#not-a-tag`
```python
# also-not-a-tag
```
https://example.com/#fragment
#abcdef
"""
    assert inline_tags(text) == ["real-tag"]


def test_extract_wikilinks():
    text = "[[Project A]] and [[Folder/Note#Heading|Alias]] and ![[image.png]]"
    assert extract_wikilinks(text) == ["Folder/Note", "Project A", "image.png"]


def test_scan_vault(tmp_path: Path):
    (tmp_path / ".obsidian").mkdir()
    note = tmp_path / "note.md"
    note.write_text("---\ntags: [project, test]\n---\n# Note\n[[Other]]", encoding="utf-8")

    scan = scan_vault(tmp_path)

    assert len(scan.notes) == 1
    assert scan.notes[0].tags == ["project", "test"]
    assert scan.notes[0].wikilinks == ["Other"]
