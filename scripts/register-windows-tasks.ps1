param(
    [string]$RepoRoot = ".",

    [string]$TaskPrefix = "Academic Monitor -",

    [string]$DailyAt = "08:00",

    [string]$Image = "news-monitor:latest",

    [string]$EnvFile = ".env",

    [string[]]$InstanceNames = @()
)

$ErrorActionPreference = "Stop"

function Resolve-AbsolutePath {
    param([string]$PathValue)
    return (Resolve-Path -LiteralPath $PathValue).Path
}

function Get-TaskTriggerTime {
    param([string]$TimeValue)

    try {
        $parsed = [datetime]::ParseExact(
            $TimeValue,
            "HH:mm",
            [System.Globalization.CultureInfo]::InvariantCulture
        )
        return (Get-Date).Date.AddHours($parsed.Hour).AddMinutes($parsed.Minute)
    }
    catch {
        throw "Invalid -DailyAt value '$TimeValue'. Expected HH:mm, for example 08:00."
    }
}

function Test-SelectedInstance {
    param(
        [string]$DirectoryName,
        [string]$UserName,
        [string[]]$SelectedNames
    )

    if (-not $SelectedNames -or $SelectedNames.Count -eq 0) {
        return $true
    }

    foreach ($selected in $SelectedNames) {
        if ($selected -eq $DirectoryName -or $selected -eq $UserName) {
            return $true
        }
    }

    return $false
}

$repoRootAbs = Resolve-AbsolutePath $RepoRoot
$runScriptAbs = Resolve-AbsolutePath (Join-Path $repoRootAbs "scripts/run-monitor.ps1")
$envAbs = Resolve-AbsolutePath (Join-Path $repoRootAbs $EnvFile)
$instancesRoot = Resolve-AbsolutePath (Join-Path $repoRootAbs "instances")

if (-not (Test-Path -LiteralPath $runScriptAbs)) {
    throw "run-monitor.ps1 not found: $runScriptAbs"
}

if (-not (Test-Path -LiteralPath $envAbs)) {
    throw ".env file not found: $envAbs"
}

if (-not (Get-Command Register-ScheduledTask -ErrorAction SilentlyContinue)) {
    throw "Register-ScheduledTask is not available. Run this script in Windows PowerShell as the target user."
}

if ($repoRootAbs.StartsWith("\\")) {
    Write-Warning "RepoRoot resolves to a UNC path: $repoRootAbs"
    Write-Warning "Task Scheduler can use this, but a native Windows path such as C:\Academic_Research_Monitor is usually more reliable."
}

$triggerTime = Get-TaskTriggerTime $DailyAt
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable

$selectedNames = @($InstanceNames | ForEach-Object { [string]$_ } | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
$createdTasks = @()

$instanceDirs = Get-ChildItem -LiteralPath $instancesRoot -Directory | Sort-Object Name
foreach ($instanceDir in $instanceDirs) {
    $configAbs = Join-Path $instanceDir.FullName "config.json"
    if (-not (Test-Path -LiteralPath $configAbs)) {
        continue
    }

    $configJson = Get-Content -LiteralPath $configAbs -Raw | ConvertFrom-Json
    $userName = [string]$configJson.user.name
    if ([string]::IsNullOrWhiteSpace($userName)) {
        throw "user.name is missing in config: $configAbs"
    }

    if (-not (Test-SelectedInstance -DirectoryName $instanceDir.Name -UserName $userName -SelectedNames $selectedNames)) {
        continue
    }

    $configRel = $configAbs.Substring($repoRootAbs.Length).TrimStart('\')
    $taskName = ("{0} {1}" -f $TaskPrefix.TrimEnd(), $userName).Trim()
    $argumentList = @(
        "-ExecutionPolicy Bypass",
        "-File `"$runScriptAbs`"",
        "-RepoRoot `"$repoRootAbs`"",
        "-ConfigPath `"$configRel`"",
        "-Image `"$Image`"",
        "-EnvFile `"$EnvFile`""
    ) -join " "

    $action = New-ScheduledTaskAction `
        -Execute "powershell.exe" `
        -Argument $argumentList `
        -WorkingDirectory $repoRootAbs

    $trigger = New-ScheduledTaskTrigger -Daily -At $triggerTime
    $description = "Runs the academic monitor instance '$userName' via Docker Desktop one-shot runtime."

    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description $description `
        -Force | Out-Null

    $createdTasks += [pscustomobject]@{
        TaskName   = $taskName
        UserName   = $userName
        ConfigPath = $configRel
        DailyAt    = $DailyAt
    }
}

if (-not $createdTasks -or $createdTasks.Count -eq 0) {
    if ($selectedNames.Count -gt 0) {
        throw "No matching instance configs found for: $($selectedNames -join ', ')"
    }
    throw "No instance configs found under: $instancesRoot"
}

Write-Host "Registered Windows Task Scheduler tasks:"
$createdTasks | Format-Table -AutoSize
Write-Host ""
Write-Host "Use Task Scheduler or 'Get-ScheduledTask' to review them."
