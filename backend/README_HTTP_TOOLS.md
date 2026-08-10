# AgentX Stage 13 - Tool HTTP Hot-Swapping Documentation

## Overview

AgentX Stage 13 implements HTTP-based tool hot-swapping, allowing tools to be updated without restarting the main service. This enables true "plug-and-play" capability for tools.

## Key Features

### 🔄 HTTP Tool Services
- **Independent Services**: Tools can run as separate HTTP services
- **Hot-Swapping**: Tools can be updated without service restart
- **Backward Compatibility**: Default behavior unchanged (local imports)
- **Error Handling**: Graceful HTTP failures with descriptive errors
- **Logging**: Comprehensive HTTP call tracking and debugging

### 🛠️ Architecture

```
Environment Variable: TOOL_LOAD_MODE=http
┌─────────────────────────────────────────────────┐
│ Main Service (AgentX)                    │
│ - Uses HTTP tools via tool_client.py    │
│ - Falls back to local if HTTP fails    │
└─────────────────────────────────────────────────┘
         │ HTTP Tool Services (Independent)
         │ - kol_search_server (Port 8101)
         │ - report_server (Port 8104)
         └─────────────────────────────────┘
```

## Quick Start

### 1. Start Tool Services

```bash
# Terminal 1: KOL Search Service
$ export RUN_AS_HTTP_SERVICE=true
$ python app/mcp_servers/kol_search_server.py

# Terminal 2: Report Service  
$ export RUN_AS_HTTP_SERVICE=true
$ python app/mcp_servers/report_server.py
```

### 2. Start Main Service with HTTP Mode

```bash
$ export TOOL_LOAD_MODE=http
$ python app/main.py
```

### 3. Test HTTP Tools

```bash
# Test KOL Search
curl -X POST "http://localhost:8101/tools/search_kols" \
  -H "Content-Type: application/json" \
  -d '{"category": "beauty", "count": 3}'

# Test Report Generation
curl -X POST "http://localhost:8104/tools/generate_performance_report" \
  -H "Content-Type: application/json" \
  -d '{"kol_name": "LisaBeauty", "campaign_id": "campaign_001"}'
```

### 4. Test Hot-Swapping

```bash
# Stop report service (simulate tool update)
# Kill the report_server process

# Test with main service - should show error
curl -X POST "http://localhost:8000/chat" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "帮 LisaBeauty 生成一份活动报告"}'

# Restart report service (should work again)
# Start report_server again
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TOOL_LOAD_MODE` | `local` | Tool loading mode: `local` or `http` |
| `RUN_AS_HTTP_SERVICE` | `false` | Enable HTTP service mode for tool servers |

### Tools Configuration (config/tools.yaml)

```yaml
tools:
  # HTTP-enabled tools
  - name: search_kols
    module: app.mcp_servers.kol_search_server
    function: search_kols
    description: "查找特定品类的达人（KOL）"
    endpoint: "http://localhost:8101/tools/search_kols"
    
  - name: generate_performance_report
    module: app.mcp_servers.report_server
    function: generate_performance_report
    description: "生成达人合作效果报告"
    endpoint: "http://localhost:8104/tools/generate_performance_report"
    
  - name: generate_strategy_suggestion
    module: app.mcp_servers.report_server
    function: generate_strategy_suggestion
    description: "生成平台营销策略建议"
    endpoint: "http://localhost:8104/tools/generate_strategy_suggestion"

  # Local fallback tools (used when TOOL_LOAD_MODE=local)
  - name: get_current_time
    module: app.agent
    function: get_current_time
    description: "获取当前时间"
    
  - name: generate_outreach
    module: app.mcp_servers.outreach_server
    function: generate_outreach
    description: "生成达人合作邀约话术"
```

## API Endpoints

### Tool Service Endpoints

#### KOL Search Server (Port 8101)
- `POST /tools/search_kols` - Search KOLs by category
- `GET /health` - Health check

#### Report Server (Port 8104)
- `POST /tools/generate_performance_report` - Generate performance reports
- `POST /tools/generate_strategy_suggestion` - Generate strategy suggestions
- `GET /health` - Health check

### HTTP Request Format

```json
{
  "category": "beauty",
  "count": 3
}
```

### HTTP Response Format

```json
{
  "status": "success",
  "data": [...],
  "message": "Found 3 KOLs in beauty category"
}
```

## Error Handling

### HTTP Tool Client Features
- **Retry Logic**: 3 attempts with exponential backoff
- **Timeout Protection**: 30-second timeout per request
- **Error Logging**: Detailed HTTP call tracking
- **Graceful Degradation**: Returns descriptive errors on failure

### Error Response Examples

```json
{
  "error": "HTTP request timeout after 3 attempts: RequestTimeout"
}

{
  "error": "HTTP request failed: ConnectionError"
}

{
  "error": "Tool generate_performance_report failed: Internal server error"
}
```

## Debugging

### HTTP Call Logging

The system logs all HTTP tool calls with detailed information:

```
[HTTP_TOOL_CALL] ATTEMPT: search_kols -> http://localhost:8101/tools/search_kols
[HTTP_TOOL_CALL] Parameters: {"category": "beauty", "count": 3}
[HTTP_TOOL_CALL] SUCCESS: Response: {"status": "success", "data": [...]}
```

### Health Check

```bash
curl http://localhost:8101/health
# Response: {"status": "healthy", "service": "kol_search"}

curl http://localhost:8104/health  
# Response: {"status": "healthy", "service": "report"}
```

## Troubleshooting

### Common Issues

1. **Port Conflicts**: Ensure ports 8101, 8104 are available
2. **Environment Variables**: Check TOOL_LOAD_MODE and RUN_AS_HTTP_SERVICE are set correctly
3. **Service Discovery**: Verify services are running before starting main service
4. **Network Issues**: Check firewall settings if HTTP calls fail

### Debug Commands

```bash
# Check if services are running
netstat -an | grep ":8101\|:8104"

# Test HTTP connectivity
curl -v http://localhost:8101/health

# Check environment variables
echo "TOOL_LOAD_MODE: $TOOL_LOAD_MODE"
echo "RUN_AS_HTTP_SERVICE: $RUN_AS_HTTP_SERVICE"
```

## Migration Guide

### From Local to HTTP Mode

1. **Set Environment**: `export TOOL_LOAD_MODE=http`
2. **Update Configuration**: Add `endpoint` fields to tools.yaml
3. **Start Services**: Run tool services independently
4. **Test Integration**: Verify main service can call HTTP tools
5. **Monitor Logs**: Check HTTP_TOOL_CALL logs for debugging

### Back to Local Mode

1. **Clear Environment**: `unset TOOL_LOAD_MODE`
2. **Stop Services**: Kill independent tool services
3. **Restart Main**: `python app/main.py`

## Security Considerations

### Current State
- **No Authentication**: HTTP tool services are open for development
- **Local Network**: Services bind to localhost only
- **Production**: Add authentication tokens for tool services

### Future Enhancements
- **Service Discovery**: Dynamic service registration
- **Load Balancing**: Multiple service instances
- **Authentication**: Token-based access control
- **Monitoring**: Service health metrics and alerts
