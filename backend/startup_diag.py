"""
startup_diag.py — 服务启动自检

在服务启动时自动检测：
1. 模块 .py / .pyc 版本一致性（防止旧进程用旧字节码）
2. 关键函数签名完整性（防止接口变更导致运行时崩溃）
3. LLM 客户端连通性（可选）

调用方式：被 server.py lifespan 导入调用，或独立运行 python -m backend.startup_diag
"""
from __future__ import annotations
import importlib
import inspect
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("startup_diag")

# ============================================================
# 关键模块清单 — 检查这些文件的 .py / .pyc 一致性
# ============================================================
CRITICAL_MODULES = [
    "decompose_engine",
    "llm_client",
    "intent_registry",
    "agent_engine",
    "report",
    "precheck",
    "memory",
    "intent",
]

# 关键函数白名单 — 检查这些函数的参数签名
SIGNATURE_CHECKS: dict[str, list[dict[str, Any]]] = {
    "llm_client": [
        {
            "func": "chat",
            "must_have_params": ["json_mode"],
            "must_not_miss": ["json_mode"],  # 参数必须存在（不能只定义在父类）
        },
    ],
    "decompose_engine": [
        {
            "func": "DecomposeEngine.decompose",
            "must_have_params": [],  # 无特殊要求
        },
    ],
}


def _get_module_path(module_name: str) -> Path | None:
    """获取模块 .py 的绝对路径"""
    if module_name in sys.modules:
        mod = sys.modules[module_name]
        if hasattr(mod, "__file__") and mod.__file__:
            return Path(mod.__file__)
    # 尝试直接 import
    try:
        mod = importlib.import_module(f"backend.{module_name}")
        if hasattr(mod, "__file__") and mod.__file__:
            return Path(mod.__file__)
    except Exception:
        pass
    # 从文件系统查找
    for base in [
        Path(__file__).parent,  # backend/
        Path(__file__).parent.parent,  # 项目根
    ]:
        p = base / f"{module_name}.py"
        if p.exists():
            return p
    return None


def check_module_version(module_name: str) -> dict:
    """
    检查 .py 和 __pycache__/.pyc 的 mtime 一致性。
    返回: {"module": name, "py_mtime": ..., "pyc_mtime": ..., "fresh": True/False}
    """
    result: dict[str, Any] = {"module": module_name, "py_path": None, "pyc_path": None,
                              "py_mtime": None, "pyc_mtime": None, "fresh": True}

    py_path = _get_module_path(module_name)
    if not py_path:
        result["error"] = f"找不到模块 {module_name}"
        return result

    result["py_path"] = str(py_path)
    result["py_mtime"] = os.path.getmtime(py_path)

    # 查找 .pyc 缓存
    pycache_dir = py_path.parent / "__pycache__"
    if pycache_dir.exists():
        pyc_name = f"{py_path.stem}.cpython-{sys.version_info.major}{sys.version_info.minor}.pyc"
        pyc_path = pycache_dir / pyc_name
        if pyc_path.exists():
            result["pyc_path"] = str(pyc_path)
            result["pyc_mtime"] = os.path.getmtime(pyc_path)
            # .pyc 比 .py 旧 → stale
            # .pyc 比 .py 新 → 可能是最近编译的，没问题
            # 但 .pyc 远新于 .py → 也正常（import 时编译）
            result["fresh"] = result["pyc_mtime"] >= result["py_mtime"] - 1
        else:
            # 无 .pyc → 没问题，import 时会编译
            result["pyc_path"] = None
            result["pyc_mtime"] = None
            result["fresh"] = True

    return result


def check_signature(module_name: str, spec: dict) -> dict:
    """
    检查模块中某函数是否具有必要参数。
    spec: {"func": "chat", "must_have_params": ["json_mode"]}
    """
    result: dict[str, Any] = {"module": module_name, "func": spec["func"],
                               "found": False, "missing_params": []}

    try:
        if module_name in sys.modules:
            mod = sys.modules[module_name]
        else:
            mod = importlib.import_module(f"backend.{module_name}")
    except Exception as e:
        result["error"] = f"导入失败: {e}"
        return result

    # 解析 func 名（支持 ClassName.method）
    parts = spec["func"].split(".")
    obj = mod
    for part in parts:
        if hasattr(obj, part):
            obj = getattr(obj, part)
        else:
            result["error"] = f"{part} 不存在"
            return result

    result["found"] = True
    if not callable(obj):
        result["error"] = "不是可调用对象"
        return result

    try:
        sig = inspect.signature(obj)
        result["sig"] = str(sig)
        for param_name in spec.get("must_have_params", []):
            if param_name not in sig.parameters:
                result["missing_params"].append(param_name)
    except (ValueError, TypeError):
        # C 扩展等无法检查签名
        result["sig_unavailable"] = True

    return result


def run_diagnostics() -> list[dict]:
    """执行全部自检，返回结果列表"""
    results: list[dict] = []

    # 1. 模块版本一致性
    for mod_name in CRITICAL_MODULES:
        r = check_module_version(mod_name)
        results.append(r)

    # 2. 函数签名检查
    for mod_name, specs in SIGNATURE_CHECKS.items():
        for spec in specs:
            r = check_signature(mod_name, spec)
            results.append(r)

    return results


def print_diagnostics(results: list[dict]) -> None:
    """格式化输出自检结果"""
    print("\n" + "=" * 60)
    print("  织镜 启动自检报告")
    print("=" * 60)

    has_issues = False
    for r in results:
        module = r.get("module", "?")
        if "error" in r:
            print(f"  ❌ [{module}] {r['error']}")
            has_issues = True
            continue

        if "func" in r:
            # 签名检查
            func_name = r.get("func", "?")
            if r.get("missing_params"):
                print(f"  ❌ [{module}.{func_name}] 缺少参数: {', '.join(r['missing_params'])}")
                has_issues = True
            elif not r.get("found"):
                print(f"  ❌ [{module}.{func_name}] 未找到")
                has_issues = True
            else:
                print(f"  ✅ [{module}.{func_name}] 签名: {r.get('sig', '可用')}")
        else:
            # 版本一致性检查
            py_mtime = r.get("py_mtime")
            pyc_mtime = r.get("pyc_mtime")
            fresh = r.get("fresh", True)
            py_mtime_str = time.strftime("%m-%d %H:%M:%S", time.localtime(py_mtime)) if py_mtime else "?"
            pyc_mtime_str = time.strftime("%m-%d %H:%M:%S", time.localtime(pyc_mtime)) if pyc_mtime else "无"
            if pyc_mtime is None:
                status = "✓"  # 没 pyc，import 时实时编译
                print(f"  ✓  [{module}] .py={py_mtime_str}, .pyc=无缓存 (实时编译)")
            elif fresh:
                print(f"  ✓  [{module}] .py={py_mtime_str}, .pyc={pyc_mtime_str}")
            else:
                print(f"  ⚠️  [{module}] .py 比 .pyc 新! .py={py_mtime_str}, .pyc={pyc_mtime_str}")
                print(f"       → 建议清除 __pycache__ 后重启")
                has_issues = True

    print("=" * 60)
    if has_issues:
        print("  ⚠️  发现潜在问题，建议修复后重启")
    else:
        print("  ✅ 所有检查通过")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
    results = run_diagnostics()
    print_diagnostics(results)
