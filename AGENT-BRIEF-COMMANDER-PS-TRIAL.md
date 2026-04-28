# Agent brief: TOSCA Commander REST trial — PowerShell path

This document is written for an **AI agent** (Claude Code, Copilot, or similar) running on the user's client machine. The agent's job is to drive the PowerShell trial of `trial.ps1` against a live on-prem Tosca Server, troubleshoot anything that breaks, and report results back.

A human tester can also follow this doc verbatim — every command is shown literally.

---

## 1. Mission

Validate that a new on-prem TOSCA Commander REST CLI (`tosca_commander_cli.py`) and its sibling PowerShell probe (`trial.ps1`) can:

- Authenticate against the on-prem Tosca Server REST Webservice (TCRS).
- Open a workspace.
- Read an existing TestCase that references at least one Module.
- **Re-create both objects as new copies under different names** — the new TestCase must reference the new Module copy (not the original).
- Persist the writes via `CheckInAll`.
- Verify the writes via TQL search.

The trial is **non-destructive**: it adds two new named objects to the workspace (`<originalModule>_v2` and `<originalTestCase>_clone`). It does not modify, delete, or execute anything that already exists.

## 2. Inputs you receive

The user has placed two files in a folder on the client machine (typical: `C:\Users\<user>\Documents\Test\` or `C:\Users\<user>\Desktop\tosca-trial\`):

| File | Role |
|---|---|
| `trial.ps1` | Self-contained PowerShell 5.1+ script. Implements the trial via `Invoke-RestMethod`. ASCII-only — no Unicode, encoding-agnostic. |
| `.env.commander.example` | Env-file template. Copy → `.env`, fill in values. |

You must **not** assume Python is installed; this entire trial runs in PowerShell only.

## 3. Environment

You will need to gather four things from the user (or their Tosca Commander UI):

1. **Tosca Server base URL** — the host (and optional port) of the on-prem Tosca Server, e.g. `http://your-tosca-server:1111` or `https://tosca-server.example.com`. Ask the user; do not guess. The CLI auto-appends `/rest/toscacommander` if missing.
2. **Workspace name** — the **exact case-sensitive folder name** that lives under the server's `WorkspaceBasePath` (configured in `appsettings.json`). The Tosca Commander UI title bar shows it. Common mistake: case differs from what the user remembers.
3. **Auth credentials** — pick ONE combo:
   - **LDAP / AD (most common)** — `TOSCA_COMMANDER_AUTH=basic`, `TOSCA_COMMANDER_USER=user@DOMAIN.FQDN` (UPN format, exactly as shown in the Tosca Login dialog), `TOSCA_COMMANDER_PASSWORD=<the AD password>`. The Tosca login dialog labels this "LDAP" but on the wire it's HTTP Basic.
   - **PAT** — `TOSCA_COMMANDER_TOKEN=<long base64 blob from Tosca Server → Profile → Personal Access Tokens>`. Paste verbatim; do not decode.
   - **Windows SSO (Negotiate)** — `TOSCA_COMMANDER_AUTH=negotiate` and **no other auth fields**. Uses the logged-in Windows session via SSPI. Only works if Tosca Server is fronted by IIS with Windows Authentication.
   - **Explicit-cred NTLM** — `TOSCA_COMMANDER_AUTH=ntlm` + `USER` + `PASSWORD`.
   - **OAuth2 client-credentials** — `TOSCA_COMMANDER_CLIENT_ID` + `TOSCA_COMMANDER_CLIENT_SECRET`. Token endpoint `<server>/tua/connect/token`.

## 4. Pre-flight (one-time, in the same PowerShell window)

```powershell
# 4.1  Confirm shell. If the prompt is `>` only (no `PS`), this is cmd.exe — open Windows PowerShell instead.
$PSVersionTable.PSVersion       # must be >= 5.1

# 4.2  cd to the folder containing trial.ps1
cd "<path-to-folder>"
dir                              # confirm both trial.ps1 and .env.commander.example are present

# 4.3  Allow unsigned scripts in this PowerShell window only
Unblock-File .\trial.ps1                                   # remove Mark-of-the-Web (downloaded-from-internet flag)
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass # answer Y at the yellow prompt
# -Scope Process = only this window. Reverts when window closes. No admin needed.

# 4.4  Create .env from the template, then edit
Copy-Item .\.env.commander.example .env
notepad .env
# (When saving from Notepad, use Save (Ctrl+S), NOT Save As — Save-As may auto-append .txt.
#  If Save-As is unavoidable, change "Save as type" to "All Files (*.*)" first.)

# 4.5  Sanity-check the env was written cleanly (skips PASSWORD line)
Get-Content .env | Select-String -NotMatch '^\s*#|^\s*$|PASSWORD'
```

`.env` content (uncomment ONE auth combo):

```env
TOSCA_COMMANDER_BASE_URL=http://your-server:1111
TOSCA_COMMANDER_WORKSPACE=YourWorkspace_ExactCase

# Auth A — PAT (recommended)
TOSCA_COMMANDER_TOKEN=<paste verbatim>

# Auth B — Basic / LDAP / AD
#TOSCA_COMMANDER_AUTH=basic
#TOSCA_COMMANDER_USER=user@DOMAIN.FQDN
#TOSCA_COMMANDER_PASSWORD=<AD password>

# Auth C — OAuth2 client-creds
#TOSCA_COMMANDER_CLIENT_ID=
#TOSCA_COMMANDER_CLIENT_SECRET=

# Auth D — Windows SSO via SSPI
#TOSCA_COMMANDER_AUTH=negotiate

# Auth E — explicit-cred NTLM
#TOSCA_COMMANDER_AUTH=ntlm
#TOSCA_COMMANDER_USER=DOMAIN\you
#TOSCA_COMMANDER_PASSWORD=
```

## 5. Phase 1 — discovery (no parameters)

```powershell
.\trial.ps1
```

**Expected output**:

```
Tosca Commander REST trial -- PowerShell
  Base URL : http://your-server:1111/rest/toscacommander
  Workspace: YourWorkspace
  Auth mode: <pat|basic|negotiate|ntlm|client-creds>

[1] GET ... (version probe)
{
  "Version": "<x.y.z>"
}

[2] GET ... (open workspace)
{ ... workspace JSON ... }

DISCOVERY MODE -- finding TestCases that reference Modules and resolving their parents...
  project root UniqueId = 01XXX...

[3] TQL =>SUBPARTS:TestCase  (probing first 20 to find 5 with Module refs)
  found candidate 1: <TestCaseName> -> <ModuleName>
  ...

Phase-2-ready candidates:
# TestCase   TC_Id  TC_Parent  Module  MOD_Id  MOD_Parent
- ----...    ...    ...        ...     ...     ...

Copy ONE line below into PowerShell to run Phase 2 on the matching row:
  # row 1: ...
  .\trial.ps1 -TestCaseId <TC_Id> -ModuleId <MOD_Id> -TestCaseParentId <TC_Parent> -ModuleParentId <MOD_Parent>
  ...
```

**Capture for the report**: the entire console output of Phase 1.

## 6. Phase 2 — round-trip (one of the printed lines)

Pick any row from Phase 1's output. Right-click → paste → Enter. The exact line looks like:

```powershell
.\trial.ps1 -TestCaseId 01ABC... -ModuleId 01XYZ... `
            -TestCaseParentId 01PQR... -ModuleParentId 01STU...
```

**Expected output**:

```
[1] GET ... (version probe)
[2] GET ... (open workspace)

[3] GET TestCase <TC_Id> (depth 5)
  Source TC Name = <name>

[4] GET Module <MOD_Id> (depth 3)
  Source MOD Name = <name>

[5] POST new Module under <MOD_Parent> (strip + rename '_v2')
  -> new Module UniqueId = 01NEWMOD...

[6] POST new TestCase under <TC_Parent> (strip + rename '_clone' + rewrite <MOD_Id> -> 01NEWMOD...)
  -> new TestCase UniqueId = 01NEWTC...

[7] CheckInAll
  [OK] CheckInAll OK

[8] Verify both via TQL
  TC clone hits     : 1
  Module clone hits : 1

DONE.
Created:
  Module    : <name>_v2     UniqueId=01NEWMOD...
  TestCase  : <name>_clone  UniqueId=01NEWTC...   -> references 01NEWMOD... (was 01XYZ...)
```

**Capture for the report**: the full Phase 2 output, especially any HTTP error response bodies if a step fails.

## 7. API reference for this workflow

`trial.ps1` only touches the **TCRS** (Tosca Commander REST Webservice) under `/rest/toscacommander`. Endpoints below are aligned with **devcorner 2024.2** docs; a self-describing operations index lives at `<base>/help` on most builds. Memorize the shapes — they're what you compare against when something fails.

### Auth headers (per devcorner 2024.2)

| Mode | Headers |
|---|---|
| **Basic / LDAP / AD** | `Authorization: Basic <base64(user:pass)>` *(no AuthMode header)* |
| **PAT** | `Authorization: <token>` *(token raw — no `Basic` prefix, no base64)* + `AuthMode: pat` |
| **Client-credentials** | `Authorization: Basic <base64(client_id:client_secret)>` + `AuthMode: clientCredentials` *(plain Basic, NOT OAuth2)* |
| **Negotiate** | Native NTLM/Kerberos challenge; `Invoke-RestMethod -UseDefaultCredentials` |
| **NTLM (explicit creds)** | `Invoke-RestMethod -Credential` |

If a tenant requires the LDAP-specific routing header (rare), set `TOSCA_COMMANDER_AUTH_MODE` env var and we'll forward it.

### Endpoints used by `trial.ps1`, in execution order

| # | Method | Path | Purpose | Request body | Expected 2xx response |
|---|---|---|---|---|---|
| 1 | `GET` | `<base>` | Version probe; also a cheap auth/connectivity check. | none | `{ "Version": "<x.y.z>" }` |
| 2 | `GET` | `<base>/<workspace>` | Open the workspace via TCAPI shim. 404 = workspace folder missing under `WorkspaceBasePath`. | none | object with workspace metadata; shape varies by version |
| 3 | `GET` | `<base>/<workspace>/search?tql=<urlencoded TQL>` | **Canonical TQL search** (top-level, workspace-scoped, no rootId). Parameter is `tql`, not `tqlString`. | none | array of matching objects |
| 4 | `GET` | `<base>/<workspace>/object/<id>?depth=<N>` | Fetch a single object plus children up to depth N. | none | object with `UniqueId`, `Name`, properties, nested `Subparts`/refs |
| 5 | `POST` | `<base>/<workspace>/object/<parentId>` | Create a new object under `<parentId>`. Body = TCAPI object representation (server-minted fields stripped, `Name` renamed, refs rewritten). On strict newer builds the canonical form may be `POST <base>/<workspace>/object` with parent in body — probe if 405/404. | TCAPI object body | newly-created node JSON, includes **new** `UniqueId` |
| 6 | `POST` | `<base>/<workspace>/task/CheckInAll` | Workspace-level generic task — commits all pending TCAPI changes. Optional query param `?checkincomment=<text>` for an audit comment. | `{}` | usually 204 |
| 7 | `DELETE` | `<base>/<workspace>/object/<id>` | Cleanup. Only run if the user asks. | none | empty body / 204 |

### Other canonical TCRS endpoints worth knowing

| Path | Purpose |
|---|---|
| `<base>/GetWorkspaces` (GET) | List every workspace under `WorkspaceBasePath`. Names come back **prefixed with `\`** — strip it before reuse. Sanity-check the workspace name spelling here when step 2 returns 404. |
| `<base>/<ws>/metainfo` (GET) | List all object types in this workspace. (Note: path is **`metainfo`**, not `meta`.) |
| `<base>/<ws>/metainfo/<TypeName>` (GET) | Type summary — fields + supported tasks. |
| `<base>/<ws>/metainfo/<TypeName>/attributes` (GET) | Full attribute schema for the type. Useful for deciding what to keep / strip on create. |
| `<base>/<ws>/metainfo/<TypeName>/associations` (GET) | Full association schema. |
| `<base>/<ws>/treeview` (GET) | Workspace tree root. |
| `<base>/<ws>/treeview/<id>/subparts` (GET) | Direct children of an object. Different from `?depth=` on the object endpoint. |
| `<base>/<ws>/object/<id>/task/ExportAutomationObjects` (GET) | TSU export — Tosca's portable bundle for cross-workspace migration. Returns binary; save to disk. |
| `<base>/<ws>/task/importaoresults` (POST) | TSU import counterpart. |
| `<base>/<ws>/object/<id>/task` (GET) | List tasks supported by this object. |
| `<base>/<ws>/object/<execListId>/testcaselogswithtestcases` (GET) | Paired ExecutionLog ↔ TestCase retrieval — replaces a TQL walk for log inspection. |
| `<base>/<ws>/projectid` (GET) | Workspace's project ID. |
| `<base>/<ws>/revision` (GET) | Workspace revision info. |
| `<base>/<ws>/getissues` (POST) | Workspace validation issues. |

### Field-name reality check

The script makes three assumptions about response shapes that may differ on real tenants. **If a step fails or behaves wrong, this is your first hypothesis**:

| Helper in `trial.ps1` | Default assumption | Real-world variants seen | How to confirm against your tenant |
|---|---|---|---|
| `Get-OwnerUniqueId` | The parent reference is in one of: `OwnerUniqueId`, `ParentUniqueId`, `OwnerId`, `ParentId`, `Parent` | Some Tosca builds nest it: `Parent.UniqueId`; older ones use `OwnerId` only; some use `OwnerRef` | Run a manual `objects get` (probe §8) on any object and inspect its top-level keys. |
| `Find-ModuleRefs` | A module reference is a 26-char Crockford base32 UniqueId (`^[0-9A-HJKMNP-TV-Z]{26}$`) under any property whose name contains `Module` | Some builds use 32-char GUIDs (with dashes); some put the ref inside a struct (`{ "ModuleReference": { "UniqueId": "..." } }`) instead of as a flat string | Inspect a TestCase's body (probe §8). Look for any field with `Module` in the key whose value is a UniqueId-shaped string OR a struct containing one. |
| `Remove-ServerFields` strip list | `UniqueId`, `Revision`, `CreatedBy/At`, `ModifiedBy/At`, `NodePath` | Some builds also reject: `OwnerUniqueId` (write-only on create), `Persistence`, `Marker`, `Status` audit fields | If POST returns 400 with a "field X cannot be set on create" message, that field needs to be added to the strip list. |

## 8. Probing the API directly (when the script fails)

When `trial.ps1` reports an unexpected response, **do not iterate the script blindly** — call the relevant endpoint by hand first and inspect the actual JSON. Save your auth headers into `$h` once (per devcorner 2024.2 patterns):

```powershell
# Basic / LDAP / AD
$h = @{Authorization = "Basic " + [Convert]::ToBase64String(
        [Text.Encoding]::UTF8.GetBytes("$env:TOSCA_COMMANDER_USER`:$env:TOSCA_COMMANDER_PASSWORD"))}

# OR — PAT (token raw, AuthMode header)
$h = @{Authorization = $env:TOSCA_COMMANDER_TOKEN; AuthMode = 'pat'}

# OR — Client credentials (Basic with cid:csecret, AuthMode header)
$h = @{
  Authorization = "Basic " + [Convert]::ToBase64String(
      [Text.Encoding]::UTF8.GetBytes("$env:TOSCA_COMMANDER_CLIENT_ID`:$env:TOSCA_COMMANDER_CLIENT_SECRET"))
  AuthMode = 'clientCredentials'
}

$base = "<base>/rest/toscacommander"
$ws   = "<workspace>"
```

Then probe each step in isolation:

```powershell
# 1) Version probe
Invoke-RestMethod -Uri "$base"                           -Headers $h | ConvertTo-Json -Depth 3

# 2) List workspaces (sanity-check the workspace name spelling)
Invoke-RestMethod -Uri "$base/GetWorkspaces"             -Headers $h
# names come back prefixed with '\' — strip before reuse

# 3) Open workspace (must be 200; 404 = wrong name; 401 = bad creds)
Invoke-RestMethod -Uri "$base/$ws"                       -Headers $h | ConvertTo-Json -Depth 3

# 4) Canonical TQL search (top-level, GET, parameter is `tql`)
$tql = [uri]::EscapeDataString('=>SUBPARTS:TestCase')
Invoke-RestMethod -Uri "$base/$ws/search?tql=$tql"       -Headers $h `
  | Select-Object -First 3 | ConvertTo-Json -Depth 5

# 5) Fetch one object — exhaustively inspect its top-level keys
$obj = Invoke-RestMethod -Uri "$base/$ws/object/<some-UniqueId>?depth=5" -Headers $h
$obj | Get-Member -MemberType NoteProperty | Select-Object Name           # all top-level field names
$obj.PSObject.Properties.Name -match 'Module'                              # any key referencing Module
$obj.PSObject.Properties.Name -match 'Owner|Parent'                        # parent-reference candidates

# 6) Create probe — try a tiny body to see what the server complains about
#    Pick any folder UniqueId you have from steps 4/5 above as <parentId>.
#    (The project root is also a valid parent: GET $base/$ws/object/project/ → grab UniqueId.)
$parentId = '<paste-any-folder-UniqueId-from-step-4-or-5>'
$probeBody = @{ TypeName = 'TestCase'; Name = 'cli_probe_temporary' } | ConvertTo-Json
try {
  Invoke-RestMethod -Method POST -Uri "$base/$ws/object/$parentId" -Headers $h `
    -Body $probeBody -ContentType 'application/json'
} catch {
  $_.Exception.Response.GetResponseStream() | % { (New-Object IO.StreamReader $_).ReadToEnd() }
  # ^ read the actual error body — this names the missing/extra fields
}
```

The output of step 5's `Get-Member` query is the most useful single artifact — it tells you the **exact field names** the server returns, which is what `Get-OwnerUniqueId` and `Find-ModuleRefs` need to match.

## 9. Patching `trial.ps1` when the API differs

You **may edit `trial.ps1`** if the probes in §8 reveal a field-name or shape mismatch the default heuristics don't handle. This is expected behavior, not a workaround. Constraints:

- **Keep the script ASCII-only.** No Unicode characters anywhere — they break Windows PowerShell 5.1's parser when there's no UTF-8 BOM. Use `->` / `--` / `[OK]` instead of `→` / `—` / `✓`.
- **Patch the helper, not the call site.** If the parent-reference field is wrong, fix `Get-OwnerUniqueId`. If module-ref detection misses a struct, fix `Find-ModuleRefs`. Don't inline ad-hoc field accesses scattered through Phase 1/2.
- **Commit the change in your scratch copy** (don't push) — but *do* report the diff.
- **Re-run after each patch** — never stack untested fixes.

### Common patches you may need

**A. Parent reference is nested or differently named**

If `Get-OwnerUniqueId` returns null on real responses, expand the probe list. Example:

```powershell
function Get-OwnerUniqueId {
    param($Obj)
    foreach ($key in 'OwnerUniqueId','ParentUniqueId','OwnerId','ParentId','Parent','OwnerRef') {
        if ($Obj -and $Obj.PSObject.Properties[$key]) {
            $v = $Obj.PSObject.Properties[$key].Value
            if ($v -is [string] -and $v) { return $v }
            # Nested: { "Parent": { "UniqueId": "..." } }
            if ($v -and $v.PSObject -and $v.PSObject.Properties['UniqueId']) {
                return $v.PSObject.Properties['UniqueId'].Value
            }
        }
    }
    return $null
}
```

**B. Module references are GUIDs, not ULIDs**

Broaden the regex in `Find-ModuleRefs`:

```powershell
# was: -match '^[0-9A-HJKMNP-TV-Z]{26}$'   (Crockford base32 ULID)
# now:
if ($p.Value -is [string] `
    -and ($p.Value -match '^[0-9A-HJKMNP-TV-Z]{26}$' `
       -or $p.Value -match '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$') `
    -and -not $Out.Contains($p.Value)) {
    $null = $Out.Add($p.Value)
}
```

