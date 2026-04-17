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
client.e2g_url(path)           # /{spaceId}/_e2g/api/{path}            (execution units, attachments, agent logs)
```

## API quirks to be aware of

- **Inventory v3 PATCH body**: `{"operations": [{"op": "Replace", ...}]}` — wrapper object, PascalCase op.
- **MBT builder PATCH body**: `[{"op": "replace", ...}]` — bare array, lowercase op.
- **Inventory search filters**: use lowercase `"contains"` / `"and"` — PascalCase returns 0 results despite swagger saying otherwise.
- **TSU export request field**: `reusableTestStepBlockIds` (correct spelling) — not `reuseeable` (API path typo).
- **Block IDs**: not the same as module entity IDs from Inventory. Extract from `testCaseItems[].reusableTestStepBlockId` via `cases get --json <id>`.
- **`parameterLayerId`**: every `TestStepFolderReferenceV2` in a test case must have one (fresh ULID). Omitting it silently drops all parameter values.
- **`--json` flag placement**: before positional args — `cases get --json <id>` ✓, never `cases get -- <id> --json`.
- **MBT test case ID = Inventory `entityId`**: `cases get`/`steps`/`update` accept only the Inventory `entityId` (e.g. `WcucATcH0UKiiL9aoQsJyg`). The playlist item's `id` and the inventory record's `attributes.surrogate` UUID both 404. Resolve via `inventory search … --type TestCase --json` → `id.entityId`.
- **`version` in PUT body**: rejected by case / block / module PUT endpoints. The CLI's `update_case`, `update_block`, `update_module` strip it automatically; when building a body by hand, drop the key.
- **Step-level logs via E2G API** (works under `Tricentis_Cloud_API`): `playlists logs <runId>` resolves the run's `executionId`, walks `/_e2g/api/executions/{executionId}` units, lists attachments, and downloads each via SAS-signed Azure Blob URLs (`logs.txt`, `JUnit.xml`, `TBoxResults.tas`, `TestSteps.json`, `Recording.mp4`). Use `--save <dir>` to dump all attachments; `--execution-id / -e` if the input is already an executionId. `playlists attachments <runId>` lists SAS URLs without downloading.
- **`playlistRun.id` ≠ E2G `executionId`**: the `_e2g/api/executions/{id}` endpoint keys on `PlaylistRunV1.executionId`, not the playlist run's own `id`. Passing the playlist run id 404s. Always read `executionId` from `playlists status <runId>` first (or let the CLI commands above do it).
- **SAS URL caveats**: TTL ≈ 30 min; the blob GET must NOT carry an Authorization header — the SAS signature is the entire auth. Attachment names come back as `name + fileExtension` pairs; `name` is one of `logs`, `JUnit`, `TBoxResults`, `TestSteps`, `Recording`.

## Html engine runtime quirks

- **"More than one matching tab"**: agents that reuse the user's personal Chrome match multiple tabs with `Title=*`. Add a module-level `Url=https://<host>*` TechnicalId to scope document matching to the test host.
- **"The Browser could not be found"**: Tricentis Chrome extension is not attached to the Chrome instance the agent is driving. Environment fix (install/enable the extension in the target profile) — no test-case change resolves this.
- **`CloseBrowser Title="*"` fails on empty agents**: throws `UnestablishedConnectionException` after 10 s when no Chrome is running. Remove the cleanup on grid agents, or wrap in a `ControlFlowItemV2 If` with a narrow `Title="*<AppName>*"` on workstation agents.
- **`ControlFlowItemV2 If` for optional elements**: works when the module-level `Title`/`Url` can cleanly miss (Verify evaluates `false`). Hard-fails when the document itself isn't found — narrow the module-level selector before relying on `If`.
- **Scanned modules' `SelfHealingData`**: carries the page's title/URL at scan time. When reusing a scanned module on a different flow, drop the `SelfHealingData` steering param — stale hints interfere with document matching.
- **Html module steering defaults that actually work**: `AllowedAriaControls` populated (standard aria list), `EnableSlotContentHandling=False`, `IgnoreInvisibleHtmlElements=True`. Empty `AllowedAriaControls` or `EnableSlotContentHandling=True` cause erratic element resolution.

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
