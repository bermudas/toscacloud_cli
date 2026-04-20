---
name: tosca-automation
description: "Use this skill for any Tricentis TOSCA Cloud task — even if the user doesn't mention TOSCA, CLI, or test automation explicitly. Triggers on: creating or updating test cases, web (Html engine) or SAP GUI (SapEngine) modules, playlists, or inventory folders; running or checking tests; searching inventory; working with reusable test step blocks; importing/exporting TSU files; or any TOSCA Cloud REST API operation. Covers the full lifecycle: discover → build → place → verify."
license: MIT
compatibility: "Python 3.10+. Packages: httpx typer[all] rich python-dotenv. Requires .env with TOSCA_TENANT_URL and TOSCA_SPACE_ID. Run from the project root: python tosca_cli.py <command>"
argument-hint: "Describe the TOSCA task (e.g. 'create a test case for login flow', 'run smoke playlist and show failures', 'move all Web test cases into the Regression folder')"
metadata:
  author: bermudas
  version: "1.0"
  repository: https://github.com/bermudas/toscacloud_cli
---

## When to use this skill

Use this skill for any task involving the Tricentis TOSCA Cloud REST API or the `tosca_cli.py` CLI:

- **Test cases** — create, update, clone, patch work state, export/import TSU
- **Modules** — create or update Html (web) or SAP GUI modules with locator attributes
- **Reusable blocks** — extend parameters, wire block references into test cases
- **Inventory** — search, move, organize into folders
- **Playlists** — list, run, check results
- **Web automation** (Html engine) — use Playwright to discover element locators, build modules, assemble 4-folder test cases
- **SAP GUI automation** (SapEngine) — create screen modules with `RelativeId` locators, wire the Precondition block
- **Any TOSCA Cloud REST API operation** not listed above

## Core principle — always discover before acting

The MBT API has no general list endpoint; use Inventory for user-created artifacts and `/packages` for built-in modules:

1. `inventory search "<name>" --type TestCase` — find test case IDs
2. `inventory search "<name>" --type Module` — find **user-created** module IDs (built-in Standard modules do not appear here)
3. `cases get <id> --json` + `cases steps <id> --json` — ground truth for step composition, module IDs, attribute refs, config params
4. **Standard modules** (engine-bundled — OpenUrl, CloseBrowser, Wait, Execute JavaScript, HTTP, DB, file, email, T-code, etc.) do NOT appear in `inventory search`. Discover via `GET /_mbt/api/v2/builder/packages`. **Before** building a custom wrapper for any common capability, check there first — see [standard-modules.md](references/standard-modules.md).
5. Use the discovered JSON as the template when creating or patching similar cases.

## Workflow discipline — one artifact at a time

Work sequentially, not in batches. Each build cycle is a complete loop:

1. **Discover** — `inventory search` → read an existing similar artifact (`cases steps --json` / `modules get --json`) as ground truth.
2. **Explore** — use Playwright MCP (web) or read similar existing modules (SAP) to confirm element identity **before** writing JSON. Never commit a module whose locator matches >1 element — verify via `browser_evaluate` that the count is exactly 1.
3. **Build** — module → test case → placement, using fresh ULIDs where required (`parameterLayerId`, `businessParameter.id`, block-ref `parameters[].id`). **Before finalizing identification choices, action modes, or folder structure**, reconcile against [best-practices.md](references/best-practices.md) (condensed from the 10 official Tricentis Best Practices KBs) — it is the "whether/why" reference that complements the mechanical how-to guides.
4. **Run** — personal agent via MCP for iterative debug, shared agent via CLI for CI/scheduled runs.
5. **Inspect** — on failure, read the exact TBox message via `GetFailedTestSteps` (MCP) or `playlists logs` (CLI). Classify the failure (see next section) before changing anything.
6. **Fix** — minimum-diff change: patch the offending module/step, not the whole case.
7. **Confirm the write landed** — GET the artifact and check that the **`version` bumped** and the specific field you edited actually changed. A `✓ patched` / `204 No Content` from the API is **not** proof the delta was applied: MBT silently accepts unsupported JSON Patch ops (e.g. `remove` on an array element, deep JSON pointer paths like `/testCaseItems/1/items/2/testStepValues/0/value`, `move`) and returns 204 with zero changes. Inventory v3 PATCH has its own PascalCase/`{"operations":[…]}` wrapper — a request in MBT shape is accepted but ignored. Never report a change as done, never run the test, and never claim a fix based on the CLI's own "success" message alone. If PATCH did nothing, fall back to full PUT (`cases update` / `modules update` / `blocks update`).
8. **Validate** — re-run and confirm the step that previously failed now passes. Don't move on until green (or the failure is a documented application defect).
9. **Report** — IDs (entityId / moduleId / playlistId), folder placement, any remaining gaps.

