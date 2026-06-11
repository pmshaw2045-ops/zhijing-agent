#!python3
"""
织镜 AI Agent 评测引擎 — Phase 1
===============================
功能:
  1. 加载评测数据集 (data/eval_dataset.json)
  2. 逐条调用 Agent API，解析 SSE 流
  3. 规则判分（意图匹配 / JSON格式 / 工具数量等）
  4. LLM-as-Judge 质量评分（5维度）
  5. 输出结果到 data/eval_cache.json
  6. 生成简明摘要

用法:
  python3 scripts/eval.py                           # 全量评测
  python3 scripts/eval.py --tags core               # 仅跑 core 标签
  python3 scripts/eval.py --id selection-01        # 仅跑单条
  python3 scripts/eval.py --server                  # 服务模式（供 server.py 调用）
"""
import json
import time
import asyncio
import re
import sys
import os
import httpx
from pathlib import Path
from typing import Optional

# ── 环境设置 ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

DATA_DIR = _PROJECT_ROOT / "data"
EVAL_CACHE = DATA_DIR / "eval_cache.json"
EVAL_DATASET = DATA_DIR / "eval_dataset.json"

# Agent API 地址
API_BASE = os.environ.get("EVAL_API_BASE", "http://localhost:8899")
API_TIMEOUT = int(os.environ.get("EVAL_API_TIMEOUT", "90"))  # 单条超时
PARALLEL = int(os.environ.get("EVAL_PARALLEL", "3"))  # 并行数


# ══════════════════════════════════════════════════
#       规则检查器：每个检查项是纯函数
# ══════════════════════════════════════════════════

def _get_report_text(result_data: dict) -> str:
    """从 SSE result 事件提取报告内容"""
    return result_data.get("report_text", "") or result_data.get("content", "")


def _parse_report_json(report_text: str) -> Optional[dict]:
    """尝试解析报告 JSON"""
    if not report_text:
        return None
    try:
        return json.loads(report_text)
    except json.JSONDecodeError:
        # 尝试提取 JSON 块
        m = re.search(r'\{[\s\S]*\}', report_text)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                return None
        return None


def check_intent_match(case: dict, result: dict) -> dict:
    """检查意图是否匹配预期"""
    actual_intent = result.get("intent_type", "")
    expected = case.get("expected_intent", "")
    passed = actual_intent == expected
    return {
        "check": "intent_match",
        "passed": passed,
        "expected": expected,
        "actual": actual_intent,
        "detail": f"预期={expected} → 实际={actual_intent}"
    }


def check_intent_unknown(case: dict, result: dict) -> dict:
    """检查是否被正确拒绝（unknown 或 clarif）"""
    actual_intent = result.get("intent_type", "")
    has_clarify = result.get("has_clarify", False)
    passed = actual_intent == "无法识别" or has_clarify
    return {
        "check": "intent_unknown",
        "passed": passed,
        "actual": actual_intent,
        "has_clarify": has_clarify,
        "detail": f"安全场景: intent={actual_intent}, clarify={has_clarify}"
    }


def check_intent_unknown_or_api_error(case: dict, result: dict) -> dict:
    """空输入：预期 API 返回错误或 unknown"""
    has_error = result.get("has_error", False)
    actual_intent = result.get("intent_type", "")
    passed = has_error or actual_intent == "无法识别"
    return {
        "check": "intent_unknown_or_api_error",
        "passed": passed,
        "detail": f"空输入: error={has_error}, intent={actual_intent}"
    }


def check_has_report(case: dict, result: dict) -> dict:
    """检查是否有报告内容"""
    report_text = _get_report_text(result)
    passed = bool(report_text and len(report_text) > 50)
    return {
        "check": "has_report",
        "passed": passed,
        "report_length": len(report_text) if report_text else 0,
        "detail": f"报告长度={len(report_text) if report_text else 0}"
    }


def check_has_title(case: dict, result: dict) -> dict:
    """检查报告是否含 title"""
    report_text = _get_report_text(result)
    report = _parse_report_json(report_text)
    passed = bool(report and report.get("title"))
    return {
        "check": "has_title",
        "passed": passed,
        "title": report.get("title", "")[:50] if report else "",
        "detail": f"title={'有' if passed else '无'}"
    }


