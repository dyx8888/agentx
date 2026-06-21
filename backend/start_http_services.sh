#!/bin/bash
"""
AgentX Tool Services Startup Script
Starts all tool microservices in HTTP mode for hot-swapping functionality
"""

echo "🚀 Starting AgentX Tool Services..."

# Function to start a service with environment variable
start_tool_service() {
    local service_name=$1
    local script_path=$2
    local port=$3
    
    echo "📦 Starting $service_name on port $port..."
    
    # Start service in background
    RUN_AS_HTTP_SERVICE=true PORT=$port python $script_path &
    local pid=$!
    
    if ps -p $pid > /dev/null; then
        echo "✅ $service_name started (PID: $pid)"
        echo $pid >> /tmp/agentx_tool_services.pids
    else
        echo "❌ Failed to start $service_name"
        return 1
    fi
    
    sleep 2  # Give each service time to start
}

# Clean up any existing PID file
rm -f /tmp/agentx_tool_services.pids

# Start all tool services
start_tool_service "KOL Search Service" "app/mcp_servers/kol_search_server.py" "8101"
start_tool_service "Script Generation Service" "app/mcp_servers/script_server.py" "8103"
start_tool_service "Report Service" "app/mcp_servers/report_server.py" "8104"
start_tool_service "Outreach Service" "app/mcp_servers/outreach_server.py" "8105"
start_tool_service "Monitor Service" "app/mcp_servers/monitor_server.py" "8104"

echo ""
echo "🎯 All services started! Tool endpoints:"
echo "• KOL Search:     http://localhost:8101/tools/search_kols"
echo "• Script Gen:      http://localhost:8103/tools/generate_script"
echo "• Report:         http://localhost:8104/tools/generate_performance_report"
echo "• Strategy:        http://localhost:8104/tools/generate_strategy_suggestion"
echo "• Outreach:        http://localhost:8105/tools/generate_outreach"
echo "• Delivery Status: http://localhost:8104/tools/check_delivery_status"
echo "• Arrival Script:  http://localhost:8104/tools/generate_arrival_script"
echo ""

echo "🔧 To start main service in HTTP mode:"
echo 'export TOOL_LOAD_MODE="http"'
echo "python app/main.py"
echo ""

echo "🛑 To stop all services, press Ctrl+C or run: ./stop_http_services.sh"
echo "💡 Individual services can be stopped with: kill <PID>"

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "🛑 Stopping services..."
    
    if [ -f /tmp/agentx_tool_services.pids ]; then
        while read -r pid; do
            if ps -p $pid > /dev/null; then
                kill $pid
                echo "✅ Stopped process $pid"
            fi
        done < /tmp/agentx_tool_services.pids
        rm -f /tmp/agentx_tool_services.pids
    fi
    
    echo "👋 AgentX Tool Services stopped"
    exit 0
}

# Set up signal handlers
trap cleanup SIGINT SIGTERM

# Wait for services to run
while true; do
    sleep 5
    
    # Check if any services are still running
    running_count=0
    if [ -f /tmp/agentx_tool_services.pids ]; then
        while read -r pid; do
            if ps -p $pid > /dev/null; then
                ((running_count++))
            fi
        done < /tmp/agentx_tool_services.pids
    fi
    
    if [ $running_count -eq 0 ]; then
        echo "⚠️ All services have stopped"
        break
    fi
done
