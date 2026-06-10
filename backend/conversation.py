"""ConversationManager — 多轮对话场景检测 + 查询增强 + 实体提取

v2 新增能力:
  - 追问实体提取（规则 + LLM 兜底）
  - 结构化 goal 合并（替换旧 goal 字段而非文本拼接）
  - LLM 场景兜底（关键词未命中时）
"""
import json
import logging
import re
from enum import Enum, auto

from .llm_client import chat_sync, MODEL_FLASH

logger = logging.getLogger(__name__)


class Scenario(Enum):
    NEW_QUERY = auto()
    FOLLOWUP_DEEPEN = auto()
    FOLLOWUP_COMPARE = auto()
    FOLLOWUP_MODIFY = auto()
    NEW_TOPIC = auto()


class ConversationManager:
    """多轮对话管理器 v2（实体提取 + 结构化 goal 合并）"""

    MAX_QUERY_LENGTH = 2000

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
        "改成", "换成", "调整为", "改为", "修改", "调整",
        "不要", "去掉", "重新", "换一个", "换种", "改一下",
        "换一下", "重来", "再试", "换风格", "换种风格",
    ]
    _NEW_TOPIC = [
        "换个", "新的", "另外", "换一个话题", "其他", "不问这个了",
        "换话题", "分析别的", "不分析这个了",
    ]

    _INTENT_KEYWORDS = {
        "选品": "单品选品分析", "选品分析": "单品选品分析",
        "竞品": "多品牌竞品对标", "竞品对比": "多品牌竞品对标", "竞品对标": "多品牌竞品对标",
        "趋势": "品类趋势洞察", "趋势分析": "品类趋势洞察", "趋势洞察": "品类趋势洞察",
        "文案": "商品文案生成", "文案生成": "商品文案生成",
        "定价": "定价策略分析", "定价分析": "定价策略分析", "定价策略": "定价策略分析",
        "上新": "上新排期建议", "上新排期": "上新排期建议", "排期": "上新排期建议",
        "文生图": "文生图", "生图": "文生图", "图片": "文生图",
    }
    _PATTERN_INTENT_SWITCH = re.compile(r"(?:换成|改成|换|改为)\s*(.+?)$")
    _PATTERN_THAT = re.compile(r"那[的]?([\u4e00-\u9fa5]+?)(?:呢|怎么样|如何|什么情况|的情况)?$")
    _PATTERN_CHANGE_TO = re.compile(r"(?:改成|换成|换为|改为|调整为)\s*([\u4e00-\u9fa5\w]+)")
    _PATTERN_COMPARE_WITH = re.compile(r"(?:对比|比较|vs)\s*([\u4e00-\u9fa5\w]+)")
    _PATTERN_APPEND = re.compile(r"(?:追加|加上|添加|增加)\s*([\u4e00-\u9fa5\w]+)")
    _PATTERN_REMOVE = re.compile(r"(?:不要|去掉|删除|移除|排除)\s*([\u4e00-\u9fa5\w]+)")

    @staticmethod
    def _sanitize(text: str) -> str:
        if not isinstance(text, str):
            return str(text) if text is not None else ""
        cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
        return cleaned[:ConversationManager.MAX_QUERY_LENGTH]

    # ========== 场景检测 ==========

    def detect_scenario(self, query: str, last_intent: str = "",
                        working_memory: dict = None) -> Scenario:
        query = self._sanitize(query)
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
        if last_intent and len(query) < 30:
            return Scenario.FOLLOWUP_DEEPEN
        if last_intent:
            llm_result = self._detect_scenario_llm(query, last_intent)
            if llm_result is not None:
                return llm_result
        return Scenario.NEW_QUERY

    def _detect_scenario_llm(self, query: str, last_intent: str) -> Scenario | None:
        try:
            prompt = f"""用户上次意图：{last_intent}
用户当前输入：{query}

判断当前输入属于以下哪种场景，只输出场景名称（一个词）：
new_query     — 全新的问题，与上轮无关
followup_deepen — 针对上轮结果的深入追问
followup_compare — 要求与上轮结果对比
followup_modify — 修改上轮的条件/参数后重新分析
new_topic    — 换话题（可能保留偏好）"""
            raw = chat_sync(prompt, model=MODEL_FLASH, max_tokens=30)
            name = raw.strip().lower()
            mapping = {
                "followup_deepen": Scenario.FOLLOWUP_DEEPEN,
                "followup_compare": Scenario.FOLLOWUP_COMPARE,
                "followup_modify": Scenario.FOLLOWUP_MODIFY,
                "new_topic": Scenario.NEW_TOPIC,
            }
            return mapping.get(name)
        except Exception as e:
            logger.warning(f"LLM scenario detection failed: {e}")
            return None

    # ========== 实体提取 ==========

    def extract_entities_from_followup(self, query: str,
                                       last_intent: dict) -> dict | None:
        query = self._sanitize(query)

        # 1. 意图切换："换成品类趋势分析"
        m = self._PATTERN_INTENT_SWITCH.search(query)
        if m:
            text_after = m.group(1)
            for kw, intent_name in self._INTENT_KEYWORDS.items():
                if kw in text_after:
                    return {"intent_type": intent_name}

        # 2. 追加："追加泡泡袖"
        m = self._PATTERN_APPEND.search(query)
        if m:
            return {"品类": m.group(1), "_action": "append_category"}

        # 3. 去除："不要蕾丝"
        m = self._PATTERN_REMOVE.search(query)
        if m:
            return {"_remove": m.group(1)}

        # 4. 对比句式："对比伊芙丽"
        m = self._PATTERN_COMPARE_WITH.search(query)
        if m:
            return {"竞品品牌": [m.group(1)]}

        # 5. 替换句式："换成夏装"
        m = self._PATTERN_CHANGE_TO.search(query)
        if m:
            return {"品类": m.group(1)}

        # 6. "那泡泡袖呢" 句式
        m = self._PATTERN_THAT.search(query)
        if m:
            return {"品类": m.group(1)}

        # 7. LLM 兜底提取
        return self._extract_entities_llm(query)

    def _extract_entities_llm(self, query: str) -> dict | None:
        try:
            prompt = f"""用户追问：{query}

从上方的追问中提取可能的产品/品牌实体。
输出 JSON，没有则输出 {{}}：
{{"品类": "提取的品类名（如有）", "竞品品牌": ["品牌名"]}}
只输出 JSON，不要其他文字。"""
            raw = chat_sync(prompt, model=MODEL_FLASH, max_tokens=100)
            result = json.loads(raw)
            result = {k: v for k, v in result.items() if v}
            return result if result else None
        except Exception as e:
            logger.warning(f"LLM entity extraction failed: {e}")
            return None

    # ========== Goal 合并 ==========

    def merge_goal(self, last_goal: dict, changes: dict | None) -> dict:
        if not changes:
            return last_goal
        new_goal = dict(last_goal)
        for key, value in changes.items():
            if key == "intent_type":
                new_goal = {}
            elif key == "_action":
                continue
            elif key == "_remove":
                for field in ["风格", "品类", "关键词"]:
                    if field in new_goal:
                        if isinstance(new_goal[field], list):
                            new_goal[field] = [x for x in new_goal[field] if value not in str(x)]
                        elif isinstance(new_goal[field], str):
                            new_goal[field] = new_goal[field].replace(value, "").strip()
            elif key == "竞品品牌":
                existing = new_goal.get("竞品品牌", [])
                if isinstance(existing, str):
                    existing = [existing]
                if isinstance(value, list):
                    for item in value:
                        if item not in existing:
                            existing.append(item)
                elif value not in existing:
                    existing.append(value)
                new_goal["竞品品牌"] = existing
            else:
                new_goal[key] = value
        if changes.get("_action") == "append_category":
            cat = changes.get("品类", "")
            if cat:
                old_cat = last_goal.get("品类", "")
                if old_cat and cat not in old_cat:
                    new_goal["品类"] = f"{old_cat}、{cat}"
        return new_goal

    # ========== 增强查询（v1 兼容保留） ==========

    def augment_query(self, query: str, scenario: Scenario,
                      working_memory: dict = None) -> str:
        return query

    # ========== 工具方法 ==========

    def is_followup(self, query: str) -> bool:
        all_followup = (self._FOLLOWUP_DEEPEN + self._FOLLOWUP_COMPARE +
                       self._FOLLOWUP_MODIFY)
        return any(kw in query for kw in all_followup)

    def has_entity_changes(self, query: str) -> bool:
        patterns = [self._PATTERN_THAT, self._PATTERN_CHANGE_TO,
                    self._PATTERN_COMPARE_WITH, self._PATTERN_APPEND,
                    self._PATTERN_REMOVE, self._PATTERN_INTENT_SWITCH]
        return any(p.search(query) for p in patterns)


_conversation_mgr: ConversationManager | None = None


def get_conversation_manager() -> ConversationManager:
    global _conversation_mgr
    if _conversation_mgr is None:
        _conversation_mgr = ConversationManager()
    return _conversation_mgr
