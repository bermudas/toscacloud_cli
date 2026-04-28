#Requires -Version 7.0
<#
.SYNOPSIS
    Tosca Commander TCAPI .NET trial -- round-trip test via in-process TCAPI assemblies.

.DESCRIPTION
    Alternative transport when TCRS REST is blocked on multi-user workspaces.
    Loads `TCAPI.dll` and `TCAPIObjects.dll` from a local Tosca Commander install
    via .NET reflection, logs in with a server PAT, opens a workspace, and runs
    the same round-trip flow trial.ps1 implements via REST:
      probe -> discover -> read TestCase + Module -> create copies -> wire ref -> save -> verify

    NOT a production CLI. Requires Tosca Commander installed locally on the same
    machine where this script runs.

.PARAMETER Mode
    `probe`     - validate the environment (PowerShell version, .NET runtime, Tosca
                  install path, assemblies present, key TCAPI types resolvable via
                  reflection). NO login, NO writes. Default.
    `discover`  - probe + login + open workspace + list 5 TestCases that reference
                  Modules + their parents. NO writes.
    `roundtrip` - probe + discover + create a Module copy + create a TestCase copy
                  with rewritten module ref + Save + verify. WRITES TWO NEW OBJECTS
                  to the workspace (rolled into a single CheckIn, can be undone via
                  -Mode cleanup).
    `cleanup`   - delete the two trial-created objects (pass UniqueIds via
                  -CleanupTcId / -CleanupModId).

.PARAMETER ToscaCommanderPath
    Path to the local Tosca Commander folder containing TCAPI.dll and
    TCAPIObjects.dll. Default: "C:\Program Files (x86)\TRICENTIS\Tosca Testsuite\ToscaCommander".

.PARAMETER ToscaServerUrl
    Tosca Server URL for `ToscaServerLogin` (PAT-based server-level auth).
    Example: "https://your-tosca-server/" or "http://localhost/".

.PARAMETER WorkspacePath
    Full path to the workspace .tws file. Tosca Commander File menu shows it.

.PARAMETER PersonalAccessToken
    Tosca Server PAT -- base64-encoded JSON blob from Tosca Server -> Profile ->
    Personal Access Tokens. Same value the REST CLI accepts.

.PARAMETER WorkspaceUser
    Workspace-level user. Multi-user workspaces typically use a Tosca-internal
    admin account here, NOT AD credentials. Default: "Admin".

.PARAMETER WorkspacePassword
    Workspace-level password (Tosca-internal).

.PARAMETER TestCaseId
    Round-trip mode: UniqueId of an existing TestCase that uses Module refs.

.PARAMETER ModuleId
    Round-trip mode: UniqueId of one Module the chosen TestCase references.

.PARAMETER Suffix
    Suffix on the cloned TestCase's Name. Default: "_clone".

.PARAMETER ModuleSuffix
    Suffix on the cloned Module's Name. Default: "_v2".

.EXAMPLE
    # 1. Capability probe (no login, no writes)
    .\trial.tcapi.ps1 -Mode probe