Don't batch: don't build 5 cases and then run them together. Build one, run it, fix it, then start the next.

## No-defect-masking rule

When a run fails, classify BEFORE changing anything:

| Failure type | Typical signal | Permitted action |
|---|---|---|
| **Infrastructure** | `Could not find Link ...`, `More than one matching tab`, stale `SelfHealingData`, extension not attached, timing | Fix the TechnicalId, tighten module-level `Url`/`Title`, add a `Wait`, fix the agent environment. Re-run. |
| **Application defect — isolated** | One `Verify` step fails; the rest of the flow still executes meaningfully | Keep the `Verify` step. Note the defect in the step `description` or a tracker link; raise the bug. **Do not** delete or weaken the assertion. |
| **Application defect — blocks flow** | The product bug prevents the core path (popup never opens, login rejected on valid creds) | Let the test fail. A red run is the correct regression signal for a real bug. |

**Forbidden — regardless of reasoning:**
- Removing a `Verify` step to make the run green.
- Changing `actionMode: Verify` + `actionProperty: "Visible"`/`"InnerText"` to a weaker form (dropping `actionProperty` so the step just interacts).
- Deleting an attribute from a module so a failing lookup stops happening.
- Setting `disabled: true` on a step that catches a genuine product bug.
- Wrapping a failing `Verify` in `ControlFlowItemV2 If` so the test silently skips the bug.
- The **re-scoping trap**: concluding "this assertion belongs in a different test case" and removing it from the current one. If a step belonged in this case when it was written, it belongs there now.

The only legitimate way to keep a run green while a known product bug exists is to raise the bug and either leave the test failing or set `disabled: true` with a description linking to the tracker. Masking a defect creates false confidence and defeats the regression suite.

## TechnicalId priority (Html engine)

When picking locator parameters for a new Html module attribute, prefer higher-rank options first. Stability beats cleverness — avoid framework-generated class names and long absolute XPaths.

1. **`Tag` + unique `Title`** — stable, locale-independent. Use when the target has a meaningful `title=""`.
2. **`Tag: INPUT` + `Name`** — first-choice locator for form fields.
3. **`Tag` + `InnerText`** — clickable buttons/links with short, unique, stable, locale-appropriate text. Remember `InnerText` matches the full `textContent` exactly, including nested children, and is case-sensitive (so it differs from CSS `text-transform: uppercase` rendering).
4. **`Tag` + `HREF` + `ClassName`** — nav links. `HREF` must be absolute; `ClassName` discriminates between duplicated mobile/desktop/dropdown copies of the same link.
5. **`Tag` + `ClassName`** — last resort. Prefer semantic BEM-style class names; avoid framework-generated hashes like `css-xyz123`.

`Id` is silently ignored by the Html engine — never rely on it. After picking a candidate, run a uniqueness check via Playwright MCP:

```javascript
document.querySelectorAll('<your css>').length   // MUST be 1
```

If >1, add another discriminator before saving the module. TOSCA will NOT warn you at save time — the ambiguity only surfaces at runtime as `Could not find Link '...'` or `More than one matching ...`.

## Pre-run quality gates

Before triggering a run, confirm these **mechanical** checks here, and walk through the **conformance** checklist in [best-practices.md](references/best-practices.md) (naming, TestCase structure, identification priority, forbidden `{CLICK}`/`{SENDKEYS}` patterns, etc.):