**C. Module reference is a struct, not a flat string**

If module refs are `{ "ModuleReference": { "UniqueId": "..." } }`:

```powershell
# Inside Find-ModuleRefs, extend the dict-walk:
foreach ($p in $Obj.PSObject.Properties) {
    if ($p.Name -like '*Module*') {
        if ($p.Value -is [string] -and $p.Value -match '^[0-9A-HJKMNP-TV-Z]{26}$') {
            $null = $Out.Add($p.Value)
        }
        if ($p.Value -is [System.Management.Automation.PSCustomObject] `
            -and $p.Value.PSObject.Properties['UniqueId']) {
            $null = $Out.Add($p.Value.PSObject.Properties['UniqueId'].Value)
        }
    }
    Find-ModuleRefs $p.Value $Out | Out-Null
}
```

(And in this case, **`--rewrite-ref` won't work as a flat string swap** — the script's `Edit-Refs` would need to also rewrite the nested `UniqueId` value. Same recursive walk, just match on `UniqueId` keys whose ancestor was named `*Module*`.)

**D. Server rejects an extra field on POST**

If step `[5]` or `[6]` returns 400 with "field 'Persistence' cannot be set on create", append the field to the strip list:

```powershell
$Script:ServerMintedFields = @('UniqueId','Revision','CreatedBy','CreatedAt',
                               'ModifiedBy','ModifiedAt','NodePath',
                               'Persistence')   # added per server rejection