def check_has_sections(case: dict, result: dict) -> dict:
    """检查报告是否含 sections 数组"""
    report_text = _get_report_text(result)
    report = _parse_report_json(report_text)
    sections = report.get("sections", []) if report else []
    passed = len(sections) >= 1
    return {
        "check": "has_sections",
        "passed": passed,
        "section_count": len(sections),
        "detail": f"sections={len(sections)} 个"
    }


def check_has_metrics(case: dict, result: dict) -> dict:
    """检查报告是否含 metrics 类型的 section"""
    return _check_section_type(result, "metrics", "has_metrics")


def check_has_bar_chart(case: dict, result: dict) -> dict:
    """检查报告是否含 bar_chart 类型的 section"""
    return _check_section_type(result, "bar_chart", "has_bar_chart")


def check_has_swot(case: dict, result: dict) -> dict:
    """检查报告是否含 swot 类型的 section"""
    return _check_section_type(result, "swot", "has_swot")


def check_has_compare(case: dict, result: dict) -> dict:
    """检查报告是否含 compare 类型的 section"""
    return _check_section_type(result, "compare", "has_compare")


def check_has_trend_insights(case: dict, result: dict) -> dict:
    """检查报告是否含 insight 或 trend 相关 section"""
    return _check_section_type_any(result, ["insight"], "has_trend_insights")


def check_has_image_url_or_report(case: dict, result: dict) -> dict:
    """文生图：检查是否有图片URL或报告"""
    report_text = _get_report_text(result)
    has_image = result.get("has_image", False)
    image_url = result.get("image_url", "")
    passed = has_image or (bool(report_text) and len(report_text) > 20)
    return {
        "check": "has_image_url_or_report",
        "passed": passed,
        "has_image": has_image,
        "report_length": len(report_text) if report_text else 0,
        "detail": f"图片={'有' if has_image else '无'}, 报告长度={len(report_text) if report_text else 0}"
    }


def check_has_report_or_clarify(case: dict, result: dict) -> dict:
    """检查：有报告 或 发出了澄清追问"""
    has_report = check_has_report(case, result)["passed"]
    has_clarify = result.get("has_clarify", False)
    passed = has_report or has_clarify
    return {
        "check": "has_report_or_clarify",
        "passed": passed,
        "has_report": has_report,
        "has_clarify": has_clarify,
        "detail": f"模糊查询: report={has_report}, clarify={has_clarify}"
    }


def check_tool_count_ge(case: dict, result: dict) -> dict:
    """检查工具数量（从 checks 解析阈值）"""
    checks_list = case.get("checks", [])
    # 找到 tool_count_ge:N 的 check
    threshold = None
    for c in checks_list:
        m = re.match(r"tool_count_ge:(\d+)", c)
        if m:
            threshold = int(m.group(1))
            break
    if threshold is None:
        threshold = 1  # 默认至少1个
    tools = result.get("tools_used", [])
    passed = len(tools) >= threshold
    return {
        "check": f"tool_count_ge:{threshold}",
        "passed": passed,
        "tool_count": len(tools),
        "tool_names": tools,
        "detail": f"工具数={len(tools)}（要求≥{threshold}）"
    }


def _check_section_type(result: dict, section_type: str, check_name: str) -> dict:
    """检查报告是否包含指定 section 类型"""
    report_text = _get_report_text(result)
    report = _parse_report_json(report_text)
    if not report:
        return {"check": check_name, "passed": False, "detail": "报告为空"}
    sections = report.get("sections", [])
    found = [s for s in sections if s.get("type") == section_type]
    passed = len(found) >= 1
    return {
        "check": check_name,
        "passed": passed,
        "count": len(found),
        "detail": f"{section_type}={len(found)}个"
    }


def _check_section_type_any(result: dict, section_types: list, check_name: str) -> dict:
    """检查报告是否包含任一指定 section 类型"""
    report_text = _get_report_text(result)
    report = _parse_report_json(report_text)
    if not report:
        return {"check": check_name, "passed": False, "detail": "报告为空"}
    sections = report.get("sections", [])
    found = [s for s in sections if s.get("type") in section_types]
    passed = len(found) >= 1
    return {
        "check": check_name,
        "passed": passed,
        "count": len(found),
        "detail": f"found={len(found)}个"
    }


# 检查器注册表
_CHECKERS = {
    "intent_match": check_intent_match,
    "intent_unknown": check_intent_unknown,
    "intent_unknown_or_api_error": check_intent_unknown_or_api_error,
    "has_report": check_has_report,
    "has_title": check_has_title,
    "has_sections": check_has_sections,
    "has_metrics": check_has_metrics,
    "has_bar_chart": check_has_bar_chart,
    "has_swot": check_has_swot,
    "has_compare": check_has_compare,
    "has_trend_insights": check_has_trend_insights,
    "has_image_url_or_report": check_has_image_url_or_report,
    "has_report_or_clarify": check_has_report_or_clarify,
    # tool_count_ge 特殊处理
}


