#Requires -Version 5.1
<#
.SYNOPSIS
    Tosca Commander REST API -- round-trip trial (no Python required).

.DESCRIPTION
    Self-contained PowerShell script that proves the new Commander CLI's flow
    works against your Tosca Server, without installing Python.
    It exercises exactly the same TCRS endpoints as `tosca_commander_cli.py`:

      1. Read auth + base URL from .env (same format as the Python CLI uses).
      2. Probe: GET <base>  -> version JSON.
      3. Open workspace + find one TestCase that uses Modules + one Module.
      4. GET both bodies with depth.
      5. Strip server-minted fields, rename, rewrite the TestCase's module ref.
      6. POST the Module copy, then POST the TestCase copy with the rewritten ref.
      7. CheckInAll.
      8. Verify both via TQL.

    NOT a production CLI -- it's a one-shot probe. The Python script
    `tosca_commander_cli.py` is the maintained tool.

.PARAMETER TestCaseId
    UniqueId of an existing TestCase that uses Module references. If omitted,
    the script runs in DISCOVERY mode (steps 1-3 above) and prints candidate
    IDs to feed back in on a second run.

.PARAMETER ModuleId
    UniqueId of one Module the chosen TestCase actually references.

.PARAMETER TestCaseParentId
    UniqueId of the parent under which the TestCase copy will be created.
    Typically the TestCases component folder, or any folder you have write
    access to.

.PARAMETER ModuleParentId
    UniqueId of the parent under which the Module copy will be created.

.PARAMETER Suffix
    Suffix appended to the cloned TestCase's Name. Default: "_clone".

.PARAMETER ModuleSuffix
    Suffix appended to the cloned Module's Name. Default: "_v2".

.PARAMETER EnvFile
    Path to the .env file. Default: ".env" in the current directory.

.EXAMPLE
    # Phase 1 -- discovery (run with no IDs)
    .\trial.ps1

