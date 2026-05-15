#!/usr/bin/env bash
# 昔涟 V3.3 · 安装脚本
# 用法：bash scripts/setup.sh
set -euo pipefail

# ═══════════════════════════════════════════════════
# 颜色
# ═══════════════════════════════════════════════════
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

# ═══════════════════════════════════════════════════
# 0. 定位项目根目录
# ═══════════════════════════════════════════════════
cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)
echo -e "${CYAN}📂 项目目录：${PROJECT_ROOT}${NC}"

# ═══════════════════════════════════════════════════
# 1. Python 检查
# ═══════════════════════════════════════════════════
echo ""
echo -e "${YELLOW}[1/5] 检查 Python...${NC}"
PYTHON_CMD=""
for cmd in python3.12 python3 python; do
    if command -v $cmd &>/dev/null; then
        VER=$($cmd --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
        if [ "$(echo "$VER >= 3.12" | bc 2>/dev/null || echo 0)" = "1" ] || [ "${VER%%.*}" -ge 3 ] && [ "${VER#*.}" -ge 12 ]; then
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
echo -e "${YELLOW}[2/5] 检查 uv...${NC}"
if ! command -v uv &>/dev/null; then
    echo "📥 安装 uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv &>/dev/null; then
        echo -e "${RED}❌ uv 安装失败，请手动安装：https://docs.astral.sh/uv/${NC}"
        exit 1
    fi
fi
echo -e "${GREEN}✅ uv $(uv --version)${NC}"

# ═══════════════════════════════════════════════════
# 3. Python 依赖
# ═══════════════════════════════════════════════════
echo ""
echo -e "${YELLOW}[3/5] 安装 Python 依赖...${NC}"
uv sync
echo -e "${GREEN}✅ Python 依赖已就绪${NC}"

# ═══════════════════════════════════════════════════
# 4. 前端构建
# ═══════════════════════════════════════════════════
echo ""
echo -e "${YELLOW}[4/5] 构建前端...${NC}"
FRONTEND_DIR="packages/frontend"
if [ -f "$FRONTEND_DIR/package.json" ]; then
    cd "$FRONTEND_DIR"
    if ! command -v npm &>/dev/null; then
        echo -e "${YELLOW}⚠️  npm 未安装，跳过前端构建${NC}"
        echo "   前端开发需手动运行：cd packages/frontend && npm run dev"
    else
        npm install --silent
        npm run build --silent
        echo -e "${GREEN}✅ 前端已构建 → ${FRONTEND_DIR}/dist/${NC}"
    fi
    cd "$PROJECT_ROOT"
else
    echo -e "${YELLOW}⚠️  未找到前端项目，跳过${NC}"
fi

# ═══════════════════════════════════════════════════
# 5. .env 引导
# ═══════════════════════════════════════════════════
echo ""
echo -e "${YELLOW}[5/5] 检查 .env...${NC}"
if [ ! -f ".env" ]; then
    echo "📝 创建 .env 模板..."
    cat > .env << 'ENVEOF'
# 昔涟 V3.3 环境变量
# 必填：至少配置一个 API Key

# DeepSeek V4-Pro（核心对话，至少一个）
DEEPSEEK_API_KEY=sk-your-key-here
# DEEPSEEK_API_KEY_2=sk-your-second-key   # 可选，双Key轮询

# 嵌入 API（硅基流动 bge-m3，开源免费额度可用）
EMBED_API_KEY=sk-your-key-here
EMBED_BASE_URL=https://api.siliconflow.cn/v1

# 可选配置
# BIND_HOST=0.0.0.0          # 局域网访问
# HTTP_PORT=8000              # HTTP 端口
# FRONTEND_DEV=1              # 开发模式（前端独立 Vite HMR）
# NO_HTTP=1                   # 禁用 HTTP 通道（仅终端）
ENVEOF
    echo -e "${YELLOW}⚠️  .env 已创建，请编辑填入 API Key 后重新运行${NC}"
    echo -e "${YELLOW}   vi .env${NC}"
else
    echo -e "${GREEN}✅ .env 已存在${NC}"
fi

# ═══════════════════════════════════════════════════
# 完成
# ═══════════════════════════════════════════════════
echo ""
echo -e "${MAGENTA}╭────────────────────────────────╮${NC}"
echo -e "${MAGENTA}│  ✨  安装完成！                    │${NC}"
echo -e "${MAGENTA}│                                  │${NC}"
echo -e "${MAGENTA}│  启动：uv run python main.py     │${NC}"
echo -e "${MAGENTA}│  或：  bash scripts/start.sh     │${NC}"
echo -e "${MAGENTA}╰────────────────────────────────╯${NC}"
