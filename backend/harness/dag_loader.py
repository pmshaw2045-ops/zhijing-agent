"""DAGLoader — 从配置加载DAG模板，支持热更新"""
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from ..intent_registry import get_all_dags

# 默认 DAG 模板（从 registry 构建，兜底用）
_DEFAULT_DAGS = get_all_dags()

class DAGLoader:
    """DAG配置加载器"""

    def __init__(self, config_dir: Optional[Path] = None):
        self._config_dir = config_dir
        self._cache: Optional[dict] = None

    def load(self, mode: str) -> dict | None:
        """加载指定模式的DAG配置"""
        dags = self._load_all()
        return dags.get(mode)

    def load_all(self) -> dict:
        """加载所有DAG配置"""
        return dict(self._load_all())

    def _load_all(self) -> dict:
        if self._cache is not None:
            return self._cache

        if self._config_dir:
            dag_file = self._config_dir / "dags.json"
            if dag_file.exists():
                try:
                    self._cache = json.loads(dag_file.read_text(encoding="utf-8"))
                    logger.info(f"DAGs loaded from {dag_file}")
                    return self._cache
                except Exception as e:
                    logger.warning(f"Failed to load DAGs from {dag_file}: {e}")

        # Fallback to built-in defaults
        self._cache = dict(_DEFAULT_DAGS)
        logger.info("Using built-in default DAGs")
        return self._cache

    def reload(self):
        """清除缓存，强制重新加载（开发模式热更新）"""
        self._cache = None
        return self._load_all()


# 全局单例
_loader: DAGLoader | None = None


def get_dag_loader() -> DAGLoader:
    global _loader
    if _loader is None:
        _loader = DAGLoader()
    return _loader