.EXAMPLE
    # Phase 2 -- round-trip (paste the IDs from phase 1)
    .\trial.ps1 -TestCaseId 01ABC... -ModuleId 01XYZ... `
                -TestCaseParentId 01PQR... -ModuleParentId 01STU...
#>

param(
    [string]$TestCaseId,
    [string]$ModuleId,
    [string]$TestCaseParentId,
    [string]$ModuleParentId,
    [string]$Suffix       = "_clone",
    [string]$ModuleSuffix = "_v2",
    [string]$EnvFile      = ".env"
)

$ErrorActionPreference = 'Stop'

# ----------------------------------------------------------------------------
# 0. Helpers
# ----------------------------------------------------------------------------

function Read-EnvFile {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        throw "Env file not found: $Path. Copy .env.commander.example to .env and fill it in."
    }
    $vars = @{}
    foreach ($line in Get-Content $Path) {
        if ($line -match '^\s*$|^\s*#') { continue }
        if ($line -match '^\s*([^=#\s]+)\s*=\s*(.*)$') {
            $vars[$Matches[1]] = $Matches[2].Trim().Trim('"').Trim("'")
        }
    }
    return $vars
}

function Get-NormalizedBaseUrl {
    param([string]$Raw)
    $u = $Raw.TrimEnd('/')
    if ($u -notmatch '/rest/toscacommander$') { $u += '/rest/toscacommander' }
    return $u
}

function Get-AuthHeaders {
    param([hashtable]$Env)
    $mode  = ($Env['TOSCA_COMMANDER_AUTH'] | ForEach-Object { if ($_) { $_.ToLower() } else { 'auto' } })
    $user  = $Env['TOSCA_COMMANDER_USER']
    $pass  = $Env['TOSCA_COMMANDER_PASSWORD']
    $token = $Env['TOSCA_COMMANDER_TOKEN']
    $cid   = $Env['TOSCA_COMMANDER_CLIENT_ID']
    $csec  = $Env['TOSCA_COMMANDER_CLIENT_SECRET']

    if ($mode -eq 'negotiate') {
        return @{ Mode = 'negotiate'; Headers = @{}; UseDefaultCredentials = $true }
    }

    if ($mode -eq 'ntlm') {
        if (-not ($user -and $pass)) { throw "TOSCA_COMMANDER_AUTH=ntlm requires TOSCA_COMMANDER_USER and TOSCA_COMMANDER_PASSWORD." }
        $secPass = ConvertTo-SecureString $pass -AsPlainText -Force
        $cred    = New-Object System.Management.Automation.PSCredential($user, $secPass)
        return @{ Mode = 'ntlm'; Headers = @{}; Credential = $cred }
    }

    if ($mode -eq 'pat' -or ($mode -eq 'auto' -and $token)) {
        if (-not $token) { throw "TOSCA_COMMANDER_AUTH=pat requires TOSCA_COMMANDER_TOKEN." }
        # Per devcorner 2024.2 docs: PAT goes raw in Authorization (no Basic
        # prefix, no base64) with explicit AuthMode header.
        return @{
            Mode    = 'pat'
            Headers = @{ Authorization = $token; AuthMode = 'pat' }
            UseDefaultCredentials = $false
        }
    }

    if ($mode -eq 'client-creds' -or ($mode -eq 'auto' -and $cid)) {
        if (-not ($cid -and $csec)) { throw "client-creds requires TOSCA_COMMANDER_CLIENT_ID + _CLIENT_SECRET." }
        # Per devcorner 2024.2 docs: client-creds is plain Basic auth with
        # client_id:client_secret + an explicit AuthMode header. NOT the
        # OAuth2 token-exchange flow at /tua/connect/token (that's AOS).
        $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${cid}:${csec}"))
        return @{
            Mode    = 'client-creds'
            Headers = @{ Authorization = "Basic $b64"; AuthMode = 'clientCredentials' }
            UseDefaultCredentials = $false
        }
    }

    if (-not ($user -and $pass)) {
        throw @"
No Commander credentials found. Set ONE of:
  TOSCA_COMMANDER_TOKEN                       (PAT)
  TOSCA_COMMANDER_USER + _PASSWORD            (Basic / AD)
  TOSCA_COMMANDER_CLIENT_ID + _CLIENT_SECRET  (OAuth2)
  TOSCA_COMMANDER_AUTH=negotiate              (IIS Windows Auth)
"@
    }
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("${user}:${pass}"))
    return @{ Mode = 'basic'; Headers = @{ Authorization = "Basic $b64" }; UseDefaultCredentials = $false }
}

function Invoke-Tcrs {
    param(
        [hashtable]$Auth,
        [string]$Method,
        [string]$Url,
        $Body
    )
    $args = @{
        Uri     = $Url
        Method  = $Method
        Headers = $Auth.Headers + @{ Accept = 'application/json' }
    }
    if ($Auth.UseDefaultCredentials) { $args.UseDefaultCredentials = $true }
    if ($Auth.Credential)            { $args.Credential            = $Auth.Credential }
    if ($null -ne $Body) {
        $args.Body        = ($Body | ConvertTo-Json -Depth 30 -Compress)
        $args.ContentType = 'application/json'
    }
    return Invoke-RestMethod @args
}

# ---- Recursive transforms (mirror tosca_commander_cli.py helpers) ----------

$Script:ServerMintedFields = @('UniqueId','Revision','CreatedBy','CreatedAt',
                               'ModifiedBy','ModifiedAt','NodePath')

function Remove-ServerFields {
    param($Obj)
    if ($null -eq $Obj) { return $null }
    if ($Obj -is [System.Management.Automation.PSCustomObject]) {
        $out = [PSCustomObject]@{}
        foreach ($p in $Obj.PSObject.Properties) {
            if ($Script:ServerMintedFields -contains $p.Name) { continue }
            Add-Member -InputObject $out -NotePropertyName $p.Name -NotePropertyValue (Remove-ServerFields $p.Value)
        }
        return $out
    }
    if ($Obj -is [System.Collections.IList]) {
        return @($Obj | ForEach-Object { Remove-ServerFields $_ })
    }
    return $Obj
}

function Get-OwnerUniqueId {
    # Probe common field names that hold the parent reference. Tosca versions
    # have used different names over the years; try them in order of frequency.
    param($Obj)
    foreach ($key in 'OwnerUniqueId','ParentUniqueId','OwnerId','ParentId','Parent') {
        if ($Obj -and $Obj.PSObject.Properties[$key]) {
            $v = $Obj.PSObject.Properties[$key].Value
            if ($v -is [string] -and $v) { return $v }
            if ($v -and $v.UniqueId)      { return $v.UniqueId }
        }
    }
    return $null
}

function Test-IsToscaUniqueId {
    # Tosca UniqueIds appear in two formats across versions:
    #   ULID -- 26-char Crockford base32  (e.g. 01KF3FGGNNCC98DADNTGARBQAB)
    #   GUID -- 36-char hyphenated         (e.g. 3a16a7b4-94cc-b7aa-65c9-f9fb5bec6a6b)
    param([string]$Value)
    if (-not $Value) { return $false }
    if ($Value -match '^[0-9A-HJKMNP-TV-Z]{26}$') { return $true }    # ULID
    if ($Value -match '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$') { return $true }  # GUID
    return $false
}

function Find-ModuleRefs {
    # Walks an arbitrary deserialized JSON tree for property values that:
    #   (a) live under a key whose name contains 'Module', and
    #   (b) look like a Tosca UniqueId (ULID or hyphenated GUID -- see Test-IsToscaUniqueId).
    # Also handles the struct-wrapped form { "ModuleReference": { "UniqueId": "..." } }.
    # Returns deduped strings.
    param($Obj, [System.Collections.ArrayList]$Out = $null)
    if ($null -eq $Out) { $Out = New-Object System.Collections.ArrayList }
    if ($null -eq $Obj) { return $Out }
    if ($Obj -is [System.Management.Automation.PSCustomObject]) {
        foreach ($p in $Obj.PSObject.Properties) {
            if ($p.Name -like '*Module*') {
                # Direct string value (most common shape)
                if ($p.Value -is [string] -and (Test-IsToscaUniqueId $p.Value) -and -not $Out.Contains($p.Value)) {
                    $null = $Out.Add($p.Value)
                }
                # Struct-wrapped: { "ModuleReference": { "UniqueId": "..." } }
                if ($p.Value -is [System.Management.Automation.PSCustomObject] `
                    -and $p.Value.PSObject.Properties['UniqueId']) {
                    $nested = $p.Value.PSObject.Properties['UniqueId'].Value
                    if ($nested -is [string] -and (Test-IsToscaUniqueId $nested) -and -not $Out.Contains($nested)) {
                        $null = $Out.Add($nested)
                    }
                }
            }
            Find-ModuleRefs $p.Value $Out | Out-Null
        }
    } elseif ($Obj -is [System.Collections.IList]) {
        foreach ($it in $Obj) { Find-ModuleRefs $it $Out | Out-Null }
    }
    return $Out
}

