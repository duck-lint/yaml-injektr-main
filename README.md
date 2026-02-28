# yaml-injektr

`yaml-injektr` bulk-replaces YAML frontmatter in Obsidian Markdown notes using a user-supplied payload.

It is safe by default:
- Dry-run unless `--apply` is provided.
- Continues after per-file errors.
- Uses atomic writes (`os.replace`) when applying.

## Install

```bash
pip install -e .
```

## Usage

Console script:

```bash
yaml-injektr --target /path/to/vault --payload payload.yaml
```

Module mode:

```bash
python -m yaml_injektr --target /path/to/vault --payload payload.yaml
```

### Dry-run (default)

```bash
yaml-injektr --target ./vault --payload ./payload.yaml
```

### Apply changes

```bash
yaml-injektr --target ./vault --payload ./payload.yaml --apply
```

### UUIDv7 token in payload

`payload.yaml`:

```yaml
uuid: "{uuidv7}"
title: New Title
status: active
```

If a note already has a top-level `uuid`, that existing value is preserved and wins over payload values/tokens.

### Date from filename

`payload.yaml`:

```yaml
journal_entry_date: "{file_date:%Y-%m-%d}"
```

Examples:

```bash
yaml-injektr --target ./Journals/2025-12 --payload payload.yaml --apply
yaml-injektr --target "./Journals/December 2025" --payload payload.yaml --year-month 2025-12 --apply
```

Rules:
- Supports `{file_date}` (ISO `YYYY-MM-DD`) and `{file_date:<strftime-format>}`.
- Day comes from filename stem prefix (for example: `03_monday.md`, `4_tuesday.md`).
- Year-month comes from the file path (`YYYY-MM` or `YYYY_MM`, last match wins) or `--year-month YYYY-MM`.
- If `{file_date...}` is present and year-month cannot be resolved from paths, provide `--year-month`.

## frontmatter behavior

- frontmatter is only detected when the file starts with `---` on line 1.
- Closing marker must be exactly `---` or `...`.
- Missing closing marker is treated as an error and file is not modified.
- Existing top-level `uuid` is preserved (case-sensitive key `uuid`).
- Existing frontmatter keys other than preserved `uuid` are removed.

## File walking and excludes

When `--target` is a directory:
- Default glob is `**/*.md`
- `--glob "*.md"` matches only files at the target root
- `--glob "**/*.md"` matches markdown files recursively (including target-root files)
- Default excluded directory names are:
  - `.obsidian`
  - `.trash`
  - `.git`
  - `node_modules`

Add excludes by passing one or more `--exclude-dir` flags. Use `--no-default-excludes` to disable the defaults.

## Output streams

By default the CLI emits both:

- JSONL records to `stdout` (one per processed file)
- Human summary to `stderr`

In the summary, `skipped` counts excluded directories.

JSONL fields include:
- `path`
- `status` (`changed | unchanged | skipped | error`)
- `had_frontmatter`
- `preserved_uuid`
- `generated_uuid`
- `reason`

When a directory is excluded (default excludes or `--exclude-dir`), the CLI emits a JSONL record with
`status: "skipped"`, `reason: "excluded_dir"`, and an additional `is_dir: true` field.

Disable either stream:

```bash
yaml-injektr --target ./vault --payload ./payload.yaml --no-json
yaml-injektr --target ./vault --payload ./payload.yaml --no-summary
```

## Exit codes

- `0`: completed with no per-file errors
- `1`: CLI usage/input errors
- `2`: one or more files failed during processing


## Development / Running tests

```bash
python -m venv .venv
```

Activate the virtual environment:

- Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

- macOS/Linux:

```bash
source .venv/bin/activate
```

Install the package (editable for development):

```bash
python -m pip install -e .
```

Run tests:

```bash
python -m unittest -v
python -m unittest discover -s tests -v
```
