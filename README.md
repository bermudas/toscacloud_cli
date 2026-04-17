# TOSCA Cloud CLI

An AI-native command-line interface for Tricentis TOSCA Cloud.

Covers seven API surfaces: Identity, MBT/Builder (v2), Playlists (v2), Inventory (v3 + v1 undocumented folder operations), Simulations (v1), and Reuseable Test Step Blocks (MBT v2).

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## Prerequisites

- Python 3.10+
- Access to a Tricentis TOSCA Cloud tenant
- OAuth2 client credentials (see [Getting Credentials](#getting-credentials))

---

## Setup

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure connection settings

Settings are stored in `.env` in the project directory.

```bash
python tosca_cli.py config set \
    --tenant        https://your-tenant.my.tricentis.com \
    --token-url     https://your-org-tricentis.okta.com/oauth2/default/v1/token \
    --client-id     your-client-id \
    --client-secret your-client-secret \
    --space-id      your-space-uuid
```

### 3. Test connectivity

```bash
python tosca_cli.py config test
# Token obtained successfully.
# Identity API reachable. Found 22 application(s).
```

---

## Getting Credentials

> **Official guide:** [Get a client secret – Tricentis TOSCA Cloud docs](https://docs.tricentis.com/tosca-cloud/en-us/content/admin_guide/get_client_secret.htm)

### Which app to use

Run `python tosca_cli.py identity apps` to list all registered OAuth2 applications in your tenant and find the one intended for API access.

### Generate a client secret

```bash
# Check if secrets already exist
python tosca_cli.py identity secrets <appId>

# Generate a new secret (copy it immediately – shown only once)
python tosca_cli.py identity new-secret <appId>

# Retrieve a secret value by its secretId
python tosca_cli.py identity get-secret <appId> <secretId>
```

### Finding your Space ID

The space ID is a UUID visible in the TOSCA Cloud UI URL:
`https://your-tenant.my.tricentis.com/<space-uuid>/...`

```bash
python tosca_cli.py config set --space-id your-space-uuid
```

### Why Okta?

TOSCA Cloud uses Okta as a separate identity provider. The token URL
(`your-org-tricentis.okta.com`) issues JWTs that TOSCA Cloud validates.
The exact Okta URL is visible in any Swagger UI under **Authorize**.

---

## Command Reference

All commands accept `--json` for raw JSON output and `--help` for full option details.

---

### `config`

| Command | Description |
|---------|-------------|
| `config set [options]` | Save settings to `.env` in the project directory |
| `config show` | Display current settings (secrets masked) |
| `config test` | Fetch token + verify Identity API reachability |

**Options for `config set`:**

| Flag | Env var | Default |
|------|---------|---------|
| `--tenant` | `TOSCA_TENANT_URL` | — |
| `--space-id` | `TOSCA_SPACE_ID` | `default` |
| `--token-url` | `TOSCA_TOKEN_URL` | — |
| `--client-id` | `TOSCA_CLIENT_ID` | — |
| `--client-secret` | `TOSCA_CLIENT_SECRET` | — |
| `--scope` | `TOSCA_SCOPE` | `tta` |
| `--timeout` | `TOSCA_TIMEOUT` | `30` |
| `--no-ssl` | `TOSCA_VERIFY_SSL=false` | — |
| `--openai-key` | `TOSCA_OPENAI_KEY` | — |

---

### `identity`

Manage OAuth2 applications and client secrets.

```bash
python tosca_cli.py identity apps
python tosca_cli.py identity secrets <appId>
python tosca_cli.py identity new-secret <appId>
python tosca_cli.py identity get-secret <appId> <secretId>
python tosca_cli.py identity delete-secret <appId> <secretId>
```

---

### `cases`

Test case operations via MBT/Builder API v2.

> **Discovery:** The MBT API has no list/search endpoint. Use `inventory search --type TestCase` to find test case IDs first.

```bash
# Show full metadata
python tosca_cli.py cases get <caseId>

# Show full recursive step tree with all values, module refs, attribute refs
python tosca_cli.py cases steps <caseId>
python tosca_cli.py cases steps <caseId> --json

# Clone an existing test case with all steps, values, and config params
python tosca_cli.py cases clone <caseId>
python tosca_cli.py cases clone <caseId> --name "My copy"

# Create a blank test case
python tosca_cli.py cases create --name "My TC" --desc "..." --state Planned

# Full replace (PUT) — supply a complete TestCaseV2 JSON body
python tosca_cli.py cases update <caseId> --json-file updated_case.json

# Partial update (PATCH) — RFC 6902 JSON Patch operations
python tosca_cli.py cases patch <caseId> \
    --operations '[{"op":"replace","path":"/workState","value":"Completed"}]'

# Export test cases / modules / blocks to a binary .tsu file (MBT v2 endpoint)
# At least one of --ids, --module-ids, --block-ids must be provided
python tosca_cli.py cases export-tsu --ids "id1,id2,id3" --output my_export.tsu
python tosca_cli.py cases export-tsu --ids "id1" --block-ids "bid1" --output bundle.tsu

# Import test cases from a .tsu file (undocumented MBT v2 endpoint)
python tosca_cli.py cases import-tsu --file my_export.tsu

# Delete
python tosca_cli.py cases delete <caseId> --force
```

**`cases steps` output** shows a Rich tree with:
- Configuration parameters (e.g. `Browser = 'Edge'`)
- Folder hierarchy (Precondition / Process / Verification / Postcondition)
- Each `TestStepV2` with its `moduleReference.id`, `packageReference`, and every
  `testStepValue` (name, value, actionMode, operator, dataType, attrRef)

**`cases clone` behaviour:**
- Fetches the full `TestCaseV2` payload and strips generated item/value IDs
  (module and attribute refs are preserved so the steps still resolve correctly)
- POSTs as a new test case — default name is `AI Copilot – <original name>`
- Waits up to 15 s for Inventory indexing, then copies tags from the source
- Move the cloned case to the correct folder with:
  `inventory move testCase <newId> --folder-id <folderId>`

WorkState enum: `Planned` | `InWork` | `Completed`

---

### `blocks`

Reuseable Test Step Block operations via MBT/Builder API v2.

Blocks are reusable step sequences that encapsulate multiple test steps behind a named parameter interface (`businessParameters`). They appear in the portal as **Reuseable Test Step Blocks** and are referenced from test cases via `TestStepFolderReferenceV2` items.

> **Discovery:** Use `inventory search --type Module` to find block IDs (blocks are indexed alongside modules in Inventory).

```bash
# Show block details and all business parameters with IDs and valueRanges
python tosca_cli.py blocks get <blockId>
python tosca_cli.py blocks get <blockId> --json

# Add a new business parameter to a block (e.g. adding a 4th material slot)
python tosca_cli.py blocks add-param <blockId> --name Material4
python tosca_cli.py blocks add-param <blockId> --name Material4 --desc "4th material"
python tosca_cli.py blocks add-param <blockId> --name Material4Quantity --value-range '1,2,3,4'

# Update the valueRange of an existing parameter (e.g. extend NumberOfMaterials to cover 4)
python tosca_cli.py blocks set-value-range <blockId> NumberOfMaterials --values '1,2,3,4'

# Delete a block
python tosca_cli.py blocks delete <blockId> --force
```

**`blocks add-param` output** prints the **new parameter's ULID** — capture it to use as `referencedParameterId` when building or updating test case step trees.

**Key rules when working with blocks and test cases:**

| Rule | Detail |
|------|--------|
| `version` is read-only | The `version` field is stripped automatically before every PUT. Never include it in a manual JSON body. |
| `businessParameters` require `id` | Every parameter entry must have an `id` (ULID). The CLI generates these automatically via `add-param`. |
| `parameterLayerId` is required | Each `TestStepFolderReferenceV2` in a test case must have a `parameterLayerId` (ULID). Omitting it causes all parameter values to be silently ignored. |
| `referencedParameterId` links values | Each parameter entry in a test case step must have `referencedParameterId` pointing to the corresponding `businessParameter.id` in the block. |
| Use `cases update` to apply values | After extending a block, PUT the full updated `TestCaseV2` body via `cases update <id> --json-file updated.json`. |

---

### `modules`

Module operations via MBT/Builder API v2.

> **Discovery:** Use `inventory search --type Module` to find module IDs.

```bash
python tosca_cli.py modules get <moduleId>
python tosca_cli.py modules create --name "LoginModule" --iface Gui
python tosca_cli.py modules delete <moduleId> --force
```

InterfaceType enum: `Gui` | `NonGui`

---

### `playlists`

Full run lifecycle via Playlist API v2.

```bash
# List and inspect playlists
python tosca_cli.py playlists list
python tosca_cli.py playlists list --search "smoke" --limit 20
python tosca_cli.py playlists get <playlistId>

# Create / update / delete a playlist
python tosca_cli.py playlists create --name "Smoke" --json-file playlist.json
python tosca_cli.py playlists update <playlistId> --name "New Name"
python tosca_cli.py playlists delete <playlistId> --force

# Add or update a characteristic (e.g. pin to a specific agent)
python tosca_cli.py playlists set-characteristic <playlistId> \
    --name AgentIdentifier --value Tosca-Team-Agent

# Trigger a run (returns RunId immediately)
python tosca_cli.py playlists run <playlistId>

# Override parameters at run time
python tosca_cli.py playlists run <playlistId> \
    --param-overrides '[{"name":"Environment","value":"staging"}]'

# Trigger and block until done, then print results
python tosca_cli.py playlists run <playlistId> --wait --poll 10

# Private run (not visible to other users)
python tosca_cli.py playlists run <playlistId> --private

# Run status and management
python tosca_cli.py playlists status <runId>
python tosca_cli.py playlists cancel <runId> --reason "Manual stop"
python tosca_cli.py playlists tc-runs <runId>

# JUnit results (JSON format)
python tosca_cli.py playlists results <runId>
python tosca_cli.py playlists results <runId> --save results.json

# Per-unit agent logs (full TBox transcript with .NET stack traces)
python tosca_cli.py playlists logs <runId>
python tosca_cli.py playlists logs <runId> --save ./logs            # save logs.txt + JUnit.xml + TBoxResults.tas + TestSteps.json per unit
python tosca_cli.py playlists logs <executionId> -e --quiet --save ./logs   # input is already an E2G executionId

# List per-unit attachments with their SAS-signed Azure Blob URLs (logs, JUnit, TBoxResults, TestSteps, Recording)
python tosca_cli.py playlists attachments <runId>
python tosca_cli.py playlists attachments <runId> --json

# List all runs in the space
python tosca_cli.py playlists list-runs
python tosca_cli.py playlists list-runs --limit 100

# Delete a run record
python tosca_cli.py playlists delete-run <runId> --force
```

Run states: `pending` | `running` | `canceling` | `succeeded` | `failed` | `canceled` | `unknown`

---

### `inventory`

Artifact discovery and folder management.

Inventory v3 is the **search layer** across all artifact types — use it to find IDs before
calling the MBT or Playlists API. Folder management uses the undocumented v1 portal API.

#### Search and inspect

```bash
# Search all artifact types
python tosca_cli.py inventory search "login"

# Filter by type
python tosca_cli.py inventory search "" --type TestCase --limit 50
python tosca_cli.py inventory search "SAP" --type TestCase

# Scope to a specific folder (client-side folderKey filter)
python tosca_cli.py inventory search "" --type TestCase --folder-id <folderEntityId>

# Include breadcrumb path in results
python tosca_cli.py inventory search "login" --include-ancestors

# Get full inventory record for a specific artifact
python tosca_cli.py inventory get TestCase <entityId>
python tosca_cli.py inventory get Module <entityId>
python tosca_cli.py inventory get TestCase <entityId> --include-ancestors
```

Extract entity IDs from JSON output:

```bash
python tosca_cli.py inventory search "" --type TestCase --json | \
  python3 -c "import json,sys; [print(a['id']['entityId'], a['name']) for a in json.load(sys.stdin)]"
```

#### Move artifacts into folders

```bash
# Move any artifact to a folder
python tosca_cli.py inventory move testCase <entityId> --folder-id <folderEntityId>
python tosca_cli.py inventory move Module <entityId> --folder-id <folderEntityId>
```

The folder entity ID is the UUID shown in the portal URL:
`…/inventory/artifacts/<folder-entity-id>`

#### Folder management (undocumented v1 portal API)

```bash
# Create a folder (at root, or inside a parent)
python tosca_cli.py inventory create-folder --name "Regression"
python tosca_cli.py inventory create-folder --name "Regression" \
    --parent-id "00000000-0000-0000-0000-000000000000" \
    --desc "Regression suites"

# Rename a folder
python tosca_cli.py inventory rename-folder <folderEntityId> --name "New Name"

# Delete a folder (children moved to parent by default — "ungroup")
python tosca_cli.py inventory delete-folder <folderEntityId>
# Delete folder and all its contents recursively
python tosca_cli.py inventory delete-folder <folderEntityId> --delete-children --force

# Show the ancestor chain (breadcrumb) for a folder
python tosca_cli.py inventory folder-ancestors <folderEntityId>

# List the full folder tree (or a subtree)
python tosca_cli.py inventory folder-tree
python tosca_cli.py inventory folder-tree --folder-ids "id1,id2"
```

---

### `simulations`

Simulation file management via Simulations API v1.

```bash
python tosca_cli.py simulations list
python tosca_cli.py simulations list --tags "regression,api"
python tosca_cli.py simulations get <fileId>
python tosca_cli.py simulations create \
    --name "api-mock.json" \
    --file ./api-mock.json \
    --tags "api,v2" \
    --components "Services,Runnables"
python tosca_cli.py simulations delete <fileId>
```

---

### `ask`

AI assistant — describe what you want in plain English, get a CLI command back (requires OpenAI API key).

```bash
pip install openai
python tosca_cli.py config set --openai-key sk-...

python tosca_cli.py ask "show me all steps for the successful login test case"
python tosca_cli.py ask "clone the login test case"
python tosca_cli.py ask "run the smoke test playlist and wait"
python tosca_cli.py ask "move test case abc to the regression folder"
python tosca_cli.py ask "export test cases id1 and id2 to a tsu file"
python tosca_cli.py ask "cancel run xyz" --dry-run   # preview without executing
```

---

## Known API Limitations

| Limitation | Detail |
|------------|--------|
| No test case list/search in MBT | `GET /testCases` doesn't exist — use `inventory search --type TestCase` |
| No module list/search in MBT | Same — use `inventory search --type Module` |
| Inventory indexing delay | After creating a test case via MBT API, the Inventory index takes 3–10 s to reflect it. The CLI retries automatically. |
| Delete requires owner permissions | `DELETE /testCases/{id}` returns 403 for `Tricentis_Cloud_API` service account by default. |
| JUnit results are JSON | `GET /runs/{id}/junit` returns `TestSuitesV1` as JSON, not XML despite the name. |
| Run ID field | `POST /runs` returns `PlaylistRunCreationOutputV1 { id }` — the field is `id`, not `executionId`. |
| Inventory v3 PATCH body | Inventory v3 PATCH uses a **wrapper object** `{"operations": [...]}` with PascalCase ops (`Replace`, `Add`). This differs from MBT/Builder PATCH which uses a bare array with lowercase ops. The `folderKey` field is read-only via v3; use `inventory move` instead. |
| Inventory v3 search filter casing | The swagger documents `SearchFilterOperatorV1` as PascalCase (`Contains`, `And`), but the live API only accepts **lowercase** (`contains`, `and`). PascalCase returns 0 results. |
| `--json` flag placement | Place `--json` **before** positional arguments: `cases get --json <id>` ✓. Using `--` as an end-of-options separator causes Typer to treat `--json` as a positional arg and silently fall back to Rich display output instead of JSON. |
| Block IDs ≠ Module entity IDs | `inventory search --type Module` returns entity IDs for modules, but these do **not** work with `blocks get`. Block IDs must come from a test case: `cases get --json <caseId>` → `testCaseItems[].reusableTestStepBlockId` (where `$type == "TestStepFolderReferenceV2"`). |
| `playlistRun.id` ≠ E2G `executionId` | The `_e2g/api/executions/{id}` endpoint keys on `PlaylistRunV1.executionId` (e.g. `7041def3-…`), not the playlist run's own `id` (e.g. `0d0e40dc-…`). Passing the playlist run id 404s with "Execution not found". `playlists logs` and `playlists attachments` resolve this via `playlists status` automatically — pass `--execution-id / -e` to skip the lookup. |
| Playlists v2 has no per-step log endpoint | `playlists results <runId>` returns only `<failure />`. Use `playlists logs <runId>` instead — it routes through the E2G API and downloads the actual TBox transcript (logs.txt) plus JUnit.xml, TBoxResults.tas, TestSteps.json, and Recording.mp4 (when present). |
| E2G attachment URLs are SAS-signed | The `contentDownloadUri` returned by `_e2g/api/executions/{id}/units/{id}/attachments` is a fully signed Azure Blob URL. **Do NOT add `Authorization`** to the GET — the SAS signature is the auth, and adding a Bearer token causes Azure to 403. SAS TTL ≈ 30 min; re-list to refresh. |

---

## Undocumented APIs

These endpoints are not in any published Swagger spec. They were reverse-engineered from the
portal JavaScript bundle (`toscainv`).

### Inventory v1 — Folder Operations

All under `/{spaceId}/_inventory/api/v1/`:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `PUT` | `folders/artifacts` | Move artifacts into a folder |
| `POST` | `folders` | Create a new folder |
| `PATCH` | `folders/{folderId}` | Rename a folder (JSON Patch array body) |
| `DELETE` | `folders/{folderId}` | Delete a folder |
| `GET` | `folders/{folderId}/ancestors` | Get ancestor chain of a folder |
| `POST` | `folders/tree-items` | List the folder tree |

`DELETE` body: `{"childBehavior": "moveToParent" | "deleteRecursively" | "abort"}`

### MBT/Builder v2 — TSU Export/Import

Both under `/{spaceId}/_mbt/api/v2/builder/`:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `tsu/exports` | Export test cases to a binary `.tsu` file |
| `POST` | `tsu/imports` | Import test cases from a `.tsu` file (multipart/form-data) |

`tsu/exports` body: `TsuExportRequestV2 { testCaseIds, moduleIds, reusableTestStepBlockIds }` → returns binary blob

> **Note:** the request field is spelled `reusableTestStepBlockIds` (correct English), even though the API *path* uses the typo `reuseeable`.
### E2G – Execution Units & Attachments

All under `/{spaceId}/_e2g/api/`:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `executions/{executionId}` | Execution doc with `items[]` (one `UnitV1` per test case) |
| `GET` | `executions/{executionId}/units/{unitId}/attachments` | List attachments for a unit — returns SAS-signed Azure Blob URLs |

`executionId` comes from `PlaylistRunV1.executionId` (NOT the playlist run's own `id`).

Attachment record shape:
```json
{
  "name": "logs",          // or "JUnit", "TBoxResults", "TestSteps", "Recording"
  "fileExtension": "txt",  // or "xml", "tas", "json", "mp4"
  "contentDownloadUri": "https://e2gweuprod001resblobs.blob.core.windows.net/.../logs?sv=…&se=…&sr=b&sp=r&sig=…",
  "appendUri": "https://…?sp=a&sig=…"
}
```

The blob hostname pattern is `https://e2g<region>prod001resblobs.blob.core.windows.net/<tenant-slug>/<spaceId>/<executionId>/<unitId>/<attachmentName>`. SAS TTL ≈ 30 min. The blob GET must NOT carry an `Authorization` header.

Wrapped by `playlists logs` and `playlists attachments` in the CLI.

### MBT/Builder v2 – Reuseable Test Step Blocks

All under `/{spaceId}/_mbt/api/v2/builder/reuseableTestStepBlocks/` (note the typo — "reuseable"):

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `{id}` | Fetch full block with all `businessParameters` |
| `PUT` | `{id}` | Replace entire block body (strips `version` automatically) |
| `PATCH` | `{id}` | Partial update via RFC 6902 JSON Patch |
| `DELETE` | `{id}` | Delete the block |

**Block PUT quirks:**
- The `version` field is **read-only** and must be omitted from the PUT body.
- Every item in `businessParameters` must have an `id` field (ULID). The CLI generates fresh ULIDs via `_generate_ulid()` when adding new parameters.
- ULIDs use **Crockford base32** encoding (10 timestamp chars + 16 random chars = 26 chars).
---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `TOSCA_TENANT_URL` | ✓ | Tenant root URL |
| `TOSCA_SPACE_ID` | | Space ID (default: `default`) |
| `TOSCA_TOKEN_URL` | ✓ | Okta OAuth2 token endpoint |
| `TOSCA_CLIENT_ID` | ✓ | OAuth2 client ID |
| `TOSCA_CLIENT_SECRET` | ✓ | OAuth2 client secret |
| `TOSCA_SCOPE` | | OAuth2 scope (default: `tta`) |
| `TOSCA_TIMEOUT` | | HTTP timeout in seconds (default: `30`) |
| `TOSCA_VERIFY_SSL` | | `false` to disable SSL verification |
| `TOSCA_OPENAI_KEY` | | OpenAI key for `ask` command |

---

## Token Caching

The OAuth2 Bearer token is cached at `token.json` in the project directory (mode `0600`) and
auto-refreshed 60 s before expiry.

```bash
rm token.json   # force token refresh
```

---

## API Reference

> **Official API docs:** [TOSCA Cloud APIs overview](https://docs.tricentis.com/tosca-cloud/en-us/content/references/tosca_apis.htm#playlist-api)

Each API also exposes a live Swagger UI at the path shown below (replace `{spaceId}` with yours):

> **Note on swagger accuracy:** The published Tricentis swagger specs occasionally diverge from live API behaviour. Known examples: the Inventory v3 search filter enum is documented as PascalCase (`Contains`, `And`) but the live endpoint only accepts lowercase; the Inventory v3 PATCH body format differs from the MBT builder PATCH format despite both referencing "JSON Patch". If a CLI method returns unexpected results or errors, cross-check against the live Swagger UI at your tenant URL — and consult the Known API Limitations section below.

| API | Base path | Swagger UI path |
|-----|-----------|-----------------|
| Identity | `/_identity/api/v1/` | `/_identity/apiDocs/swagger` |
| MBT/Builder | `/{spaceId}/_mbt/api/v2/builder/` | `/{spaceId}/_mbt/apiDocs/swagger` |
| Playlists | `/{spaceId}/_playlists/api/v2/` | `/{spaceId}/_playlists/apiDocs/swagger` |
| Inventory v3 | `/{spaceId}/_inventory/api/v3/` | `/{spaceId}/_inventory/apiDocs/swagger` |
| Inventory v1 *(undocumented)* | `/{spaceId}/_inventory/api/v1/` | — |
| Simulations | `/{spaceId}/_simulations/api/v1/` | `/{spaceId}/_simulations/apiDocs/swagger` |

---

## License

[MIT](LICENSE) © 2026 Alexander Bychinskiy
