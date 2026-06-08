#!/bin/bash
# ============================================================
# restart.sh — 织镜服务重启脚本（带洁净启动自检）
# ============================================================
# 作用：
#   1. 强制杀死旧进程
#   2. 清除所有 __pycache__ 字节码缓存
#   3. 确认端口释放
#   4. 启动新服务
#   5. 运行健康检查 + 启动自检
#   6. 检测 decompose 是否正常
# ============================================================
set -eo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8899}"
LOG_LEVEL="${LOG_LEVEL:-info}"

echo ""
echo "========================================"
echo "  织镜 ZHÌJÌNG — 洁净重启"
echo "========================================"

# Step 1: Kill old process
echo ""
echo "[1/6] 杀死旧进程..."
OLD_PID=$(lsof -ti:"$PORT" 2>/dev/null || true)
if [ -n "$OLD_PID" ]; then
    echo "  旧进程 PID: $OLD_PID"
    kill -9 "$OLD_PID" 2>/dev/null || true
    sleep 1
    if lsof -ti:"$PORT" >/dev/null 2>&1; then
        echo "  ⚠️  端口 $PORT 仍未释放，再等 2 秒..."
        sleep 2
        lsof -ti:"$PORT" | xargs kill -9 2>/dev/null || true
        sleep 1
    fi
    echo "  ✅ 旧进程已终止"
else
    echo "  无旧进程 (端口 $PORT 未占用)"
fi

# Step 2: Clear __pycache__
echo ""
echo "[2/6] 清除 Python 字节码缓存..."
PYCACHE_COUNT=$(find "$PROJECT_DIR/backend" -name __pycache__ -type d 2>/dev/null | wc -l | tr -d ' ')
find "$PROJECT_DIR/backend" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
echo "  已清除 $PYCACHE_COUNT 个 __pycache__ 目录"

# Step 3: Verify port
echo ""
echo "[3/6] 确认端口可用..."
if lsof -ti:"$PORT" >/dev/null 2>&1; then
    echo "  ❌ 端口 $PORT 仍被占用！"
    echo "  手动: lsof -ti:$PORT | xargs kill -9"
    exit 1
fi
echo "  ✅ 端口 $PORT 可用"

# Step 4: Start server
echo ""
echo "[4/6] 启动服务 (uvicorn backend.server:app --port $PORT)..."
cd "$PROJECT_DIR"
python3 -m uvicorn backend.server:app \
    --host 0.0.0.0 \
    --port "$PORT" \
    --log-level "$LOG_LEVEL" &
PID=$!
echo "  PID: $PID"
echo "  等待就绪..."

for i in $(seq 1 20); do
    sleep 1
    if curl -sf "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
        echo "  ✅ 服务就绪 (${i}s)"
        break
    fi
    if [ "$i" -eq 20 ]; then
        echo "  ❌ 服务启动超时！"
        echo "  手动: cd $PROJECT_DIR && python3 -m uvicorn backend.server:app --host 0.0.0.0 --port $PORT"
        exit 1
    fi
done

# Step 5: Health check
echo ""
echo "[5/6] 健康检查..."
HEALTH=$(curl -sf "http://localhost:$PORT/api/health" 2>/dev/null || echo '{"status":"fail"}')
echo "  Health: $HEALTH"

# Step 6: Verify decompose engine
echo ""
echo "[6/6] 验证 decompose 引擎..."
VERIFY=$(python3 -c "
import sys, json, asyncio
sys.path.insert(0, '$PROJECT_DIR/backend')
from decompose_engine import DecomposeEngine
from harness.dag_loader import DAGLoader

async def check():
    engine = DecomposeEngine(DAGLoader())
    intent = {'intent_type': '单品选品分析', 'goal': {'品类': '连衣裙'}}
    p = engine.build_prompt(intent, 'selection')
    if len(p) < 800:
        return json.dumps({'status': 'WARN', 'message': f'prompt only {len(p)} chars'})
    return json.dumps({'status': 'OK', 'prompt_len': len(p)})

print(asyncio.run(check()))
" 2>/dev/null) || echo '{"status":"FAIL","message":"script error"}'
echo "  Decompose: $VERIFY"

# Final status
echo ""
echo "========================================"
if echo "$VERIFY" | grep -qE '"status"\s*:\s*"OK"'; then
    echo "  ✅ 洁净重启完成"
    echo "  ➜  http://localhost:$PORT"
else
    echo "  ⚠️  服务已启动，但 decompose 验证异常"
    echo "  ➜  http://localhost:$PORT"
    echo "  ➜  请检查: $VERIFY"
fi
echo "========================================"
echo ""
