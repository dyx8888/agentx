param(
    [switch]$PlanOnly,
    [switch]$CheckOverlay,
    [switch]$CheckLightweight
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$ComposeFile = Join-Path $Root "backend\docker-compose.yml"
$OverlayFile = Join-Path $Root "backend\docker-compose.full-smoke.yml"
$LightweightComposeFile = Join-Path $Root "backend\docker-compose.lightweight.yml"

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

function Show-Items {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title,
        [Parameter(Mandatory = $true)]
        [string[]]$Items
    )

    Write-Host ("{0}:" -f $Title)
    foreach ($item in $Items) {
        Write-Host ("  - {0}" -f $item)
    }
}

function Show-ComposePlan {
    Write-Host "Compose plan summary; this is static guidance for the current public-demo compose file."
    Show-Items "default_services" @(
        "etcd",
        "redis",
        "report-server",
        "kol-search",
        "postgres",
        "main",
        "frontend",
        "minio",
        "milvus"
    )
    Show-Items "published_ports" @(
        "frontend 3000->80",
        "main 8000->8000",
        "kol-search 8101->8101",
        "report-server 8104->8104",
        "postgres 5432->5432",
        "redis 6379->6379",
        "minio-console 9001->9001",
        "milvus 19530->19530",
        "milvus-health 9091->9091"
    )
    Show-Items "named_volumes" @(
        "redis_data -> /data",
        "postgres_data -> /var/lib/postgresql/data",
        "etcd_data -> /etcd",
        "minio_data -> /minio_data",
        "milvus_data -> /var/lib/milvus"
    )
    Show-Items "bind_mounts" @(
        "backend/data -> /app/data",
        "backend/.env -> /app/.env:ro (risk: container can read it if the file exists; this script only checks existence)"
    )
    Show-Items "heavy_services" @(
        "milvus",
        "etcd",
        "minio",
        "postgres",
        "redis"
    )
    Show-Items "build_network_risks" @(
        "backend Dockerfile may run apt-get",
        "backend Dockerfile may run pip install",
        "backend Dockerfile may download embedding model artifacts",
        "frontend Dockerfile may run npm ci"
    )
    Write-Host "overlay_config_check: run with -CheckOverlay to parse backend/docker-compose.full-smoke.yml with compose config --services."
}

function Show-LightweightPlan {
    Write-Host "Lightweight compose plan; this is the recommended first Docker startup rehearsal after explicit authorization."
    Write-Host "lightweight_compose_file: $LightweightComposeFile"
    Write-Host "lightweight_project_name: agentx-public-demo-lightweight"
    Show-Items "lightweight_services" @(
        "redis",
        "postgres"
    )
    Show-Items "lightweight_excluded_services" @(
        "milvus",
        "etcd",
        "minio",
        "main",
        "frontend",
        "kol-search",
        "report-server"
    )
    Show-Items "lightweight_ports" @(
        "redis 6379->6379",
        "postgres 5432->5432"
    )
    Show-Items "lightweight_named_volumes" @(
        "agentx_public_demo_lightweight_redis_data -> /data",
        "agentx_public_demo_lightweight_postgres_data -> /var/lib/postgresql/data"
    )
    Show-Items "lightweight_bind_mounts" @(
        "none; backend/.env is not mounted by the lightweight compose file"
    )
    Write-Host "future_start_guard: use docker compose -f backend/docker-compose.lightweight.yml up --no-build --pull never -d redis postgres only after explicit authorization."
    Write-Host "missing_image_policy: if redis:7-alpine or postgres:15-alpine is missing, --pull never must fail and stop instead of downloading."
    Write-Host "volume_safety: lightweight compose uses isolated project and volume names to avoid reusing default backend_* volumes."
    Write-Host "lightweight_config_check: run with -CheckLightweight to parse backend/docker-compose.lightweight.yml with compose config --services."
}

Push-Location $Root
try {
    Write-Host "Public-demo Docker precheck only. No containers are started."
    Write-Host "Allowed default commands: docker --version; docker compose version; docker compose -f backend/docker-compose.yml config --services."
    Write-Host "Optional overlay parse: docker compose -f backend/docker-compose.yml -f backend/docker-compose.full-smoke.yml config --services when -CheckOverlay is set."
    Write-Host "Optional lightweight parse: docker compose -f backend/docker-compose.lightweight.yml config --services when -CheckLightweight is set."
    Write-Host "Forbidden by this script: docker compose up, docker compose build, docker compose pull, docker compose down -v, docker system prune."
    Write-Host "Full-smoke overlay for later explicit authorization: $OverlayFile"

    Report-EnvFilePresence -Label "backend/.env" -Path (Join-Path $Root "backend\.env")
    Report-EnvFilePresence -Label ".env" -Path (Join-Path $Root ".env")
    Report-EnvFilePresence -Label "frontend/.env.production" -Path (Join-Path $Root "frontend\.env.production")
    Report-EnvFilePresence -Label "frontend/.env.local" -Path (Join-Path $Root "frontend\.env.local")

    Show-ComposePlan
    Show-LightweightPlan
    Write-Host "This precheck reports env file presence only and never reads env file contents."

    if ($PlanOnly) {
        Write-Host "PlanOnly set; no docker command was executed."
        return
    }

    Invoke-AllowedDocker "docker" @("--version")
    Invoke-AllowedDocker "docker" @("compose", "version")
    Invoke-AllowedDocker "docker" @("compose", "-f", $ComposeFile, "config", "--services")

    if ($CheckOverlay) {
        Invoke-AllowedDocker "docker" @("compose", "-f", $ComposeFile, "-f", $OverlayFile, "config", "--services")
    }

    if ($CheckLightweight) {
        Invoke-AllowedDocker "docker" @("compose", "-f", $LightweightComposeFile, "config", "--services")
    }

    Write-Host "Docker public-demo precheck completed. No up/build/pull/down/prune command was executed."
}
finally {
    Pop-Location
}