- [ ] Module has root-level `Engine: Html` (or `SapEngine`) configuration parameter.
- [ ] Every `TestStepFolderReferenceV2` has a fresh ULID `parameterLayerId`.
- [ ] Every parameter value entry has `referencedParameterId` pointing to a real `businessParameter.id` on the block.
- [ ] `version` field stripped from PUT bodies (the CLI does this automatically).
- [ ] Each attribute locator matches exactly one element on the live page (Playwright MCP uniqueness check).
- [ ] Precondition starts with `OpenUrl` (all 3 params: `Url`, `UseActiveTab=False`, `ForcePageSwitch=True`) and a `Wait` step for SPAs.
- [ ] Leftover-tab handling: on workstation agents that share the user's Chrome, cleanup is wrapped in `ControlFlowItemV2 If` with a narrow `Title="*<AppName>*"` — never an unconditional `CloseBrowser Title="*"`.
- [ ] Local Runner preflight done (extension enabled in target browser, browser maximized) for personal-agent runs.
- [ ] Conformance walkthrough completed — see [best-practices.md](references/best-practices.md) "Agent checklist" section.

## Declarative execution

Act, don't ask. Once the user has approved a task ("build a test for flow X"), execute the full discover → build → place → run → inspect loop without asking for permission between steps. State what you are doing, not what you propose to do.

- ✗ "Shall I create the module first or the test case?"
- ✓ "Creating the module now." (then does it)

Only pause for explicit confirmation on irreversible actions: `delete-folder`, `delete-block`, `--force`, overwriting a test case whose current version you haven't inspected.

## Decision tree

| Goal | First action |
|------|-------------|
| Extend coverage / gap fill | `inventory search` in the folder → `cases steps --json` on ALL existing cases to find the pattern |
| Create new test case | `inventory search` for similar cases first → clone or assemble from template |
| Find something | `inventory search "<keywords>" [--type TestCase\|Module\|folder]` |
| Run tests on grid/team agent | CLI: `playlists list` → `playlists run <id> --wait` |
| Run on developer's local machine (iterative debug) | MCP: `RunPlaylist(playlistId, runOnAPersonalAgent=true)` — see Iterative loop section below |
| Move / organize | `inventory move <type> <entityId> --folder-id <folderEntityId>` |
| Export / import | `cases export-tsu --ids "id1,id2" --output file.tsu` / `cases import-tsu --file file.tsu` |
| Create Web test case | Use Playwright to snapshot the page → discover element locators → create module → create case → see [Web Automation guide](references/web-automation.md) |
| Create SAP GUI test case | `inventory search "<TCODE>" --type Module` → create/reuse modules → assemble case → see [SAP GUI guide](references/sap-automation.md) |
| Run JavaScript in the page / read cookie / scroll / CSS query a hydrated SPA / scanner is blind to body content | Use the `Verify JavaScript Result` or `Execute JavaScript` **Standard** module (GUIDs + attribute IDs + ready-to-paste JSON in [standard-modules.md](references/standard-modules.md)). Do NOT reach for `{SCRIPT[...]}` dynamic value — it is not a registered command on Tosca Cloud. Do NOT try to import the Standard subset — it's already on the agent, reachable by GUID |
| Any functionality the platform probably ships (HTTP, DB query, file, email, clipboard, timing, T-code…) | First `GET /_mbt/api/v2/builder/packages` → find the module → get attribute IDs via `packages/{packageId}/modules/{moduleId}` → hard-code the GUIDs in your generated test step. Writing a custom wrapper is almost always wrong |

## Key CLI commands