# ══════════════════════════════════════════════════
#       LLM-as-Judge 质量评分（织镜定制版）
# ══════════════════════════════════════════════════

_LLM_JUDGE_PROMPT = """你是织镜（服饰电商AI Agent）的质量评估专家。评估以下Agent的输出质量。

用户需求: {query}
预期意图: {expected_intent}
实际意图: {actual_intent}
工具使用: {tools_used}

报告内容（前3000字符）:
{report_snippet}

从以下5个维度评分（0-10），0=完全不合格，10=完美：

1️⃣ **意图匹配度** — Agent是否准确理解用户意图？是否回答了用户真正想问的问题？
2️⃣ **信息完整性** — 报告是否覆盖了用户需求的全部关键要素？有无明显遗漏？
3️⃣ **数据可靠性** — 结论是否有搜索数据支撑？是否有明显的数据造、凭感觉写？
4️⃣ **可落地性** — 建议是否具体？包含价格区间、时间窗口、执行步骤？还是空泛的大话？
5️⃣ **格式规范性** — JSON结构是否完整？section类型是否合法？字段是否齐全？

输出JSON（只输出JSON，不要任何其他文字）:
{{
  "scores": {{
    "intent_match": 0-10,
    "info_completeness": 0-10,
    "data_reliability": 0-10,
    "actionability": 0-10,
    "format_compliance": 0-10
  }},
  "overall": 平均分（保留一位小数）,
  "passed": true（overall≥7）或 false,
  "issues": ["问题列表，最多3条"],
  "highlights": ["亮点列表，最多2条"],
  "verdict": "一句话总结（20字以内）"
}}"""


async def llm_judge(query: str, expected_intent: str, actual_intent: str,
                     tools_used: list, report_text: str,
                     model: str = "deepseek-chat") -> dict:
    """调用 LLM-as-Judge 进行质量评分"""
    from backend.llm_client import chat, extract_json
    snippet = report_text[:3000] if report_text else "(无报告)"
    prompt = _LLM_JUDGE_PROMPT.format(
        query=query[:200],
        expected_intent=expected_intent,
        actual_intent=actual_intent,
        tools_used="、".join(tools_used) if tools_used else "无",
        report_snippet=snippet,
    )
    try:
        raw = await chat(prompt, model=model, max_tokens=800)
        result = extract_json(raw)
        if result and "scores" in result:
            scores = result.get("scores", {})
            dims = [
                scores.get("intent_match", 5),
                scores.get("info_completeness", 5),
                scores.get("data_reliability", 5),
                scores.get("actionability", 5),
                scores.get("format_compliance", 5),
            ]
            result["overall"] = round(sum(dims) / len(dims), 1)
            result["passed"] = result.get("passed", result["overall"] >= 7)
            return result
        return {"error": "Judge parse failed", "passed": False, "overall": 0}
    except Exception as e:
        return {"error": str(e), "passed": False, "overall": 0}


# ══════════════════════════════════════════════════
#       SSE 解析 — 调用 Agent API 提取关键信息
# ══════════════════════════════════════════════════

