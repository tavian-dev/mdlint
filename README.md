# mdlint

Lint markdown knowledge bases for consistency. Zero dependencies, pure Python.

Checks for broken links, missing frontmatter fields, orphaned files, duplicate titles, and empty files.

## Usage

```bash
# Basic lint
python mdlint.py ./notes

# With frontmatter schema validation
python mdlint.py ./notes --schema type:str confidence:float last_updated:date

# Only show errors and warnings (skip info)
python mdlint.py ./notes --level warning

# JSON output
python mdlint.py ./notes --json
```

## Checks

| Code | Level | Description |
|------|-------|-------------|
| E001 | error | Cannot read file |
| E002 | error | Frontmatter field has wrong type |
| E003 | error | Broken internal link |
| W001 | warning | Empty file |
| W002 | warning | Missing required frontmatter field |
| W003 | warning | Date field doesn't match YYYY-MM-DD |
| W004 | warning | Duplicate title across files |
| I001 | info | Orphaned file (nothing links to it) |

## Link formats

Detects both wikilinks and standard markdown links:
- `[[filename]]` and `[[filename|display text]]`
- `[text](path.md)`

## Schema validation

Use `--schema` to require frontmatter fields:
```bash
mdlint ./notes --schema type:str confidence:float date:date
```

Types: `str` (any string), `float` (numeric), `date` (YYYY-MM-DD format).

## License

MIT
