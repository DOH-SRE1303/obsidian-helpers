# vault-tools

Small, expandable Typer CLI tools for auditing and indexing Obsidian vaults.

This is intentionally boring infrastructure: scan vaults, export reports, and create a reliable base for future migration/indexing tools.

## Suggested layout

Keep the CLI repo beside your vaults:

```text
Obsidian/
├── vault-tools/          # this repo
├── vault-old/            # frozen snapshot / evidence archive
├── vault-new/            # curated, version-controlled vault
└── repo-index-output/    # optional later
```

Then store reusable vault profiles in `vault-tools.yml`:

```yaml
default_vault: new
vaults:
  old:
    path: ../vault-old
    role: source
    description: Read-only legacy vault snapshot used as migration evidence.
  new:
    path: ../vault-new
    role: target
    description: Version-controlled working vault.
```

`vault-tools.yml` is intentionally gitignored by default because local paths are usually machine-specific. Commit a `vault-tools.example.yml` if you want a shareable template.

## Install locally

```bash
python -m venv .venv
source .venv/bin/activate  # Windows Git Bash
python -m pip install -e .
```

On PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## Configure vault profiles

```bash
vt vault init --empty
vt vault add old ../vault-old --role source --description "Frozen legacy vault"
vt vault add new ../vault-new --role target --description "Version-controlled working vault" --default
vt vault list
vt vault show new
vt vault default old
```

You can also pass `--config path/to/vault-tools.yml`, or set `VAULT_TOOLS_CONFIG`.

## Commands

Use a direct vault path:

```bash
vt stats "C:/path/to/vault"
vt info "C:/path/to/vault" --out reports/vault-info.md --max-depth 2
```

Use the default configured vault:

```bash
vt stats
vt info --out reports/vault-info.md --max-depth 2
vt manifest --out exports/vault-manifest.json
vt audit no-tags --out reports/no-tags.md
vt audit broken-links --out reports/broken-links.md
vt audit orphan-attachments --out reports/orphan-attachments.md
```

Use a specific profile:

```bash
vt stats --profile old
vt info --profile new --format json --out exports/new-vault-info.json
vt tree --profile old --max-depth 3 --out reports/old-tree.md
vt audit no-tags --profile old --under "Meetings" --format csv --out reports/old-no-tags-meetings.csv
```

## Current audits

- Vault stats
- Folder tree export
- Full JSON manifest
- Notes without tags
- Broken wikilinks
- Orphan attachments
- File type counts
- Frontmatter field counts
- Tag counts
- Optional `.obsidian` plugin/template metadata
- Named vault profiles via `vault-tools.yml`

## Planned next audits

- Compare two vault profiles, such as `old` vs `new`
- Migration dry-runs from source vault to target vault
- Meeting-like notes missing `projects` metadata
- Daily-note-derived meeting notes
- Notes with people but no project
- Project tags without project map notes
- Single-use tags
- Duplicate or near-duplicate titles
- Notes with no inbound or outbound links
- Attachments used by multiple notes
- Notes with TODO/action items
- Notes with decisions but no decision note
- Stale generated maps
- Repo index command for GitHub repositories

## Design notes

- Keep the old vault as evidence.
- Generate reports/maps into a new version-controlled vault or separate repo folder.
- Prefer repeatable exports over manual cleanup.
- Treat GitHub repositories as another source system, not ordinary vault folders.
- Use named profiles so future commands can compare, migrate, or synthesize across vaults without hardcoded paths.
