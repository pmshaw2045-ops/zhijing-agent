#!/bin/bash
# ============================================================
# 织镜 Fashion Agent — 密钥迁移脚本
# 从 ~/.hermes/.env 提取所需密钥写入项目 .env
# ============================================================
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
HERMES_ENV="$HOME/.hermes/.env"
TARGET="$PROJECT_DIR/.env"

echo "织镜密钥迁移"
echo "源: $HERMES_ENV"
echo "目标: $TARGET"
echo ""

if [ ! -f "$HERMES_ENV" ]; then
    echo "❌ 未找到 ~/.hermes/.env，请先配置 Hermes Agent"
    exit 1
fi

# 需要的密钥清单
KEYS=(
    DEEPSEEK_API_KEY
    ARK_API_KEY
    TAVILY_API_KEY
    BOCHA_API_KEY
)

# 生成 .env 文件头
cat > "$TARGET" << 'HEADER'
# ============================================================
# 织镜 Fashion Agent — 环境变量
# 自动生成于: $(date)
# 云部署: 直接设置环境变量即可，无需此文件
# ============================================================

HEADER

MISSING=()
for key in "${KEYS[@]}"; do
    # 从 hermes .env 提取值
    val=$(grep "^${key}=" "$HERMES_ENV" | head -1 | cut -d'=' -f2- | sed 's/^["'\'']//;s/["'\'']$//')
    if [ -n "$val" ] && [ "$val" != "***" ]; then
        echo "${key}=${val}" >> "$TARGET"
        echo "  ✅ ${key}"
    else
        MISSING+=("$key")
        echo "# ${key}=<请手动填写>" >> "$TARGET"
        echo "  ⚠️  ${key} — 未找到，请手动填写"
    fi
done

echo ""
echo "已写入: $TARGET"

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "以下密钥需手动填写:"
    for k in "${MISSING[@]}"; do
        echo "  - $k"
    done
fi

echo ""
echo "下一步: cd $PROJECT_DIR && pip install python-dotenv && python -m uvicorn backend.server:app --port 8899"
