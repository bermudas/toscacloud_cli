# GitHub Copilot Instructions — TOSCA Cloud + Commander CLIs

## Project overview

Two sibling Python CLIs in one repo:

- **`tosca_cli.py`** — Tricentis **TOSCA Cloud** (multi-tenant SaaS). `ToscaClient` class, OAuth2 client_credentials, MBT / Inventory / Playlists / Identity / Simulations.
- **`tosca_commander_cli.py`** — Tricentis **TOSCA Commander** (on-prem REST Webservice, `/rest/toscacommander`). `ToscaCommanderClient` class, pluggable auth (Basic / PAT / OAuth2 / Negotiate / NTLM), workspace + object CRUD + TQL + tasks + files + approvals.

Both files are top-level modules, no hidden packages. Typer sub-apps expose commands per surface. They share `.env` (different prefixes: `TOSCA_*` vs `TOSCA_COMMANDER_*`) and Rich/JSON output conventions, but no class hierarchy.

When the user describes an on-prem workspace (`Tricentis.Tosca.RestApiService`, `localhost:1111`, `WorkspaceBasePath`, TCAPI, multi-user workspace, AD auth), prefer `tosca_commander_cli.py`. When they mention `*.my.tricentis.com`, MBT, Inventory entityIds, Okta, or playlists, use `tosca_cli.py`. The two are not interchangeable — IDs and bodies don't transfer.

For the on-prem skill reference (TQL syntax, approval workflow, KB0021775 screenshot pattern), see `.claude/skills/tosca-commander-automation/SKILL.md`.

## Agents + skills layout (shared with Claude Code)

- **Skills** (agentskills.io spec) live at `.claude/skills/<name>/SKILL.md` — Copilot (CLI + VS Code) and Claude Code both auto-discover this path; no mirroring needed. Current skills: `tosca-automation`, `browser-verify`.
- **VS Code Copilot custom agent** at `.github/agents/tosca.agent.md` — full TOSCA operator persona with VS Code-native tool bindings.
- **Claude Code subagent** at `.claude/agents/tosca.md` — same persona for Claude's `Agent` tool.
- **Tool-agnostic repo brief** at `/AGENTS.md` — pointer index; `.github/copilot-instructions.md` (this file) and `/CLAUDE.md` hold the tool-specific details.
- **MCP servers** configured in `.mcp.json` (Claude) and `.vscode/mcp.json` (VS Code) — the TOSCA Cloud MCP server is wired via `mcp-remote` with PKCE OAuth for the developer's identity.

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