```bash
# Discovery
python tosca_cli.py inventory search "<name>" [--type TestCase|Module|folder] [--include-ancestors]
python tosca_cli.py inventory search "" --type TestCase --folder-id <entityId>
python tosca_cli.py inventory get TestCase <entityId> --include-ancestors

# Test cases
python tosca_cli.py cases get <caseId> --json          # full metadata
python tosca_cli.py cases steps <caseId> --json        # full step tree (use this first)
python tosca_cli.py cases create --name "..." --state Planned
python tosca_cli.py cases update <caseId> --json-file case.json   # full PUT
python tosca_cli.py cases clone <caseId> --name "..."
python tosca_cli.py cases export-tsu --ids "id1,id2" [--module-ids "m1"] [--block-ids "b1"] --output file.tsu
python tosca_cli.py cases import-tsu --file file.tsu

# Modules
python tosca_cli.py modules get <moduleId> [--json]
python tosca_cli.py modules create --name "..." --iface Gui
python tosca_cli.py modules update <moduleId> --json-file body.json

# Reusable blocks
python tosca_cli.py blocks get <blockId>
python tosca_cli.py blocks add-param <blockId> --name <name> [--value-range '1,2,3']
python tosca_cli.py blocks set-value-range <blockId> <paramName> --values '1,2,3,4'
python tosca_cli.py blocks delete <blockId> --force

# Test case patch (partial update)
python tosca_cli.py cases patch <caseId> --operations '[{"op":"replace","path":"/workState","value":"Completed"}]'

# Playlists
python tosca_cli.py playlists list
python tosca_cli.py playlists list-runs
python tosca_cli.py playlists run <id> --wait
python tosca_cli.py playlists results <runId>
python tosca_cli.py playlists logs <runId>                    # per-unit agent logs (E2G, full TBox transcript)
python tosca_cli.py playlists logs <runId> --save ./logs      # save logs.txt + JUnit.xml + TBoxResults.tas + TestSteps.json
python tosca_cli.py playlists attachments <runId>             # SAS URLs per unit (no download)

# Folders
python tosca_cli.py inventory move testCase <entityId> --folder-id <folderEntityId>
python tosca_cli.py inventory create-folder --name "..." [--parent-id "..."]
python tosca_cli.py inventory rename-folder <folderId> --name "..."
python tosca_cli.py inventory delete-folder <folderId> [--delete-children] --force
python tosca_cli.py inventory folder-ancestors <folderId>
python tosca_cli.py inventory folder-tree --folder-ids "<parentFolderId>"
```

## Critical caveats

