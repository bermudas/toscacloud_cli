# TOSCA Cloud CLI — Project Guide for Claude

## What this project is

A Python CLI (`tosca_cli.py`) for Tricentis TOSCA Cloud REST APIs. Single-file, no hidden packages.
Covers: Identity, MBT/Builder v2 (test cases, modules, reuseable blocks), Playlists v2, Inventory v3 + v1 (undocumented folder ops), Simulations v1.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then fill in your credentials
python tosca_cli.py config test
```

Config and token cache live in the project directory (`.env`, `token.json`) — never in `~/.tosca_cli`.

## Architecture

Single file, no sub-packages:
- `ToscaClient` class — all HTTP calls, one method per API endpoint. URL builders: `identity()`, `mbt()`, `playlist()`, `inventory_url()`, `inventory_v1_url()`, `simulations_url()`, `e2g_url()`.
- Typer sub-apps: `config_app`, `identity_app`, `cases_app`, `modules_app`, `blocks_app`, `playlists_app`, `inventory_app`, `simulations_app`.
- `_get_access_token()` — OAuth2 client_credentials, token cached in `token.json` (0600), auto-refreshed 60 s before expiry.
- `_output_json()` — Rich syntax-highlighted JSON when stdout is a tty, plain `print(raw)` otherwise (for piping). Place `--json` **before** positional args.
- `_generate_ulid()` — Crockford base32 ULID generator, used for fresh IDs in block parameters and test case step references.

## Key patterns

**Always discover before acting** — the MBT API has no list endpoint for user artifacts; use Inventory for those and `/packages` for engine-bundled Standard modules:
```bash
python tosca_cli.py inventory search "<name>" --type TestCase --json
python tosca_cli.py cases get --json <caseId>          # ground-truth metadata
python tosca_cli.py cases steps <caseId>               # step tree with all module/attr IDs
```

**Standard modules (OpenUrl, CloseBrowser, Wait, Execute JavaScript, Verify JavaScript Result, DB/HTTP/File/Mail etc.) don't appear in inventory** — they're bundled with the agent. Discover via:
```python
# one-liner — requires `source .venv/bin/activate`
python -c "import sys;sys.path.insert(0,'.');from tosca_cli import ToscaClient;c=ToscaClient();import json;print(json.dumps(c.get(c.mbt('packages')),indent=2))" | less
# full attribute tree for a specific standard module (replace <pkg> and <moduleGuid>)
python -c "import sys;sys.path.insert(0,'.');from tosca_cli import ToscaClient;c=ToscaClient();import json;print(json.dumps(c.get(c.mbt('packages/<pkg>/modules/<moduleGuid>')),indent=2))"
```
Validated Html-package module GUIDs (appear to be platform constants — the engine's dispatch keys): `OpenUrl=9f8d14b3-7651-4add-bcfe-341a996662cc`, `CloseBrowser=3019e887-48ca-4a7e-8759-79e7762c6152`, **`Execute JavaScript=54f432f6-61ed-4c9a-a7dc-9e3970a08323`**, **`Verify JavaScript Result=a9cc198f-ae01-4665-ac02-5000d6b0c7de`**, `Wait (Timing)=80b7982e-0e10-4bc0-bdf3-6bc04503fd63`. **Attribute GUIDs inside these modules are NOT guaranteed stable across tenants — always re-discover them via `packages/<pkg>/modules/<moduleGuid>` on the target tenant** rather than copying from docs or another project. See `.claude/skills/tosca-automation/references/standard-modules.md` for the full discovery workflow and step-JSON skeleton.

**When the Html scanner is blind to body content** (header findable, body not; `browser_evaluate` confirms element is in the top-level DOM; no iframe / shadow DOM / CSS-hidden ancestor): pivot to `Verify JavaScript Result` instead of iterating Steering params. It dispatches through `SpecialExecutionTask: VerifyJavaScriptResult` (CDP `Runtime.evaluate`), bypassing the AutomationExtension DOM observer. Module-level Steering flags (`IgnoreInvisibleHtmlElements`, `ScrollToFindElement`, `UseWebDriverSteeringExclusively`, `IframeProcessingEnabled`, etc.) do **not** unblock scanner-blindness — the root cause is in the observer injection pipeline (tenant-level `Disable Ajax Tracer injection on pages` setting, or a page hydration race), not in element visibility filtering.

**`{SCRIPT[...]}` / `{XP[...]}` / `{EVAL[...]}` dynamic expressions are not registered** on Tosca Cloud (`No suitable value found for command SCRIPT.`). The only way to run JS from a test step is the standard modules above.

**Do not attempt `OpenUrl("javascript:…")` as a DIY JS-execution hack.** Chrome does accept the navigation and the JS runs, but the resulting tab ends up in a state where TBox can bind the window by Title/URL yet cannot find ANY element inside it (not even `<body>` / `<html>` / `<head>`). Dead end for verification. Use `Verify JavaScript Result`.

**Block IDs** — `inventory search --type Module` returns module entity IDs, not block IDs. Get block IDs from a test case: `cases get --json <caseId>` → `testCaseItems[].reusableTestStepBlockId` where `$type == "TestStepFolderReferenceV2"`.

**`--json` flag** — must go before positional arguments: `cases get --json <id>` ✓. Using `--` separator causes Typer to treat `--json` as a positional, silently falling back to Rich output.

**Inventory PATCH vs MBT PATCH** — two different formats:
- Inventory v3 PATCH: `{"operations": [{"op": "Replace", ...}]}` (wrapper object, PascalCase op)
- MBT builder PATCH: `[{"op": "replace", ...}]` (bare array, lowercase op)

**Confirm every write landed — CLI `✓` / HTTP 204 / `{}` are not proof.** After every mutation (`cases patch`, `cases update`, `modules update`, `blocks update`, `inventory patch`), GET the artifact and assert both (a) `version` field bumped, and (b) the specific field you edited actually changed. MBT PATCH silently accepts and drops unsupported ops — observed silent no-op surfaces: deep JSON-pointer paths into nested step trees (e.g. `/testCaseItems/N/items/M/testStepValues/K/value`), `remove` on array elements, `move`. Inventory v3 silently ignores MBT-shape bodies (bare array / lowercase op) the same way. When a confirm-GET shows no diff, fall back to full PUT (`cases update --json-file`, `modules update --json-file`, etc.). A throwaway probe like `{"op":"replace","path":"/description","value":"probe"}` round-trip is enough to calibrate whether the endpoint is applying your ops before you send real ones.

**`"` inside a Verify/Execute JavaScript value silently breaks the step.** TBox's dynamic-value parser treats `"` at the JS value root as an expression delimiter (same as `{` and `[`). A value like `return document.querySelectorAll("h2.stripe_title").length.toString()` returns an empty string (`Actual: ""`) even though the JS is valid and `document.title` access in the same step works. Wrapping in an IIFE surfaces the diagnostic `Token is not valid in this context: "`. **Fix**: use `'single quotes'` in the JS — `return document.querySelectorAll('h2.stripe_title').length.toString()`. Full detail + reproduction trace: `.claude/skills/tosca-automation/references/standard-modules.md`.

**Mega-menu `{MOUSEOVER}` from trigger to deep submenu link often fails even when the selector is correct.** A straight-line diagonal mouse move crosses sibling top-level triggers (Products / Patients / Research / …) and swaps the open panel mid-flight — the subsequent `{CLICK}` then sees the target as invisible and times out (`Link '…' is not steerable`). Two fixes in order of preference: (1) `{MOUSE[MOUSEOVER][HorizontalFirst]}` single-step L-path on the target Link, or (2) add a **waypoint attribute** to the module — a link on the same y-row as the top-level trigger, inside the opened submenu's column — and `MOUSEOVER` it between the trigger hover and the target hover. Full pattern + Novartis reproduction in `.claude/skills/tosca-automation/references/web-automation.md`.

**`Verify JavaScript Result` returns empty `Result` silently when tab-pattern match fails** — unlike GUI Html modules which raise `No matching tab was found`, a VJS step with `UseActiveTab=False` + `Title`/`Url` patterns that match zero tabs produces `Actual: ""` (and Verify mismatches). Same on-screen surface as the `"`-in-JS trap, different root cause. When you need a tab-bound JS execute and the patterns might not match, prefer `UseActiveTab=True` (skip the Search Criteria lookup — JS runs on whatever Chrome has focused) or verify the Title/Url first with a GUI `WaitOn` on a page element.

**Verify JS Result module metadata is tenant-specific.** On the validated sandbox tenant the module is packaged with `Engine: Html` + `SpecialExecutionTask: VerifyJavaScriptResult` — and server-side PUT reverts any attempt to set `moduleReference.metadata.engine=Framework`; other tenants in the reference material use `Engine: Framework`. **Always fetch the actual module** via `GET /_mbt/api/v2/builder/packages/Html/modules/a9cc198f-ae01-4665-ac02-5000d6b0c7de` and copy its `metadata.engine` verbatim rather than hard-coding from another project.

**Inventory search operators** — despite swagger showing PascalCase (`Contains`, `And`), the live API only accepts lowercase: `contains`, `and`.

**Test case assembly** — when building new cases, always clone an existing one as a template. Each `TestStepFolderReferenceV2` needs a fresh `parameterLayerId` (ULID) and each parameter entry needs `referencedParameterId` pointing to the block's `businessParameter.id`.

**MBT test case ID = Inventory `entityId`** — `cases get`/`cases steps`/`cases update` accept the Inventory `entityId` (e.g. `WcucATcH0UKiiL9aoQsJyg`). The playlist item's own `id` field and the inventory record's `attributes.surrogate` UUID **both 404** against the MBT API. Always resolve via `inventory search … --type TestCase --json` → `id.entityId` and pass that verbatim.

**Debugging failed playlist runs** — Playlists v2 only returns a bare `<failure />` JUnit. The real per-step agent log lives behind the E2G API and is reachable from the CLI:

```bash
python tosca_cli.py playlists logs <runId>                  # prints logs.txt for each unit
python tosca_cli.py playlists logs <runId> --save ./logs    # download all attachments per unit
python tosca_cli.py playlists attachments <runId>           # table of SAS URLs per unit
```

3-step recipe these commands wrap (`Tricentis_Cloud_API` works as-is — no extra role needed):
1. `GET /{spaceId}/_playlists/api/v2/playlistRuns/{runId}` → read `executionId`.
2. `GET /{spaceId}/_e2g/api/executions/{executionId}` → run doc with `items[]` (one `UnitV1` per test case, each with `id`, `name`, `state`, `assignedAgentId`).
3. `GET /{spaceId}/_e2g/api/executions/{executionId}/units/{unitId}/attachments` → SAS-signed Azure Blob URLs: `logs.txt`, `JUnit.xml`, `TBoxResults.tas`, `TestSteps.json`, `Recording.mp4` (only when recorded). SAS TTL ≈ 30 min; the blob GET needs **no Authorization header** — the signature is the entire auth.

**Critical ID mapping**: `playlistRun.id` (e.g. `0d0e40dc-…`) **does not** resolve under `_e2g/api/executions/` — it 404s. Always use `playlistRun.executionId` (e.g. `7041def3-…`). The CLI commands above resolve this for you; pass `--execution-id / -e` to skip the lookup if you already have the executionId.

Alternative source: the local E2G agent mirror at `C:\Users\<user>\AppData\Local\Temp\E2G\…` (same content, no SAS expiry).

## Agent & skill wiring in this repo

All AI coding tools share one storage layout — no mirroring or symlinks needed:

| What | Path | Who reads it |
|------|------|--------------|
| Skills ([agentskills.io](https://agentskills.io) spec) | `.claude/skills/<name>/SKILL.md` + `references/` + `scripts/` | Claude Code, GitHub Copilot (CLI + VS Code), Cursor, Gemini CLI, OpenAI Codex, etc. — all recognize `.claude/skills/` as an official skill directory |
| Claude Code subagent | `.claude/agents/<name>.md` | `Agent` tool with `subagent_type: <name>` |
| VS Code Copilot custom agent / chat mode | `.github/agents/<name>.agent.md` | Copilot in VS Code |
| Repo-wide Claude brief | `CLAUDE.md` (this file) | Claude Code |
| Repo-wide Copilot brief | `.github/copilot-instructions.md` | GitHub Copilot |
| Tool-agnostic pointer | `AGENTS.md` at root | Many agents recognize this by convention |
| MCP servers | `.mcp.json` (Claude) + `.vscode/mcp.json` (VS Code) | Each tool has its own |

Current skills: `tosca-automation` (TOSCA Cloud full lifecycle), `browser-verify` (real-mouse CDP browser inspection).
Current subagents: `tosca` (delegated TOSCA work in isolated context).

When adding a new skill, put it under `.claude/skills/` — both Claude and Copilot will pick it up.

## Polling personal-agent run results via MCP

The CLI's `playlists status/logs` returns **403** on personal-agent runs — `Tricentis_Cloud_API` can't see them. Use MCP:

1. **Authoritative pass/fail for a specific playlist** — `mcp__ToscaCloudMcpServer__GetRecentPlaylistRunLogs(playlistId)`. Returns a succeeded-and-failed-log pair; `["No succeeded runs found."]` means the latest run for that playlist did **not** pass.
2. **Find an executionId for your run** — `mcp__ToscaCloudMcpServer__GetRecentRuns({nameFilter: "<exact playlist name>"})`. The `nameFilter` must be the **exact** playlist name including any em-dash (`—`, `\u2014`) / en-dash; partial substring doesn't match. Returns executionIds for runs of that playlist.
3. **Inspect failures** — `mcp__ToscaCloudMcpServer__GetFailedTestSteps({runIds: ["<executionId>"]})`. Requires the **executionId**, not the `playlistRun.id` returned by `RunPlaylist` — passing the latter errors with `"Run with the specified ID doesn't exist."`
4. **Do not** trust `GetRecentRuns({stateFilter})` without `nameFilter` — it returns ~10 executionIds sorted alphabetically by UUID (not by time) and you can't tell which is yours. Always filter by name.

Compact recipe after `RunPlaylist(...runOnAPersonalAgent=true)`:
```
wait ~60–120s
runs = GetRecentRuns({ nameFilter: "<playlist-name-with-em-dash>" })
newExec = pick id not in previously-seen set
GetFailedTestSteps({ runIds: [newExec] })
```

## Iterative test-development loop (Local Runner + MCP)

The fastest debug loop for a brand-new test case is to bind it to the user's **own machine as a personal agent** and re-run via MCP after each fix. This is the path the Portal's "Run on personal agent" button uses.

### One-time setup on the developer machine
1. Install the **Tosca Local Runner / Cloud Agent** (a.k.a. E2G personal agent) — registers under the developer's user identity in TOSCA Cloud.
2. Install and enable the **Tricentis Automation Extension** in Chrome and/or Edge (the browser the test will drive).
3. Keep the target browser window **maximized** during the run — TOSCA matches elements relative to viewport coordinates and shrunken / minimized windows cause `Element not in view` / `Coordinate out of bounds` failures.

### CLI vs MCP — identity matters
- **CLI** (`tosca_cli.py`) uses `Tricentis_Cloud_API` (`client_credentials`). It can only see and dispatch to **shared / team / cloud** agents (`"private": false` in `_e2g/api/agents`). Personal agents are filtered out — `GET /_e2g/api/agents/<personalAgentId>` returns **403 "Unauthorized access to agent"**, and any `playlists run` will sit `pending` forever.
- **MCP** (`ToscaCloudMcpServer`) is wired in `.vscode/mcp.json` via `mcp-remote` with PKCE OAuth. First connection opens a browser, the developer logs in to Okta as themselves, and the refresh token is cached. From then on every MCP call carries the **developer's user identity**, so it can list, dispatch to, and read runs from the developer's personal agent.

### The loop
```
1. Explore the target site/screen with Playwright MCP
   - browser_navigate <url> → browser_snapshot → identify elements
   - For Web: find Tag / InnerText / HREF / unique ClassName
   - Run browser_evaluate to confirm the locator is unique (querySelectorAll(...).length === 1)

2. Build / update the test artifacts with the CLI (service-account is fine here)
   - python tosca_cli.py modules create / modules update --json-file …
   - python tosca_cli.py cases create / cases update --json-file …

3. Trigger on the developer's personal agent via MCP
   - mcp__ToscaCloudMcpServer__RunPlaylist(playlistId, runOnAPersonalAgent=true)
   - Local Runner picks it up; the developer sees the maximized browser drive itself

4. Poll completion via MCP (CLI can't see private runs — 403)
   - mcp__ToscaCloudMcpServer__GetRecentRuns({stateFilter: "Succeeded"|"Failed"|"Running"})
   - The newly returned id is your executionId

5. On failure, inspect via MCP
   - mcp__ToscaCloudMcpServer__GetFailedTestSteps({runIds:[<executionId>]})
   - Returns the per-step failure tree with the engine's exact message ("No matching tab", stack trace, etc.)

6. Fix the offending module/step in the CLI, go back to step 3
```

The playlist itself doesn't need any `AgentIdentifier` characteristic — `runOnAPersonalAgent: true` is the entire routing instruction. The CLI's service-token-side `playlists logs` only works for shared-agent runs; for personal-agent runs use MCP for both triggering *and* failure inspection.

## Running a quick smoke test

```bash
python tosca_cli.py config test
python tosca_cli.py inventory search "login" --type TestCase
python tosca_cli.py playlists list
```

## Adding a new CLI command

1. Add a `ToscaClient` method with a docstring: HTTP verb, endpoint path, return type.
2. Add a Typer command on the relevant `*_app` with `--json` flag and Rich output.
3. Update `README.md` Command Reference section.
4. If it exposes a new API quirk, add a row to the Known API Limitations table in `README.md`.

## Files

| File | Purpose |
|------|---------|
| `tosca_cli.py` | Entire CLI — `ToscaClient` + all Typer commands |
| `.env` / `.env.example` | Credentials (`.env` is gitignored) |
| `token.json` | Cached OAuth2 token (gitignored) |
| `requirements.txt` | Runtime dependencies |
| `swaggers/` | Tenant-specific swagger exports for reference (gitignored) |
| `README.md` | User-facing docs |
| `CLAUDE.md` | This file — project guide for Claude Code |
| `.github/agents/tosca.agent.md` | TOSCA Automation agent instructions (full reference: decision tree, CLI commands, caveats, Web + SAP how-to) |
| `.claude/skills/tosca-automation/SKILL.md` | Agent Skills package (agentskills.io spec) — project skill, auto-discovered by Claude Code |
| `.claude/skills/tosca-automation/references/web-automation.md` | Html engine how-to (module structure, standard module IDs, Playwright discovery, 4-folder pattern) |
| `.claude/skills/tosca-automation/references/sap-automation.md` | SapEngine how-to (standard module IDs, Precondition block, RelativeId patterns, ControlFlowItemV2) |
| `.claude/skills/tosca-automation/references/blocks.md` | Reusable blocks deep dive (block↔case wiring, parameterLayerId, ULID rules, extend workflow) |
| `.claude/skills/tosca-automation/references/standard-modules.md` | Standard modules discovery + Execute/Verify JavaScript reference (Html package GUIDs, full attribute-ID trees, ready-to-paste JSON step skeletons, Drupal-blindness case study) |
| `.claude/skills/tosca-automation/references/best-practices.md` | Condensed summary of the 10 official Tricentis Best Practices KBs — module identification priority, TestCase structure, forbidden action patterns |

## Dependencies (requirements.txt)

`httpx`, `typer[all]`, `rich`, `python-dotenv` — no ORM, no frameworks.
