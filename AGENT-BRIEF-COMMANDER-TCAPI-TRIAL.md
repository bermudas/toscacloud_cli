# Agent brief: TOSCA Commander TCAPI .NET trial — round-trip via in-process assemblies

This document is written for an **AI agent** (Claude Code, Copilot, or similar) running on the user's Windows client machine. The agent's job is to validate that the **TCAPI .NET assembly transport** (loading `TCAPI.dll` directly via PowerShell + reflection) works as an alternative to the REST/TCRS path — specifically when TCRS auth is blocked on multi-user workspaces.

A human tester can also follow this verbatim — every command is shown literally.

> **This is the second of two trial paths.** The first is the REST/TCRS trial at `AGENT-BRIEF-COMMANDER-PS-TRIAL.md`. Use this one **only** if the REST path returned 401 / 403 on a multi-user workspace and you cannot get AD credentials.

---

## 1. Mission

Prove the in-process **TCAPI .NET** transport can:

1. Load Tosca's local DLLs and authenticate to the Tosca Server with a PAT.
2. Open a multi-user workspace using **Tosca-internal** credentials (NOT AD — multi-user workspaces inside Tosca are typically authored with their own admin password, separate from AD).
3. Search the workspace for an existing TestCase that references a Module.
4. Re-create both as new copies under different names — the new TestCase pointing at the new Module copy.
5. Persist via `workspace.CheckIn()` (or `Save()`).
6. Verify both via TQL.

Same end-state as the REST trial: two new named objects in the workspace, no modifications to existing artifacts, fully reversible.

## 2. Why this exists

