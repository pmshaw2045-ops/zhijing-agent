#!python3
"""CI 评测摘要生成器 — 从 eval_cache.json 生成文本报告"""
import json
import sys
from pathlib import Path

cache_path = Path("data/eval_cache.json")
if not cache_path.exists():
    print("⚠️  eval_cache.json not found — no eval results to report")
    sys.exit(0)

with open(cache_path) as f:
    data = json.load(f)

s = data.get("summary", {})
cases = data.get("cases", [])

print("=" * 52)
print(f"  EVAL REPORT — {s.get('eval_time', '?')}")
print("=" * 52)

pr = s.get("pass_rate", 0)
total = s.get("total_cases", 0)
passed = s.get("passed", 0)
print(f"  Pass Rate:  {pr}% ({passed}/{total})")
print(f"  Avg Time:   {s.get('avg_execution_time_ms', 0)}ms")
print()

# 分意图
intent_stats = s.get("intent_stats", {})
if intent_stats:
    print("  By Intent:")
    for name in sorted(intent_stats.keys()):
        st = intent_stats[name]
        rate = round(st["passed"] / st["total"] * 100)
        bar = "█" * (rate // 10) + "░" * (10 - rate // 10)
        print(f"    {bar}  {name:12s}  {rate:3d}%  ({st['passed']}/{st['total']})")
    print()

# 失败 case
failed = [c for c in cases if not c.get("passed")]
if failed:
    print(f"  Failed ({len(failed)}):")
    for c in failed:
        fails = [ch["check"] for ch in c.get("checks", []) if not ch.get("passed")]
        print(f"    ❌ {c['id']}: {c.get('intent_type','?')} — {', '.join(fails[:3])}")
else:
    print("  All cases passed! 🎉")

print("=" * 52)