```

**E. TQL via POST is rejected**

If step `[3]` of Phase 1 returns 405 / 415, switch to GET:

```powershell
# was: Invoke-Tcrs $auth 'POST' "$base/$ws/object/$rootId/task/search?tqlString=..."
# try: Invoke-Tcrs $auth 'GET'  "$base/$ws/object/$rootId/task/search?tqlString=..."
```

### After patching

1. Re-run Phase 1 (or whichever phase failed). If it now succeeds, continue.
2. If Phase 2 still fails, repeat: probe → identify field mismatch → patch → re-run.
3. After at most three failed patch cycles, **stop and report**. Don't burn unbounded iterations on a stuck shape — escalate with the artifacts you've collected (probe outputs from §8, current diff against the original `trial.ps1`, error bodies).

## 10. Common errors — decision tree

When a step fails, identify the symptom from this table; do NOT iterate blindly.

| Symptom (key text in error) | Root cause | Action |
|---|---|---|
| `'PS>' is not recognized as the name of a cmdlet` | The user typed the literal `PS>` prompt prefix. | Type only what comes after the prompt. `PS C:\…>` is printed by PowerShell already. |
| `'.\trial.ps1' is not recognized…` and `dir` shows no `trial.ps1` | File is in a different folder, or got saved as `trial.ps1.txt` (Windows hides the `.txt`). | `dir` to see the real name; `Get-Location` to confirm the cwd; `Rename-Item .\trial.ps1.txt .\trial.ps1` if the hidden `.txt` is the culprit. |
| `cannot be loaded… not digitally signed… UnauthorizedAccess` | ExecutionPolicy is `RemoteSigned` or `AllSigned`. | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` (answer `Y`); also `Unblock-File .\trial.ps1` if the file came from email/web. |
| `Missing closing '}' / Unexpected token` with garbled chars like `â†'`, `â€"`, `Ã©` in the error printout | File got transcoded in transit (UTF-8 → Windows-1252). The current `trial.ps1` is pure ASCII so this should not happen — if it does, the file was modified somewhere. | Re-fetch `trial.ps1` from the user as a **zip** (not pasted as text in email/Slack). |
| `(404) Not Found` on step `[2]` (open workspace) | Workspace name in `.env` doesn't match a folder under the server's `WorkspaceBasePath`. Auth most likely already passed (a 401 / 403 would say so). | Confirm the workspace name with the Tosca Commander UI title bar (case-sensitive) or by asking the Tosca admin which folder is at `WorkspaceBasePath`. Some Tosca builds expose `GET /rest/toscacommander/GetWorkspaces` — try it. |
| `(401) Unauthorized` | Bad credentials, or wrong auth mode. | If LDAP/AD: ensure UPN format (`user@FQDN.full`). Confirm the password by logging into Tosca Commander UI as that user. If using PAT, ensure the token blob was pasted with no surrounding quotes. |
| `(403) Forbidden` | Auth passed but user lacks permission on the workspace or object. | Ask the Tosca admin to grant the user write access on the workspace. |
| `Invoke-RestMethod : Could not establish trust relationship for the SSL/TLS secure channel` | HTTPS cert is self-signed and PowerShell rejects it. | The script does not currently set `[Net.ServicePointManager]::ServerCertificateValidationCallback`. Workaround: prepend in PS: `[Net.ServicePointManager]::ServerCertificateValidationCallback = { $true }`. |
| `Phase 1 prints "No TestCases with Module references found in the first 20 results."` | Workspace is empty or only has standalone TestCases with no module refs. | Ask the user for a different workspace, or have them point at a workspace with active web/SAP/API automation. |
| `Phase 2 step [5] returns HTTP 400 / 422 with a field-name in the error` | The TCAPI rejects something in the body shape — most often: an enum value the target workspace doesn't define, or a property the source had set that's required to be unset on create. | Capture the full error body and report it back with the offending field name. The CLI maintainer can then add that field to the `--strip-server-fields` list or to a `--rewrite-ref` instruction. |
| `Phase 2 step [6] succeeds but the new TestCase still references the OLD Module (visible in the verify output)` | The `--rewrite-ref` heuristic only matches exact string equality; the source body wraps the ref in a struct (e.g. `{ "ModuleReference": "01XYZ..." }`) where the ref is a property *value* — not an issue — OR the value appears with extra whitespace / different casing. | Capture the full create response. The maintainer can then refine the rewrite logic or apply a pre-edit. |

