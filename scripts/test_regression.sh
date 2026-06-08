#!/bin/bash
# ============================================================
# 织镜 ZHÌJÌNG — 回归测试脚本
# 用法: bash test_regression.sh
# 覆盖: 健康检查、认证、速率限制、指标、7种意图、文生图
# ============================================================
set -e

BASE="http://localhost:8899"
PASS=0
FAIL=0
TOTAL=0

pass() { PASS=$((PASS+1)); TOTAL=$((TOTAL+1)); echo "  ✅ $1"; }
fail() { FAIL=$((FAIL+1)); TOTAL=$((TOTAL+1)); echo "  ❌ $1 — $2"; }

echo "═══════════════════════════════════════"
echo "  织镜 回归测试"
echo "═══════════════════════════════════════"
echo ""

# ── 1. 基础设施 ──
echo "── 基础设施 ──"

# 1.1 健康检查
s=$(curl -s -o /dev/null -w "%{http_code}" $BASE/api/health)
[ "$s" = "200" ] && pass "健康检查" || fail "健康检查" "HTTP $s"

# 1.2 未认证访问 (dev模式)
s=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/api/chat \
  -H 'Content-Type: application/json' -d '{"message":"测试"}')
[ "$s" = "200" ] && pass "Dev模式无Token" || fail "Dev模式无Token" "HTTP $s"

# 1.3 错误Token = 401
s=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/api/chat \
  -H 'Content-Type: application/json' -H 'Authorization: *** \
  -d '{"message":"测试"}')
[ "$s" = "401" ] && pass "错误Token=401" || fail "错误Token=401" "HTTP $s"

# 1.4 指标端点
s=$(curl -s -o /dev/null -w "%{http_code}" $BASE/api/metrics)
[ "$s" = "200" ] && pass "指标端点" || fail "指标端点" "HTTP $s"

# ── 2. 意图回归 (只测关键3个，节省时间) ──
echo ""
echo "── 意图回归 ──"

test_intent() {
    local name=$1 msg=$2
    local tmp=$(mktemp)
    local code=$(curl -s -w "%{http_code}" -o "$tmp" -X POST $BASE/api/chat \
        -H 'Content-Type: application/json' \
        -d "{\"message\":\"$msg\",\"session_id\":\"reg_${name}\"}" \
        --max-time 180 2>/dev/null)
    if [ "$code" != "200" ]; then
        fail "$name" "HTTP $code"
        rm -f "$tmp"
        return
    fi
    # 检查输出是否含 result 或 image_result 事件
    if grep -q '"type":"result"' "$tmp" 2>/dev/null; then
        pass "$name"
    elif grep -q '"type":"image_result"' "$tmp" 2>/dev/null; then
        pass "$name (图片)"
    elif grep -q '"type":"clarify"' "$tmp" 2>/dev/null; then
        fail "$name" "触发了澄清（prompt 信息不足）"
    else
        fail "$name" "无 result/image_result/clarify 事件"
    fi
    rm -f "$tmp"
}

test_intent "选品分析" "分析2025夏季法式茶歇裙在天猫淘宝的选品机会，关注价格带和趋势"
test_intent "趋势洞察" "2025夏季连衣裙流行趋势洞察，重点关注面料和廓形"
test_intent "文案生成" "生成法式茶歇裙的淘宝标题和详情页卖点文案，突出V领收腰设计"
test_intent "竞品对标" "太平鸟和伊芙丽连衣裙竞品对比，分析价格策略和差异化定位"
test_intent "定价策略" "2025夏季连衣裙在天猫的定价策略分析，考虑成本利润"
test_intent "文生图" "生成一张图片：法式碎花茶歇裙产品摄影图，V领收腰，纯白背景"

# ── 3. 速率限制验证 ──
echo ""
echo "── 速率限制 ──"
# 快速连续发5个请求，确认不会触发429 (dev默认60rpm)
RATE_OK=true
for i in 1 2 3 4 5; do
    s=$(curl -s -o /dev/null -w "%{http_code}" -X POST $BASE/api/chat \
        -H 'Content-Type: application/json' \
        -d '{"message":"你好","session_id":"rate_test"}' --max-time 5 2>/dev/null)
    if [ "$s" = "429" ]; then RATE_OK=false; break; fi
done
$RATE_OK && pass "速率限制(5连发未触发429)" || fail "速率限制" "正常请求被限流"

# ── 汇总 ──
echo ""
echo "═══════════════════════════════════════"
echo "  通过: $PASS / $TOTAL"
if [ $FAIL -gt 0 ]; then
    echo "  ❌ 失败: $FAIL"
    exit 1
else
    echo "  ✅ 全部通过"
    exit 0
fi
echo "═══════════════════════════════════════"
