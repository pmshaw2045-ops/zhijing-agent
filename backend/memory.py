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

    # 服饰电商类目同义词映射（大类→相关词，用于关键词检索兜底）
    CATEGORY_SYNONYMS = {
        "连衣裙": ["连衣裙", "茶歇裙", "碎花裙", "衬衫裙", "A字裙", "吊带裙", "裹身裙",
                   "法式裙", "缎面裙", "娃娃裙", "直筒裙", "衬衫裙", "百褶裙"],
        "上衣": ["上衣", "衬衫", "T恤", "针织衫", "打底衫", "雪纺衫", "吊带",
                "POLO衫", "卫衣", "毛衣"],
        "半身裙": ["半身裙", "半裙", "迷笛裙", "铅笔裙", "百褶裙", "伞裙", "皮裙"],
        "裤子": ["裤子", "牛仔裤", "阔腿裤", "直筒裤", "短裤", "运动裤", "休闲裤"],
        "外套": ["外套", "西装", "风衣", "夹克", "大衣", "牛仔外套", "针织开衫"],
        "女装": ["女装", "连衣裙", "上衣", "半身裙", "裤子", "外套", "套装"],
        "套装": ["套装", "西服套装", "两件套", "上衣+半裙"],
        "旗袍": ["旗袍", "新中式", "改良旗袍"],
    }

    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._async_lock = asyncio.Lock()

        # 存储后端：sqlite（默认）或 json（兼容旧版）
        self._backend = None
        self._store = {}  # JSON 模式用；SQLite 模式仅 stats() 兼容
        use_sqlite = True
        try:
            from .config import STORE_BACKEND as _store_backend
            use_sqlite = _store_backend.lower() == "sqlite"
        except Exception:
            use_sqlite = os.environ.get("STORE_BACKEND", "sqlite").lower() == "sqlite"

        if use_sqlite:
            from .store import SQLiteBackend, migrate_json_to_sqlite
            self._backend = SQLiteBackend()
            # 首次使用 SQLite 时自动迁移 JSON 数据
            if MEMORY_FILE.exists():
                migrated = migrate_json_to_sqlite(MEMORY_FILE)
                if migrated > 0:
                    logger.info(f"已从 JSON 迁移 {migrated} 个会话到 SQLite")
                MEMORY_FILE.rename(MEMORY_FILE.with_suffix(".json.bak"))
            self._store = {"sessions": {}, "long_term": {"knowledge_snippets": []}}
        else:
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
        """标记数据需要持久化。flush() 时统一写入"""
        self._dirty = True

    async def flush(self):
        """异步刷新脏数据到磁盘（JSON: 写文件，SQLite: 写数据库）"""
        if self._dirty:
            if self._backend and hasattr(self, '_active_sid') and hasattr(self, '_active_session'):
                self._backend.set_session(self._active_sid, self._active_session)
            elif not self._backend:
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

    def get_injectable_context(self, session_id: str, intent_type: str = "") -> str:
        """返回可直接注入LLM prompt的Markdown格式记忆上下文

        Args:
            session_id: 会话ID
            intent_type: 当前意图类型。提供后只注入同意图类型的分析历史，
                        防止跨意图上下文污染。Phase 1（意图识别）不传此参数
                        以保留全量上下文；Phase 6（报告生成）必须传以隔离历史。
        """
        session = self._get_session(session_id)
        conv = session.get("conversation", [])
        working = session.get("working", {})
        summary = session.get("summary", "")
        topic = session.get("topic_context", {})
        history = session.get("analysis_history", [])
        # 意图过滤：只保留同意图类型的分析历史
        if intent_type and history:
            history = [h for h in history if h.get("intent", "") == intent_type]

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

        # 异步 embedding + 向量存储（不阻塞主流程）
        try:
            import asyncio
            asyncio.create_task(self._index_analysis(
                session_id, query, intent, summary
            ))
        except Exception:
            pass

    async def find_related_analyses(self, session_id: str, category: str,
                                     intent_type: str = "") -> tuple[list[dict], dict]:
        """语义检索同类目/同类意图的历史分析记录。
        
        返回 (results, search_info)，search_info 包含检索过程数据供 Console 展示。
        语义检索 score < 0.3 时回退到关键词匹配。
        """
        search_info = {"query": f"{category} {intent_type}", "latency_ms": 0, "method": "keyword"}
        if not session_id or not (category or intent_type):
            return [], search_info
        session = self._get_session(session_id)
        context = session.get("working", {}).get("context", {})
        history = context.get("analysis_history", [])

        # 语义检索（向量相似度）
        t0 = time.time()
        search_text = f"{category} {intent_type}"
        query_vec = None
        # 如果数据库中有向量再尝试 embedding，避免无谓的 LLM 调用
        try:
            if self._backend and self._backend.get_vectors(limit=1):
                query_vec = await self.embed_text(search_text)
        except Exception:
            pass
        if query_vec:
            # LLM embedding 一致性约 0.5-0.6，不使用硬阈值，用排序替代
            vec_results = await self.search_vectors(query_vec, top_k=5, min_score=0.0)
            search_info["latency_ms"] = round((time.time() - t0) * 1000)
            if vec_results:
                search_info["method"] = "semantic"
                # 标准化字段名：向量存储用 summary，下游用 key_findings
                for r in vec_results:
                    r["key_findings"] = r.get("summary", "")
                    r["timestamp"] = r.get("_timestamp", 0)
                return vec_results, search_info

        # 回退：关键词匹配（含同义词扩展）
        search_info["latency_ms"] = round((time.time() - t0) * 1000)
        related = []
        for h in reversed(history):
            # 原始类目匹配
            h_cat = h.get("category", "")
            cat_match = False
            if category and h_cat:
                # 精确包含匹配
                if category in h_cat or h_cat in category:
                    cat_match = True
                else:
                    # 同义词扩展匹配
                    syns_new = set(self.CATEGORY_SYNONYMS.get(category, [category]))
                    syns_hist = set(self.CATEGORY_SYNONYMS.get(h_cat, [h_cat]))
                    if syns_new & syns_hist:
                        cat_match = True
            intent_match = intent_type and h.get("intent", "") == intent_type
            if intent_type:
                # 已知意图类型时只允许精确意图匹配，防止跨意图污染
                if intent_match:
                    related.append({**h, "_score": -1, "_source": "keyword"})
            else:
                # 无意图类型时（Phase 1 意图识别阶段）用类目匹配兜底
                if cat_match:
                    related.append({**h, "_score": -1, "_source": "keyword"})
            if len(related) >= 3:
                break
        return related, search_info

    def get_working_context(self, session_id: str) -> dict:
        """获取增强的工作记忆上下文"""
        working = self.get_working_memory(session_id)
        return working.get("context", {})


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

    # === 语义检索（RAG） ===

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """纯 Python 余弦相似度，零依赖"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(y * y for y in b) ** 0.5
        if norm_a < 1e-10 or norm_b < 1e-10:
            return 0.0
        return dot / (norm_a * norm_b)

    async def embed_text(self, text: str) -> list[float] | None:
        """用 LLM 将文本转为 embedding 向量。失败返回 None 且不抛异常。"""
        if not text or not text.strip():
            return None
        try:
            from .llm_client import chat_sync, extract_json
            prompt = (
                "你是一个文本向量化工具。将以下文本转为浮点数向量。\n"
                "规则：\n"
                "1. 输出一个JSON数组，包含16个浮点数\n"
                "2. 每个数的范围在-1.0到1.0之间\n"
                "3. 语义越相似的两个文本，输出向量的余弦相似度越高\n"
                "4. 只输出JSON数组，不要任何说明文字\n\n"
                f"文本: {text[:800]}"
            )
            # 用 asyncio.to_thread 避免阻塞事件循环，5 秒超时
            import asyncio
            raw = await asyncio.wait_for(
                asyncio.to_thread(lambda: chat_sync(prompt, max_tokens=300)),
                timeout=5.0
            )
            vec = extract_json(raw)
            if isinstance(vec, list) and len(vec) >= 4:
                return [float(v) for v in vec[:16]]
            return None
        except asyncio.TimeoutError:
            logger.warning(f"embed_text timeout for '{text[:40]}...'")
            return None
        except Exception as e:
            logger.warning(f"embed_text failed: {e}")
            return None

    async def search_vectors(self, query_vec: list[float], top_k: int = 5,
                              min_score: float = 0.0) -> list[dict]:
        """从 SQLite 加载向量，余弦相似度检索 top-K"""
        if not query_vec:
            return []
        try:
            if not self._backend:
                return []
            vectors = self._backend.get_vectors(limit=500)
        except Exception as e:
            logger.warning(f"search_vectors load failed: {e}")
            return []

        scored = []
        for v in vectors:
            score = self._cosine_similarity(query_vec, v["vector"])
            if score >= min_score:
                scored.append({
                    **v["metadata"],
                    "_score": round(score, 4),
                    "_session_id": v["session_id"],
                    "_timestamp": v["created_at"],
                })

        scored.sort(key=lambda x: x["_score"], reverse=True)
        return scored[:top_k]

    async def _index_analysis(self, session_id: str, query: str,
                               intent: dict, summary: str):
        """分析完成后异步 embedding + 存储（不阻塞主流程）"""
        if not self._backend:
            return
        text = f"{intent.get('intent_type', '')} {intent.get('goal', {}).get('品类', '')} {summary[:200]}"
        vec = await self.embed_text(text)
        if vec is None:
            return
        try:
            import hashlib
            vec_id = f"analysis:{session_id}:{int(time.time())}"
            metadata = {
                "query": query[:200],
                "intent": intent.get("intent_type", ""),
                "category": intent.get("goal", {}).get("品类", ""),
                "summary": summary[:300],
                "source": "analysis_history",
            }
            self._backend.save_vector(vec_id, session_id, vec, metadata)
        except Exception as e:
            logger.warning(f"_index_analysis save failed: {e}")

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
