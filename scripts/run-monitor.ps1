param(
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,

    [string]$Image = "news-monitor:latest",

    [string]$EnvFile = ".env",

    [string]$RepoRoot = "."
)

$ErrorActionPreference = "Stop"

$DockerDesktopDefaultPath = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$DockerReadyTimeoutSeconds = 300
$DockerReadyPollIntervalSeconds = 5

function Resolve-AbsolutePath {
    param([string]$PathValue)
    return (Resolve-Path -LiteralPath $PathValue).Path
}

function Test-DockerCli {
    $null = Get-Command docker -ErrorAction SilentlyContinue
    return $null -ne $?
}

function Test-DockerReady {
    docker info *> $null
    return $LASTEXITCODE -eq 0
}

function Start-DockerDesktopIfNeeded {
    if (Test-DockerReady) {
        Write-Host "Docker is already ready."
        return
    }

    if (-not (Test-Path -LiteralPath $DockerDesktopDefaultPath)) {
        throw "Docker Desktop executable not found at: $DockerDesktopDefaultPath"
    }

    $dockerDesktopRunning = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
    if (-not $dockerDesktopRunning) {
        Write-Host "Docker is not ready. Starting Docker Desktop..."
        Start-Process -FilePath $DockerDesktopDefaultPath | Out-Null
    }
    else {
        Write-Host "Docker Desktop is running, waiting for Docker engine to become ready..."
    }

    $deadline = (Get-Date).AddSeconds($DockerReadyTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-DockerReady) {
            Write-Host "Docker is ready."
            return
        }

        Write-Host "Waiting for Docker to become ready..."
        Start-Sleep -Seconds $DockerReadyPollIntervalSeconds
    }

    throw "Docker did not become ready within $DockerReadyTimeoutSeconds seconds."
}

$repoRootAbs = Resolve-AbsolutePath $RepoRoot
$configAbs = Resolve-AbsolutePath (Join-Path $repoRootAbs $ConfigPath)
$envAbs = Resolve-AbsolutePath (Join-Path $repoRootAbs $EnvFile)
$instanceDirAbs = Split-Path -Parent $configAbs

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker CLI not found. Please install Docker Desktop and ensure 'docker' is available in PATH."
}

if (-not (Test-Path -LiteralPath $configAbs)) {
    throw "Config file not found: $configAbs"
}

if (-not (Test-Path -LiteralPath $envAbs)) {
    throw ".env file not found: $envAbs"
}

$configJson = Get-Content -LiteralPath $configAbs -Raw | ConvertFrom-Json
$containerName = [string]$configJson.user.name
$containerName = $containerName.Trim()
$validContainerName = $containerName -match '^[A-Za-z0-9_-]+$'
if ([string]::IsNullOrWhiteSpace($containerName) -or -not $validContainerName) {
    throw "user.name is missing or invalid in config: $configAbs"
}
$outputDirValue = [string]$configJson.output_dir
if ([string]::IsNullOrWhiteSpace($outputDirValue)) {
    throw "output_dir is missing in config: $configAbs"
}

$outputRootAbs = Join-Path $repoRootAbs "output"
$outputAbs = Join-Path $repoRootAbs $outputDirValue
New-Item -ItemType Directory -Force -Path $outputRootAbs | Out-Null
New-Item -ItemType Directory -Force -Path $outputAbs | Out-Null

Write-Host "Running monitor once..."
Write-Host "  Image: $Image"
Write-Host "  Container: $containerName"
Write-Host "  Config: $configAbs"
Write-Host "  Instance dir: $instanceDirAbs"
Write-Host "  Env: $envAbs"
Write-Host "  Output root: $outputRootAbs"
Write-Host "  Output: $outputAbs"

Start-DockerDesktopIfNeeded

$existingContainer = docker ps -a --format "{{.Names}}" | Where-Object { $_ -eq $containerName }
if ($existingContainer) {
    throw "A container named '$containerName' already exists. Remove it before running this monitor again."
}

docker run --rm `
    --name "$containerName" `
    --env-file "$envAbs" `
    -v "${instanceDirAbs}:/app/instance:ro" `
    -v "${outputRootAbs}:/app/output" `
    --entrypoint python `
    "$Image" /app/run.py --config /app/instance/config.json

if ($LASTEXITCODE -ne 0) {
    throw "docker run failed with exit code $LASTEXITCODE"
}

Write-Host "Monitor run completed successfully."
