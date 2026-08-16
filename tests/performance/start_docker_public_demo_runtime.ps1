param(
    [switch]$PlanOnly,
    [switch]$CheckOverlay,
    [switch]$CheckLightweight,
    [switch]$CheckBackendLightweight
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$ComposeFile = Join-Path $Root "backend\docker-compose.yml"
$OverlayFile = Join-Path $Root "backend\docker-compose.full-smoke.yml"
$LightweightComposeFile = Join-Path $Root "backend\docker-compose.lightweight.yml"
$BackendLightweightComposeFile = Join-Path $Root "backend\docker-compose.backend-lightweight.yml"
$FrontendLightweightComposeFile = Join-Path $Root "backend\docker-compose.frontend-lightweight.yml"

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

function Show-BackendLightweightPlan {
    Write-Host "Backend lightweight compose plan; this is for a later no-env backend smoke after explicit authorization."
    Write-Host "backend_lightweight_compose_file: $BackendLightweightComposeFile"
    Write-Host "backend_lightweight_project_name: agentx-public-demo-backend-lightweight"
    Write-Host "backend_lightweight_image: ${AGENTX_BACKEND_LIGHTWEIGHT_IMAGE:-agentx-backend:latest} (existing local image only; not proof of current public-demo HEAD code unless AGENTX_BACKEND_LIGHTWEIGHT_IMAGE points to a current HEAD smoke tag after an authorized build)"
    Show-Items "backend_lightweight_services" @(
        "main"
    )
    Show-Items "backend_lightweight_excluded_services" @(
        "redis",
        "postgres",
        "milvus",
        "etcd",
        "minio",
        "frontend",
        "kol-search",
        "report-server"
    )
    Show-Items "backend_lightweight_ports" @(
        "main 8000->8000"
    )
    Show-Items "backend_lightweight_networks" @(
        "agentx-public-demo-lightweight-network (external; created by backend/docker-compose.lightweight.yml)"
    )
    Show-Items "backend_lightweight_bind_mounts" @(
        "none; no backend/.env, .env, backend/.env.production, frontend/.env.production, or frontend/.env.local is mounted"
    )
    Show-Items "backend_lightweight_safe_env" @(
        "ENV=dev",
        "ENVIRONMENT=development",
        "DATABASE_URL=postgresql://agentx:change-me-local-only@agentx-lightweight-postgres:5432/agentx",
        "REDIS_URL=redis://agentx-lightweight-redis:6379/0",
        "RATE_LIMIT_REDIS_URL=redis://agentx-lightweight-redis:6379/1",
        "ENABLE_EVOLUTION_API=false",
        "ENABLE_PUBLIC_DOCS=false",
        "AGENT_EVAL_MODE=1",
        "AGENTX_BACKEND_LIGHTWEIGHT_SMOKE=1",
        "TOOL_DESCRIPTION_AUTO_ENHANCE=0",
        "TOOL_LOAD_MODE=local",
        "MILVUS_HOST=127.0.0.1",
        "MILVUS_PORT=19530"
    )
    Write-Host "backend_future_start_guard: use docker compose -f backend/docker-compose.backend-lightweight.yml up --no-build --pull never -d main only after explicit authorization."
    Write-Host "backend_missing_image_policy: if agentx-backend:latest is missing, --pull never must fail and stop instead of downloading."
    Write-Host "backend_code_proof_limit: this smoke reuses a local image and cannot prove the image was built from the current public-demo HEAD."
    Write-Host "backend_smoke_build_arg: authorized current-source smoke builds should pass --build-arg DOWNLOAD_EMBEDDING_MODEL=false to avoid embedding model downloads."
    Write-Host "backend_lightweight_config_check: run with -CheckBackendLightweight to parse backend/docker-compose.backend-lightweight.yml with compose config --services."
}

function Show-FrontendLightweightPlan {
    Write-Host "Frontend lightweight compose plan; this is static guidance for a later frontend smoke after explicit authorization."
    Write-Host "frontend_lightweight_compose_file: $FrontendLightweightComposeFile"
    Write-Host "frontend_lightweight_project_name: agentx-public-demo-frontend-lightweight"
    Write-Host "frontend_lightweight_image: ${AGENTX_FRONTEND_LIGHTWEIGHT_IMAGE:-agentx-frontend:latest} (existing local image only; not proof of current public-demo HEAD code unless AGENTX_FRONTEND_LIGHTWEIGHT_IMAGE points to a current HEAD smoke tag after an authorized build)"
    Show-Items "frontend_lightweight_services" @(
        "frontend"
    )
    Show-Items "frontend_lightweight_excluded_services" @(
        "backend",
        "redis",
        "postgres",
        "milvus",
        "etcd",
        "minio",
        "kol-search",
        "report-server"
    )
    Show-Items "frontend_lightweight_ports" @(
        "frontend 3000->80"
    )
    Show-Items "frontend_lightweight_networks" @(
        "agentx-public-demo-lightweight-network (external; shared with lightweight backend when explicitly started)"
    )
    Show-Items "frontend_lightweight_bind_mounts" @(
        "none; no frontend/.env.production, frontend/.env.local, .env, or other env file is mounted"
    )
    Show-Items "frontend_lightweight_build_risks" @(
        "frontend Dockerfile runs npm ci and may access npm registry during an authorized build",
        "Vite can inline VITE_* values into dist, so real frontend env files are excluded from Docker context",
        "authorized current-source lightweight frontend builds should pass --build-arg NGINX_CONF=nginx.lightweight.conf to proxy to agentx-lightweight-backend"
    )
    Write-Host "frontend_proxy_boundary: frontend nginx must target agentx-lightweight-backend or a deliberate network alias; do not rely on container localhost for backend access."
    Write-Host "frontend_future_start_guard: use docker compose -f backend/docker-compose.frontend-lightweight.yml up --no-build --pull never -d frontend only after explicit authorization."
    Write-Host "frontend_missing_image_policy: if agentx-frontend:latest or the selected AGENTX_FRONTEND_LIGHTWEIGHT_IMAGE is missing, --pull never must fail and stop instead of downloading."
    Write-Host "frontend_code_proof_limit: old agentx-frontend:latest can only prove an old local image smoke; current-source proof requires an authorized build to a new non-latest tag."
    Write-Host "frontend_lightweight_config_note: this script does not add a frontend Docker execution path; parse manually only after explicit authorization."
}
Push-Location $Root
try {
    Write-Host "Public-demo Docker precheck only. No containers are started."
    Write-Host "Allowed default commands: docker --version; docker compose version; docker compose -f backend/docker-compose.yml config --services."
    Write-Host "Optional overlay parse: docker compose -f backend/docker-compose.yml -f backend/docker-compose.full-smoke.yml config --services when -CheckOverlay is set."
    Write-Host "Optional lightweight parse: docker compose -f backend/docker-compose.lightweight.yml config --services when -CheckLightweight is set."
    Write-Host "Optional backend lightweight parse: docker compose -f backend/docker-compose.backend-lightweight.yml config --services when -CheckBackendLightweight is set."
    Write-Host "Forbidden by this script: docker compose up, docker compose build, docker compose pull, docker compose down -v, docker system prune."
    Write-Host "Full-smoke overlay for later explicit authorization: $OverlayFile"

    Report-EnvFilePresence -Label "backend/.env" -Path (Join-Path $Root "backend\.env")
    Report-EnvFilePresence -Label ".env" -Path (Join-Path $Root ".env")
    Report-EnvFilePresence -Label "frontend/.env.production" -Path (Join-Path $Root "frontend\.env.production")
    Report-EnvFilePresence -Label "frontend/.env.local" -Path (Join-Path $Root "frontend\.env.local")

    Show-ComposePlan
    Show-LightweightPlan
    Show-BackendLightweightPlan
    Show-FrontendLightweightPlan
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

    if ($CheckBackendLightweight) {
        Invoke-AllowedDocker "docker" @("compose", "-f", $BackendLightweightComposeFile, "config", "--services")
    }

    Write-Host "Docker public-demo precheck completed. No up/build/pull/down/prune command was executed."
}
finally {
    Pop-Location
}