| Situation | What to do |
|-----------|-----------|
| `--json` flag placement | Place before positional args: `cases get --json <id>` ✓ |
| Block IDs ≠ Module entity IDs | Get block IDs from `cases get --json <caseId>` → `testCaseItems[].reusableTestStepBlockId` where `$type == "TestStepFolderReferenceV2"` |
| `parameterLayerId` missing | Each `TestStepFolderReferenceV2` **must** have a fresh ULID `parameterLayerId` or all parameter values are silently ignored |
| Entity ID truncation in table | Always use `--json` to get full IDs before passing to commands |
| Html module root `Engine` param | Manually created Html modules must have `{"name":"Engine","value":"Html","type":"Configuration"}` in the root-level `parameters` array. Without it: _XModules and XModuleAttributes have to provide the configuration param "Engine"_ |
| Duplicate page elements | Modern pages render the same nav link in mobile + desktop. `Tag+InnerText+HREF` alone matches all copies. Use `browser_evaluate` to count matches; add `ClassName` to discriminate. |
| Leftover browser tab | Start Precondition with `CloseBrowser Title="*"` before `OpenUrl` to avoid _"More than one matching tab"_ |
| MBT PATCH ops | Lowercase: `replace`, `add`, `remove`. Response is 204 No Content — always GET the artifact afterwards and confirm `version` bumped and the target field actually changed. Unsupported ops (deep JSON-pointer paths into nested step trees, `remove` on array elements, `move`) are **silently ignored**: CLI still prints `✓ patched`, server still returns 204, but the body is unchanged. When the confirm-GET shows no diff, fall back to `cases update`/`modules update`/`blocks update` (full PUT). |
| Inventory v3 PATCH body | Wrapper: `{"operations": [{"op": "Replace", ...}]}` — PascalCase op. Same confirm-GET rule: an MBT-shape body (bare array, lowercase op) is accepted and 204'd but applies no changes. |
| Confirm writes before claiming success | Never trust the CLI's own `✓` line, an HTTP 204, or a `{}` response body as proof that your edit persisted. Always follow a write with a GET and assert the delta (usually: `version` field bumped). MBT PATCH has two silent-no-op cases (unsupported ops, deep paths); `modules update` returns `{}` on success too. One trivial probe — `{"op":"replace","path":"/description","value":"…"}` round-trip — is enough to calibrate whether the endpoint is accepting your shape before you batch real edits. |
| Inventory search filter | Despite swagger, only lowercase works: `contains`, `and` |
| SAP standard modules | Not in inventory. `SAP Logon`, `SAP Login`, `T-code` — use IDs directly from [SAP guide](references/sap-automation.md) |
| TSU export field | `reusableTestStepBlockIds` (no double-e) |
| `version` in PUT body | Omit — rejected by case, block, **and** module PUT endpoints. CLI's `update_case`/`update_block`/`update_module` strip it automatically |
| MBT test case ID = Inventory `entityId` | `cases get`/`steps`/`update` accept only the Inventory `entityId`. Playlist item `id` and inventory `attributes.surrogate` both 404. Resolve via `inventory search … --type TestCase --json` → `id.entityId` |
| Failed playlist run with `<failure />` only | Playlists v2 has no step-level log endpoint, but E2G does. Use `playlists logs <runId>` — it walks `/_e2g/api/executions/{executionId}` units → `/units/{unitId}/attachments` → SAS-signed Azure Blob downloads (logs.txt, JUnit.xml, TBoxResults.tas, TestSteps.json, Recording.mp4). Works under `Tricentis_Cloud_API`. The endpoint keys on `PlaylistRunV1.executionId`, **not** the playlist run's `id` — the CLI resolves this via `playlists status` automatically; pass `--execution-id / -e` to skip the lookup. SAS TTL ≈ 30 min; the blob GET must NOT carry an Authorization header. |
| Personal-agent runs need MCP, not CLI | `Tricentis_Cloud_API` (CLI service token) cannot dispatch to or read a developer's personal Local Runner — `_e2g/api/agents/<personalAgentName>` returns 403, and `playlists status <runId>` on a private run returns 403. Use `mcp__ToscaCloudMcpServer__RunPlaylist(playlistId, runOnAPersonalAgent=true)` to trigger and `GetRecentRuns` + `GetFailedTestSteps` to inspect — MCP carries the developer's user identity (PKCE OAuth via `mcp-remote` configured in `.vscode/mcp.json`). |
| `cases delete` / `modules delete` / `blocks delete` → 403 | The `Tricentis_Cloud_API` client-credentials role has create/read/update/patch on MBT artifacts but **no delete privilege** on this tenant. Symptom: `DELETE /_mbt/api/v2/builder/testCases/{id}` returns 403 regardless of query-string tweaks (`?force=true`, `?permanent=true`), and all bulk variants (`testCases/bulkDelete`, `testCases/delete`, `DELETE /testCases` with body) are 405 — no such route. Inventory-side DELETE routes (`_inventory/api/v3/artifacts/testCase/{id}`, v1 equivalents) are 404/405. The MCP tool set carries the user's identity but doesn't expose a delete-test-case / delete-module / delete-block tool — only `DeletePlaylistById`. **Workarounds**: (a) delete via the Portal UI (the logged-in user's browser token has delete); (b) ask tenant admin to grant the Cloud-API role `testCases:delete` / `modules:delete` / `reuseableTestStepBlocks:delete`. Always run `inventory search` + playlist-reference scan before delete either way — dangling `sourceId` references in playlists are a harder cleanup than keeping a stale "(Copy)" case around. |
| Local Runner preflight | Before triggering on a personal agent: install Tosca Local Runner / Cloud Agent on the developer's machine; install + enable Tricentis Automation Extension in Chrome and/or Edge; keep the target browser **maximized** (minimized windows cause coordinate-out-of-bounds and silent click misses). |
| Html "More than one matching tab" | Agent shares user's Chrome profile. Add module-level `Url=https://<host>*` TechnicalId to scope document matching to one tab. Also prepend a `ControlFlowItemV2 If` to Precondition: condition = Verify always-visible app element Visible=True, then = `CloseBrowser Title="*<AppName>*"` |
| Click operation values | Uppercase in braces: `{CLICK}`, `{DOUBLECLICK}`, `{RIGHTCLICK}`, `{ALTCLICK}`, `{CTRLCLICK}`, `{SHIFTCLICK}`, `{LONGCLICK}`, `{MOUSEOVER}`, `{DRAG}`, `{DROP}`. For hover use `{MOUSEOVER}` — **not** `{Hover}` (fails with _"No suitable value found for command Hover"_). Add `{MOUSEOVER}` to the Link's `valueRange`. Synthetic JS events don't fire CSS `:hover`; TOSCA's `{MOUSEOVER}` emits a real mouse move |
| Keyboard command values | All uppercase-braced: `{ENTER}` `{TAB}` `{ESC}` `{F1}`..`{F24}` `{UP}` `{DOWN}` `{LEFT}` `{RIGHT}` `{BACKSPACE}` `{DEL}` `{HOME}` `{END}` `{SHIFT}` `{CTRL}` `{ALT}`. Advanced: `{SENDKEYS["..."]}`, `{KEYPRESS[code]}`, `{KEYDOWN/KEYUP[code]}`, `{TEXTINPUT["..."]}`. Ref: [keyboard_operations](https://docs.tricentis.com/tosca-cloud/en-us/content/references/keyboard_operations.htm) |
| Action mode cheat-sheet | `Input` write; `Insert` (API modules); `Verify` + `actionProperty` assert; `Buffer`/`Output` capture into `{B[name]}`; `WaitOn` dynamic wait; `Select` pick a specific child; `Constraint`/`Exclude` narrow tables. Ref: [action_types](https://docs.tricentis.com/tosca-cloud/en-us/content/references/action_types.htm) |
| Dynamic expressions | `{CP[Param]}` config param; `{B[Var]}` buffer (case-sensitive, **test-case-scoped** — does NOT cross cases); `{MATH[...]}` arithmetic with `Abs/Ceiling/Floor/Max/Min/Pow/Round/Sign/Sqrt/Truncate`; string ops `{STRINGLENGTH}` `{STRINGTOLOWER}` `{STRINGTOUPPER}` `{TRIM}` `{STRINGREPLACE}` `{STRINGSEARCH}` `{BASE64}` `{NUMBEROFOCCURRENCES}` |
| `InnerText` exact-match | TOSCA's `InnerText` TechnicalId matches the full element `innerText` exactly, including text of nested children. A card link wrapping an `<h2>` will have `innerText="<caption>\n<heading>"` and will not match a short caption. Drop `InnerText`; use Tag + HREF + ClassName or a `Title` attribute |
| Parent `visibility:hidden` propagates | Closed mega-menus hide children via parent styling; TOSCA's default `IgnoreInvisibleHtmlElements=True` filters them out. Open the parent before looking up the child, or set `IgnoreInvisibleHtmlElements=False` as a Steering module param |
| Html "The Browser could not be found" | Tricentis Chrome extension not attached to the agent's Chrome. Fix on the agent (install/enable extension), **not** in the test case |
| `ControlFlowItemV2` for optional elements | Works cleanly when the module-level selector (`Title`/`Url`) can produce a clean no-match. Verify steps inside the condition evaluate `false` on hidden elements; they hard-fail when the document itself can't be found. Narrow the module-level selector before relying on `If` |
| Test case PUT requires `id` in body | The full PUT body must include `"id": "<caseId>"` — API rejects bodies without it |
| New case not in inventory immediately | After `cases create`, wait 3–10 s before searching — CLI retries automatically |
| Placing a case after create/clone | Always run `inventory move testCase <newId> --folder-id <folderId>` — creation alone doesn't place it |
| Finding a folder's entity ID | Use `inventory folder-tree --folder-ids "<parentId>"` or read the UUID from the portal URL |
| `inventory search --folder-id` | Filters client-side by matching the `folderKey` suffix — pass `--folder-ids` with parent IDs |
| `modules update` returns `{}` | A 200/204 with empty body is normal — verify with `modules get <id> --json` afterwards |
| Block params need `id` | Every `businessParameters` entry needs a ULID `id` — always use `blocks add-param` which generates one |
| `referencedParameterId` | Each parameter value entry must match a `businessParameter.id` from the block — get IDs via `blocks get <blockId> --json` |
| `{CP[ParamName]}` syntax | Reference test config params in step values: `{CP[Username]}`, `{CP[Password]}` |
| ProcessOperations `subValues` | The `Arguments` step uses `actionMode: "Select"` with each CLI arg as a separate item in `subValues[]` — multiple args in one `value` string won't work |
| Standard modules invisible in `inventory search` | Intentional. Discover via `GET /_mbt/api/v2/builder/packages` + `packages/{pkg}/modules/{moduleId}`. Top-level module GUIDs appear stable; attribute GUIDs are NOT confirmed stable — re-discover per tenant. See [standard-modules.md](references/standard-modules.md) |
| `{SCRIPT[...]}` / `{XP[...]}` dynamic-value expansion | Not registered on Tosca Cloud. To run JS from a test step, use the `Execute JavaScript` / `Verify JavaScript Result` Standard modules — see [standard-modules.md](references/standard-modules.md) |
| Html scanner blind to body content (not iframe / not shadow DOM / not CSS-hidden) | Module Steering flags won't fix it. Pivot to `Verify JavaScript Result` (CDP-based, bypasses the scanner). Full diagnostic playbook + anti-patterns in [standard-modules.md](references/standard-modules.md) |

## ULID generation

The CLI's `_generate_ulid()` creates Crockford base32 ULIDs. Generate a **fresh** ULID for:
- Each `parameterLayerId` in a block reference
- Each `businessParameter.id` added to a block
- Each parameter entry in a test case's block reference

## Step JSON discriminator

Items use `$type`:
- `TestStepFolderV2` — inline folder, children in `items[]`
- `TestStepFolderReferenceV2` — block reference, ID in `reusableTestStepBlockId`
- `TestStepV2` — atomic step
- `ControlFlowItemV2` — If/Then conditional

## Iterative test-development loop (Local Runner + MCP)

Use this loop when developing a new test case end-to-end on the developer's own machine — fastest feedback because no shared queueing, and the developer can watch the browser drive itself.

**One-time prerequisites on the developer machine**
1. Install **Tosca Local Runner / Cloud Agent** — registers a *private* personal agent under the developer's Okta identity (visible only to MCP, not to the CLI service token).
2. Install + enable the **Tricentis Automation Extension** in Chrome and/or Edge.
3. Keep the target browser window **maximized** before each run (minimized → coordinate-out-of-bounds, missed clicks).

**The loop**
1. **Explore** the target site with Playwright MCP (`browser_navigate` → `browser_snapshot` → identify Tag/InnerText/HREF/ClassName; verify locator uniqueness with `browser_evaluate`).
2. **Build / update** modules and the test case via the CLI (service token is fine for build operations).
3. **Trigger** via MCP — NOT the CLI: `mcp__ToscaCloudMcpServer__RunPlaylist(playlistId, runOnAPersonalAgent=true)`. The CLI's service token is 403'd on personal agents.
4. **Wait** via MCP: `mcp__ToscaCloudMcpServer__GetRecentRuns({stateFilter: "Succeeded"|"Failed"|"Running"})` — the new id appearing is the executionId.
5. **Inspect failures** via MCP: `mcp__ToscaCloudMcpServer__GetFailedTestSteps({runIds:[<executionId>]})` — returns the per-step failure tree with the engine's exact message + stack trace.
6. **Fix** the failing module/step/RTSB via the CLI, then back to step 3.

**Do not** pin `AgentIdentifier` on the playlist — `runOnAPersonalAgent: true` is the entire routing instruction, and the playlist stays generic for grid runs too.

For shared/team-agent runs (CI, scheduled jobs, parameter-overridden runs), use the CLI's `playlists run` and `playlists logs` — those work fine under the service-account token.

## Detailed how-to guides

- Read [Web Automation (Html engine)](references/web-automation.md) when creating or updating Html engine modules, building web test cases, or using Playwright to discover element locators and class names.
- Read [SAP GUI Automation (SapEngine)](references/sap-automation.md) when creating or updating SAP GUI modules, assembling SAP test cases, or working with T-codes, RelativeId locators, or the Precondition reusable block.
- Read [Reusable Blocks](references/blocks.md) when working with reusable test step blocks — extending block parameters, wiring block references into test cases, or debugging `parameterLayerId` / `referencedParameterId` issues.
- Read [Standard Modules & Execute/Verify JavaScript](references/standard-modules.md) when you need to: run JavaScript in the browser, read cookies / storage / computed styles, work around a scanner that's blind to body content, or use any out-of-the-box platform module (HTTP, DB, file, email, clipboard, timing, T-code). Includes the `/packages` discovery endpoint recipe and the full Html-package GUID table.
- Read [Best Practices (condensed KB summary)](references/best-practices.md) before finalizing module identification choices, TestCase structure, or TestStep action modes — it compresses the 10 official Tricentis Best Practices articles into a single checklist.