function Edit-Refs {
    param($Obj, [hashtable]$Map)
    if ($null -eq $Obj) { return $null }
    if ($Obj -is [System.Management.Automation.PSCustomObject]) {
        $out = [PSCustomObject]@{}
        foreach ($p in $Obj.PSObject.Properties) {
            Add-Member -InputObject $out -NotePropertyName $p.Name -NotePropertyValue (Edit-Refs $p.Value $Map)
        }
        return $out
    }
    if ($Obj -is [System.Collections.IList]) {
        return @($Obj | ForEach-Object { Edit-Refs $_ $Map })
    }
    if ($Obj -is [string] -and $Map.ContainsKey($Obj)) {
        return $Map[$Obj]
    }
    return $Obj
}

# ----------------------------------------------------------------------------
# 1. Bootstrap
# ----------------------------------------------------------------------------

Write-Host "Tosca Commander REST trial -- PowerShell" -ForegroundColor Cyan
$envVars = Read-EnvFile $EnvFile
$baseUrl = Get-NormalizedBaseUrl $envVars['TOSCA_COMMANDER_BASE_URL']
$ws      = $envVars['TOSCA_COMMANDER_WORKSPACE']
if (-not $ws) { throw "TOSCA_COMMANDER_WORKSPACE not set in $EnvFile." }
Write-Host "  Base URL : $baseUrl"
Write-Host "  Workspace: $ws"

$auth = Get-AuthHeaders $envVars
Write-Host "  Auth mode: $($auth.Mode)"
Write-Host ""

# ----------------------------------------------------------------------------
# 2. Probe -- version + open workspace
# ----------------------------------------------------------------------------

