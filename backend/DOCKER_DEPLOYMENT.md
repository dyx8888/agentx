# AgentX Docker 部署指南

## 概述

AgentX 已完全容器化，支持一键部署所有服务，包括主服务、工具微服务和数据持久化。

## 快速开始

### 1. 环境准备

确保已安装：
- Docker Desktop (Windows/Mac) 或 Docker Engine (Linux)
- Docker Compose

### 2. 配置环境变量

```bash
# 复制环境变量模板
cp .env.example .env

# 编辑 .env 文件，设置必要的 API 密钥
# DEEPSEEK_API_KEY=your_deepseek_api_key_here
```

### 3. 启动服务

**Linux/Mac:**
```bash
chmod +x start.sh
./start.sh
```

**Windows:**
```powershell
.\start.ps1
```

**手动启动:**
```bash
docker-compose up --build -d
```

## 服务架构

### 服务列表

| 服务名称 | 端口 | 描述 | 健康检查 |
|---------|------|------|----------|
| main | 8000 | 主 FastAPI 服务 | `/health` |
| kol-search | 8101 | KOL 搜索工具服务 | `/health` |
| report-server | 8104 | 报告生成工具服务 | `/health` |
| postgres (可选) | 5432 | PostgreSQL 数据库 | - |

### 网络配置

所有服务运行在 `agentx-network` 网络中，可以通过服务名互相访问：
- 主服务调用 KOL 搜索: `http://kol-search:8101`
- 主服务调用报告服务: `http://report-server:8104`

### 数据持久化

以下目录通过 Docker 卷持久化：
- `./data`: SQLite 数据库、ChromaDB 向量数据、训练数据等
- `postgres_data`: PostgreSQL 数据（可选）

## 验证部署

### 1. 健康检查

```bash
# 检查主服务
curl http://localhost:8000/health

# 检查 KOL 搜索服务
curl http://localhost:8101/health

# 检查报告服务
curl http://localhost:8104/health
```

### 2. 服务状态

```bash
# 查看所有服务状态
docker-compose ps

# 查看服务日志
docker-compose logs -f

# 查看特定服务日志
docker-compose logs -f main
```

### 3. 功能测试

```bash
# 测试聊天接口
curl -X POST http://localhost:8000/chat/ \
  -H "Content-Type: application/json" \
  -d '{
    "message": "帮我找3个美妆博主",
    "agent_name": "Amy"
  }'
```

## 配置选项

### 环境变量

| 变量名 | 默认值 | 描述 |
|---------|---------|------|
| `DEEPSEEK_API_KEY` | - | DeepSeek API 密钥（必需） |
| `TOOL_LOAD_MODE` | `http` | 工具加载模式：`http` 或 `local` |
| `DATABASE_URL` | `sqlite:///data/feedback.db` | 数据库连接字符串 |
| `HF_ENDPOINT` | `https://hf-mirror.com` | Hugging Face 镜像地址 |
| `RUN_AS_HTTP_SERVICE` | `true` | 工具服务 HTTP 模式 |

### 数据库选择

**SQLite (默认):**
- 适合开发和测试
- 数据文件: `./data/feedback.db`

**PostgreSQL (生产推荐):**
- 在 `docker-compose.yml` 中取消注释 postgres 服务
- 设置 `DATABASE_URL=postgresql://agentx:<strong-generated-password>@postgres:5432/agentx`

## 常用操作

### 启动/停止

```bash
# 启动所有服务
docker-compose up -d

# 停止所有服务
docker-compose down

# 重新构建并启动
docker-compose up --build -d

# 查看实时日志
docker-compose logs -f
```

### 更新部署

```bash
# 拉取最新代码
git pull

# 重新构建镜像
docker-compose build --no-cache

# 重启服务
docker-compose up -d
```

### 数据备份

```bash
# 备份数据目录
tar -czf agentx-backup-$(date +%Y%m%d).tar.gz data/

# 恢复数据
tar -xzf agentx-backup-YYYYMMDD.tar.gz
```

## 故障排除

### 常见问题

1. **端口冲突**
   ```bash
   # 检查端口占用
   netstat -tulpn | grep :8000
   # 修改 docker-compose.yml 中的端口映射
   ```

2. **权限问题**
   ```bash
   # 修复数据目录权限
   sudo chown -R $USER:$USER data/
   ```

3. **内存不足**
   ```bash
   # 增加 Docker 内存限制
   # 在 Docker Desktop 设置中调整内存分配
   ```

4. **模型下载失败**
   ```bash
   # 检查网络连接
   # 设置 HF_ENDPOINT 环境变量
   export HF_ENDPOINT=https://hf-mirror.com
   ```

### 日志分析

```bash
# 查看错误日志
docker-compose logs | grep ERROR

# 查看特定时间段日志
docker-compose logs --since="2024-01-01T00:00:00"
```

## 生产部署建议

### 1. 资源配置

- **CPU**: 至少 2 核心
- **内存**: 至少 4GB
- **存储**: 至少 10GB

### 2. 安全配置

- 使用强密码
- 启用 HTTPS
- 配置防火墙规则
- 定期备份数据

### 3. 监控

- 配置健康检查监控
- 设置日志收集
- 监控资源使用情况

## API 文档

- **Swagger UI**: http://localhost:8000/docs
- **前端对接文档**: [API_DOCS.md](./API_DOCS.md)

## 技术支持

如遇到部署问题，请检查：
1. Docker 版本是否兼容
2. 环境变量是否正确设置
3. 网络连接是否正常
4. 系统资源是否充足

---

## 部署验证清单

- [ ] Docker 和 Docker Compose 已安装
- [ ] .env 文件已配置
- [ ] 所有服务正常启动
- [ ] 健康检查通过
- [ ] 聊天功能正常
- [ ] 工具服务调用正常
- [ ] 数据持久化正常
- [ ] 日志记录正常

部署完成后，AgentX 后端服务即可投入使用！