- **Standard modules — discover via `/packages`**: `GET /_mbt/api/v2/builder/packages` returns every engine-bundled package (Html, Timing, ProcessOperations, Mail, JSON, Database, BasicWindowOperations, TBox Automation Tools, etc.) and every module's name + GUID. Fetch the full attribute tree per module via `GET /_mbt/api/v2/builder/packages/{packageId}/modules/{moduleId}`. Standard-module GUIDs are stable across tenants — hard-code them. These modules do **not** appear in `inventory search --type Module` (that endpoint only lists user-created artifacts). Always check `/packages` **before** building a custom wrapper. Known Html-package GUIDs: OpenUrl `9f8d14b3-7651-4add-bcfe-341a996662cc`, CloseBrowser `3019e887-48ca-4a7e-8759-79e7762c6152`, **Execute JavaScript `54f432f6-61ed-4c9a-a7dc-9e3970a08323`**, **Verify JavaScript Result `a9cc198f-ae01-4665-ac02-5000d6b0c7de`**. Full per-attribute map in `.claude/skills/tosca-automation/references/standard-modules.md`.
- **Execute / Verify JavaScript — the CDP escape hatch**: when the legacy Html scanner can't see body content on a page (symptom: `Could not find …` / `WaitOn Actual=False` while `browser_evaluate` confirms the element exists in DOM, and no iframe/shadow-DOM/CSS-hidden ancestor explains it), do NOT try to fix it by tweaking Steering flags. The blindness is in the AutomationExtension's DOM observer (tenant `Disable Ajax Tracer injection on pages` setting, Drupal/React hydration, etc.). Use the `Verify JavaScript Result` standard module — its `SpecialExecutionTask: VerifyJavaScriptResult` dispatch uses CDP `Runtime.evaluate` and bypasses the scanner entirely. Mandatory: the JavaScript attribute must include `return`; **ALL `{` and `}` anywhere in the JS string are TBox expression delimiters** (not just at the top level — even callback bodies like `function(a){return a.text}` fail; the IIFE pattern is equally unsafe); set `Search Criteria → UseActiveTab = False` when you supply Title/Url. `{SCRIPT[...]}` and `{XP[...]}` dynamic value expressions are **not registered** on Tosca Cloud — the only JS path is these standard modules.
- **Write all VJS JavaScript brace-free and single-quote-only.** TBox's dynamic-value parser treats `{`, `}`, and `"` as expression delimiters throughout the entire JS string. Use arrow expressions (`a => a.text`), ternary+comma (`el ? (el.click(), 'clicked') : 'not found'`), and `var x = expr;` statements. Never use `function(a){...}` callback bodies, `if/else` blocks, or object literals `{key: val}` inside the JS string.
- **`el.click()` in VJS JS can be silently intercepted — use `window.location.href = el.href` instead.** CMS frameworks (Drupal `data-extlink=""`, React/Vue synthetic events) attach click listeners that call `event.preventDefault()`, cancelling navigation. The JS returns its value normally (no error), but the page URL is unchanged. Diagnosis: VJS step reports "clicked", subsequent URL-verify step fails with the old URL. Fix: `window.location.href = el.href` bypasses all event handlers.
- **VJS probe for robust conditional CloseBrowser.** Use a VJS step as the `ControlFlowItemV2 If` condition instead of an Html-module element Verify: `UseActiveTab=False + Title=*<AppName>* + JS: return 'present' + Result Verify 'present'`. When no matching tab exists, VJS silently returns `""` → Verify mismatches → condition false → CloseBrowser skipped. When the tab is open, VJS returns `"present"` → condition true → CloseBrowser runs. No scanned module required; handles "browser not running at all" cleanly.
- **`"` in a Verify/Execute JavaScript value silently returns empty.** TBox's dynamic-value parser treats `"` at the JS value root as an expression delimiter (same as `{` and `[`). A value like `return document.querySelectorAll("h2.stripe_title").length.toString()` silently comes back as `Actual: ""` even though the JS is valid and `document.title` in the same step works. Wrapping in an IIFE surfaces the diagnostic `Token is not valid in this context: "`. **Fix**: use `'single quotes'` in the JS — `return document.querySelectorAll('h2.stripe_title').length.toString()`. If you truly need `"` in the body (e.g. literal URL in a JSON payload), triple them: `"""https://host"""`.
- **VJS module metadata is tenant-specific**: the reference calls for `moduleReference.metadata.engine = "Framework"`, but on some tenants the module is actually packaged with `Engine: Html` + `SpecialExecutionTask: VerifyJavaScriptResult` — server-side PUT reverts any cross-tenant value. Always fetch the actual module via `GET /_mbt/api/v2/builder/packages/Html/modules/<guid>` and copy its `metadata.engine` verbatim instead of hard-coding from another project.
- **`Verify JavaScript Result` returns `""` silently when tab patterns don't match** — unlike GUI Html modules which raise `No matching tab was found`, a VJS step with `UseActiveTab=False` + non-matching `Title`/`Url` produces `Actual: ""`. Same symptom as the `"`-in-JS trap, different root cause. Prefer `UseActiveTab=True` when the clicked navigation leaves the target as Chrome's active tab, or gate the VJS step behind a `WaitOn` of a GUI-module element that can only exist on the target page.
- **Inventory v3 PATCH body**: `{"operations": [{"op": "Replace", ...}]}` — wrapper object, PascalCase op. A MBT-shape body (bare array, lowercase) is accepted, 204'd, and ignored.
- **MBT builder PATCH body**: `[{"op": "replace", ...}]` — bare array, lowercase op. Unsupported ops are **silently dropped**: deep JSON-pointer paths into nested step trees (`/testCaseItems/N/items/M/testStepValues/K/value`), `remove` on array elements (`/testCaseItems/N/items/M`), and `move` all return 204 with zero changes. For structural edits, use full PUT (`cases update --json-file`) instead.
- **Always confirm mutations landed**: `cases patch` / `cases update` / `modules update` / `blocks update` / `inventory patch` all have silent-no-op modes — the CLI's `✓ …` line and the API's 204/`{}` response only mean the request shape was accepted. After every write, follow up with a GET and assert `version` bumped AND the specific field you edited actually changed. For PATCH, a throwaway probe like `{"op":"replace","path":"/description","value":"probe"}` round-trip calibrates whether the endpoint is applying your ops before you send real ones.
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
- **Personal-agent runs need MCP, not the CLI**: `Tricentis_Cloud_API` (`client_credentials`) is filtered out of personal-agent records — `_e2g/api/agents/<personalAgentId>` returns 403, and any `playlists run`/`testDebugging/runs` from the CLI sits `Queued` forever. The Portal's "Run on personal agent" button uses the user's own Okta token. From the agent context, mirror that by calling `mcp__ToscaCloudMcpServer__RunPlaylist(playlistId, runOnAPersonalAgent=true)` — `mcp-remote` with PKCE in `.vscode/mcp.json` carries the developer's user identity. Inspect failures via `mcp__ToscaCloudMcpServer__GetRecentRuns({stateFilter})` + `GetFailedTestSteps({runIds})` since the CLI's `playlists status`/`logs` returns 403 on private runs. Local Runner preflight: install Tosca Local Runner, enable Tricentis Automation Extension in Chrome and/or Edge, keep the target browser **maximized**.
- **Polling personal-agent results — which MCP call does what**:
  - `GetRecentPlaylistRunLogs(playlistId)` — authoritative pass/fail for the latest per-playlist run; `["No succeeded runs found."]` means did-not-pass.
  - `GetRecentRuns({nameFilter: "<exact playlist name>"})` — returns executionIds only for matching playlist. The `nameFilter` must be **exact** including em-dash/en-dash characters (`—` is `\u2014`); partial substring matches return `[]`.
  - `GetFailedTestSteps({runIds: ["<executionId>"]})` — takes **executionId** (returned by `GetRecentRuns`), never the `playlistRun.id` returned by `RunPlaylist` (the latter errors with `"Run with the specified ID doesn't exist."`).
  - `GetRecentRuns({stateFilter})` without nameFilter returns ~10 executionIds sorted alphabetically by UUID, not by time — not reliable for locating your run.
