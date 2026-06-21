# AgentX Backend Startup Script for Windows PowerShell
Write-Host "🚀 Starting AgentX Backend Services..." -ForegroundColor Green

# Check if .env file exists, copy from .env.example if not
if (-not (Test-Path .env)) {
    Write-Host "📝 .env file not found, copying from .env.example..." -ForegroundColor Yellow
    Copy-Item .env.example .env
    Write-Host "⚠️  Please edit .env file and set your DEEPSEEK_API_KEY" -ForegroundColor Yellow
    Write-Host "   Required environment variables:" -ForegroundColor Cyan
    Write-Host "   - DEEPSEEK_API_KEY=your_deepseek_api_key_here" -ForegroundColor White
    Write-Host "   - (Optional) DATABASE_URL=postgresql://user:password@localhost:5432/agentx" -ForegroundColor White
    Write-Host "   - (Optional) TOOL_LOAD_MODE=http" -ForegroundColor White
    Write-Host ""
    Read-Host "Press Enter after setting up .env file..."
}

# Check if Docker is installed
try {
    docker --version > $null 2>&1
    Write-Host "✅ Docker is installed" -ForegroundColor Green
} catch {
    Write-Host "❌ Docker is not installed. Please install Docker Desktop first." -ForegroundColor Red
    exit 1
}

# Check if docker-compose is available
try {
    docker-compose --version > $null 2>&1
    $composeCmd = "docker-compose"
} catch {
    try {
        docker compose version > $null 2>&1
        $composeCmd = "docker compose"
    } catch {
        Write-Host "❌ docker-compose is not available. Please install docker-compose." -ForegroundColor Red
        exit 1
    }
}

Write-Host "✅ Using: $composeCmd" -ForegroundColor Green

# Create data directory if it doesn't exist
if (-not (Test-Path data)) {
    New-Item -ItemType Directory -Path data -Force
}

Write-Host "🐳 Building and starting Docker containers..." -ForegroundColor Blue

# Start Docker containers
try {
    & $composeCmd up --build -d
    Write-Host "✅ Docker containers started successfully" -ForegroundColor Green
} catch {
    Write-Host "❌ Failed to start Docker containers: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "✅ Services are starting up..." -ForegroundColor Green
Write-Host "📊 Main Service: http://localhost:8000" -ForegroundColor Cyan
Write-Host "🔧 KOL Search Tool: http://localhost:8101" -ForegroundColor Cyan
Write-Host "📈 Report Tool: http://localhost:8104" -ForegroundColor Cyan
Write-Host "📚 API Documentation: http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host ""

Write-Host "🔍 Checking service health..." -ForegroundColor Yellow
Start-Sleep -Seconds 10

# Health checks
Write-Host "Checking main service..." -ForegroundColor White
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 10
    if ($response.StatusCode -eq 200) {
        Write-Host "✅ Main service is healthy" -ForegroundColor Green
    } else {
        Write-Host "❌ Main service is not responding (Status: $($response.StatusCode))" -ForegroundColor Red
    }
} catch {
    Write-Host "❌ Main service is not responding" -ForegroundColor Red
}

Write-Host "Checking KOL search service..." -ForegroundColor White
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8101/health" -UseBasicParsing -TimeoutSec 10
    if ($response.StatusCode -eq 200) {
        Write-Host "✅ KOL search service is healthy" -ForegroundColor Green
    } else {
        Write-Host "❌ KOL search service is not responding (Status: $($response.StatusCode))" -ForegroundColor Red
    }
} catch {
    Write-Host "❌ KOL search service is not responding" -ForegroundColor Red
}

Write-Host "Checking report service..." -ForegroundColor White
try {
    $response = Invoke-WebRequest -Uri "http://localhost:8104/health" -UseBasicParsing -TimeoutSec 10
    if ($response.StatusCode -eq 200) {
        Write-Host "✅ Report service is healthy" -ForegroundColor Green
    } else {
        Write-Host "❌ Report service is not responding (Status: $($response.StatusCode))" -ForegroundColor Red
    }
} catch {
    Write-Host "❌ Report service is not responding" -ForegroundColor Red
}

Write-Host ""
Write-Host "🎉 AgentX Backend is ready!" -ForegroundColor Green
Write-Host "📝 Check logs with: $composeCmd logs -f" -ForegroundColor Cyan
Write-Host "🛑 Stop services with: $composeCmd down" -ForegroundColor Yellow