The REST path (TCRS) requires either:
- **Tricentis Server Repository workspaces** → PAT + `AuthMode: pat` headers, or
- **Multi-user workspaces** → HTTP Basic with **AD credentials** (the user's Windows-domain login, in UPN format).

When neither is available — typical case: user has a server-level PAT but no AD credentials, and the target workspace is multi-user — REST is dead-ended. The TCAPI .NET path solves this because it uses Tosca's own .NET surface in-process: PAT for *server* login, and a separate Tosca-internal credential pair for *workspace* login (which can be the same `Admin/<password>` set when the workspace was created).

## 3. Inputs you receive

| File | Role |
|---|---|
| `trial.tcapi.ps1` | Starter PowerShell script. Capability check + login + workspace open + discovery work; round-trip is intentionally left as a TODO for you to implement against the live tenant (see §7). |
| `.env.commander.example` | Reference for env-var conventions; this script takes parameters directly, not from `.env`, since the TCAPI auth model differs. |

The user will give you, separately:

- Tosca Commander local install path (default: `C:\Program Files (x86)\TRICENTIS\Tosca Testsuite\ToscaCommander`).
- Tosca Server URL (e.g. `https://your-tosca-server/`).
- Workspace `.tws` file path (e.g. `C:\Tosca_Projects\Tosca_Workspaces\LEAD_GEN_AOS\LEAD_GEN_AOS.tws`).
- Server PAT (the same base64 blob the REST trial uses).
- Workspace user + password (Tosca-internal admin credentials — ask the workspace owner).

## 4. Pre-flight (Mode: probe)

Run the bundled script in capability-probe mode first — it does NOT log in or touch any workspace; it only validates the local environment:

```powershell
.\trial.tcapi.ps1 -Mode probe
```

Expected output (each line is a hard requirement; if any fails, this path is unusable on this machine):

```
[OK] PowerShell  7.x.y
[OK] .NET runtime .NET 8.x  (or .NET 6.x for older Tosca builds)
[OK] Tosca install path: C:\Program Files (x86)\TRICENTIS\Tosca Testsuite\ToscaCommander
[OK] TCAPI.dll, TCAPIObjects.dll present
[OK] Assemblies loaded
     TCAPI.dll        version: x.y.z.w
     TCAPIObjects.dll version: x.y.z.w
[OK] Key TCAPI types resolved
[OK] ToscaServerLogin overloads: (1-arg), (2-arg)

PROBE COMPLETE. Capability confirmed for TCAPI .NET path.
```

Common probe failures:

| Symptom | Cause | Fix |
|---|---|---|
| "Requires PowerShell 7+" | Default Windows PowerShell is 5.1, can't load .NET 8 assemblies. | `winget install Microsoft.PowerShell` then run from `pwsh` not `powershell.exe`. |
| "Tosca Commander folder not found" | Tosca isn't installed or installed at a non-default path. | Pass `-ToscaCommanderPath "<actual path>"`. If Tosca isn't installed at all on this machine, **stop** — this path requires a local install. |
| "Missing required assembly: ...TCAPI.dll" | Tosca install is partial or path is wrong. | Confirm with `dir <ToscaCommanderPath>\TCAPI.dll`. |
| "Type not found: Tricentis.TCAPI.TCAPI" | Assembly version doesn't expose this type — extremely old or hugely customised Tosca install. | Stop. This path is not supported. |
| Probe passes but no `(1-arg)` ToscaServerLogin overload | Tosca version doesn't accept PAT for server login. | Stop. PAT auth not available on this build. |

If probe succeeds, continue. If it fails, **stop** and report which check failed — the path is unviable on this machine.

## 5. Discovery (Mode: discover)

```powershell
.\trial.tcapi.ps1 -Mode discover `
    -ToscaServerUrl       "https://your-tosca-server/" `
    -WorkspacePath        "C:\Tosca_Projects\Tosca_Workspaces\<NAME>\<NAME>.tws" `
    -PersonalAccessToken  "<PAT base64 blob>" `
    -WorkspaceUser        "Admin" `
    -WorkspacePassword    "<workspace internal admin password>"
```

Expected: capability probe passes, then:

```
[1] Initialising TCAPI
    [OK] TCAPI ready (APIVersion: <x.y.z>)

[2] ToscaServerLogin (server-level PAT auth)
    [OK] Server login OK

[3] OpenWorkspace (workspace-level credentials)
    [OK] Workspace opened

[4] TQL search: =>SUBPARTS:TestCase (first 20)
    found N TestCase(s)

[5] First 5 TestCases:
    LoginTest                                 UniqueId=01ABC...
    ...

[6] First 5 Modules:
    LoginPage                                 UniqueId=01XYZ...
    ...

DISCOVERY COMPLETE.
```

If `[2]` fails: the PAT is wrong / expired, or this Tosca version's `ToscaServerLogin` expects a different overload. The probe identified what's available (`(1-arg)` etc.) — match the args.

If `[3]` fails: workspace credentials are wrong. Multi-user workspaces have an internal admin password that's NOT the user's AD password. Ask the workspace owner.

Pick **one TestCase that uses Module references** for the round-trip. To confirm a TestCase actually uses Modules, you can extend the script with:

```powershell
$tc = $workspace.SearchByUniqueId('<UniqueId>')   # or use Search '=>OBJECT:...'
$tc | Get-Member -MemberType Property             # see what properties exist
$tc.Subparts | ForEach-Object { $_.OwnerModule }  # walk steps for module refs
```

## 6. Round-trip (Mode: roundtrip) — your task

The starter script implements probe + login + workspace-open + discovery. **The round-trip itself is left for you to implement.** This is intentional — TCAPI's `.NET` surface varies by Tosca version enough that a generic implementation written ahead-of-time would need patching anyway. You're better positioned to write it once you've confirmed the live tenant's actual property names via reflection (`Get-Member`).

### Pseudocode

```powershell
# 6a) Resolve source objects
$tc        = $workspace.SearchByUniqueId($TestCaseId)
$mod       = $workspace.SearchByUniqueId($ModuleId)
$tcParent  = $tc.OwnerObject     # or  $tc.PSObject.Properties['OwnerObject'].Value
$modParent = $mod.OwnerObject

# 6b) Create the Module copy
$newMod          = $modParent.CreateChildObject('Module')
                   # Type-name string must match TCAPI's metadata.
                   # Could be 'Module', 'XModule', or 'MetaModule' depending on version.
                   # Probe the type name from $mod.GetType().Name first.
$newMod.Name     = "$($mod.Name)$ModuleSuffix"
# Copy required properties from $mod -> $newMod via reflection.
# At minimum: businessType, identification rules, attribute children.
$newModId        = $newMod.UniqueId

# 6c) Create the TestCase copy with rewritten module ref
$newTc           = $tcParent.CreateChildObject('TestCase')
$newTc.Name      = "$($tc.Name)$Suffix"
# Walk $tc.Subparts (or .GetTestSteps()), for each step:
#   - clone step under $newTc
#   - if step has OwnerModule == $mod, swap to $newMod
# Property and method names vary; reflect at runtime.

# 6d) Persist
$workspace.CheckIn()    # or .Save() — both exist on most Tosca versions

# 6e) Verify
Search-Tql "=>SUBPARTS:TestCase[Name=`"$($newTc.Name)`"]"
Search-Tql "=>SUBPARTS:Module[Name=`"$($newMod.Name)`"]"
```

### Constraints

- **Single-process TCAPI singleton.** Running the script twice in the same PS session throws `Api already initialized`. The starter script handles this defensively (calls `CloseInstance()` at top of every run).
- **Workspace lock semantics.** `OpenWorkspace` may take a workspace lock; `CheckIn` releases pending changes; `Close` releases the lock. Always end the session cleanly even on errors (`try { ... } finally { workspace.Close() }`).
- **Property mutation order matters.** Some TCAPI properties cannot be set after the parent commits; create the child, set required properties, then add to parent before `CheckIn`. Order of operations is per-version; reflect.

### Type-name probing — do this first

Before writing the create-flow code, run this against any existing TestCase + Module to learn the exact runtime type names you'll need to pass to `CreateChildObject`:

```powershell
$tc  = $workspace.SearchByUniqueId('<some TC UniqueId>')
$mod = $workspace.SearchByUniqueId('<some Module UniqueId>')
"$($tc.GetType().FullName)   $($tc.GetType().Name)"
"$($mod.GetType().FullName)  $($mod.GetType().Name)"
```

The short name is the one CreateChildObject takes. Common cases:
- TestCase → `TestCase`
- Module → `Module` (legacy) / `XModule` / `MetaModule` (Engine 3.0)

### Property-name probing

Before writing the property-copy code:

```powershell
$tc | Get-Member -MemberType Properties | Select-Object Name, MemberType
```

That lists every property the runtime exposes. Pick the ones that need to be copied (`Name`, `Description`, `Status`, `BusinessType`, etc.) and skip server-managed ones (`UniqueId`, `Revision`, `OwnerObject`, audit fields).

## 7. Reference implementation

The Achoo0-Adam/Tosca-TQL-Export- repo is a **read-only** baseline that proves the bootstrap (AssemblyResolve, CreateInstance, ToscaServerLogin, OpenWorkspace, Search) works against real Tosca installs. Pull it for cross-reference:

```
https://github.com/Achoo0-Adam/Tosca-TQL-Export-/blob/main/ToscaTQLExport.ps1
```

Our starter `trial.tcapi.ps1` reuses the same patterns. The **create flow** is what you'd add — that part is not in the reference repo.

## 8. Reporting back

Send a single message containing:

1. **Capability probe result** (full output of `-Mode probe` step). Confirms the path is even possible on this machine.
2. **TCAPI version** (`TCAPI.dll` and `TCAPIObjects.dll` version strings from probe).
3. **Tosca Server version** (`tcapi.APIVersionString` from the discover-mode banner).
4. **Discovery output** — the 5 TestCases + 5 Modules listed; which pair you picked.
5. **Type-name probe result** — exact runtime types of TestCase and Module on this tenant.
6. **Property-name probe result** — which properties each type exposes.
7. **Round-trip code you wrote** — the actual `CreateChildObject(...)` flow + property copy + step rewiring + Save calls.
8. **Result of the round-trip**:
   - new Module UniqueId
   - new TestCase UniqueId
   - verification TQL output (should show 1 hit each for the new names)
9. **Any TCAPI quirks** you hit (multi-step property mutation order, save semantics, etc.) — these belong in the agent brief for future runs.

## 9. Boundaries

- **Do not delete or modify the source TestCase or Module.** The trial creates two new objects; nothing else changes.
- **Do not run the script twice in the same PS session** without an intervening `pwsh` restart. TCAPI singleton state breaks. The starter script tries to clean up but the safest restart is a fresh window.
- **Do not commit Tosca workspace credentials.** Pass them via `-WorkspacePassword` only; never write them to a file.
- **Do not push your modified `trial.tcapi.ps1` back to the repo without coordinating with the user.** The starter is intentionally minimal so the user can review your TCAPI-version-specific additions.
- **If TCAPI throws and the workspace is in a half-modified state**, call `$workspace.Discard()` (or whatever the discard-pending-changes method is on your version) before `Close()` to avoid corrupting the workspace's internal state.
- **Stop after 3 failed attempts** at the round-trip on the live tenant. Report what you've collected — the maintainer will iterate from there.
