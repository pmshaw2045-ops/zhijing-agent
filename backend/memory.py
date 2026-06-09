"""
Memory System: 短期记忆 + 工作记忆 + 长期记忆持久化
基于语雀文章(七)的五层记忆架构简化落地版
"""
from __future__ import annotations
import json
import os
import time
import threading
import asyncio
from pathlib import Path
from typing import Optional, Callable, Coroutine, Any
import logging

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
MEMORY_FILE = DATA_DIR / "memory_store.json"


class MemorySystem:
    """Agent记忆系统"""

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._async_lock = asyncio.Lock()

        # 存储后端：STORE_BACKEND=sqlite 时使用 SQLite，否则使用 JSON
        self._backend = None
        if os.environ.get("STORE_BACKEND", "").lower() == "sqlite":
            try:
                from .store import SQLiteBackend
            except ImportError:
                from store import SQLiteBackend
            self._backend = SQLiteBackend()

        self._store = self._load()
        self._dirty = False
        self._ensure_defaults()

    def _load(self) -> dict:
        with self._lock:
            if MEMORY_FILE.exists():
                try:
                    return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
                except Exception as e:
                    logger.warning(f"Memory file corrupt: {e}")
                    return {}
            return {}

    def _save(self):
        if self._backend:
            return  # SQLite 模式下写操作即时完成
        with self._lock:
            MEMORY_FILE.write_text(json.dumps(self._store, ensure_ascii=False, indent=2), encoding="utf-8")

    def mark_dirty(self):
        """标记脏数据。SQLite模式下立即写回，JSON模式下延迟刷新"""
        if self._backend and hasattr(self, '_active_sid') and hasattr(self, '_active_session'):
            self._backend.set_session(self._active_sid, self._active_session)
            return
        self._dirty = True

    async def flush(self):
        """异步刷新脏数据到磁盘"""
        if self._backend:
            return  # SQLite 无需刷新
        if self._dirty:
            import asyncio
            await asyncio.to_thread(self._save)
            self._dirty = False

    def _ensure_defaults(self):
        if "sessions" not in self._store:
            self._store["sessions"] = {}
        if "long_term" not in self._store:
            self._store["long_term"] = {"domains": {}, "brands": {}, "seasons": {},
                                          "platforms": {}, "user_preferences": {},
                                          "knowledge_snippets": []}
        self._save()

    # -- 封装层：统一管理会话 dict 访问 --

    def _get_session(self, session_id):
        """获取会话dict，不存在返回空dict"""
        if self._backend:
            session = self._backend.get_session(session_id)
            self._active_sid = session_id
            self._active_session = session
            return session
        return self._store.get("sessions", {}).get(session_id, {})

    def _ensure_session(self, session_id):
        """获取或创建会话dict"""
        if self._backend:
            if not self._backend.has_session(session_id):
                self._backend.set_session(session_id, {"conversation": [], "working": {}})
            session = self._backend.get_session(session_id)
            self._active_sid = session_id
            self._active_session = session
            return session
        sessions = self._store.setdefault("sessions", {})
        if session_id not in sessions:
            sessions[session_id] = {"conversation": [], "working": {}}
            self.mark_dirty()
        return sessions[session_id]

    def get_conversation(self, session_id: str) -> list[dict[str, Any]]:
        """获取会话历史"""
        session = self._get_session(session_id)
        return session.get("conversation", [])

    def append_conversation(self, session_id: str, role: str, content: str):
        """追加会话记录 (自动裁剪超长上下文)"""
        session = self._ensure_session(session_id)
        conv = session["conversation"]
        conv.append({
            "role": role,
            "content": content[:2000],  # 截断过长内容
            "timestamp": time.time()
        })

        # 保留最近20轮
        if len(conv) > 40:
            conv = conv[-40:]
            self._ensure_session(session_id)["conversation"] = conv

        self.mark_dirty()

    # === 滑动窗口 + 递归摘要 ===
    SLIDING_WINDOW = 10  # 保留最近 N 条原始消息

    def get_injectable_context(self, session_id: str) -> str:
        """返回可直接注入LLM prompt的Markdown格式记忆上下文"""
        session = self._get_session(session_id)
        conv = session.get("conversation", [])
        working = session.get("working", {})
        summary = session.get("summary", "")
        topic = session.get("topic_context", {})
        history = session.get("analysis_history", [])

        parts = []

        # 1. 递归摘要（早期对话压缩结果）
        if summary:
            parts.append(f"## 历史对话摘要\n{summary}")

        # 2. 最近原始对话（滑动窗口内）
        recent = conv[-self.SLIDING_WINDOW:]
        if recent:
            lines = []
            for m in recent:
                role = "用户" if m["role"] == "user" else "织镜"
                text = m.get("content", "")
                if m["role"] == "assistant":
                    # 助手消息只保留标题摘要，不保留完整JSON报告
                    try:
                        if text.startswith("{") and '"title"' in text:
                            import json
                            obj = json.loads(text[:500])
                            text = obj.get("title", text[:80])
                    except Exception:
                        pass
                    text = text[:80]
                else:
                    text = text[:500]
                lines.append(f"- **{role}**: {text}")
            parts.append("## 最近对话\n" + "\n".join(lines))

        # 3. 当前工作记忆
        if working.get("last_intent"):
            parts.append(f"## 当前上下文\n"
                         f"- 当前任务意图: {working.get('last_intent', '?')}\n"
                         f"- 主题: {working.get('current_subject', '')}\n"
                         f"- 用户提及品类: {', '.join(working.get('entities', {}).get('categories', []))}")

        # 4. 主题上下文
        if topic:
            tc_parts = []
            for k, v in topic.items():
                if isinstance(v, list) and v:
                    tc_parts.append(f"- {k}: {', '.join(str(x) for x in v[-3:])}")
            if tc_parts:
                parts.append("## 主题偏好\n" + "\n".join(tc_parts))

        # 5. 分析历史
        if history:
            h_parts = []
            for h in history[-3:]:
                h_parts.append(f"- [{h.get('intent','?')}] {h.get('summary','')[:80]}")
            if h_parts:
                parts.append("## 最近分析\n" + "\n".join(h_parts))

        return "\n\n".join(parts)

    async def compress_if_needed(self, session_id: str, llm_chat_fn: Callable[[str], Coroutine[Any, Any, str]]) -> bool:
        """滑动窗口溢出时，异步压缩早期对话为摘要。返回是否执行了压缩。"""
        session = self._get_session(session_id)
        conv = session.get("conversation", [])

        if len(conv) <= self.SLIDING_WINDOW + 5:
            return False

        overflow = conv[:-(self.SLIDING_WINDOW)]
        existing_summary = session.get("summary", "")
        summary_index = session.get("summary_at_index", 0)

        new_messages = overflow[summary_index:]
        if len(new_messages) < 2:
            return False

        conv_text = "\n".join(
            f"{'用户' if m['role'] == 'user' else '织镜'}: {m.get('content', '')[:300]}"
            for m in new_messages
        )
        summary_prompt = (
            "你是一个对话摘要助手。将以下对话片段压缩为简洁的要点摘要（不超过200字），提取关键信息：品类、品牌、价格带、用户偏好、分析结论。\n\n"
        )
        if existing_summary:
            summary_prompt += f"现有历史摘要:\n{existing_summary}\n\n"
        summary_prompt += f"新增对话:\n{conv_text}\n\n请输出更新后的完整摘要（合并新旧信息）："

        try:
            new_summary = await llm_chat_fn(summary_prompt)
            if new_summary and len(new_summary) > 20:
                async with self._async_lock:
                    session = self._get_session(session_id)
                    session["summary"] = new_summary.strip()[:500]
                    session["summary_at_index"] = len(overflow)
                    self.mark_dirty()
                return True
        except Exception:
            pass
        return False

    # === 工作记忆 (当前任务上下文) ===
    def get_working_memory(self, session_id: str) -> dict:
        """获取工作记忆"""
        session = self._get_session(session_id)
        return session.get("working", {})

    def update_working_memory(self, session_id: str, key: str, value):
        """更新工作记忆中的单个字段"""
        session = self._ensure_session(session_id)
        self._ensure_session(session_id)["working"][key] = value
        self.mark_dirty()

    # === 增强工作记忆 (v2) ===
    def update_topic_context(self, session_id: str, intent: dict):
        """从意图提取结构化主题上下文"""
        goal = intent.get("goal", {})
        entities = intent.get("entities", {})
        # Auto-create session if not exists
        session = self._ensure_session(session_id)
        working = self.get_working_memory(session_id)

        context = working.get("context", {})
        context["current_topic"] = {
            "category": goal.get("品类", entities.get("category", "")),
            "style": goal.get("风格", entities.get("style", "")),
            "subject": entities.get("subject", ""),
            "time": entities.get("time", ""),
            "platforms": goal.get("目标平台", entities.get("platforms", [])),
            "price_focus": goal.get("核心关注点", ""),
            "brands": goal.get("竞品品牌", entities.get("brands", [])),
            "intent": intent.get("intent_type", ""),
        }

        # 累积偏好
        prefs = context.get("user_preferences", {})
        if goal.get("风格"):
            styles = prefs.get("style_preferences", [])
            style = goal["风格"]
            if isinstance(style, str) and style not in styles:
                styles.append(style)
                prefs["style_preferences"] = styles[-5:]  # 保留最近5个
        if goal.get("品类"):
            cats = prefs.get("category_interests", [])
            cat = goal["品类"]
            if isinstance(cat, str) and cat not in cats:
                cats.append(cat)
                prefs["category_interests"] = cats[-5:]

        context["user_preferences"] = prefs
        working["context"] = context
        self._ensure_session(session_id)["working"] = working
        self.mark_dirty()

    def record_analysis(self, session_id: str, query: str, intent: dict,
                        key_findings: str, params: dict = None):
        """记录一次分析的关键发现"""
        session = self._ensure_session(session_id)

        # 提取摘要：JSON报告正则提取title，纯文本截断
        summary = key_findings[:300]
        if key_findings.strip().startswith("{"):
            import re
            m = re.search(r'"title"\s*:\s*"([^"]+)"', key_findings)
            if m:
                summary = m.group(1)[:100]
            else:
                summary = key_findings[:100]
        else:
            summary = key_findings[:200]

        working = self.get_working_memory(session_id)
        context = working.get("context", {})
        history = context.get("analysis_history", [])
        history.append({
            "query": query[:200],
            "intent": intent.get("intent_type", ""),
            "category": intent.get("goal", {}).get("品类", ""),
            "key_findings": summary,
            "params": params or {},
            "timestamp": time.time(),
        })

        # 保留最近5条
        context["analysis_history"] = history[-5:]
        context["last_analysis"] = history[-1] if history else {}
        working["context"] = context
        self._ensure_session(session_id)["working"] = working
        self.mark_dirty()

    def find_related_analyses(self, session_id: str, category: str,
                               intent_type: str = "") -> list[dict]:
        """查找同类目/同类意图的历史分析记录（按时间倒序，最多 3 条）"""
        if not session_id or not (category or intent_type):
            return []
        session = self._get_session(session_id)
        context = session.get("working", {}).get("context", {})
        history = context.get("analysis_history", [])

        related = []
        for h in reversed(history):
            # 匹配类目（包含关系：品类名出现在类目中或反之）
            cat_match = category and (
                category in h.get("category", "")
                or h.get("category", "") in category
            )
            # 匹配意图
            intent_match = intent_type and h.get("intent", "") == intent_type

            if cat_match or intent_match:
                related.append(h)
                if len(related) >= 3:
                    break
        return related

    def get_working_context(self, session_id: str) -> dict:
        """获取增强的工作记忆上下文"""
        working = self.get_working_memory(session_id)
        return working.get("context", {})

    def build_context_prompt(self, session_id: str, intent: dict = None) -> str:
        """构建用于prompt注入的上下文字符串"""
        context = self.get_working_context(session_id)
        parts = []

        # 1. 当前分析主题
        topic = context.get("current_topic", {})
        if topic.get("category"):
            parts.append(f"当前分析品类: {topic['category']}")
            if topic.get("style"):
                parts.append(f"风格: {topic['style']}")
            if topic.get("price_focus"):
                parts.append(f"价格关注: {topic['price_focus']}")

        # 2. 上轮分析引用
        last = context.get("last_analysis")
        if last and last.get("category") == topic.get("category", ""):
            parts.append(f"上轮分析发现: {last.get('key_findings', '')}")

        # 3. 用户偏好
        prefs = context.get("user_preferences", {})
        if prefs.get("style_preferences"):
            parts.append(f"用户偏好风格: {', '.join(prefs['style_preferences'])}")
        if prefs.get("category_interests"):
            parts.append(f"用户关注品类: {', '.join(prefs['category_interests'])}")

        # 4. 历史分析摘要（不同品类的也展示）
        history = context.get("analysis_history", [])
        if len(history) > 1:
            parts.append("历史分析记录:")
            for h in history[-3:]:
                parts.append(f"  · {h['category']}: {h['key_findings'][:80]}")

        return "\n".join(parts) if parts else ""

    def append_session_chain(self, session_id: str, user_query: str,
                             assistant_summary: str):
        """维护多轮对话链"""
        session = self._ensure_session(session_id)
        working = self.get_working_memory(session_id)
        context = working.get("context", {})

        chain = context.get("session_chain", [])
        chain.append({
            "user": user_query[:200],
            "assistant_summary": assistant_summary[:300],
        })

        # 保留最近5轮
        context["session_chain"] = chain[-5:]
        working["context"] = context
        self._ensure_session(session_id)["working"] = working
        self.mark_dirty()

    # === 长期记忆 (跨会话持久化) ===
    def get_long_term(self, key: str = None) -> dict:
        """获取长期记忆"""
        lt = self._store.get("long_term", {})
        return lt.get(key, lt) if key else lt

    def update_long_term(self, key: str, value):
        """更新长期记忆"""
        self._store["long_term"][key] = value
        self.mark_dirty()

    def add_knowledge(self, snippet: str, tags: list = None):
        """添加知识片段到长期记忆"""
        entry = {
            "content": snippet,
            "tags": tags or [],
            "timestamp": time.time()
        }
        self._store["long_term"]["knowledge_snippets"].append(entry)
        # 保留最近100条
        if len(self._store["long_term"]["knowledge_snippets"]) > 100:
            self._store["long_term"]["knowledge_snippets"] = \
                self._store["long_term"]["knowledge_snippets"][-100:]
        self.mark_dirty()

    # === 记忆检索 ===
    def recall(self, session_id: str, query: str = None) -> dict:
        """召回与当前任务相关的所有记忆"""
        return {
            "conversation": self.get_conversation(session_id),
            "working": self.get_working_memory(session_id),
            "long_term": self.get_long_term(),
        }

    # === 统计 ===
    def stats(self, session_id: str = None) -> dict:
        """记忆系统统计"""
        if session_id:
            conv_len = len(self.get_conversation(session_id))
            working_keys = list(self.get_working_memory(session_id).keys())
            return {
                "short_term_count": conv_len,
                "working_keys": working_keys,
                "knowledge_count": len(self._store["long_term"]["knowledge_snippets"])
            }
        return {
            "total_sessions": len(self._store["sessions"]),
            "knowledge_count": len(self._store["long_term"]["knowledge_snippets"])
        }
