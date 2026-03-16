---
name: tosca-automation
description: "Use this skill for any Tricentis TOSCA Cloud task — even if the user doesn't mention TOSCA, CLI, or test automation explicitly. Triggers on: creating or updating test cases, web (Html engine) or SAP GUI (SapEngine) modules, playlists, or inventory folders; running or checking tests; searching inventory; working with reusable test step blocks; importing/exporting TSU files; or any TOSCA Cloud REST API operation. Covers the full lifecycle: discover → build → place → verify."
license: MIT
compatibility: "Python 3.10+. Packages: httpx typer[all] rich python-dotenv. Requires .env with TOSCA_TENANT_URL and TOSCA_SPACE_ID. Run from the project root: python tosca_cli.py <command>"
metadata:
  author: bermudas
  version: "1.0"
  repository: https://github.com/bermudas/toscacloud_cli
---

## Core principle — always discover before acting

The MBT API has no list endpoint. Use Inventory as the discovery layer:

1. `inventory search "<name>" --type TestCase` — find test case IDs
2. `inventory search "<name>" --type Module` — find module IDs
3. `cases get <id> --json` + `cases steps <id> --json` — ground truth for step composition, module IDs, attribute refs, config params
4. Use that JSON as the template when creating or patching similar cases

## Decision tree

| Goal | First action |
|------|-------------|
| Extend coverage / gap fill | `inventory search` in the folder → `cases steps --json` on ALL existing cases to find the pattern |
| Create new test case | `inventory search` for similar cases first → clone or assemble from template |
| Find something | `inventory search "<keywords>" [--type TestCase\|Module\|folder]` |
| Run tests | `playlists list` → `playlists run <id> --wait` |
| Move / organize | `inventory move <type> <entityId> --folder-id <folderEntityId>` |
| Export / import | `cases export-tsu --ids "id1,id2" --output file.tsu` / `cases import-tsu --file file.tsu` |
| Create Web test case | Use Playwright to snapshot the page → discover element locators → create module → create case → see [Web Automation guide](references/web-automation.md) |
| Create SAP GUI test case | `inventory search "<TCODE>" --type Module` → create/reuse modules → assemble case → see [SAP GUI guide](references/sap-automation.md) |

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

# Playlists
python tosca_cli.py playlists list
python tosca_cli.py playlists run <id> --wait
python tosca_cli.py playlists results <runId>

# Folders
python tosca_cli.py inventory move testCase <entityId> --folder-id <folderEntityId>
python tosca_cli.py inventory create-folder --name "..." [--parent-id "..."]
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
| MBT PATCH ops | Lowercase: `replace`, `add`, `remove` |
| Inventory v3 PATCH body | Wrapper: `{"operations": [{"op": "Replace", ...}]}` — PascalCase op |
| Inventory search filter | Despite swagger, only lowercase works: `contains`, `and` |
| SAP standard modules | Not in inventory. `SAP Logon`, `SAP Login`, `T-code` — use IDs directly from [SAP guide](references/sap-automation.md) |
| TSU export field | `reusableTestStepBlockIds` (no double-e) |
| `version` in PUT body | Omit — rejected by both case and block PUT endpoints |

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

## Detailed how-to guides

- Read [Web Automation (Html engine)](references/web-automation.md) when creating or updating Html engine modules, building web test cases, or using Playwright to discover element locators and class names.
- Read [SAP GUI Automation (SapEngine)](references/sap-automation.md) when creating or updating SAP GUI modules, assembling SAP test cases, or working with T-codes, RelativeId locators, or the Precondition reusable block.
