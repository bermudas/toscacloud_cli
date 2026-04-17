# Web Automation (Html Engine) — Detailed Guide

## Discovery workflow with Playwright

```
1. browser_navigate <url>
2. browser_snapshot                — get accessibility tree
3. browser_evaluate 'document.querySelectorAll("a[href='/path']").length'
   → must return 1; if > 1, find a discriminating ClassName
4. browser_evaluate 'JSON.stringify(Array.from(document.querySelectorAll("a[href='/path']")).map(function(el){return {cls:el.className}}))'
   → pick the class unique to the target element (e.g. top-navigation__item-link)
5. browser_click ref=<refId>       — navigate forward
6. Repeat for each step in the user journey
```

**Always verify element uniqueness before writing the module.** Many sites render nav links in both a mobile hamburger menu and a desktop nav bar. TOSCA will fail at runtime, not at save time, if a locator matches more than one element.

## Module structure

```json
{
  "$type": "ApiModuleV2",
  "id": "<moduleId>",
  "name": "<AppName> | <PageName>",
  "businessType": "HtmlDocument",
  "interfaceType": "Gui",
  "parameters": [
    {"id": "<ULID>", "name": "Engine", "value": "Html", "type": "Configuration"}
  ],
  "attributes": [
    {
      "id": "<fresh-ULID>",
      "name": "<HumanLabel>",
      "businessType": "Link",
      "defaultActionMode": "Input",
      "defaultDataType": "String",
      "defaultOperator": "Equals",
      "valueRange": ["{Click}", "{Rightclick}"],
      "isVisible": true,
      "isRecursive": false,
      "cardinality": "ZeroToOne",
      "interfaceType": "Gui",
      "parameters": [
        {"name": "BusinessAssociation", "value": "Descendants", "type": "Configuration"},
        {"name": "Engine",              "value": "Html",         "type": "Configuration"},
        {"name": "Tag",                 "value": "A",            "type": "TechnicalId"},
        {"name": "InnerText",           "value": "<linkText>",   "type": "TechnicalId"},
        {"name": "HREF",                "value": "/path",        "type": "TechnicalId"},
        {"name": "ClassName",           "value": "<cssClass>",   "type": "TechnicalId"}
      ]
    }
  ]
}
```

**The root-level `parameters` array must contain `Engine: Html`.** Without it, TOSCA throws `XModules and XModuleAttributes have to provide the configuration param "Engine"` at runtime. Scanned modules have it automatically; manually created ones do not.

### Module-level identifiers (TechnicalId on the module root, not on an attribute)