## 11. Reporting back

When the trial completes (success or failure), produce a single message containing:

1. **Status**: `success` / `partial` / `failed` + a one-sentence summary.
2. **Auth mode that worked**: one of `pat`, `basic`, `client-creds`, `negotiate`, `ntlm`.
3. **Tosca Server version** (top of Phase 1 output).
4. **Workspace name** used.
5. **Phase 1 console output** in full.
6. **Phase 2 console output** in full — both stdout and any error stream.
7. **Created object UniqueIds** (new Module + new TestCase) so they can be cleaned up later if needed.
8. **Any deviations from the expected output** above, even minor ones (extra fields, different property names).
9. **If you patched `trial.ps1`**: a unified diff (or before/after of each helper you changed), the symptom that drove each patch, and the §8 probe output that confirmed it.
10. **Sanitization**: redact tokens, AD passwords, customer-identifying TestCase names, and any internal hostnames if the user requires it. Keep all UniqueIds and Tosca-internal field names — those are needed for tuning.

Cleanup commands (only run if the user asks):

```powershell
# Use the UniqueIds reported in step 7 above
$h = @{Authorization = "Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("$env:TOSCA_COMMANDER_USER`:$env:TOSCA_COMMANDER_PASSWORD"))}
Invoke-RestMethod -Method DELETE -Uri "<base>/<workspace>/object/<NewTcId>"  -Headers $h
Invoke-RestMethod -Method DELETE -Uri "<base>/<workspace>/object/<NewModId>" -Headers $h
Invoke-RestMethod -Method POST   -Uri "<base>/<workspace>/task/CheckInAll"   -Headers $h
```

## 12. Boundaries

- **Do not** modify or delete any source object (the original TestCase + Module the trial reads).
- **Do not** execute test runs, change permissions, or touch any Tosca Server config.
- **Do not** install Python or any Python dependencies.
- **Do not** push, commit, or share the contents of `.env` — it contains secrets.
- **If credentials seem wrong**, ask the user before re-trying with new ones. Do not brute-force.
- **If the workspace name is uncertain**, list candidates from the user / admin rather than guessing.
