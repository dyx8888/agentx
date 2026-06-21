# AgentX HTTP 工具热插拔指南

## 概述

AgentX Stage 21 实现了工具服务的 HTTP 热插拔功能，允许在不重启主服务的情况下独立启动、停止和更新工具服务。

## 核心特性

- **热插拔**: 工具服务可独立启停，不影响主服务
- **HTTP 通信**: 主服务通过 HTTP 调用工具服务
- **向后兼容**: 默认使用本地导入模式，保持原有行为
- **容错处理**: 工具服务故障时不影响主服务运行

## 服务端口分配

| 服务名称 | 端口 | 端点路径 | 功能描述 |
|---------|------|----------|----------|
| KOL 搜索服务 | 8101 | `/tools/search_kols` | 查找特定品类的达人 |
| 脚本生成服务 | 8103 | `/tools/generate_script` | 生成短视频脚本 |
| 报告服务 | 8104 | `/tools/generate_performance_report` | 生成达人合作效果报告 |
| 报告服务 | 8104 | `/tools/generate_strategy_suggestion` | 生成平台营销策略建议 |
| 监控服务 | 8104 | `/tools/check_delivery_status` | 查询快递配送状态 |
| 监控服务 | 8104 | `/tools/generate_arrival_script` | 生成快递提醒私信 |
| 外联服务 | 8105 | `/tools/generate_outreach` | 生成达人合作邀约话术 |

## 快速启动

### 方式一：使用启动脚本（推荐）

#### Windows (PowerShell)
```powershell
# 启动所有工具服务
.\start_http_services.ps1

# 在另一个终端启动主服务（HTTP 模式）
$env:TOOL_LOAD_MODE="http"
python app/main.py
```

#### Linux/Mac (Bash)
```bash
# 给脚本执行权限
chmod +x start_http_services.sh

# 启动所有工具服务
./start_http_services.sh

# 在另一个终端启动主服务（HTTP 模式）
export TOOL_LOAD_MODE="http"
python app/main.py
```

### 方式二：手动启动

```bash
# 终端 1: KOL 搜索服务
RUN_AS_HTTP_SERVICE=true PORT=8101 python app/mcp_servers/kol_search_server.py

# 终端 2: 脚本生成服务
RUN_AS_HTTP_SERVICE=true PORT=8103 python app/mcp_servers/script_server.py

# 终端 3: 报告服务
RUN_AS_HTTP_SERVICE=true PORT=8104 python app/mcp_servers/report_server.py

# 终端 4: 外联服务
RUN_AS_HTTP_SERVICE=true PORT=8105 python app/mcp_servers/outreach_server.py

# 终端 5: 监控服务
RUN_AS_HTTP_SERVICE=true PORT=8104 python app/mcp_servers/monitor_server.py

# 终端 6: 主服务（HTTP 模式）
export TOOL_LOAD_MODE="http"
python app/main.py
```

## 使用示例

### 测试工具热插拔

1. **启动所有服务**
   ```powershell
   .\start_http_services.ps1
   ```

2. **验证服务健康状态**
   ```bash
   curl http://localhost:8101/health
   curl http://localhost:8103/health
   curl http://localhost:8104/health
   curl http://localhost:8105/health
   ```

3. **测试功能**
   - 向 Amy 发送："帮我找 3 个美妆博主"
   - 向 Ben 发送："帮 LisaBeauty 生成一份活动报告"
   - 向 CC 发送："帮我写一个保湿面霜的抖音脚本"

4. **验证热插拔**
   ```bash
   # 关闭报告服务（模拟故障）
   # 找到报告服务进程并终止
   
   # 再次向 Ben 请求报告
   # 应看到错误提示但主服务不崩溃
   
   # 重新启动报告服务
   RUN_AS_HTTP_SERVICE=true PORT=8104 python app/mcp_servers/report_server.py
   
   # 再次请求报告，应恢复正常
   ```

## 配置说明

### 环境变量

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `TOOL_LOAD_MODE` | `local` | 工具加载模式：`local`（本地导入）或 `http`（HTTP 调用） |
| `RUN_AS_HTTP_SERVICE` | `false` | 是否以 HTTP 服务模式运行工具服务 |
| `PORT` | 见上表 | 工具服务监听端口 |

### 工具配置

工具配置文件：`config/tools.yaml`

```yaml
tools:
  - name: search_kols
    module: app.mcp_servers.kol_search_server
    function: search_kols
    description: "查找特定品类的达人（KOL）"
    endpoint: "http://localhost:8101/tools/search_kols"  # HTTP 模式端点
```

## 故障排除

### 常见问题

1. **端口冲突**
   - 确保端口 8101-8105 未被占用
   - 使用 `netstat -an | grep 810` 检查端口占用

2. **服务启动失败**
   - 检查 Python 环境和依赖
   - 查看服务日志输出

3. **HTTP 调用失败**
   - 确认工具服务正在运行
   - 检查防火墙设置
   - 验证端点 URL 正确性

4. **主服务无法加载工具**
   - 确认 `TOOL_LOAD_MODE=http`
   - 检查 `tools.yaml` 配置
   - 查看主服务日志中的 `[HTTP_TOOL]` 标记

### 日志查看

**工具服务日志**：
- 每个服务启动时会显示端口信息
- HTTP 请求会在主服务日志中显示 `[HTTP_TOOL_CALL]` 标记

**主服务日志**：
- `[HTTP_TOOL] Loading tool ... via HTTP endpoint` - 工具通过 HTTP 加载
- `[LOCAL_TOOL] Loading tool ... via local import` - 工具通过本地导入

## 停止服务

### Windows
```powershell
# 关闭 PowerShell 窗口或按 Ctrl+C
# 或在任务管理器中结束进程
```

### Linux/Mac
```bash
# 使用提供的停止脚本
./stop_http_services.sh

# 或手动终止
pkill -f "python.*mcp_servers"
```

## 开发指南

### 添加新工具服务

1. **创建工具服务**
   - 继承现有服务模板
   - 实现 MCP 工具函数
   - 添加 HTTP 端点处理

2. **配置端点**
   - 在 `tools.yaml` 中添加端点配置
   - 分配唯一端口

3. **测试热插拔**
   - 验证独立启停功能
   - 测试 HTTP 调用正常

### 最佳实践

- **服务隔离**: 每个工具服务独立运行，故障不传播
- **端口管理**: 使用端口分配表避免冲突
- **容错设计**: HTTP 调用失败时优雅降级
- **日志记录**: 详细记录工具调用和错误信息

---

**注意**: 首次使用前请确保所有依赖已安装，建议先在本地模式下测试正常后再切换到 HTTP 模式。
