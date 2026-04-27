---
name: tosca-commander-automation
description: "Use this skill for any task involving the on-prem Tricentis TOSCA Commander REST API (TCRS), driven by `tosca_commander_cli.py` against a workspace served by `Tricentis.Tosca.RestApiService` at /rest/toscacommander. Triggers on: opening a workspace; CRUD on TestCases/Modules/ExecutionLists/Requirements; running TestCases or ExecutionLists locally; TQL searches; pre-execution approval workflow; retrieving ExecutionLog files (logs, screenshots) per KB0021775. NOT for Tosca Cloud — see `tosca-automation` for that."
license: MIT
compatibility: "Python 3.10+. Packages: httpx typer[all] rich python-dotenv. Optional extras for Windows-auth: requests-negotiate-sspi (Negotiate) or httpx-ntlm (explicit-cred NTLM). Requires .env with TOSCA_COMMANDER_BASE_URL plus an auth combo. Run from the project root: python tosca_commander_cli.py <command>"
argument-hint: "Describe the on-prem Tosca task (e.g. 'list all TestCases in folder X', 'run ExecutionList LoginTests on the local agent', 'export screenshots from yesterday's failed run')"
metadata:
  author: bermudas
  version: "0.1"
---

## When to use this skill

Use this skill for any task that hits the **Tosca Commander REST Webservice (TCRS)** on-prem:

