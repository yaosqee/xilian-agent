#!/usr/bin/env bash
# 昔涟 V3.3 · 一键启动脚本
# 用法：bash scripts/start.sh
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${MAGENTA}"
echo "  ╭────────────────────────────────╮"
echo "  │     🐾 昔涟 V3.3 · 心之涟漪      │"
echo "  │        一键启动 start.sh          │"
echo "  ╰────────────────────────────────╯"
echo -e "${NC}"

# ═══════════════════════════════════════════════════
# 0. 环境检查
# ═══════════════════════════════════════════════════

# .env
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠️  未找到 .env，请先运行 bash scripts/setup.sh${NC}"
    exit 1
fi

# Python + uv
if ! command -v uv &>/dev/null; then
    echo -e "${YELLOW}⚠️  uv 未安装，请先运行 bash scripts/setup.sh${NC}"
    exit 1
fi

# ═══════════════════════════════════════════════════
# 1. 数据库迁移
# ═══════════════════════════════════════════════════
echo "🔄 检查数据库..."
if uv run alembic current 2>/dev/null | grep -q "(head)"; then
    echo -e "${GREEN}✅ 数据库已是最新${NC}"
else
    echo "📦 执行数据库迁移..."
    uv run alembic upgrade head 2>/dev/null || true
fi

# ═══════════════════════════════════════════════════
# 2. 前端检查
# ═══════════════════════════════════════════════════
DIST_DIR="packages/frontend/dist"
if [ -d "$DIST_DIR" ] && [ -f "$DIST_DIR/index.html" ]; then
    echo -e "${GREEN}✅ 前端已就绪${NC}"
elif [ "${FRONTEND_DEV:-}" = "1" ]; then
    echo -e "${CYAN}🔧 前端开发模式（FRONTEND_DEV=1）${NC}"
else
    echo -e "${YELLOW}📦 前端未构建，正在构建...${NC}"
    if [ -f "packages/frontend/package.json" ] && command -v npm &>/dev/null; then
        cd packages/frontend
        npm install --silent 2>/dev/null || npm install
        npm run build --silent 2>/dev/null || npm run build
        cd "$PROJECT_ROOT"
        echo -e "${GREEN}✅ 前端构建完成${NC}"
    else
        echo -e "${YELLOW}⚪ 前端不可用，API-only 模式${NC}"
    fi
fi

# ═══════════════════════════════════════════════════
# 3. 启动
# ═══════════════════════════════════════════════════
echo ""
echo -e "${MAGENTA}🐾 昔涟正在醒来...${NC}"
echo -e "${CYAN}   → http://localhost:${HTTP_PORT:-8000}${NC}"
echo ""

uv run python main.py
