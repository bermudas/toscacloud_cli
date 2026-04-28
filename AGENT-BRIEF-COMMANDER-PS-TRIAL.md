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

## 7. Common errors — decision tree

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

## 8. Reporting back

When the trial completes (success or failure), produce a single message containing:

1. **Status**: `success` / `partial` / `failed` + a one-sentence summary.
2. **Auth mode that worked**: one of `pat`, `basic`, `client-creds`, `negotiate`, `ntlm`.
3. **Tosca Server version** (top of Phase 1 output).
4. **Workspace name** used.
5. **Phase 1 console output** in full.
6. **Phase 2 console output** in full — both stdout and any error stream.
7. **Created object UniqueIds** (new Module + new TestCase) so they can be cleaned up later if needed.
8. **Any deviations from the expected output** above, even minor ones (extra fields, different property names).
9. **Sanitization**: redact tokens, AD passwords, customer-identifying TestCase names, and any internal hostnames if the user requires it. Keep all UniqueIds and Tosca-internal field names — those are needed for tuning.

Cleanup commands (only run if the user asks):

```powershell
# Use the UniqueIds reported in step 7 above
$h = @{Authorization = "Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("$env:TOSCA_COMMANDER_USER`:$env:TOSCA_COMMANDER_PASSWORD"))}
Invoke-RestMethod -Method DELETE -Uri "<base>/<workspace>/object/<NewTcId>"  -Headers $h
Invoke-RestMethod -Method DELETE -Uri "<base>/<workspace>/object/<NewModId>" -Headers $h
Invoke-RestMethod -Method POST   -Uri "<base>/<workspace>/task/CheckInAll"   -Headers $h
```

## 9. Boundaries

- **Do not** modify or delete any source object (the original TestCase + Module the trial reads).
- **Do not** execute test runs, change permissions, or touch any Tosca Server config.
- **Do not** install Python or any Python dependencies.
- **Do not** push, commit, or share the contents of `.env` — it contains secrets.
- **If credentials seem wrong**, ask the user before re-trying with new ones. Do not brute-force.
- **If the workspace name is uncertain**, list candidates from the user / admin rather than guessing.