These determine *which HtmlDocument* (i.e. browser tab) the module binds to at runtime. On a shared-Chrome agent (user's personal browser with many tabs), the defaults are too loose.

| Param | Type | Good value | Why |
|-------|------|-----------|-----|
| `Engine` | Configuration | `Html` | Required — see above |
| `Title` | TechnicalId | `*<AppName>*` (glob) | Restricts document match by tab title |
| `Url` | TechnicalId | `https://<host>*` | **Add this** to disambiguate when multiple tabs share a title pattern — this alone stops the _"More than one matching tab"_ error without needing a `CloseBrowser` first |
| `ControlFramework` | Steering | `None` | Default for vanilla HTML |
| `AllowedAriaControls` | Steering | `button; checkbox; combobox; link; listbox; menuitem; menuitemcheckbox; menuitemradio; option; radio; scrollbar; slider; spinbutton; switch; tab; textbox; treeitem` | Empty value causes erratic element resolution |
| `EnableSlotContentHandling` | Steering | `False` | `True` triggers shadow-DOM traversal that many ordinary pages don't need |
| `IgnoreInvisibleHtmlElements` | Steering | `True` | Skip off-screen duplicates of the same element |

Scanned modules also carry a `SelfHealingData` steering param with hints about the page at scan time (Title + URL). **When reusing a scanned module for a different flow, drop the `SelfHealingData` entry** — the module still works via TechnicalIds, and stale self-healing hints can interfere with document matching on the new flow.

## businessType by element

| Element | `businessType` | `valueRange` |
|---------|---------------|-------------|
| `<a>` | `Link` | `["{Click}", "{Rightclick}"]` |
| `<button>` | `Button` | `["{Click}"]` |
| `<input type=text>` | `TextBox` | `["{Click}", "{Doubleclick}", "{Rightclick}"]` |
| `<input type=checkbox>` | `Checkbox` | `["{Click}"]` |
| `<select>` | `Combobox` | `["{Select}"]` |
| `<div>`/`<span>` container to verify | `Container` | — |
| page root | `HtmlDocument` | — (module-level only) |

## Standard framework module IDs

| Step | Module ID | Attribute | Attr ref ID | Notes |
|------|-----------|-----------|-------------|-------|
| `OpenUrl` | `9f8d14b3-7651-4add-bcfe-341a996662cc` | `Url` | `39e342b2-960b-2251-d1b9-5b340c12fa19` | Navigate |
| same | same | `UseActiveTab` | `39ef3b0d-1ee2-a137-d5d3-976be1b8c766` | Always `"False"` |
| same | same | `ForcePageSwitch` | `deaad6b0-32d2-4c60-a682-40e30540e3d9` | Always `"True"` |
| `CloseBrowser` | `3019e887-48ca-4a7e-8759-79e7762c6152` | `Title` | `39e342b2-958e-3e2f-7c85-29871c23f1dc` | Value = title glob; `"*"` = any |
| `Wait` | `80b7982e-0e10-4bc0-bdf3-6bc04503fd63` | `Duration` | `39e342b2-958e-ba1f-bb58-702e193d6016` | ms; `dataType: Numeric` |
| `Buffer` | `8415c10d-ab41-44a7e-949a-602f4dddd2d2` | `<name>` | `39e342b2-958e-0a6b-cbfd-5fdd372ca255` | Store value in buffer |

## 4-folder test case structure

```
Precondition   — CloseBrowser Title="*"  ← ALWAYS FIRST: clears leftover browser sessions
               — OpenUrl (Url + UseActiveTab=False + ForcePageSwitch=True)
Process        — User actions (click links, fill inputs, click buttons)
Verification   — Verify steps (actionMode: Verify + actionProperty)
Teardown       — CloseBrowser + optional Wait
```

> **Why CloseBrowser first?** A leftover browser tab from a previous run causes _"More than one matching tab"_. Starting with `CloseBrowser Title="*"` (wildcard) guarantees a clean slate — **on grid agents and workstations that run a dedicated Chrome profile**. On workstation agents that reuse the user's personal Chrome, `Title="*"` would close the user's own tabs — narrow it to `Title="*<AppName>*"` and wrap in a `ControlFlowItemV2 If` that first verifies a known app element is visible.

> **When CloseBrowser fails with `UnestablishedConnectionException`** — the agent has no running Chrome at all (typical on a fresh grid agent). `CloseBrowser` tries to handshake with the extension, hits a 10 s timeout, and aborts. In that case remove the cleanup step entirely — `OpenUrl` will launch Chrome itself.

> **`"The Browser could not be found"` at the first interactive step** — the Tricentis Chrome extension is not installed/enabled in the Chrome instance the agent is driving. OpenUrl opens the tab, but subsequent steps have no bridge. Fix on the agent (install the extension in the profile, or configure a dedicated profile). **No test-case change resolves this.**

## OpenUrl step template (all 3 params required)

```json
{
  "$type": "TestStepV2",
  "name": "OpenUrl – https://example.com",
  "moduleReference": {
    "id": "9f8d14b3-7651-4add-bcfe-341a996662cc",
    "packageReference": {"id": "Html", "type": "Standard"},
    "metadata": {"isRescanEnabled": false, "engine": "Framework"}
  },
  "testStepValues": [
    {
      "name": "Url", "value": "https://example.com",
      "actionMode": "Input", "dataType": "String", "operator": "Equals",
      "moduleAttributeReference": {
        "id": "39e342b2-960b-2251-d1b9-5b340c12fa19",
        "moduleId": "9f8d14b3-7651-4add-bcfe-341a996662cc",
        "packageReference": {"id": "Html", "type": "Standard"}
      }
    },
    {
      "name": "UseActiveTab", "value": "False",
      "actionMode": "Input", "dataType": "String", "operator": "Equals",
      "moduleAttributeReference": {
        "id": "39ef3b0d-1ee2-a137-d5d3-976be1b8c766",
        "moduleId": "9f8d14b3-7651-4add-bcfe-341a996662cc",
        "packageReference": {"id": "Html", "type": "Standard"},
        "metadata": {"valueRange": ["True", "False"]}
      }
    },
    {
      "name": "ForcePageSwitch", "value": "True",
      "actionMode": "Input", "dataType": "String", "operator": "Equals",
      "moduleAttributeReference": {
        "id": "deaad6b0-32d2-4c60-a682-40e30540e3d9",
        "moduleId": "9f8d14b3-7651-4add-bcfe-341a996662cc",
        "packageReference": {"id": "Html", "type": "Standard"},
        "metadata": {"valueRange": ["True", "False"]}
      }
    }
  ]
}
```

## Verify steps

```json
{
  "name": "Error message",
  "value": "Please enter a valid email address.",
  "actionMode": "Verify",
  "actionProperty": "InnerText",
  "operator": "Equals",
  "dataType": "String"
}
```

| `actionProperty` | Checks |
|-----------------|--------|
| `"Visible"` | Element is visible; value `"True"` |
| `"InnerText"` | Exact inner text matches value |
| `""` (empty) | Plain interaction, no assertion |

## Test case config params

```json
"testConfigurationParameters": [
  {"name": "Browser", "value": "Chrome", "dataType": "String"}
]
```

Supported: `Chrome`, `Edge`, `Firefox`.

## Password fields

```json
{
  "name": "Password:", "value": "",
  "password": {"id": "<encrypted-id>"},
  "actionMode": "Input", "dataType": "Password", "operator": "Equals"
}
```

Reference config params in steps: `{CP[Username]}`, `{CP[Password]}`.

## Conditional steps — `ControlFlowItemV2` for optional elements

Wrap a step in an `If` block when the element may or may not be present (cookie banners, leftover tabs, optional popups). **Works reliably only when the module-level selector can cleanly miss** — i.e. add a tight `Url=https://host.tld*` to the module so the document match returns a clean no-match instead of hard-failing.

```json
{
  "$type": "ControlFlowItemV2",
  "statementTypeV2": "If",
  "id": "<ULID>",
  "name": "If cookie banner shown",
  "disabled": false,
  "condition": {
    "id": "<ULID>",
    "name": "Condition",
    "disabled": false,
    "items": [
      {
        "$type": "TestStepV2",
        "id": "<ULID>",
        "name": "Accept Cookies visible?",
        "moduleReference": { "id": "<pageModuleId>", "metadata": {...} },
        "testStepValues": [{
          "id": "<ULID>",
          "name": "Accept Cookies",
          "value": "True",
          "actionMode": "Verify",
          "actionProperty": "Visible",
          "dataType": "String",
          "operator": "Equals",
          "moduleAttributeReference": { "id": "<attrId>", "moduleId": "<pageModuleId>", "metadata": {...} },
          "subValues": [],
          "disabled": false
        }]
      }
    ]
  },
  "conditionPassed": {
    "id": "<ULID>",
    "name": "Then",
    "disabled": false,
    "items": [ /* the original Click step */ ]
  }
}
```

Top-level keys: `$type`, `statementTypeV2` (`"If"`), `condition` (inline folder), `conditionPassed` (inline folder), `id`, `name`, `disabled`. No `conditionFailed` — just omit and nothing runs on the false branch.

Typical uses that have been verified in production:
- Cookie banner (OneTrust `#onetrust-accept-btn-handler`) — condition: Verify `Accept Cookies` Visible=True
- Leftover browser tab cleanup — condition: Verify a known nav element Visible=True; then: `CloseBrowser Title="*<AppName>*"`

## Debugging a failed run

1. `playlists results <runId>` returns only `<failure />`. No step-level logs exist via the Playlists v2 API.
2. Logs are stored in Azure Blob and fetched by the Portal via `/{spaceId}/_e2g/api/executions/{executionId}/units/{unitId}/attachments`, which returns SAS-signed URLs like:
   ```
   https://e2gweuprod001resblobs.blob.core.windows.net/<tenant-slug>/<spaceId>/<executionId>/<unitId>/logs?sv=…&se=…&sr=b&sp=r&sig=…
   ```
   SAS TTL ≈ 30 min. The blob GET takes **no Authorization header** — the SAS is the entire auth. Also available on the same endpoint: `TBoxResults.tas`, `TestSteps.json`, `Recording.mp4`, `junit_result_*.xml`.
3. The `Tricentis_Cloud_API` client app this CLI uses is **403'd** on that attachments endpoint today (no E2G role). Workarounds:
   - Grant the app E2G-read access (admin change on the tenant).
   - Copy the SAS URL from the Portal DevTools Network tab and `curl` it.
   - Re-run locally on an E2G agent: the same log mirrors at `C:\Users\<user>\AppData\Local\Temp\E2G\<runUuid>\…`.
3. Common error mapping:

   | TBox message | Likely cause | Fix |
   |--------------|-------------|-----|
   | `UnestablishedConnectionException` at CloseBrowser | No Chrome running on agent | Remove the cleanup step, or wrap in `If` + narrow `Title` |
   | `The Browser could not be found` | Tricentis Chrome extension not attached | Install/enable extension in agent's Chrome profile — not a test fix |
   | `More than one matching tab was found` | Agent shares user's Chrome; multiple tabs match | Add `Url=https://<host>*` TechnicalId at module level |
   | `Could not find HtmlDocument … Title: <pattern>` | Module-level selector doesn't match | Tighten/fix `Title`; add `Url` for host-scoped match |
   | `Could not find Link '…'` | Element locator ambiguous or DOM changed | Re-check via Playwright `browser_evaluate` + uniqueness count |

## Creation workflow

```bash
# 1. Playwright: snapshot page, verify element uniqueness with browser_evaluate
# 2. Check for existing module
python tosca_cli.py inventory search "<AppName>" --type Module

# 3. Create module (if none exists)
python tosca_cli.py modules create --name "<AppName> | <PageName>" --iface Gui --json
# Write module JSON file with Engine param at root level + attribute params
python tosca_cli.py modules update <moduleId> --json-file /tmp/module.json
python tosca_cli.py modules get <moduleId> --json   # verify

# 4. Create test case
python tosca_cli.py cases create --name "<description>" --state Planned --json
python tosca_cli.py cases update <caseId> --json-file /tmp/case.json
python tosca_cli.py cases steps <caseId>
python tosca_cli.py inventory move testCase <caseId> --folder-id <folderId>
```
