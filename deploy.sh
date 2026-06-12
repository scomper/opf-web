#!/bin/bash
# OPF 隐私信息检测平台 — 一键部署 / 升级脚本
# 自动检测：首次安装 → 直接部署 | 已有旧版 → 备份 → 升级

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "========================================"
echo "  OPF 隐私信息检测平台"
echo "========================================"
echo ""

# ─── 检测环境 ─────────────────────────────────────────────────────
if ! command -v docker &> /dev/null; then
    echo "❌ 未检测到 Docker，请先安装："
    echo "   macOS:   https://docs.docker.com/desktop/install/mac-install/"
    echo "   Windows: https://docs.docker.com/desktop/install/windows-install/"
    echo "   Linux:   https://docs.docker.com/engine/install/"
    exit 1
fi

if ! docker info &> /dev/null 2>&1; then
    echo "❌ Docker 未启动，请先启动 Docker Desktop"
    exit 1
fi

echo "✅ Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null)"

TOTAL_MEM=$(docker system info --format '{{.MemTotal}}' 2>/dev/null || echo 0)
TOTAL_MEM_GB=$((TOTAL_MEM / 1073741824))
if [ "$TOTAL_MEM_GB" -lt 12 ]; then
    echo "⚠️  内存 ${TOTAL_MEM_GB}GB，建议 16GB+（Docker Desktop → Settings → Resources）"
    read -p "   继续？(y/N) " -n 1 -r; echo
    [[ ! $REPLY =~ ^[Yy]$ ]] && exit 1
else
    echo "✅ 内存 ${TOTAL_MEM_GB}GB"
fi

# ─── 检测是否已有旧版本 ───────────────────────────────────────────
IS_UPGRADE=false
EXISTING_IMAGES=$(docker images --format "{{.Repository}}" 2>/dev/null | grep -c "opf-web" || true)
EXISTING_CONTAINERS=$(docker ps -a --format "{{.Names}}" 2>/dev/null | grep -c "opf-web" || true)
HAS_WHITELIST=false
if [ -d "$SCRIPT_DIR/whitelist" ] && [ "$(ls -A "$SCRIPT_DIR/whitelist"/*.json 2>/dev/null)" ]; then
    HAS_WHITELIST=true
fi

if [ "$EXISTING_IMAGES" -gt 0 ] || [ "$EXISTING_CONTAINERS" -gt 0 ]; then
    IS_UPGRADE=true
fi

echo ""
if [ "$IS_UPGRADE" = true ]; then
    echo "🔄 检测到旧版本，进入升级模式"
    [ "$EXISTING_IMAGES" -gt 0 ] && echo "   镜像: ${EXISTING_IMAGES} 个"
    [ "$EXISTING_CONTAINERS" -gt 0 ] && echo "   容器: ${EXISTING_CONTAINERS} 个"
else
    echo "🆕 首次安装"
fi

# ─── 升级：自动备份 ───────────────────────────────────────────────
BACKUP_DIR=""
if [ "$IS_UPGRADE" = true ] && [ "$HAS_WHITELIST" = true ]; then
    BACKUP_DIR="$SCRIPT_DIR/whitelist_backup_$(date +%Y%m%d_%H%M%S)"
    echo ""
    echo "📦 自动备份白名单和敏感词库..."
    mkdir -p "$BACKUP_DIR"
    for f in "$SCRIPT_DIR/whitelist"/*.json; do
        fname=$(basename "$f")
        # 跳过缓存文件
        if [ "$fname" = "scan_cache.json" ]; then continue; fi
        cp "$f" "$BACKUP_DIR/$fname"
        echo "   ✅ $fname"
    done
    echo "   备份位置: $BACKUP_DIR"
fi

# ─── 升级：停止旧容器 ─────────────────────────────────────────────
if [ "$IS_UPGRADE" = true ]; then
    echo ""
    echo "🛑 停止旧容器..."
    docker compose down 2>/dev/null || true
    echo "   ✅ 已停止"
fi

# ─── 检查 OPF 模型 ────────────────────────────────────────────────
MODEL_DIR="$HOME/.opf/privacy_filter"
echo ""
if [ -f "$MODEL_DIR/model.safetensors" ]; then
    echo "✅ OPF 模型已存在"
else
    if [ -f "$SCRIPT_DIR/model/model.safetensors" ]; then
        echo "📥 从部署包复制 OPF 模型..."
        mkdir -p "$MODEL_DIR"
        cp "$SCRIPT_DIR/model/"* "$MODEL_DIR/"
        echo "   ✅ 已复制到 $MODEL_DIR"
    else
        echo "📥 下载 OPF 模型（~2.8GB）..."
        pip install -q huggingface_hub 2>/dev/null || pip3 install -q huggingface_hub
        python3 -c "
from huggingface_hub import snapshot_download
snapshot_download('openai/privacy_filter', local_dir='$MODEL_DIR', local_dir_use_symlinks=False)
"
        echo "   ✅ 下载完成"
    fi
fi

# ─── 构建并启动 ────────────────────────────────────────────────────
echo ""
if [ "$IS_UPGRADE" = true ]; then
    echo "🔨 重建容器并启动..."
else
    echo "🔨 构建容器（首次约 5-10 分钟）..."
fi
docker compose up --build -d

# ─── 升级：恢复备份 ───────────────────────────────────────────────
if [ -n "$BACKUP_DIR" ] && [ -d "$BACKUP_DIR" ]; then
    echo ""
    echo "📦 恢复白名单和敏感词库..."
    for f in "$BACKUP_DIR"/*.json; do
        fname=$(basename "$f")
        cp "$f" "$SCRIPT_DIR/whitelist/$fname"
        echo "   ✅ $fname"
    done
fi

# ─── 等待启动 ─────────────────────────────────────────────────────
echo ""
echo "   等待服务启动..."
sleep 10

# ─── 验证 ──────────────────────────────────────────────────────────
WEB_PORT=${WEB_PORT:-8081}
if curl -s -o /dev/null -w "%{http_code}" "http://localhost:$WEB_PORT/" 2>/dev/null | grep -q "200"; then
    echo ""
    echo "========================================"
    if [ "$IS_UPGRADE" = true ]; then
        echo "  ✅ 升级完成！"
    else
        echo "  ✅ 安装完成！"
    fi
    echo ""
    echo "  打开浏览器访问：http://localhost:$WEB_PORT"
    echo ""
    echo "  管理命令："
    echo "    启动：docker compose up -d"
    echo "    停止：docker compose down"
    echo "    重启：docker compose restart"
    echo "    日志：docker compose logs -f"
    echo "========================================"
else
    echo ""
    echo "⚠️  服务启动中，30 秒后访问 http://localhost:$WEB_PORT"
fi
