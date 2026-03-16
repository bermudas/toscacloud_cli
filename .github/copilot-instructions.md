# GitHub Copilot Instructions — TOSCA Cloud CLI

## Project overview

Single-file Python CLI (`tosca_cli.py`) for Tricentis TOSCA Cloud REST APIs.
`ToscaClient` class handles all HTTP. Typer sub-apps expose commands per API surface.

## Code style

- Python 3.10+, type hints throughout, `|` union syntax (not `Optional` where avoidable).
- `ToscaClient` methods: one method per API endpoint, docstring with `VERB /path → ReturnType`.
- Every Typer command: `--json` flag for raw output, Rich table/panel for human output.
- Use `_output_json(data)` for JSON output — it auto-detects tty vs pipe.
- Use `_exit_err(msg)` for user-facing errors (prints red, raises `typer.Exit(1)`).
- Use `_generate_ulid()` whenever a fresh ULID is needed (block params, parameterLayerIds).

## URL builders (use these, never construct URLs manually)

```python
client.identity(path)          # /_identity/api/v1/{path}
client.mbt(path)               # /{spaceId}/_mbt/api/v2/builder/{path}
client.playlist(path)          # /{spaceId}/_playlists/api/v2/{path}
client.inventory_url(path)     # /{spaceId}/_inventory/api/v3/{path}
client.inventory_v1_url(path)  # /{spaceId}/_inventory/api/v1/{path}  (undocumented)
client.simulations_url(path)   # /{spaceId}/_simulations/api/v1/{path}
```

## API quirks to be aware of

- **Inventory v3 PATCH body**: `{"operations": [{"op": "Replace", ...}]}` — wrapper object, PascalCase op.
- **MBT builder PATCH body**: `[{"op": "replace", ...}]` — bare array, lowercase op.
- **Inventory search filters**: use lowercase `"contains"` / `"and"` — PascalCase returns 0 results despite swagger saying otherwise.
- **TSU export request field**: `reusableTestStepBlockIds` (correct spelling) — not `reuseeable` (API path typo).
- **Block IDs**: not the same as module entity IDs from Inventory. Extract from `testCaseItems[].reusableTestStepBlockId` via `cases get --json <id>`.
- **`parameterLayerId`**: every `TestStepFolderReferenceV2` in a test case must have one (fresh ULID). Omitting it silently drops all parameter values.
- **`--json` flag placement**: before positional args — `cases get --json <id>` ✓, never `cases get -- <id> --json`.

## Adding a new command — checklist

1. Add `ToscaClient` method (docstring with HTTP verb + endpoint path).
2. Add Typer command to the right `*_app` with `--json` flag and short `--help` text.
3. Update `README.md` Command Reference for the relevant group.
4. If a new API quirk is found, add it to the Known API Limitations table.

## Running

```bash
source .venv/bin/activate
python tosca_cli.py config test        # verify credentials
python tosca_cli.py inventory search "name" --type TestCase
```