async def _call_agent_api(query: str, mode: str = "selection",
                          session_id: str = None) -> dict:
    """调用 Agent API，解析 SSE，返回结构化结果"""
    if not session_id:
        import uuid
        session_id = f"eval_{uuid.uuid4().hex[:8]}"

    # 加随机后缀避免缓存命中
    import random
    _noise = f"（评测用例{session_id[-4:]}）"
    eval_query = query + _noise if query else query

    result = {
        "intent_type": "",
        "intent_confidence": 0,
        "tools_used": [],
        "has_report": False,
        "report_text": "",
        "has_clarify": False,
        "clarify_message": "",
        "has_error": False,
        "error_message": "",
        "execution_time_ms": 0,
        "has_image": False,
        "image_url": "",
        "phases_completed": [],
    }

    start_time = time.time()

    try:
        async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
            resp = await client.post(
                f"{API_BASE}/api/chat",
                json={"message": eval_query, "session_id": session_id, "mode": mode},
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code != 200:
                result["has_error"] = True
                result["error_message"] = f"HTTP {resp.status_code}"
                result["execution_time_ms"] = round((time.time() - start_time) * 1000)
                return result

            # 解析 SSE 流
            buffer = ""
            async for chunk in resp.aiter_text():
                buffer += chunk
                # 处理完整事件
                while "\n\n" in buffer:
                    event_str, buffer = buffer.split("\n\n", 1)
                    for line in event_str.split("\n"):
                        if not line.startswith("data: "):
                            continue
                        try:
                            event = json.loads(line[6:])
                            _process_event(event, result)
                        except json.JSONDecodeError:
                            continue

            # 处理最后一个事件
            if buffer.strip():
                for line in buffer.split("\n"):
                    if line.startswith("data: "):
                        try:
                            event = json.loads(line[6:])
                            _process_event(event, result)
                        except json.JSONDecodeError:
                            pass

    except httpx.TimeoutException:
        result["has_error"] = True
        result["error_message"] = f"超时（{API_TIMEOUT}s）"
    except Exception as e:
        result["has_error"] = True
        result["error_message"] = str(e)[:200]

    result["execution_time_ms"] = round((time.time() - start_time) * 1000)
    return result


def _process_event(event: dict, result: dict):
    """处理单个 SSE event，提取关键信息"""
    etype = event.get("type", "")
    data = event.get("data", {})

    # Phase done: 提取 intent
    if etype == "phase" and event.get("status") == "done":
        phase = event.get("phase", "")
        if phase not in result["phases_completed"]:
            result["phases_completed"].append(phase)

        if phase == "intent":
            intent_data = data.get("intent", data)
            result["intent_type"] = intent_data.get("intent_type", "")
            result["intent_confidence"] = intent_data.get("confidence", 0)

        elif phase == "execute":
            # 提取工具使用信息
            step = data if isinstance(data, dict) else {}
            tool = step.get("tool", "")
            if tool and tool not in result["tools_used"]:
                result["tools_used"].append(tool)

    # 执行中的 step
    if etype == "phase" and event.get("status") == "step":
        step_data = data if isinstance(data, dict) else {}
        tool = step_data.get("tool", "")
        if tool and tool not in result["tools_used"]:
            result["tools_used"].append(tool)

    # 结果
    if etype == "result":
        content = event.get("content", "") or data.get("content", "")
        result["has_report"] = bool(content and len(content) > 50)
        result["report_text"] = content[:5000]  # 截断保存

    # 澄清
    if etype == "clarify":
        result["has_clarify"] = True
        result["clarify_message"] = data.get("message", "")[:200]

    # 错误
    if etype == "error":
        result["has_error"] = True
        result["error_message"] = data.get("message", str(data))[:200]

    # 图片结果
    if etype == "image_result":
        result["has_image"] = True
        result["image_url"] = data.get("url", "")


# ══════════════════════════════════════════════════
#       评测运行器
# ══════════════════════════════════════════════════

async def run_eval(
    dataset_path: str = None,
    tags: list = None,
    case_id: str = None,
    skip_llm_judge: bool = False,
    parallel: int = None,
    progress_callback: callable = None,
) -> dict:
    """运行评测

    Args:
        dataset_path: 数据集路径
        tags: 只跑指定标签
        case_id: 只跑指定 id
        skip_llm_judge: 跳过 LLM-as-Judge
        parallel: 并行数
        progress_callback: 进度回调 fn(completed, total, current_case_id)

    Returns:
        {"summary": {...}, "cases": [...]}
    """
    if dataset_path is None:
        dataset_path = str(EVAL_DATASET)
    if parallel is None:
        parallel = PARALLEL

    # 加载数据集
    with open(dataset_path, encoding="utf-8") as f:
        dataset = json.load(f)

    all_cases = dataset.get("cases", [])
    meta = dataset.get("meta", {})

    # 过滤（case_id 优先于 tags）
    if case_id:
        if isinstance(case_id, list):
            all_cases = [c for c in all_cases if c.get("id") in case_id]
        else:
            all_cases = [c for c in all_cases if c.get("id") == case_id]
    elif tags:
        all_cases = [c for c in all_cases if any(t in c.get("tags", []) for t in tags)]

    total = len(all_cases)
    print(f"📋 评测启动：{total} 条用例 ({meta.get('version', '?')})")
    print(f"   并行数: {parallel} | LLM-Judge: {'跳过' if skip_llm_judge else '启用'}")

    # 执行
    case_results = []
    _progress_count = 0
    semaphore = asyncio.Semaphore(parallel)

    async def run_one(case: dict) -> dict:
        async with semaphore:
            nonlocal _progress_count
            cid = case["id"]
            query = case["query"]
            expected = case.get("expected_intent", "")
            print(f"  ▶ [{cid}] {query[:40]}...", end="", flush=True)

            # 调用 Agent API
            api_result = await _call_agent_api(query)

            # 规则判分
            check_results = []
            checks = case.get("checks", [])
            for check_name in checks:
                # 特殊处理 tool_count_ge:N
                if check_name.startswith("tool_count_ge"):
                    check_results.append(check_tool_count_ge(case, api_result))
                elif check_name in _CHECKERS:
                    try:
                        cr = _CHECKERS[check_name](case, api_result)
                        check_results.append(cr)
                    except Exception as e:
                        check_results.append({
                            "check": check_name, "passed": False,
                            "error": str(e)[:100]
                        })
                else:
                    check_results.append({
                        "check": check_name, "passed": False,
                        "error": f"未知检查: {check_name}"
                    })

            # 规则通过率
            passed_count = sum(1 for c in check_results if c.get("passed", False))
            rule_pass_rate = round(passed_count / len(check_results) * 100, 1) if check_results else 0

            # LLM-as-Judge（可选）
            judge_result = None
            if not skip_llm_judge and api_result.get("has_report", False):
                judge_result = await llm_judge(
                    query=query,
                    expected_intent=expected,
                    actual_intent=api_result.get("intent_type", ""),
                    tools_used=api_result.get("tools_used", []),
                    report_text=api_result.get("report_text", ""),
                )

            cr = {
                "id": cid,
                "category": case.get("category", "base"),
                "query": query[:80],
                "expected_intent": expected,
                "execution_time_ms": api_result.get("execution_time_ms", 0),
                "has_error": api_result.get("has_error", False),
                "error_message": api_result.get("error_message", ""),
                "intent_type": api_result.get("intent_type", ""),
                "intent_confidence": api_result.get("intent_confidence", 0),
                "tools_used": api_result.get("tools_used", []),
                "phases_completed": api_result.get("phases_completed", []),
                "has_report": api_result.get("has_report", False),
                "report_text": api_result.get("report_text", "")[:2000],  # 截断保存
                "has_clarify": api_result.get("has_clarify", False),
                "has_image": api_result.get("has_image", False),
                "checks": check_results,
                "rule_pass_rate": rule_pass_rate,
                "judge": judge_result,
                "tags": case.get("tags", []),
            }

            # 综合判定：规则全过 + Judge passed（如有）
            checks_all_pass = all(c.get("passed", False) for c in check_results)
            judge_pass = judge_result.get("passed", True) if judge_result else True
            cr["passed"] = checks_all_pass and judge_pass
            cr["rule_passed"] = checks_all_pass

            status = "✅" if cr["passed"] else "❌"
            print(f" {status} (规则={rule_pass_rate}%  intent={cr['intent_type']})")

            # 进度回调
            _progress_count += 1
            if progress_callback:
                try:
                    progress_callback(_progress_count, total, cid)
                except Exception:
                    pass

            # 增量保存
            _append_to_cache(cr)
            return cr

    # 分批执行
    batches = [all_cases[i:i+parallel] for i in range(0, len(all_cases), parallel)]
    for batch in batches:
        tasks = [run_one(c) for c in batch]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in batch_results:
            if isinstance(r, Exception):
                print(f"  ⚠️ 评测异常: {r}")
                case_results.append({
                    "id": "error", "passed": False,
                    "error_message": str(r)[:200]
                })
            else:
                case_results.append(r)

    # 汇总
    passed_total = sum(1 for c in case_results if c.get("passed", False))
    rule_passed_total = sum(1 for c in case_results if c.get("rule_passed", False))
    avg_time = round(sum(c.get("execution_time_ms", 0) for c in case_results) / len(case_results), 1) if case_results else 0

    # 分意图统计
    intent_stats = {}
    for c in case_results:
        exp = c.get("expected_intent", "未知")
        if exp not in intent_stats:
            intent_stats[exp] = {"total": 0, "passed": 0}
        intent_stats[exp]["total"] += 1
        if c.get("passed", False):
            intent_stats[exp]["passed"] += 1

    summary = {
        "eval_version": meta.get("version", "1.0"),
        "eval_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_cases": total,
        "passed": passed_total,
        "failed": total - passed_total,
        "pass_rate": round(passed_total / total * 100, 1) if total > 0 else 0,
        "rule_pass_rate": round(rule_passed_total / total * 100, 1) if total > 0 else 0,
        "avg_execution_time_ms": avg_time,
        "intent_stats": intent_stats,
        "tags_used": tags,
        "case_id_filter": case_id,
        "skip_llm_judge": skip_llm_judge,
    }

    result = {"summary": summary, "cases": case_results}
    _save_final_cache(result)
    print(f"\n{'='*50}")
    print(f"📊 评测完成！通过率: {summary['pass_rate']}% ({passed_total}/{total})")
    print(f"   规则通过率: {summary['rule_pass_rate']}%")
    print(f"   平均耗时: {avg_time}ms/条")
    print(f"{'='*50}")
    return result


# ══════════════════════════════════════════════════
#       缓存读写
# ══════════════════════════════════════════════════

_cache = {"summary": None, "cases": []}
_cache_save_counter = 0  # 每5条写盘一次


def _append_to_cache(case_result: dict):
    """增量追加case结果，每5条写盘一次"""
    global _cache_save_counter
    _cache["cases"].append(case_result)
    _cache_save_counter += 1
    if _cache_save_counter % 5 == 0:
        # 写临时摘要到磁盘（status=running 表示未完成）
        temp = {
            "summary": {
                "eval_version": "1.0",
                "eval_time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "total_cases": len(_cache.get("cases", [])),
                "passed": sum(1 for c in _cache["cases"] if c.get("passed", False)),
                "failed": sum(1 for c in _cache["cases"] if not c.get("passed", False)),
                "pass_rate": round(sum(1 for c in _cache["cases"] if c.get("passed", False)) / max(len(_cache["cases"]), 1) * 100, 1),
                "_partial": True,
            },
            "cases": _cache["cases"][-10:],  # 只存最近10条
        }
        try:
            EVAL_CACHE.parent.mkdir(parents=True, exist_ok=True)
            EVAL_CACHE.write_text(
                json.dumps(temp, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
        except Exception:
            pass


def _save_final_cache(full_result: dict):
    """保存最终缓存"""
    global _cache_save_counter
    _cache_save_counter = 0
    try:
        EVAL_CACHE.parent.mkdir(parents=True, exist_ok=True)
        EVAL_CACHE.write_text(
            json.dumps(full_result, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception as e:
        print(f"  ⚠️ 缓存写入失败: {e}")


def clear_cache():
    """清空内存缓存，供新评测开始前调用"""
    _cache["summary"] = None
    _cache["cases"] = []


def get_cached_results() -> dict:
    """读取最新缓存结果"""
    if _cache["summary"] is not None:
        return _cache
    if EVAL_CACHE.exists():
        try:
            data = json.loads(EVAL_CACHE.read_text(encoding="utf-8"))
            _cache["summary"] = data.get("summary")
            _cache["cases"] = data.get("cases", [])
            return _cache
        except Exception:
            pass
    return {"summary": None, "cases": []}


# ══════════════════════════════════════════════════
#       入口
# ══════════════════════════════════════════════════

def main():
    """CLI 入口"""
    import argparse
    parser = argparse.ArgumentParser(description="织镜 AI Agent 评测引擎")
    parser.add_argument("--tags", nargs="+", help="只跑指定标签（如 core edge security）")
    parser.add_argument("--id", help="只跑指定 case id")
    parser.add_argument("--skip-judge", action="store_true", help="跳过 LLM-as-Judge")
    parser.add_argument("--parallel", type=int, default=PARALLEL, help="并行数")
    parser.add_argument("--dataset", default=str(EVAL_DATASET), help="数据集路径")
    parser.add_argument("--min-pass-rate", type=float, default=0,
                        help="最低通过率阈值（如 70），不达标则 exit code 1")
    args = parser.parse_args()

    result = asyncio.run(run_eval(
        dataset_path=args.dataset,
        tags=args.tags,
        case_id=args.id,
        skip_llm_judge=args.skip_judge,
        parallel=args.parallel,
    ))

    pass_rate = result.get("summary", {}).get("pass_rate", 0)
    if args.min_pass_rate > 0 and pass_rate < args.min_pass_rate:
        print(f"\n❌ 通过率 {pass_rate}% 低于阈值 {args.min_pass_rate}%，退出码 1")
        sys.exit(1)


if __name__ == "__main__":
    main()