Write-Host "[1] GET $baseUrl  (version probe)" -ForegroundColor Yellow
try {
    $version = Invoke-Tcrs $auth 'GET' $baseUrl
    $version | ConvertTo-Json -Depth 10
} catch {
    throw "Version probe failed: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "[2] GET $baseUrl/$ws  (open workspace)" -ForegroundColor Yellow
$wsInfo = Invoke-Tcrs $auth 'GET' "$baseUrl/$ws"
$wsInfo | ConvertTo-Json -Depth 5

# Project root -- needed by both discovery (TQL search root) and round-trip (verify step).
$rootResp = Invoke-Tcrs $auth 'GET' "$baseUrl/$ws/object/project/"
$rootId   = $rootResp.UniqueId
if (-not $rootId) { $rootId = $rootResp.Id }
if (-not $rootId) { throw "Could not resolve project-root UniqueId from response." }

# ----------------------------------------------------------------------------
# 3. Discovery mode -- print candidate IDs and exit
# ----------------------------------------------------------------------------

if (-not $TestCaseId -or -not $ModuleId -or -not $TestCaseParentId -or -not $ModuleParentId) {
    Write-Host ""
    Write-Host "DISCOVERY MODE -- finding TestCases that reference Modules and resolving their parents..." -ForegroundColor Magenta
    Write-Host "  project root UniqueId = $rootId"

    Write-Host ""
    Write-Host "[3] TQL =>SUBPARTS:TestCase  (probing first 20 to find 5 with Module refs)" -ForegroundColor Yellow
    # Canonical TQL endpoint per devcorner 2024.2: /<ws>/search?tql=...
    $tcs = Invoke-Tcrs $auth 'GET' "$baseUrl/$ws/search?tql=%3D%3ESUBPARTS%3ATestCase"

    $candidates = New-Object System.Collections.ArrayList
    foreach ($tc in @($tcs | Select-Object -First 20)) {
        if ($candidates.Count -ge 5) { break }
        $tcId = if ($tc.UniqueId) { $tc.UniqueId } else { $tc.Id }
        if (-not $tcId) { continue }

        try {
            $tcFull = Invoke-Tcrs $auth 'GET' "$baseUrl/$ws/object/${tcId}?depth=5"
        } catch {
            Write-Host "  skip $($tc.Name) -- GET failed" -ForegroundColor DarkGray
            continue
        }

        $modRefs = Find-ModuleRefs $tcFull
        if (-not $modRefs -or $modRefs.Count -eq 0) { continue }

        $modId = $modRefs[0]
        try {
            $modFull = Invoke-Tcrs $auth 'GET' "$baseUrl/$ws/object/${modId}?depth=0"
        } catch { continue }

        $tcParent  = Get-OwnerUniqueId $tcFull
        $modParent = Get-OwnerUniqueId $modFull
        if (-not $tcParent -or -not $modParent) {
            Write-Host "  skip $($tc.Name) -- could not resolve parent UniqueId" -ForegroundColor DarkGray
            continue
        }

        $null = $candidates.Add([PSCustomObject]@{
            '#'           = $candidates.Count + 1
            'TestCase'    = $tcFull.Name
            'TC_Id'       = $tcId
            'TC_Parent'   = $tcParent
            'Module'      = $modFull.Name
            'MOD_Id'      = $modId
            'MOD_Parent'  = $modParent
        })
        Write-Host "  found candidate $($candidates.Count): $($tcFull.Name) -> $($modFull.Name)" -ForegroundColor DarkGreen
    }

    if ($candidates.Count -eq 0) {
        Write-Host ""
        Write-Host "No TestCases with Module references found in the first 20 results." -ForegroundColor Red
        Write-Host "Try a workspace with active web/SAP/API automation, or pass IDs manually."
        return
    }

    Write-Host ""
    Write-Host "Phase-2-ready candidates:" -ForegroundColor Cyan
    $candidates | Format-Table -AutoSize | Out-String | Write-Host

    Write-Host "Copy ONE line below into PowerShell to run Phase 2 on the matching row:" -ForegroundColor Magenta
    Write-Host ""
    foreach ($c in $candidates) {
        $cmd = ".\trial.ps1 -TestCaseId {0} -ModuleId {1} -TestCaseParentId {2} -ModuleParentId {3}" -f `
               $c.TC_Id, $c.MOD_Id, $c.TC_Parent, $c.MOD_Parent
        Write-Host "  # row $($c.'#'): $($c.TestCase) -> $($c.Module)" -ForegroundColor DarkGray
        Write-Host "  $cmd" -ForegroundColor Yellow
    }
    return
}

# ----------------------------------------------------------------------------
# 4. Round-trip mode
# ----------------------------------------------------------------------------

Write-Host ""
Write-Host "[3] GET TestCase $TestCaseId (depth 5)" -ForegroundColor Yellow
$tcSrc = Invoke-Tcrs $auth 'GET' "$baseUrl/$ws/object/${TestCaseId}?depth=5"
"  Source TC Name = $($tcSrc.Name)"

Write-Host ""
Write-Host "[4] GET Module $ModuleId (depth 3)" -ForegroundColor Yellow
$modSrc = Invoke-Tcrs $auth 'GET' "$baseUrl/$ws/object/${ModuleId}?depth=3"
"  Source MOD Name = $($modSrc.Name)"

# Step A: recreate the Module first
Write-Host ""
Write-Host "[5] POST new Module under $ModuleParentId (strip + rename '$ModuleSuffix')" -ForegroundColor Yellow
$modBody = Remove-ServerFields $modSrc
$modBody.Name = "$($modBody.Name)$ModuleSuffix"
$newMod = Invoke-Tcrs $auth 'POST' "$baseUrl/$ws/object/$ModuleParentId" $modBody
$newModId = $newMod.UniqueId
if (-not $newModId) { $newModId = $newMod.Id }
"  -> new Module UniqueId = $newModId"

# Step B: recreate the TestCase with the module ref rewritten
Write-Host ""
Write-Host "[6] POST new TestCase under $TestCaseParentId (strip + rename '$Suffix' + rewrite $ModuleId -> $newModId)" -ForegroundColor Yellow
$tcBody = Remove-ServerFields $tcSrc
$tcBody = Edit-Refs $tcBody @{ $ModuleId = $newModId }
$tcBody.Name = "$($tcBody.Name)$Suffix"
$newTc = Invoke-Tcrs $auth 'POST' "$baseUrl/$ws/object/$TestCaseParentId" $tcBody
$newTcId = $newTc.UniqueId
if (-not $newTcId) { $newTcId = $newTc.Id }
"  -> new TestCase UniqueId = $newTcId"

# Step C: persist
Write-Host ""
Write-Host "[7] CheckInAll" -ForegroundColor Yellow
Invoke-Tcrs $auth 'POST' "$baseUrl/$ws/task/CheckInAll" | Out-Null
"  [OK] CheckInAll OK"

# Step D: verify
Write-Host ""
Write-Host "[8] Verify both via TQL" -ForegroundColor Yellow
$verifyTc  = Invoke-Tcrs $auth 'GET' "$baseUrl/$ws/search?tql=%3D%3ESUBPARTS%3ATestCase%5BName%3D%22$([uri]::EscapeDataString($tcBody.Name))%22%5D"
$verifyMod = Invoke-Tcrs $auth 'GET' "$baseUrl/$ws/search?tql=%3D%3ESUBPARTS%3AModule%5BName%3D%22$([uri]::EscapeDataString($modBody.Name))%22%5D"
"  TC clone hits     : $($verifyTc.Count)"
"  Module clone hits : $($verifyMod.Count)"

Write-Host ""
Write-Host "DONE." -ForegroundColor Green
Write-Host "Created:"
Write-Host "  Module    : $($modBody.Name)   UniqueId=$newModId"
Write-Host "  TestCase  : $($tcBody.Name)    UniqueId=$newTcId  -> references $newModId (was $ModuleId)"
Write-Host ""
Write-Host "Cleanup (when you're done):"
Write-Host "  Invoke-RestMethod -Method DELETE -Uri '$baseUrl/$ws/object/$newTcId'  -Headers @{Authorization='...'}"
Write-Host "  Invoke-RestMethod -Method DELETE -Uri '$baseUrl/$ws/object/$newModId' -Headers @{Authorization='...'}"
Write-Host "  (Or: python tosca_commander_cli.py objects delete $newTcId / $newModId, if Python is available.)"
