#!/usr/bin/env bash
# 昔涟 V3.3 · 一键启动脚本
# 用法：bash scripts/start.sh
set -euo pipefail

# 定位项目根目录
cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${MAGENTA}🐾 昔涟 V3.3 · 心之涟漪  启动中...${NC}"

# 检查 .env
if [ ! -f ".env" ]; then
    echo "⚠️  未找到 .env，请先运行 bash scripts/setup.sh"
    exit 1
fi

# 检查前端构建（生产模式）
DIST_DIR="packages/frontend/dist"
if [ -d "$DIST_DIR" ] && [ -f "$DIST_DIR/index.html" ]; then
    echo "✅ 前端已就绪"
else
    echo "📦 前端未构建，正在构建..."
    if [ -f "packages/frontend/package.json" ]; then
        cd packages/frontend
        npm install --silent && npm run build --silent
        cd "$PROJECT_ROOT"
        echo "✅ 前端构建完成"
    else
        echo "⚠️  未找到前端项目，将以 API-only 模式启动"
    fi
fi

echo -e "${CYAN}启动后端 + 前端（单进程）...${NC}"
echo -e "${CYAN}打开浏览器访问：http://localhost:8000${NC}"
echo ""

uv run python main.py
