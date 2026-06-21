#!/bin/bash
"""
AgentX Tool Services Stop Script
Stops all running tool microservices
"""

echo "🛑 Stopping AgentX Tool Services..."

# Function to stop services by port
stop_service_by_port() {
    local port=$1
    local service_name=$2
    
    # Find process using the port
    local pid=$(lsof -ti:$port 2>/dev/null)
    
    if [ -n "$pid" ]; then
        echo "🛑 Stopping $service_name (PID: $pid) on port $port..."
        kill -TERM $pid 2>/dev/null
        
        # Wait a bit for graceful shutdown
        sleep 2
        
        # Force kill if still running
        if ps -p $pid > /dev/null 2>&1; then
            echo "⚡ Force killing $service_name..."
            kill -KILL $pid 2>/dev/null
        fi
        
        echo "✅ $service_name stopped"
    else
        echo "ℹ️ $service_name not running on port $port"
    fi
}

# Stop all services by their ports
stop_service_by_port "8101" "KOL Search Service"
stop_service_by_port "8103" "Script Generation Service"
stop_service_by_port "8104" "Report Service"
stop_service_by_port "8105" "Outreach Service"

# Clean up PID file
rm -f /tmp/agentx_tool_services.pids

echo ""
echo "👋 All AgentX Tool Services stopped"
echo "💡 Run ./start_http_services.sh to restart them"
