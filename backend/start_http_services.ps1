#!/usr/bin/env pwsh
"""
AgentX Tool Services Startup Script
Starts all tool microservices in HTTP mode for hot-swapping functionality
"""

Write-Host "🚀 Starting AgentX Tool Services..." -ForegroundColor Green

# Function to start a service with environment variable
function Start-ToolService {
    param(
        [string]$ServiceName,
        [string]$ScriptPath,
        [string]$Port
    )
    
    Write-Host "📦 Starting $ServiceName on port $Port..." -ForegroundColor Yellow
    
    $process = Start-Process -FilePath "python" -ArgumentList @($ScriptPath) -Environment @{
        "RUN_AS_HTTP_SERVICE" = "true"
        "PORT" = $Port
    } -PassThru -WindowStyle Hidden
    
    if ($process) {
        Write-Host "✅ $ServiceName started (PID: $($process.Id))" -ForegroundColor Green
    } else {
        Write-Host "❌ Failed to start $ServiceName" -ForegroundColor Red
    }
    
    return $process
}

# Start all tool services
$services = @(
    @{
        Name = "KOL Search Service"
        Path = "app/mcp_servers/kol_search_server.py"
        Port = "8101"
    },
    @{
        Name = "Script Generation Service"
        Path = "app/mcp_servers/script_server.py"
        Port = "8103"
    },
    @{
        Name = "Report Service"
        Path = "app/mcp_servers/report_server.py"
        Port = "8104"
    },
    @{
        Name = "Outreach Service"
        Path = "app/mcp_servers/outreach_server.py"
        Port = "8105"
    },
    @{
        Name = "Monitor Service"
        Path = "app/mcp_servers/monitor_server.py"
        Port = "8104"
    }
)

$processes = @()

foreach ($service in $services) {
    $process = Start-ToolService -ServiceName $service.Name -ScriptPath $service.Path -Port $service.Port
    $processes += $process
    Start-Sleep -Seconds 2  # Give each service time to start
}

Write-Host ""
Write-Host "🎯 All services started! Tool endpoints:" -ForegroundColor Cyan
Write-Host "• KOL Search:     http://localhost:8101/tools/search_kols" -ForegroundColor White
Write-Host "• Script Gen:      http://localhost:8103/tools/generate_script" -ForegroundColor White
Write-Host "• Report:         http://localhost:8104/tools/generate_performance_report" -ForegroundColor White
Write-Host "• Strategy:        http://localhost:8104/tools/generate_strategy_suggestion" -ForegroundColor White
Write-Host "• Outreach:        http://localhost:8105/tools/generate_outreach" -ForegroundColor White
Write-Host "• Delivery Status: http://localhost:8104/tools/check_delivery_status" -ForegroundColor White
Write-Host "• Arrival Script:  http://localhost:8104/tools/generate_arrival_script" -ForegroundColor White
Write-Host ""

Write-Host "🔧 To start main service in HTTP mode:" -ForegroundColor Yellow
Write-Host '$env:TOOL_LOAD_MODE="http"' -ForegroundColor Gray
Write-Host "python app/main.py" -ForegroundColor Gray
Write-Host ""

Write-Host "🛑 To stop all services, press Ctrl+C or close this window" -ForegroundColor Red
Write-Host "💡 Individual services can be stopped via Task Manager" -ForegroundColor Gray

# Wait for user input to keep script running
try {
    while ($true) {
        Start-Sleep -Seconds 5
        
        # Check if all processes are still running
        $runningCount = 0
        foreach ($process in $processes) {
            if ($process -and !$process.HasExited) {
                $runningCount++
            }
        }
        
        if ($runningCount -eq 0) {
            Write-Host "⚠️ All services have stopped" -ForegroundColor Yellow
            break
        }
    }
}
catch {
    Write-Host "🛑 Stopping services..." -ForegroundColor Yellow
    
    # Clean up processes
    foreach ($process in $processes) {
        if ($process -and !$process.HasExited) {
            try {
                $process.Kill()
                Write-Host "✅ Stopped $($process.ProcessName)" -ForegroundColor Green
            }
            catch {
                Write-Host "⚠️ Could not stop $($process.ProcessName): $($_.Exception.Message)" -ForegroundColor Yellow
            }
        }
    }
}

Write-Host "👋 AgentX Tool Services stopped" -ForegroundColor Cyan
