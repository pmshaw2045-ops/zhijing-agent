"""ConversationManager — 多轮对话场景检测 + 查询增强"""
import json
import logging
from enum import Enum, auto

logger = logging.getLogger(__name__)


class Scenario(Enum):
    NEW_QUERY = auto()          # 新查询
    FOLLOWUP_DEEPEN = auto()    # 深入追问
    FOLLOWUP_COMPARE = auto()   # 对比引用
    FOLLOWUP_MODIFY = auto()    # 条件变更
    NEW_TOPIC = auto()          # 新主题（保留偏好）


class ConversationManager:
    """多轮对话管理器"""

    # 场景关键词（大幅扩展覆盖）
    _FOLLOWUP_DEEPEN = [
        "深入", "详细", "继续", "再说说", "具体", "展开", "进一步", "多说",
        "然后呢", "还有呢", "接着", "比如", "例如", "举例", "能具体",
        "再分析", "补充", "细化", "能展开",
    ]
    _FOLLOWUP_COMPARE = [
        "对比", "和上次", "上次的", "之前的", "上轮", "比较", "跟上一次",
        "相对于", "相比", "区别", "差异", "哪个更好", "哪一个",
        "vs", " VS ", "比起",
    ]
    _FOLLOWUP_MODIFY = [
        "改成", "换成", "调整为", "改为", "修改", "调整", "换成",
        "不要", "去掉", "重新", "换一个", "换种", "改一下",
        "换一下", "重来", "再试", "换风格", "换种风格",
    ]
    _NEW_TOPIC = [
        "换个", "新的", "另外", "换一个话题", "其他", "不问这个了",
        "换话题", "分析别的", "不分析这个了",
    ]

    def detect_scenario(self, query: str, last_intent: str = "",
                        working_memory: dict = None) -> Scenario:
        """检测当前查询的场景类型"""
        for kw in self._FOLLOWUP_COMPARE:
            if kw in query:
                return Scenario.FOLLOWUP_COMPARE

        for kw in self._FOLLOWUP_MODIFY:
            if kw in query:
                return Scenario.FOLLOWUP_MODIFY

        for kw in self._FOLLOWUP_DEEPEN:
            if kw in query:
                return Scenario.FOLLOWUP_DEEPEN

        for kw in self._NEW_TOPIC:
            if kw in query:
                return Scenario.NEW_TOPIC

        # 短查询 + 有上轮意图 → 可能是追问
        if last_intent and len(query) < 30:
            return Scenario.FOLLOWUP_DEEPEN

        return Scenario.NEW_QUERY

    def augment_query(self, query: str, scenario: Scenario,
                      working_memory: dict = None) -> str:
        """根据场景增强查询，注入上下文"""
        wm = working_memory or {}

        if scenario == Scenario.FOLLOWUP_DEEPEN:
            last = wm.get("last_analysis", {})
            if last:
                return (f"{query}\n\n[上下文：上轮分析了{last.get('category','')}的"
                        f"{last.get('intent','')}，关键发现：{str(last.get('key_findings',''))[:120]}]")

        elif scenario == Scenario.FOLLOWUP_COMPARE:
            last = wm.get("last_analysis", {})
            if last:
                return (f"对比分析：{query}\n"
                        f"[参考上轮：{last.get('query','')}，结论：{str(last.get('key_findings',''))[:120]}]")

        elif scenario == Scenario.FOLLOWUP_MODIFY:
            last = wm.get("last_analysis", {})
            if last:
                prev_params = json.dumps(last.get("params", {}), ensure_ascii=False)
                return (f"{query}\n"
                        f"[基于上轮参数修改：{prev_params}]")

        elif scenario == Scenario.NEW_TOPIC:
            # 保留偏好
            prefs = wm.get("user_preferences", {})
            if prefs:
                pref_text = ", ".join(f"{k}={v}" for k, v in prefs.items() if v)
                return f"{query}\n[用户偏好：{pref_text}]"

        return query

    def is_followup(self, query: str) -> bool:
        """快速判断是否为追问"""
        all_followup = (self._FOLLOWUP_DEEPEN + self._FOLLOWUP_COMPARE +
                       self._FOLLOWUP_MODIFY)
        return any(kw in query for kw in all_followup)


# 全局单例
_conversation_mgr: ConversationManager | None = None


def get_conversation_manager() -> ConversationManager:
    global _conversation_mgr
    if _conversation_mgr is None:
        _conversation_mgr = ConversationManager()
    return _conversation_mgr
