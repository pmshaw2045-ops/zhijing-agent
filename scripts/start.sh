#!/bin/bash
# 织镜 ZHÌJÌNG 启动脚本
set -e

cd "$(dirname "$0")"
echo "🚀 织镜 ZHÌJÌNG — 服饰电商AI Agent"
echo ""

# 确保依赖
pip3 install -q fastapi uvicorn sse-starlette 2>/dev/null

# 启动服务
echo "▶ 启动服务 (port 8899)..."
cd backend
python3 server.py
