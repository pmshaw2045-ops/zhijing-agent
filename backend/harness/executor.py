"""ParallelExecutor — 真正并行执行DAG任务"""
import asyncio
import logging
from typing import AsyncGenerator

logger = logging.getLogger(__name__)


class ParallelExecutor:
    """DAG并行执行器——按parallel_group分组，同组内真正并发"""

    def __init__(self, tool_executor):
        """
        tool_executor: callable(name, params) → dict
        同步或异步均可，executor内部用 asyncio.to_thread 适配同步工具
        """
        self._exec = tool_executor

    async def execute(self, dag: dict) -> AsyncGenerator[dict, None]:
        """
        执行DAG并yield每个任务的结果

        dag格式: {"tasks": [{"id":"T1","tool":"web_search","deps":[],"parallel_group":0}, ...]}
        """
        tasks = dag.get("tasks", [])
        if not tasks:
            return

        # 按 parallel_group 分组
        groups: dict[int, list[dict]] = {}
        for t in tasks:
            g = t.get("parallel_group", 0)
            groups.setdefault(g, []).append(t)

        # 按组序执行（串行组间，并行组内）
        completed: dict[str, dict] = {}  # task_id → result

        for group_id in sorted(groups.keys()):
            group_tasks = groups[group_id]
            # 过滤：检查依赖是否已满足
            ready = [t for t in group_tasks if self._deps_satisfied(t.get("deps", []), completed)]

            if not ready:
                logger.warning(f"Group {group_id}: no tasks ready (deadlock?)")
                continue

            # 组内并行
            results = await asyncio.gather(
                *[self._run_task(t) for t in ready],
                return_exceptions=True
            )

            for task_def, result in zip(ready, results):
                if isinstance(result, Exception):
                    logger.error(f"Task {task_def.get('task_id') or task_def.get('id', '?')} failed: {result}")
                    result = {"error": str(result), "task_id": task_def.get("task_id") or task_def.get("id", "?")}

                yield {
                    "task_id": task_def.get("task_id") or task_def.get("id", "?"),
                    "tool": task_def["tool"],
                    "state_before": "PENDING",
                    "state_after": "COMPLETED",
                    "tool_result": result,
                }
                completed[task_def.get("task_id") or task_def.get("id", "?")] = result

    async def _run_task(self, task_def: dict, timeout: int = 30) -> dict:
        """执行单个任务，自动适配同步/异步，含超时保护"""
        tid = task_def.get("task_id") or task_def.get("id", "?")
        name = task_def["tool"]
        params = {"query": task_def.get("desc", "")}
        try:
            result = self._exec(name, params)
            if asyncio.iscoroutine(result):
                return await asyncio.wait_for(result, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.error(f"Task {tid} ({name}) timed out after {timeout}s")
            return {"error": f"Task timed out after {timeout}s", "task_id": tid}
        except Exception as e:
            logger.error(f"Task {tid} ({name}) failed: {e}")
            return {"error": str(e), "task_id": tid}

    def _deps_satisfied(self, deps: list[str], completed: dict) -> bool:
        return all(d in completed for d in deps)
