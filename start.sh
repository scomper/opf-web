#!/bin/bash
# OPF Web 本地启动脚本（开发模式）
# 前提：OPF 容器已在运行（docker compose up -d）

set -e

cd "$(dirname "$0")"

# 检查 OPF 容器
if ! curl -s http://localhost:8000/health | grep -q '"ok"'; then
  echo "⚠️  OPF 容器未运行，尝试启动..."
  docker compose up -d opf 2>/dev/null || echo "请先运行: docker compose up -d"
  sleep 5
fi

# 检查 Python 依赖
if ! python3 -c "import fastapi, httpx, openpyxl, docx, pdfplumber" 2>/dev/null; then
  echo "📦 安装依赖..."
  pip3 install -r requirements.txt
fi

echo ""
echo "🚀 OPF Web 启动中..."
echo "   访问: http://localhost:8081"
echo "   OPF API: http://localhost:8000"
echo ""

python3 -m uvicorn app:app --host 0.0.0.0 --port 8081 --reload
