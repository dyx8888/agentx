#!/bin/bash

# AgentX Backend Startup Script for Linux/Mac
echo "🚀 Starting AgentX Backend Services..."

# Check if .env file exists, copy from .env.example if not
if [ ! -f .env ]; then
    echo "📝 .env file not found, copying from .env.example..."
    cp .env.example .env
    echo "⚠️  Please edit .env file and set your DEEPSEEK_API_KEY"
    echo "   Required environment variables:"
    echo "   - DEEPSEEK_API_KEY=your_deepseek_api_key_here"
    echo "   - (Optional) DATABASE_URL=postgresql://user:password@localhost:5432/agentx"
    echo "   - (Optional) TOOL_LOAD_MODE=http"
    echo ""
    read -p "Press Enter after setting up .env file..."
fi

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if docker-compose is installed
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ docker-compose is not installed. Please install docker-compose first."
    exit 1
fi

# Create data directory if it doesn't exist
mkdir -p data

echo "🐳 Building and starting Docker containers..."

# Use docker-compose or docker compose based on availability
if command -v docker-compose &> /dev/null; then
    docker-compose up --build -d
else
    docker compose up --build -d
fi

echo ""
echo "✅ Services are starting up..."
echo "📊 Main Service: http://localhost:8000"
echo "🔧 KOL Search Tool: http://localhost:8101"
echo "📈 Report Tool: http://localhost:8104"
echo "📚 API Documentation: http://localhost:8000/docs"
echo ""
echo "🔍 Checking service health..."
sleep 10

# Health checks
echo "Checking main service..."
if curl -f http://localhost:8000/health > /dev/null 2>&1; then
    echo "✅ Main service is healthy"
else
    echo "❌ Main service is not responding"
fi

echo "Checking KOL search service..."
if curl -f http://localhost:8101/health > /dev/null 2>&1; then
    echo "✅ KOL search service is healthy"
else
    echo "❌ KOL search service is not responding"
fi

echo "Checking report service..."
if curl -f http://localhost:8104/health > /dev/null 2>&1; then
    echo "✅ Report service is healthy"
else
    echo "❌ Report service is not responding"
fi

echo ""
echo "🎉 AgentX Backend is ready!"
echo "📝 Check logs with: docker-compose logs -f"
echo "🛑 Stop services with: docker-compose down"
