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
| `pat` | `TOSCA_COMMANDER_TOKEN` | Tricentis Server Repository workspaces. Sent as `Basic base64(":<token>")`. |
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
python tosca_commander_cli.py search tql '=>Subparts:TestCase[Status=="Planned"]'
python tosca_commander_cli.py search tql '=>Subparts:Module[Name=="Login"]'
python tosca_commander_cli.py search tql '=>Subparts:ExecutionList'

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

## Cross-reference

- Source of REST endpoint surface: `documentation.tricentis.com/devcorner/2024.1/tcrsapi/` (REST API / Requests / Object revisions / Caching).
- Troubleshooting: KB0012713 — health checks, common HTTP/auth/proxy errors.
- Screenshot retrieval pattern: KB0021775.
- AOS scheduling pattern (Phase 2 candidate, **out of this skill**): KB0019429.
- The konopski/tosca-commander-api Jython wrapper covers the same endpoints and is a good cross-reference for body shapes.
