"""ToolRegistry — 工具注册/发现/参数校验"""
import logging

logger = logging.getLogger(__name__)


class ToolSchema:
    """工具元数据Schema"""
    def __init__(self, name: str, description: str, parameters: dict):
        self.name = name
        self.description = description
        self.parameters = parameters

    def to_dict(self) -> dict:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


class ToolRegistry:
    """工具注册中心"""
    def __init__(self):
        self._tools: dict[str, ToolSchema] = {}
        self._aliases: dict[str, str] = {}  # 别名 → 正名

    def register(self, name: str, description: str, parameters: dict = None,
                 aliases: list[str] = None):
        """注册一个工具"""
        schema = ToolSchema(name, description, parameters or {})
        self._tools[name] = schema
        for alias in (aliases or []):
            self._aliases[alias] = name
        logger.debug(f"Tool registered: {name}")

    def resolve(self, name: str) -> str:
        """解析别名到正名"""
        return self._aliases.get(name, name)

    def get(self, name: str) -> ToolSchema | None:
        """获取工具Schema"""
        return self._tools.get(self.resolve(name))

    def list_all(self) -> list[dict]:
        """列出所有工具的dict表示"""
        return [s.to_dict() for s in self._tools.values()]

    def list_names(self) -> list[str]:
        """列出所有工具名"""
        return list(self._tools.keys())

    def validate(self, name: str) -> bool:
        """检查工具是否存在"""
        return self.resolve(name) in self._tools

    @property
    def count(self) -> int:
        return len(self._tools)


# 全局单例
_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _init_default_tools(_registry)
    return _registry


def _init_default_tools(reg: ToolRegistry):
    """初始化默认工具集"""
    reg.register("web_search", "Tavily英文搜索", {"query": "搜索关键词"})
    reg.register("bocha_search", "博查中文搜索(国内电商数据)", {"query": "搜索关键词"})
    reg.register("trend_analyze", "LLM从搜索结果提取趋势洞察",
                 {"query": "分析指令", "raw_data": "原始搜索结果"})
    reg.register("price_analyze", "LLM从搜索结果提取价格带数据",
                 {"query": "分析指令", "raw_data": "原始搜索结果"})
    reg.register("competitive_analyze", "LLM从搜索结果分析竞品格局",
                 {"query": "分析指令", "raw_data": "原始搜索结果"})
    reg.register("scoring_engine", "LLM多维度综合评分",
                 {"candidates": "候选列表", "criteria": "评分维度"})
    reg.register("report_generate", "交由LLM生成最终报告",
                 {"report_type": "报告类型", "data": "汇总数据"})
