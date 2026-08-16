param(
    [switch]$PlanOnly
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$ComposeFile = Join-Path $Root "backend\docker-compose.yml"
$OverlayFile = Join-Path $Root "backend\docker-compose.full-smoke.yml"

function Invoke-AllowedDocker {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

function Report-EnvFilePresence {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $exists = Test-Path -LiteralPath $Path -PathType Leaf
    Write-Host ("env_file_check: {0} exists={1}" -f $Label, $exists)
}

Push-Location $Root
try {
    Write-Host "Public-demo Docker precheck only. No containers are started."
    Write-Host "Allowed default commands: docker --version; docker compose version; docker compose -f backend/docker-compose.yml config --services."
    Write-Host "Forbidden by this script: docker compose up, docker compose build, docker compose pull, docker compose down -v, docker system prune."
    Write-Host "Full-smoke overlay for later explicit authorization: $OverlayFile"

    Report-EnvFilePresence -Label "backend/.env" -Path (Join-Path $Root "backend\.env")
    Report-EnvFilePresence -Label ".env" -Path (Join-Path $Root ".env")
    Report-EnvFilePresence -Label "frontend/.env.production" -Path (Join-Path $Root "frontend\.env.production")
    Report-EnvFilePresence -Label "frontend/.env.local" -Path (Join-Path $Root "frontend\.env.local")

    Write-Host "Heavy services in the full compose graph: milvus, etcd, minio, postgres, redis."
    Write-Host "Network risk: backend Dockerfile may run apt-get, pip install, and model download during build."
    Write-Host "Network risk: frontend Dockerfile may run npm ci during build."
    Write-Host "This precheck reports env file presence only and never reads env file contents."

    if ($PlanOnly) {
        Write-Host "PlanOnly set; no docker command was executed."
        return
    }

    Invoke-AllowedDocker "docker" @("--version")
    Invoke-AllowedDocker "docker" @("compose", "version")
    Invoke-AllowedDocker "docker" @("compose", "-f", $ComposeFile, "config", "--services")

    Write-Host "Docker public-demo precheck completed. No up/build/pull/down/prune command was executed."
}
finally {
    Pop-Location
}