- **Workspace lifecycle** — open, get project ID, navigate components.
- **Object CRUD** — TestCase, Module, ExecutionList, Requirement, etc.
- **TQL search** — discover artifacts via Tricentis Query Language (the on-prem analog of Cloud's `inventory search`).
- **Local execution** — `task run <execListId>` is equivalent to pressing F6 in the Tosca Commander desktop app — runs on the local Commander process, no Distributed Execution required.
- **Logs & screenshots** — walk an `ExecutionLog` → `Subparts:AttachedExecutionLogFile`, then GET each file (per KB0021775).
- **Pre-execution approval workflow** — enable / disable / request / give, with mandatory `CheckInAll` after every workflow task.
- **Generic workspace tasks** — `CheckInAll`, `UpdateAll`, `CompactWorkspace`, `RevertAll`.

**Do NOT use this skill** for Tosca Cloud (`*.my.tricentis.com`) — that's `tosca-automation`. The two products share branding and concepts but have completely different REST surfaces, auth, and ID models.

## Architectural map

| Surface | Base URL | Service | Used by this skill |
|---|---|---|---|
| **Commander REST (TCRS)** | `(http\|https)://host:1111/rest/toscacommander` | `Tricentis.Tosca.RestApiService` | **YES** — the entire skill |
| AOS (REST execution dispatch) | `https://host/automationobjectservice` | Tosca Server | not in scope (Phase 2) |
| DEX (legacy SOAP execution dispatch) | `…/DistributionServerService/ManagerService.svc` | Tosca Server | never — superseded by AOS |
| Cloud MBT/Inventory | `https://*.my.tricentis.com/<space>/_*` | Tosca Cloud SaaS | use `tosca-automation` instead |

## Auth modes (pluggable, env-var driven)

Set in `.env`. The CLI's `_select_auth()` picks the first matching combo unless `TOSCA_COMMANDER_AUTH=<mode>` forces one explicitly.

| Mode | Env vars | Notes |
|---|---|---|
| `basic` (also AD) | `TOSCA_COMMANDER_USER` + `TOSCA_COMMANDER_PASSWORD` | Works for multi-user workspaces backed by AD; just feed `DOMAIN\user`. |
| `pat` | `TOSCA_COMMANDER_TOKEN` | Tricentis Server Repository workspaces. **A Tosca Server PAT is itself a base64-encoded JSON blob** (`{ClientId, ClientSecret, Scopes[]}`) — paste it verbatim from the Tosca Server profile page; do not decode/re-encode. The CLI sends it as `Basic base64(":<token>")` per TCRS convention. The blob's embedded `Scopes[]` enumerates every Tosca Server REST microservice the token may access (`DexApi`, `FileServiceApi`, `ProjectServiceApi`, `MbtServiceApi`, `ToscaAutomationObjectServiceApi`, `ExecutionResultServiceApi`, `RpaApiGatewayApi`, `LiveCompareServiceApi`, `LicenseAdministrationApi`, …) — useful for understanding what other services the same PAT could later unlock (Phase 2: AOS, FileService). |
| `client-creds` | `TOSCA_COMMANDER_CLIENT_ID` + `_CLIENT_SECRET` | OAuth2 against `<server>/tua/connect/token`. |
| `negotiate` | `TOSCA_COMMANDER_AUTH=negotiate` | IIS Windows Auth (NTLM/Kerberos via SSPI). Extra: `pip install requests-negotiate-sspi`. Windows-only. |
| `ntlm` | `TOSCA_COMMANDER_AUTH=ntlm` + USER + PASSWORD | Explicit-cred NTLM. Extra: `pip install httpx-ntlm`. |

`config test` is the source of truth — it does a version probe + optional workspace open and reports the active auth mode.

## Core principle — discover before acting

The TCRS surface has no listing endpoint for arbitrary types. Use **TQL** (Tricentis Query Language) as the discovery primitive — it's the on-prem analog of Cloud's `inventory search`.

```bash
# 1) Find the project root once (everything else hangs off it).
python tosca_commander_cli.py workspace project-root

# 2) TQL-search for artifacts. Default root = project root.
#    Convention: UPPERCASE axis names (=>SUBPARTS), PascalCase type names (TestCase),
#    PascalCase property names ([Status="Planned"]). TQL keywords are case-insensitive,
#    but UPPERCASE is the community style — keeps your queries copy-pasteable
#    alongside Tricentis sample scripts.
python tosca_commander_cli.py search tql '=>SUBPARTS:TestCase[Status="Planned"]'
python tosca_commander_cli.py search tql '=>SUBPARTS:Module[Name="Login"]'
python tosca_commander_cli.py search tql '=>SUBPARTS:ExecutionList'

# 3) Get a specific object's full representation.
python tosca_commander_cli.py objects get <UniqueId> --depth 2

# 4) Discover what tasks an object type exposes.
python tosca_commander_cli.py meta type TestCase
```

## Workflow discipline — one artifact at a time

1. **Discover** — `search tql` to find UniqueIds; `meta type` to see what tasks/properties are valid.
2. **Build** — `objects create --json-file body.json` under the right parent.
3. **Persist** — every workflow change (especially in approvals) **must be followed by `task workspace CheckInAll`** to commit to the workspace driver. Without it, your edits live only in the cached TCAPI instance and vanish when the cache (default 60 s, see `APIInstanceCachingTime` in `Web.config`) expires.
4. **Run** — `task run <execListId> --wait` for an ExecutionList; `task object <id> Run` for a single TestCase.
5. **Inspect** — on failure, walk the run's ExecutionLog: `files logs <execLogId> --ext png` (and `--ext '*'` for everything).
6. **Confirm writes** — after every PUT/POST mutation, `objects get <id>` and verify the change. The TCAPI shim sometimes silently caches stale state for up to 60 s — see "TCAPI instance caching" below.

## Critical caveats (build these into your model)

| Situation | What to do |
|---|---|
| **TCAPI instance caching (default 60 s)** | Tosca Server's `Web.config` has `APIInstanceCachingTime` (default 60 s). After a write, subsequent reads may return the cached pre-write state for up to that long. If a confirm-GET shows no diff, wait 60 s and re-GET before re-issuing the write. |
| **License caching (default 60 s)** | Same window for the Flexera license held against TCAPI. Bursts of >1 client per workspace may queue on license acquisition. |
| **Generic vs object tasks** | Generic (workspace-level) tasks: `task workspace <Name>` — `CheckInAll`, `UpdateAll`, `CompactWorkspace`, `RevertAll` only. Everything else is `task object <id> <Name>`. |
| **POST vs GET for tasks** | The CLI POSTs by default — required for binary or long-text params. Pass `--method get` only when invoking via shell history / convenience. |
| **TQL is case-sensitive** | `=>Subparts:TestCase` ≠ `=>Subparts:testcase`. Property comparators use C#-string semantics: `[Name=="X"]`. |
| **Approval workflow needs CheckInAll** | Every `approvals enable/disable/request/give` **must** be followed by `task workspace CheckInAll` or the workflow change is dropped. The CLI prints a reminder. |
| **`--workspace` placement** | Comes after the subcommand in Typer: `python tosca_commander_cli.py objects get --workspace MyWs <id>` ✓. Or set `TOSCA_COMMANDER_WORKSPACE` in `.env` once. |
| **`run --wait` polls the ExecutionList** | Polls every `--poll-interval` (default 5 s) until a property like `ActualLogState` / `Status` / `Result` reports a terminal value. Different Tosca versions expose state on different keys; the poller checks all three. |
| **Files come from FileService** (KB0021775) | `files logs <execLogId>` runs `=>Subparts:AttachedExecutionLogFile[FileExtension=="<ext>"]` first, then `GET /object/<fileObjId>/files/<fileId>` per match. The default `--ext png` retrieves screenshots; `--ext '*'` retrieves everything. |
| **Default delete prompts for confirmation** | `objects delete <id>` requires `--force` to skip the Y/N prompt. Mirror Cloud CLI behavior. |
| **Tosca Cloud ≠ Tosca Commander** | Don't reuse Cloud entityIds, ULIDs, or playlist IDs here. Commander uses 32-char `UniqueId` strings minted by TCAPI. |

## Working-file convention

Mirrors the Cloud CLI: scratch JSON bodies, TQL probes, and dumps go under `.claude/tmp/<YYYY-MM-DD>-<intent>.json` (gitignored). **Never** under `/tmp/` (Playwright MCP and the `.gitignore` cleanup pattern won't reach it).

## Quick smoke test

```bash
source .venv/bin/activate
python tosca_commander_cli.py config show                # confirm env vars
python tosca_commander_cli.py config test --workspace MyWs
python tosca_commander_cli.py workspace project-root --workspace MyWs
python tosca_commander_cli.py search tql '=>Subparts:TestCase' --workspace MyWs
```

## Decision tree

| Goal | First action |
|---|---|
| Find existing artifacts | `search tql '=>Subparts:<TypeName>[<predicate>]'` |
| Get one artifact in detail | `objects get <UniqueId> --depth N` |
| Discover what a type can do | `meta type <TypeName>` |
| Create a new object | `objects create <parentId> --json-file body.json`; body shape from `meta type` |
| Run a TestCase / ExecutionList locally | `task run <execListId> --wait` (ExecutionList) or `task object <tcId> Run` (TestCase) |
| Read run results | `files logs <execLogId>` for screenshots; `objects get <execLogId> --depth 2` for the full tree |
| Persist edits | `task workspace CheckInAll` — always after writes that the driver buffers |
| Pre-execution approval | `approvals enable` → `approvals request <tcId>` → reviewer runs `approvals give <tcId>` → `task workspace CheckInAll` |

## Round-trip pattern — recreate an object from a fetched body

`objects get` returns a TCAPI representation that's a **superset** of what `objects create` accepts: it includes server-minted fields (`UniqueId`, `Revision`, audit timestamps, `NodePath`) that POST will reject if you send them back as-is. The CLI ships three flags on `objects create` that make round-tripping clean:

| Flag | Effect |
|---|---|
| `--strip-server-fields` | Recursively removes `UniqueId`, `Revision`, `CreatedBy`, `CreatedAt`, `ModifiedBy`, `ModifiedAt`, `NodePath` from every dict in the body. Reference fields like `OwnerModuleReference` are NOT in this set — they hold *other* objects' UniqueIds and must survive. |
| `--rename-suffix STR` | Appends STR to the root object's `Name` (e.g. `_clone_v1`). Required when posting back into the same parent — Tosca names must be unique within a parent. |
| `--rewrite-ref OLD=NEW` | Repeatable. Replaces any string value equal to OLD with NEW anywhere in the body. Used for cross-object reference rewriting (swap a TestCase's module reference to a different module's UniqueId). |
| `--show-body` | Prints the post-transformation body to stderr before POSTing — verify your transformations applied as expected. |

**Recipe 1 — recreate a single object as a new sibling** (same workspace, no ref changes; module references stay pointing at the original modules):

```bash
python tosca_commander_cli.py objects get <srcId> --depth 5 > src.json
python tosca_commander_cli.py objects create <parentId> --json-file src.json \
    --strip-server-fields --rename-suffix "_clone"
python tosca_commander_cli.py task workspace CheckInAll
```

**Recipe 2 — recreate a TestCase pointing at a freshly recreated Module copy** (proves the reference-rewriting story end-to-end):

```bash
# 1) Source IDs
python tosca_commander_cli.py search tql '=>SUBPARTS:Module[Name="Login"]'    # → MOD_OLD
python tosca_commander_cli.py search tql '=>SUBPARTS:TestCase[Name="LoginTest"]'  # → TC_OLD

# 2) Recreate the Module first under the Modules folder
python tosca_commander_cli.py objects get $MOD_OLD --depth 3 > mod.json
python tosca_commander_cli.py objects create $MOD_PARENT --json-file mod.json \
    --strip-server-fields --rename-suffix "_v2"
# capture the new Module's UniqueId from the response → MOD_NEW

# 3) Recreate the TestCase, swapping refs from MOD_OLD to MOD_NEW
python tosca_commander_cli.py objects get $TC_OLD --depth 5 > tc.json
python tosca_commander_cli.py objects create $TC_PARENT --json-file tc.json \
    --strip-server-fields --rename-suffix "_clone" \
    --rewrite-ref $MOD_OLD=$MOD_NEW

# 4) Persist
python tosca_commander_cli.py task workspace CheckInAll
```

**When the build body is wrong** (HTTP 400 on create): the API's error string usually names the offending field. The most common surprises are:
- A reference field whose name *contains* `Id` but isn't a UniqueId (e.g. `LegacyId`) — these survive `--strip-server-fields` (correctly) but may need `--rewrite-ref` if the legacy values don't exist in the target.
- A property the source had set that the target rejects because it depends on a workspace-scoped enum (e.g. `Owner`).

Pass `--show-body` to print the post-transformation JSON to stderr and inspect what's about to land.

## TQL recipe library — execution history (the day-to-day workflow)

The single highest-value type for a test automation engineer is **`ExecutionLogEntry`** — one record per executed TestCase. Properties confirmed from a 2026-vintage Tosca Server (community script `Achoo0-Adam/Tosca-TQL-Export-`):

| Property | Type | Notes |
|---|---|---|
| `Name` | string | Display name of the run |
| `NodePath` | string | Slash-delimited path inside the workspace (`/ExecutionLists/Sprint 42/My Test Run`) |
| `UniqueId` | 26-char Crockford base32 (ULID) | e.g. `01KF3FGGNNCC98DADNTGARBQAB` — same encoding as Cloud ULIDs |
| `ExecutionStatus` | enum | `Passed` \| `Failed` \| `Skipped` \| `NotExecuted` (others may exist) |
| `TestCaseName` / `TestCaseUniqueId` | strings | The TestCase that produced this log |
| `StartedAt` / `EndedAt` | ISO date | Use ISO `YYYY-MM-DD` literals in TQL filters |
| `Duration` | seconds | |
| `ExecutionEnvironment` | string | Free-text per the run's config |
| `ExecutionListName` / `ExecutionListUniqueId` | strings | Parent ExecutionList |
| `CreatedBy` / `CreatedAt` / `ModifiedBy` / `ModifiedAt` | audit fields | |
| `Description` / `Revision` | strings | |

The screenshot/log files for a given entry are reachable via the `Subparts` axis:

```
=>SUBPARTS:AttachedExecutionLogFile[FileExtension="png"]
=>SUBPARTS:AttachedExecutionLogFile[FileExtension="txt"]
=>SUBPARTS:AttachedExecutionLogFile          # all of them
```

**Ready-to-paste TQL** (root: project root unless otherwise noted):

```bash
# All execution history (warning: large workspaces — bound by date below).
python tosca_commander_cli.py search tql '=>SUBPARTS:ExecutionLogEntry'

# Failures only — the most common diagnostic query
python tosca_commander_cli.py search tql '=>SUBPARTS:ExecutionLogEntry[ExecutionStatus="Failed"]'

# Yesterday's runs (ISO date literal, no quotes around the date)
python tosca_commander_cli.py search tql "=>SUBPARTS:ExecutionLogEntry[StartedAt>='2026-04-26' AND StartedAt<='2026-04-27']"

# All runs of a specific TestCase by name
python tosca_commander_cli.py search tql '=>SUBPARTS:ExecutionLogEntry[TestCaseName="Login flow"]'

# Combine: failures of a specific TestCase since a date
python tosca_commander_cli.py search tql "=>SUBPARTS:ExecutionLogEntry[TestCaseName='Login flow' AND ExecutionStatus='Failed' AND StartedAt>='2026-04-01']"

# Top-level ExecutionLists (the containers you can `task run`)
python tosca_commander_cli.py search tql '=>SUBPARTS:ExecutionList'

# Author-side discovery: TestCases by status / by parent folder
python tosca_commander_cli.py search tql '=>SUBPARTS:TestCase[Status="Planned"]'
python tosca_commander_cli.py search tql '=>SUBPARTS:Module[Name="Login"]'

# Pull the screenshot files from a single failed run
python tosca_commander_cli.py files logs <ExecutionLogEntry-UniqueId> --ext png

# Pull every attached file (logs.txt, screenshots, …) from an ExecutionList tree
python tosca_commander_cli.py files logs <ExecutionList-UniqueId> --ext '*'
```

**TQL syntax notes**:
- Axes (`SUBPARTS`, `PARTS`, `OBJECT`) are **case-insensitive** but UPPERCASE is the convention everyone copies from.
- Type names (`ExecutionLogEntry`, `TestCase`) are PascalCase.
- Property comparators accept both `=` and `==`; quoted (`"X"`) and unquoted (`X`) literals both work for string equality. **For date literals, do not quote** — `StartedAt>=2026-04-01` works; `StartedAt>='2026-04-01'` works; bare `StartedAt>=2026/04/01` may also work depending on Tosca version (ISO-dash format is the safest).
- Combine clauses with `AND` / `OR` (uppercase).
- Predicates can chain: `[Status="Planned"] AND [Owner="alice"]` is valid.
- Use single quotes inside double-quoted shell args (or vice versa) to avoid shell-escaping pain.

## Server-side troubleshooting (no REST endpoint)

Some operational signals **cannot** be retrieved via TCRS — they live on the server's filesystem. Don't waste time hunting a non-existent REST route for these:

| What | Where (on the Tosca Server host) | Notes |
|---|---|---|
| Tosca Server **service logs** (gateway, AOS, DEX, FileService, MBT, ProjectService, …) | `%PROGRAMDATA%\TRICENTIS\ToscaServer\Logs\<ServiceName>\` | Per-service folders; rotated automatically. **No REST endpoint exposes these** — by design. To collect them, run `Achoo0-Adam/ToscaServerLogCapture` (PowerShell, on the server) or grab the folder over RDP/SMB. |
| Tosca **support logs** (Commander, Designer, Studio crash dumps & misc) | `%PROGRAMDATA%\TRICENTIS\Logs\` | Same access pattern — filesystem only. |
| **Workspace files** (.tws) | `<WorkspaceBasePath>\<WorkspaceName>\<WorkspaceName>.tws` | The path configured in `appsettings.json` of `Tricentis.Tosca.RestApiService`. The workspace name in CLI commands maps to the folder name, **not** the `.tws` file name (though typically they match). |
| **TCRS REST API config** | `C:\Program Files (x86)\TRICENTIS\Tosca Server\RestApiService\appsettings.json` | Restart the `Tricentis.Tosca.RestApiService` Windows service after edits. Cache settings live in the service's `Web.config` (see "TCAPI instance caching" caveat). |

**Execution logs (TestCase results) are different from server service logs** — they ARE accessible via REST as `ExecutionLogEntry` objects + their `Subparts:AttachedExecutionLogFile` (KB0021775). The `commander files logs <ExecutionLogEntry-id>` command wraps that walk.

## Cross-reference

- Source of REST endpoint surface: `documentation.tricentis.com/devcorner/2024.1/tcrsapi/` (REST API / Requests / Object revisions / Caching).
- Troubleshooting: KB0012713 — health checks, common HTTP/auth/proxy errors.
- Screenshot retrieval pattern: KB0021775.
- AOS scheduling pattern (Phase 2 candidate, **out of this skill**): KB0019429.
- The konopski/tosca-commander-api Jython wrapper covers the same endpoints and is a good cross-reference for body shapes.
- The Achoo0-Adam/Tosca-TQL-Export- PowerShell script is the source for the `ExecutionLogEntry` property table and the recipe library above. It uses TCAPI .NET assemblies directly, **not** REST — useful as a property reference, not a transport reference.
- The Achoo0-Adam/ToscaServerLogCapture PowerShell script is the source for the server-side log path layout. It is purely filesystem-based and runs on the server itself.
