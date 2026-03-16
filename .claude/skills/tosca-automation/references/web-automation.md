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

> **Why CloseBrowser first?** A leftover browser tab from a previous run causes _"More than one matching tab"_. Starting with `CloseBrowser Title="*"` (wildcard) guarantees a clean slate.

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
