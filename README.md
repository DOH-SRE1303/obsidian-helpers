# vault-tools

Small, expandable Typer CLIs for auditing, indexing, and eventually chatting with Obsidian vaults.

This is intentionally boring infrastructure: scan vaults, export reports, manage reusable vault profiles, and create a reliable base for future migration/indexing/chat tools.

## CLI layout

This repo now exposes three entry points:

- `vt` — vault tools for profiles, scans, reports, audits, and future safe vault manipulation commands.
- `vc` — a scaffolded vault-chat CLI for future local LLM indexing and question answering.
- `vault-tools` — an umbrella CLI that explains and dispatches to both `vt` and `vc`.

Equivalent examples:

```bash
vt stats
vault-tools vt stats
vc ask "What did I write about project X?"
vault-tools vc ask "What did I write about project X?"
```

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
current_vault: new
vaults:
  old:
    path: ../vault-old
    role: source
    nicknames:
      - legacy
    description: Read-only legacy vault snapshot used as migration evidence.
  new:
    path: ../vault-new
    role: target
    name: Curated Vault
    nicknames:
      - main
    description: Version-controlled working vault.
    required_extensions:
      core:
        - templates
      community:
        - dataview
        - templater-obsidian
```

`vault-tools.yml` is intentionally gitignored by default because local paths are usually machine-specific. Commit a `vault-tools.example.yml` if you want a shareable template.

## Config discovery

Config resolution order is:

1. `--config path/to/config.yml`
2. `VAULT_TOOLS_CONFIG`
3. nearest `vault-tools.yml`, `vault-tools.yaml`, `.vault-tools.yml`, or `.vault-tools.yaml` in the current directory or a parent directory
4. per-user fallback config:
   - Windows: `%APPDATA%/vault-tools/config.yml`
   - Linux/macOS: `~/.config/vault-tools/config.yml`

The YAML file can be edited by hand, but CLI commands are the supported way to modify profiles because they write the canonical schema and validate common mistakes.

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

## Shell autocomplete

Typer exposes shell completion for each direct executable. Install completion for whichever commands you use:

```bash
vt --install-completion
vc --install-completion
vault-tools --install-completion
```

To preview the generated completion script:

```bash
vt --show-completion
vault-tools completion-info
```

## Configure vault profiles

Grouped profile commands:

```bash
vt vault init --empty
vt vault add old ../vault-old --role source --description "Frozen legacy vault"
vt vault add new ../vault-new --role target --name "Curated Vault" --nickname main --default
vt vault list
vt vault status
vt vault show main
vt vault set main
vt vault doctor
vt vault normalize
```

You can also pass `--config path/to/vault-tools.yml`, or set `VAULT_TOOLS_CONFIG`.

## Commands

Use a direct vault path:

```bash
vt stats "C:/path/to/vault"
vt info "C:/path/to/vault" --out reports/vault-info.md --max-depth 2
```

Use the current configured vault:

```bash
vt stats
vt info --out reports/vault-info.md --max-depth 2
vt manifest --out exports/vault-manifest.json
vt audit no-tags --out reports/no-tags.md
vt audit broken-links --out reports/broken-links.md
vt audit orphan-attachments --out reports/orphan-attachments.md
```

Use a specific profile key or nickname:

```bash
vt stats --profile old
vt info --profile main --format json --out exports/new-vault-info.json
vt tree --profile old --max-depth 3 --out reports/old-tree.md
vt audit no-tags --profile old --under "Meetings" --format csv --out reports/old-no-tags-meetings.csv
```

## Extension awareness

Profiles can declare required Obsidian core and community plugins. Commands that resolve a profile check these requirements before scanning or indexing the vault and fail early if required plugins are not enabled in `.obsidian/core-plugins.json` or `.obsidian/community-plugins.json`.

```yaml
vaults:
  work:
    path: C:/path/to/vault
    required_extensions:
      core:
        - templates
      community:
        - dataview
        - templater-obsidian
```

Use `vt vault status` to see enabled extensions and `vt vault doctor` to validate profile config.

## Vault chat scaffold

`vc` is currently a command surface for the next implementation phase. It resolves the same vault profiles as `vt` and checks profile-level extension requirements, but indexing and local LLM querying are not implemented yet.

```bash
vc index
vc ask "What did I write about project X?"
vc sources "project X"
vc doctor
vc models
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
- Profile nicknames and current vault selection
- Profile-level required extension checks

## Planned next audits and tools

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
- Decisions without decision notes
- Stale generated maps
- Repo index command for GitHub repositories
- Local LLM vault chat indexing and citation-backed answers

## Design notes

- Keep the old vault as evidence.
- Generate reports/maps into a new version-controlled vault or separate repo folder.
- Prefer repeatable exports over manual cleanup.
- Treat GitHub repositories as another source system, not ordinary vault folders.
- Use named profiles and nicknames so future commands can compare, migrate, or synthesize across vaults without hardcoded paths.
- Keep note-changing commands explicit, previewable, and safe-by-default when mutation features are added.