- **Polling cadence — 5-10 s, not 60-120 s**. Personal-agent single-case runs typically finish in 15-40 s. A 90 s sleep overshoots by 2-5 prompt-cache TTL windows (≈ 300 s) and burns a fresh cache fill every iteration. Never chain `sleep N && curl` retries — use a short polling loop or fall back to `GetRecentPlaylistRunLogs`.
- **`GetRecentRuns` cap — capped at ~10, sorted alphabetically by UUID**. A newly dispatched run whose UUID sorts past the cap is **invisible** regardless of wait time, even with `nameFilter`. If two consecutive polls with identical `nameFilter` return the same pre-existing set, stop polling and pivot to `GetRecentPlaylistRunLogs(playlistId)` — it returns the latest per-playlist result regardless of UUID ordering.
- **Preserve the user's flow, don't re-dispatch on environment hiccups.** When the user reports an environment failure (`"screen locked"`, `"VPN dropped"`, `"mcp glitched, reloaded"`), re-dispatch the **existing** playlist — do NOT re-edit test artifacts. The last known-good version in MBT is still valid, and the previous run may still be executing on the agent. When a step fails, fix the step — don't replace a hover→submenu→click user journey with a direct `OpenUrl` shortcut. The test documents the journey; shortcuts destroy the coverage. Only propose a flow change after ≥ 3 distinct root-cause fixes have failed, and ask first.
- **Scratch files go under `.claude/tmp/`** (gitignored), **not `/tmp/`**. Playwright MCP is sandboxed to the project root and can't read `/tmp/`; `/tmp/` is also wiped across reboots so reproduction trails vanish. Use `.claude/tmp/<YYYY-MM-DD>-<intent>.json` for throwaway build scripts, step-dump JSON, PATCH probes, etc.

