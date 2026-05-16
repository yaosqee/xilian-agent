#!/usr/bin/env bash
# 昔涟 V3.3 · 安装脚本
# 用法：bash scripts/setup.sh
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m'

echo -e "${MAGENTA}"
echo "  ╭────────────────────────────────╮"
echo "  │     🐾 昔涟 V3.3 · 心之涟漪      │"
echo "  │        安装脚本 setup.sh          │"
echo "  ╰────────────────────────────────╯"
echo -e "${NC}"

cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)
echo -e "${CYAN}📂 项目目录：${PROJECT_ROOT}${NC}"

# ═══════════════════════════════════════════════════
# 1. Python 检查
# ═══════════════════════════════════════════════════
echo ""
echo -e "${YELLOW}[1/6] 检查 Python...${NC}"
PYTHON_CMD=""
for cmd in python3.12 python3 python; do
    if command -v $cmd &>/dev/null; then
        VER=$($cmd --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
        if [ "${VER%%.*}" -ge 3 ] && [ "${VER#*.}" -ge 12 ] 2>/dev/null; then
            PYTHON_CMD=$cmd
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}❌ 需要 Python >= 3.12，未找到。${NC}"
    echo "   安装方法：https://www.python.org/downloads/"
    exit 1
fi
echo -e "${GREEN}✅ $PYTHON_CMD ($($PYTHON_CMD --version))${NC}"

# ═══════════════════════════════════════════════════
# 2. uv 安装
# ═══════════════════════════════════════════════════
echo ""
echo -e "${YELLOW}[2/6] 检查 uv...${NC}"
if ! command -v uv &>/dev/null; then
    echo "📥 安装 uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv &>/dev/null; then
        echo -e "${RED}❌ uv 安装失败：https://docs.astral.sh/uv/${NC}"
        exit 1
    fi
fi
echo -e "${GREEN}✅ uv $(uv --version)${NC}"

# ═══════════════════════════════════════════════════
# 3. Python 依赖
# ═══════════════════════════════════════════════════
echo ""
echo -e "${YELLOW}[3/6] 安装 Python 依赖...${NC}"
uv sync
echo -e "${GREEN}✅ Python 依赖已就绪${NC}"

# ═══════════════════════════════════════════════════
# 3b. 数据库迁移（阶段7d）
# ═══════════════════════════════════════════════════
echo ""
echo "🔄 执行数据库迁移..."
if uv run alembic upgrade head 2>/dev/null; then
    echo -e "${GREEN}✅ 数据库已是最新版本${NC}"
else
    echo -e "${YELLOW}⚠️  Alembic 迁移跳过（首次启动时会自动建表）${NC}"
fi

# ═══════════════════════════════════════════════════
# 4. Node.js + 前端构建
# ═══════════════════════════════════════════════════
echo ""
echo -e "${YELLOW}[4/6] 构建前端...${NC}"
FRONTEND_DIR="packages/frontend"
if [ -f "$FRONTEND_DIR/package.json" ]; then
    cd "$FRONTEND_DIR"
    if ! command -v npm &>/dev/null; then
        echo -e "${YELLOW}⚠️  npm 未安装，跳过前端构建${NC}"
        echo "   前端开发：cd packages/frontend && npm run dev"
        echo "   安装 Node.js：https://nodejs.org/ 或 brew install node"
    else
        npm install --silent 2>/dev/null || npm install
        npm run build --silent 2>/dev/null || npm run build
        echo -e "${GREEN}✅ 前端已构建 → ${FRONTEND_DIR}/dist/${NC}"
    fi
    cd "$PROJECT_ROOT"
else
    echo -e "${YELLOW}⚠️  未找到前端项目，跳过${NC}"
fi

# ═══════════════════════════════════════════════════
# 5. Claude Code 检查（可选，编码委托用）
# ═══════════════════════════════════════════════════
echo ""
echo -e "${YELLOW}[5/6] 检查可选工具...${NC}"
if command -v claude &>/dev/null; then
    echo -e "${GREEN}✅ Claude Code 已安装 ($(claude --version 2>&1 | head -1))${NC}"
    echo "   昔涟可以委托编码任务给 Claude Code"
else
    echo -e "${YELLOW}⚪ Claude Code 未安装（可选）${NC}"
    echo "   安装：npm install -g @anthropic-ai/claude-code"
    echo "   编码委托功能需要它才能工作"
fi

# ═══════════════════════════════════════════════════
# 6. .env 引导
# ═══════════════════════════════════════════════════
echo ""
echo -e "${YELLOW}[6/6] 检查 .env...${NC}"
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "${YELLOW}⚠️  .env 已从 .env.example 创建，请编辑填入 API Key${NC}"
    else
        cat > .env << 'ENVEOF'
# 昔涟 V3.3 环境变量
# 必填：至少配置 DEEPSEEK_API_KEY

# DeepSeek V4-Pro（核心对话）
DEEPSEEK_API_KEY=sk-your-key-here
DEEPSEEK_API_KEY_2=sk-your-backup-key-here

# 嵌入 API（硅基流动 bge-m3）
EMBED_API_KEY=sk-your-embed-key
EMBED_BASE_URL=https://api.siliconflow.cn/v1
EMBED_MODEL=BAAI/bge-m3

# HTTP 服务
HTTP_PORT=8000
BIND_HOST=127.0.0.1
ENVEOF
        echo -e "${YELLOW}⚠️  .env 已创建，请编辑填入 API Key${NC}"
    fi
    echo -e "${YELLOW}   vi .env${NC}"
else
    echo -e "${GREEN}✅ .env 已存在${NC}"
fi

# ═══════════════════════════════════════════════════
# 完成
# ═══════════════════════════════════════════════════
echo ""
echo -e "${MAGENTA}╭──────────────────────────────────────╮${NC}"
echo -e "${MAGENTA}│  ✨  安装完成！                        │${NC}"
echo -e "${MAGENTA}│                                      │${NC}"
echo -e "${MAGENTA}│  启动：uv run python main.py         │${NC}"
echo -e "${MAGENTA}│  或：  bash scripts/start.sh         │${NC}"
echo -e "${MAGENTA}│                                      │${NC}"
echo -e "${MAGENTA}│  浏览器打开 http://localhost:8000     │${NC}"
echo -e "${MAGENTA}╰──────────────────────────────────────╯${NC}"
echo ""
echo -e "${CYAN}💡 提示：${NC}"
echo "   纯终端模式: NO_HTTP=1 uv run python main.py"
echo "   局域网访问: BIND_HOST=0.0.0.0 uv run python main.py"
echo "   运行测试:   uv run python -m pytest tests/ -q"