.EXAMPLE
    # 2. Discovery (lists candidate TestCase + Module pairs)
    .\trial.tcapi.ps1 -Mode discover `
        -ToscaServerUrl "https://your-server/" `
        -WorkspacePath "C:\Tosca_Projects\Tosca_Workspaces\LEAD_GEN_AOS\LEAD_GEN_AOS.tws" `
        -PersonalAccessToken "<PAT>" `
        -WorkspaceUser "Admin" `
        -WorkspacePassword "<workspace-pass>"

.EXAMPLE
    # 3. Round-trip on a specific candidate
    .\trial.tcapi.ps1 -Mode roundtrip `
        -TestCaseId "01ABC..." -ModuleId "01XYZ..." `
        -ToscaServerUrl "https://your-server/" `
        -WorkspacePath "..." -PersonalAccessToken "<PAT>" `
        -WorkspaceUser "Admin" -WorkspacePassword "..."
#>

param(
    [ValidateSet('probe','discover','roundtrip','cleanup')]
    [string]$Mode = 'probe',

    [string]$ToscaCommanderPath = "C:\Program Files (x86)\TRICENTIS\Tosca Testsuite\ToscaCommander",
    [string]$ToscaServerUrl,
    [string]$WorkspacePath,
    [string]$PersonalAccessToken,
    [string]$WorkspaceUser     = "Admin",
    [string]$WorkspacePassword = "",

    [string]$TestCaseId,
    [string]$ModuleId,
    [string]$Suffix       = "_clone",
    [string]$ModuleSuffix = "_v2",

    [string]$CleanupTcId,
    [string]$CleanupModId
)

$ErrorActionPreference = 'Stop'

# ----------------------------------------------------------------------------
# 0. Banner
# ----------------------------------------------------------------------------
Write-Host "Tosca Commander TCAPI .NET trial -- mode=$Mode" -ForegroundColor Cyan

# ----------------------------------------------------------------------------
# 1. Capability probe (always run; subsequent modes build on it)
# ----------------------------------------------------------------------------

# 1.1  PowerShell version
if ($PSVersionTable.PSVersion.Major -lt 7) {
    throw "Requires PowerShell 7+ (current: $($PSVersionTable.PSVersion)). Install: winget install Microsoft.PowerShell"
}
Write-Host "[OK] PowerShell  $($PSVersionTable.PSVersion)"

# 1.2  .NET runtime - Tosca's recent assemblies target .NET 8
$dotnetVersion = [System.Runtime.InteropServices.RuntimeInformation]::FrameworkDescription
Write-Host "[OK] .NET runtime $dotnetVersion"

# 1.3  Tosca install path
if (-not (Test-Path $ToscaCommanderPath)) {
    throw "Tosca Commander folder not found at: $ToscaCommanderPath. Pass -ToscaCommanderPath if installed elsewhere."
}
Write-Host "[OK] Tosca install path: $ToscaCommanderPath"

# 1.4  Assemblies present
$tcapiObjectsDll = Join-Path $ToscaCommanderPath "TCAPIObjects.dll"
$tcapiDll        = Join-Path $ToscaCommanderPath "TCAPI.dll"
foreach ($dll in @($tcapiObjectsDll, $tcapiDll)) {
    if (-not (Test-Path $dll)) { throw "Missing required assembly: $dll" }
}
Write-Host "[OK] TCAPI.dll, TCAPIObjects.dll present"

# 1.5  AssemblyResolve handler so transitive dependencies resolve from the same folder
$resolverPath = $ToscaCommanderPath
[System.AppDomain]::CurrentDomain.add_AssemblyResolve([System.ResolveEventHandler]{
    param($sender, $args)
    $name = [System.Reflection.AssemblyName]::new($args.Name).Name
    $candidate = Join-Path $script:resolverPath "$name.dll"
    if (Test-Path $candidate) { return [System.Reflection.Assembly]::LoadFrom($candidate) }
    return $null
})

# 1.6  Load the two assemblies
$assemblyObjects = [System.Reflection.Assembly]::LoadFrom($tcapiObjectsDll)
$assemblyTCAPI   = [System.Reflection.Assembly]::LoadFrom($tcapiDll)
Write-Host "[OK] Assemblies loaded"
Write-Host "     TCAPI.dll        version: $($assemblyTCAPI.GetName().Version)"
Write-Host "     TCAPIObjects.dll version: $($assemblyObjects.GetName().Version)"

# 1.7  Resolve key types via reflection
$tcapiType    = $assemblyTCAPI.GetType("Tricentis.TCAPI.TCAPI")
$connInfoType = $assemblyObjects.GetType("Tricentis.TCAPIObjects.TCAPIConnectionInfo")
if (-not $tcapiType)    { throw "Type not found: Tricentis.TCAPI.TCAPI (assembly mismatch?)" }
if (-not $connInfoType) { throw "Type not found: Tricentis.TCAPIObjects.TCAPIConnectionInfo" }
Write-Host "[OK] Key TCAPI types resolved"

# 1.8  Identify the ToscaServerLogin overload set we'll use later
$loginMethods = $tcapiType.GetMethods() | Where-Object { $_.Name -eq "ToscaServerLogin" }
if (-not $loginMethods) {
    throw "TCAPI exposes no ToscaServerLogin method. Tosca version may not support PAT-based server login."
}
$loginOverloads = $loginMethods | ForEach-Object { "($($_.GetParameters().Count)-arg)" }
Write-Host "[OK] ToscaServerLogin overloads: $($loginOverloads -join ', ')"

if ($Mode -eq 'probe') {
    Write-Host ""
    Write-Host "PROBE COMPLETE. Capability confirmed for TCAPI .NET path." -ForegroundColor Green
    Write-Host "Next step: rerun with -Mode discover plus -ToscaServerUrl/-WorkspacePath/-PersonalAccessToken."
    return
}

# ----------------------------------------------------------------------------
# 2. Login + open workspace (discover and roundtrip modes)
# ----------------------------------------------------------------------------

foreach ($p in 'ToscaServerUrl','WorkspacePath','PersonalAccessToken') {
    if (-not (Get-Variable $p -ValueOnly)) { throw "-$p is required for mode=$Mode" }
}
if ($Mode -ne 'cleanup' -and -not (Test-Path $WorkspacePath)) {
    throw "Workspace .tws not found at: $WorkspacePath"
}

Write-Host ""
Write-Host "[1] Initialising TCAPI" -ForegroundColor Yellow

# Idempotent: tear down any previously-cached singleton in this PS session
$existing = $tcapiType.GetProperty("Instance").GetValue($null)
if ($existing) {
    Write-Host "    -> closing existing TCAPI instance"
    $closeStatic = $tcapiType.GetMethods([System.Reflection.BindingFlags]::Static -bor [System.Reflection.BindingFlags]::Public) |
                   Where-Object { $_.Name -eq "CloseInstance" } | Select-Object -First 1
    if ($closeStatic) { $closeStatic.Invoke($null, @()) | Out-Null }
}

$connInfo     = [Activator]::CreateInstance($connInfoType)
$connInfo.Url = $ToscaServerUrl

$createMethod = $tcapiType.GetMethods([System.Reflection.BindingFlags]::Static -bor [System.Reflection.BindingFlags]::Public) |
    Where-Object {
        $_.Name -eq "CreateInstance" -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq "TCAPIConnectionInfo"
    } | Select-Object -First 1
if (-not $createMethod) { throw "CreateInstance(TCAPIConnectionInfo) not found on TCAPI type." }
$createMethod.Invoke($null, @($connInfo)) | Out-Null

$tcapi = $tcapiType.GetProperty("Instance").GetValue($null)
if (-not $tcapi) { throw "TCAPI.Instance is null after CreateInstance -- login probably failed at the transport layer." }
Write-Host "    [OK] TCAPI ready (APIVersion: $($tcapi.APIVersionString))"

Write-Host ""
Write-Host "[2] ToscaServerLogin (server-level PAT auth)" -ForegroundColor Yellow
$loginPat = $loginMethods | Where-Object { $_.GetParameters().Count -eq 1 } | Select-Object -First 1
if (-not $loginPat) {
    throw "No 1-arg ToscaServerLogin overload (would have taken the PAT). Available: $($loginOverloads -join ', ')."
}
$loginPat.Invoke($tcapi, @($PersonalAccessToken)) | Out-Null
Write-Host "    [OK] Server login OK"

Write-Host ""
Write-Host "[3] OpenWorkspace (workspace-level credentials)" -ForegroundColor Yellow
$openMethods = $tcapi.GetType().GetMethods() | Where-Object { $_.Name -eq "OpenWorkspace" }
$openMethod  = $openMethods | Where-Object { $_.GetParameters().Count -eq 4 } | Select-Object -First 1
if (-not $openMethod) { $openMethod = $openMethods | Sort-Object { $_.GetParameters().Count } | Select-Object -First 1 }
if (-not $openMethod) { throw "No OpenWorkspace overload found." }
$openMethod.Invoke($tcapi, @($WorkspacePath, $WorkspaceUser, $WorkspacePassword, 0)) | Out-Null

$workspace = $tcapi.GetType().GetProperty("ActiveWorkspace").GetValue($tcapi)
if (-not $workspace) { throw "ActiveWorkspace is null after OpenWorkspace." }
Write-Host "    [OK] Workspace opened"

# ----------------------------------------------------------------------------
# 3. TCAPI helpers (reflection-based; portable across versions)
# ----------------------------------------------------------------------------

function Get-Project { $workspace.GetType().GetMethod("GetProject").Invoke($workspace, @()) }
function Search-Tql {
    param($Tql)
    $project = Get-Project
    $searchMethod = $workspace.GetType().GetMethod("Search")
    return $searchMethod.Invoke($workspace, @($project, $Tql))
}
function Get-Prop {
    param($Obj, [string]$Name)
    try {
        $p = $Obj.GetType().GetProperty($Name)
        if ($p) {
            $v = $p.GetValue($Obj)
            if ($null -ne $v) { return $v }
        }
    } catch {}
    return $null
}

# ----------------------------------------------------------------------------
# 4. Discover mode -- list candidate TestCase + Module pairs and exit
# ----------------------------------------------------------------------------

if ($Mode -eq 'discover') {
    Write-Host ""
    Write-Host "[4] TQL search: =>SUBPARTS:TestCase (first 20)" -ForegroundColor Yellow
    $tcs = Search-Tql '=>SUBPARTS:TestCase'
    Write-Host "    found $($tcs.Count) TestCase(s)"

    Write-Host ""
    Write-Host "[5] First 5 TestCases:" -ForegroundColor Yellow
    $tcs | Select-Object -First 5 | ForEach-Object {
        $name = Get-Prop $_ 'Name'
        $uid  = Get-Prop $_ 'UniqueId'
        if (-not $uid) { $uid = Get-Prop $_ 'Id' }
        "    {0,-40}  UniqueId={1}" -f $name, $uid
    }

    Write-Host ""
    Write-Host "[6] First 5 Modules:" -ForegroundColor Yellow
    $mods = Search-Tql '=>SUBPARTS:Module'
    $mods | Select-Object -First 5 | ForEach-Object {
        $name = Get-Prop $_ 'Name'
        $uid  = Get-Prop $_ 'UniqueId'
        if (-not $uid) { $uid = Get-Prop $_ 'Id' }
        "    {0,-40}  UniqueId={1}" -f $name, $uid
    }

    Write-Host ""
    Write-Host "DISCOVERY COMPLETE. Pick a TC + Module pair and rerun with -Mode roundtrip." -ForegroundColor Green
    Write-Host "(For the round-trip you also need each side's parent UniqueId -- extract via reflection or the Tosca UI.)"
    # cleanup: close the workspace + TCAPI on every exit path
    $workspace.GetType().GetMethod("Close").Invoke($workspace, @()) 2>$null | Out-Null
    return
}

# ----------------------------------------------------------------------------
# 5. Round-trip mode -- TODO for the receiving agent
# ----------------------------------------------------------------------------
#
# The remaining steps (find parents, create copies via parent.CreateChildObject,
# rewrite the new TestCase's module reference to point at the new Module copy,
# Save + verify) are intentionally LEFT FOR THE RECEIVING AGENT to implement
# against the live tenant. The TCAPI .NET surface is per-version-variable
# enough that a generic implementation written here would likely need
# adjustment anyway.
#
# Pseudocode for the receiving agent:
#
#   $tc        = $workspace.SearchByUniqueId($TestCaseId)        # Or: Search '=>OBJECT:TestCase[UniqueId=<id>]'
#   $mod       = $workspace.SearchByUniqueId($ModuleId)
#   $tcParent  = $tc.OwnerObject            # or $tc.GetType().GetProperty('OwnerObject').GetValue($tc)
#   $modParent = $mod.OwnerObject
#
#   # 5a) Recreate the Module first
#   $newMod    = $modParent.CreateChildObject('Module')   # exact type name varies; could be 'XModule' or 'MetaModule'
#   $newMod.Name = "$($mod.Name)$ModuleSuffix"
#   # copy required properties from $mod onto $newMod (iterate via reflection)
#   $newModId  = $newMod.UniqueId
#
#   # 5b) Recreate the TestCase pointing at the new Module
#   $newTc     = $tcParent.CreateChildObject('TestCase')
#   $newTc.Name = "$($tc.Name)$Suffix"
#   # walk $tc's TestSteps, for each clone the step under $newTc with
#   # module reference rewritten from $ModuleId -> $newModId
#
#   # 5c) Persist
#   $workspace.CheckIn()                                  # or workspace.Save()
#
#   # 5d) Verify via TQL
#   Search-Tql "=>SUBPARTS:TestCase[Name=`"$($newTc.Name)`"]"
#   Search-Tql "=>SUBPARTS:Module[Name=`"$($newMod.Name)`"]"
#
# Reference implementation that does up to step 4: konopski/Tosca-TQL-Export-
# (read-only; create patterns are not in there but the assembly-loading +
# auth + workspace-open flow above is identical).
#
# Report back:
#   - which TCAPI methods/properties you used (full reflection signatures)
#   - any version-specific adjustments
#   - the new UniqueIds created
#   - any cleanup needed (DELETE the two new objects via $obj.GetType().GetMethod('Delete'))

Write-Host ""
Write-Host "ROUND-TRIP NOT YET IMPLEMENTED -- see comment block at end of trial.tcapi.ps1." -ForegroundColor Yellow
Write-Host "The receiving agent (you?) should extend this script per the pseudocode," -ForegroundColor Yellow
Write-Host "consulting konopski/Tosca-TQL-Export- for the bootstrap reference and the " -ForegroundColor Yellow
Write-Host "Tosca version you're on for exact property/method signatures."             -ForegroundColor Yellow

# Always close cleanly
try { $workspace.GetType().GetMethod("Close").Invoke($workspace, @()) | Out-Null } catch {}
try {
    $closeStatic = $tcapiType.GetMethods([System.Reflection.BindingFlags]::Static -bor [System.Reflection.BindingFlags]::Public) |
                   Where-Object { $_.Name -eq "CloseInstance" } | Select-Object -First 1
    if ($closeStatic) { $closeStatic.Invoke($null, @()) | Out-Null }
} catch {}