## Html engine runtime quirks

- **All TOSCA value expressions are UPPERCASE in braces**. Canonical references:
  - [Click operations](https://docs.tricentis.com/tosca-cloud/en-us/content/references/click_operations.htm) — `{CLICK}`, `{DOUBLECLICK}`, `{RIGHTCLICK}`, `{ALTCLICK}`, `{CTRLCLICK}`, `{SHIFTCLICK}`, `{LONGCLICK}`, `{MOUSEOVER}`, `{DRAG}`, `{DROP}`. Advanced: `{MOUSE[<action>][MoveMethod][OffsetH][OffsetV]}`. `{Hover}` is **not** valid — fails at runtime with _"No suitable value found for command Hover"_; use `{MOUSEOVER}` and add it to the Link's `valueRange`. Synthetic JS `dispatchEvent('mouseover')` does not fire the `:hover` pseudo-class; `{MOUSEOVER}` emits a real mouse move.
  - [Keyboard commands](https://docs.tricentis.com/tosca-cloud/en-us/content/references/keyboard_operations.htm) — `{ENTER}` `{TAB}` `{ESC}` `{F1}`..`{F24}` arrows, modifiers; advanced `{SENDKEYS["..."]}`, `{KEYPRESS[code]}`, `{KEYDOWN/KEYUP[code]}`, `{TEXTINPUT["..."]}`.
  - [Action modes](https://docs.tricentis.com/tosca-cloud/en-us/content/references/action_types.htm) — `Input`, `Insert` (API), `Verify` (+ `actionProperty` + `operator`), `Buffer`, `Output` (capture control prop into `{B[name]}`), `WaitOn`, `Select`, `Constraint`, `Exclude`.
  - [Dynamic expressions](https://docs.tricentis.com/tosca-cloud/en-us/content/references/values_overview.htm) — `{CP[Param]}` config param; `{B[Var]}` buffer (**case-sensitive, test-case-scoped**, does NOT cross cases); `{MATH[...]}` arithmetic with functions `Abs/Ceiling/Floor/Max/Min/Pow/Round/Sign/Sqrt/Truncate`; string ops `{STRINGLENGTH}`, `{STRINGTOLOWER}`, `{STRINGTOUPPER}`, `{TRIM}`, `{STRINGREPLACE}`, `{STRINGSEARCH}`, `{BASE64}`, `{NUMBEROFOCCURRENCES}` (with optional `[IGNORECASE]` / `[REPLACEFIRST]` / `[FINDFIRST]`).
- **`InnerText` TechnicalId is exact-match**: a card link wrapping an `<h2>` renders `innerText="<caption>\n<heading>"` and won't match a short caption. Drop `InnerText`; use `Tag` + `HREF` + `ClassName` or a unique `Title` attribute.
- **Mega-menu `{MOUSEOVER}` straight-line crosses other top-level triggers and swaps the open panel.** Symptom: `MOUSEOVER <trigger>` succeeds, `WaitOn <submenu item>` succeeds, then `Click <submenu item>` fails with `Link '…' is not steerable. The reason could be that the control is not visible` after the 10 s timeout. Root cause: TOSCA moves the cursor in a straight diagonal line from the trigger to the submenu link; the path crosses sibling top-level triggers, which close the active panel on hover. **Fixes** (prefer first): (1) use the advanced single-step form `{MOUSE[MOUSEOVER][HorizontalFirst]}` (or `[VerticalFirst]`) on the target Link — confine the cursor to an L-path; (2) add a **waypoint attribute** to the module for an element on the same y-row as the top-level trigger, inside the opened submenu column, and `MOUSEOVER` it between the trigger hover and the target hover. Call `browser_evaluate` to find a submenu link whose `getBoundingClientRect().top/bottom` overlaps the trigger's y-range — that's your waypoint. Validated case: `Novartis — verify Therapeutic Areas sections` (Sandbox).
- **Parent `visibility:hidden` propagates**: closed mega-menu items are filtered out by default `IgnoreInvisibleHtmlElements=True`. Open the parent first, or set `IgnoreInvisibleHtmlElements=False` as a module-level Steering param.
- **"More than one matching tab"**: agents that reuse the user's personal Chrome match multiple tabs with `Title=*`. Add a module-level `Url=https://<host>*` TechnicalId to scope document matching to the test host. For repeated runs on the same workstation, prepend a `ControlFlowItemV2 If` to Precondition — condition = `Verify <always-visible app element> Visible=True`, then = `CloseBrowser Title="*<AppName>*"`. Without this, the 2nd+ run of the day fails with this error.
- **"The Browser could not be found"**: Tricentis Chrome extension is not attached to the Chrome instance the agent is driving. Environment fix (install/enable the extension in the target profile) — no test-case change resolves this.
- **`CloseBrowser Title="*"` fails on empty agents**: throws `UnestablishedConnectionException` after 10 s when no Chrome is running. Remove the cleanup on grid agents, or wrap in a `ControlFlowItemV2 If` with a narrow `Title="*<AppName>*"` on workstation agents.
- **`ControlFlowItemV2 If` for optional elements**: works when the module-level `Title`/`Url` can cleanly miss (Verify evaluates `false`). Hard-fails when the document itself isn't found — narrow the module-level selector before relying on `If`.
- **Scanned modules' `SelfHealingData`**: carries the page's title/URL at scan time. When reusing a scanned module on a different flow, drop the `SelfHealingData` steering param — stale hints interfere with document matching.
- **Html module steering defaults that actually work**: `AllowedAriaControls` populated (standard aria list), `EnableSlotContentHandling=False`, `IgnoreInvisibleHtmlElements=True`. Empty `AllowedAriaControls` or `EnableSlotContentHandling=True` cause erratic element resolution.
- **`{Click}` reports Succeeded but browser doesn't navigate** — Drupal/SPA mega-menu links: the step logs `[Succeeded] Click '…'` while the tab URL never changes, then the next module's `Url=` scope fails to find the tab. Per Tricentis best-practices KB5 #12, swap `value: "{Click}"` → `value: "X"` (direct click — invokes the DOM click handler without mouse emulation). Do **not** try `{LEFTCLICK}` — not a registered keyword, throws `[Exception]` (~0.07 s). Alternative for VJS path: `window.location.href = el.href` (bypasses event handlers that call `preventDefault()`).
- **Html scanner is viewport-scoped, not document-scoped.** A `Verify` on any element below the fold fails with `Could not find …` even when `browser_evaluate('document.querySelectorAll(sel).length') ≥ 1`. `ScrollToFindElement=True` steering doesn't reliably help. Diagnostic: run `document.querySelector(sel).getBoundingClientRect().y` in `browser_evaluate`; if y ≥ window.innerHeight the element is below the fold. Fix order: (1) prepend `{SENDKEYS[{PAGEDOWN}]}` on a page element; (2) `OpenUrl` to a fragment anchor if available; (3) pivot to `Verify JavaScript Result` — CDP `Runtime.evaluate` is document-scoped. Distinct root cause from "scanner-blind" (observer disabled); always check viewport first.
- **Module-level `Url` / `Title` must be `parameterType: "TechnicalId"`, not `"Configuration"`.** If created as `Configuration`, TOSCA silently ignores them for tab scoping — symptom is persistent *"More than one matching tab was found"* regardless of how precise the pattern is. Verify with `modules get --json <id>` → `parameters[].parameterType`. Fix in-place via `modules update`.
- **`UseActiveTab = True` alone rejected on some tenants**: raises *"Specify at least one of the Search Criteria."*. Always pair with `Title=*<AppName>*` or `Url=https://<host>*`, or use `UseActiveTab=False` + Title/Url. Reliably working shape: `UseActiveTab=False` + `Title=*<AppName>*`.
- **Container nesting does NOT scope attribute matching.** Nesting a Button attribute inside a Container attribute in the module tree only affects Steering-param inheritance — TBox resolves `moduleAttributeReference.id` globally against the document. If two matching buttons exist in different page regions you still get *"Found multiple controls for Button '…'"*. Discriminate in the child's own selector (combine ancestor class + child class in `ClassName`), or scope via `Verify JavaScript Result` → `document.querySelector('.region-header button.lang-switch')`.

## VS Code Copilot-specific gotchas

- **First-turn MCP-boot cancellation after VS Code reload.** If your first request in a fresh Chat window comes back with `result.errorDetails = {"code":"canceled"}` and `response = [{"kind":"mcpServersStarting"}]`, the TOSCA MCP server is still completing its PKCE/OAuth handshake. **Retry the request once** — do not re-dispatch playlists or re-author test cases; the prior request never executed. The handshake takes 3-8 s and is async; Copilot races it on the first turn.

- **MCP vs CLI — capability split.** MCP write tools are **scaffolding-only**. Do not use `ScaffoldTestCase` when the user asks to `copy`/`clone`/`duplicate` a test case — it drops attribute bindings, `ControlFlowItemV2` nodes, and parameter values. Correct split:
  - **MCP (read/dispatch/inspect)**: `SearchArtifacts`, `AnalyzeTestCaseItems`, `GetModulesSummary`, `RunPlaylist`, `GetRecentRuns`, `GetRecentPlaylistRunLogs`, `GetFailedTestSteps`, `ListSimulatorAgents`, `Delete*ById`.
  - **CLI (writes with full fidelity)**: `cases clone`, `cases update --json-file`, `modules update --json-file`, `blocks update`, `cases patch`, `inventory move`, TSU export/import.
  - **CLI (writes with care — confirm-GET required)**: `cases patch`, `inventory patch` — silent-no-op on unsupported ops.

- **MCP tool naming convention.** Tools are `mcp__ToscaCloudMcpServer__<MethodName>` — **double underscore**, PascalCase server name, PascalCase method. Do not write `mcp_toscacloudmcp_*` in user-facing text or tool invocations — that's a Copilot-autocomplete mistake and will not resolve.

- **Output discipline — no duplicate paragraphs inside a single turn.** Copilot Chat's retry/tool-loop orchestrator occasionally re-narrates the same analysis paragraph 5-8 times inside one assistant response (each repetition also lands in the next turn's context, inflating prompt cost). Emit each analysis once; between tool calls, keep pre-tool text to one short bullet or a single sentence. If you notice identical paragraphs appearing twice in your own draft, cut the duplicates before finalizing.

## Adding a new command — checklist

1. Add `ToscaClient` method (docstring with HTTP verb + endpoint path).
2. Add Typer command to the right `*_app` with `--json` flag and short `--help` text.
3. Update `README.md` Command Reference for the relevant group.
4. If a new API quirk is found, add it to the Known API Limitations table.

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
