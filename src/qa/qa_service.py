"""QA service — AI 问答编排 (Phase 7).

Pipeline:
1. Hybrid retrieval (FTS + vector + structured + rerank)
2. Context building (with provenance)
3. LLM answer generation (if configured)
4. Source traceability attached to the answer

If the LLM is not configured (no api_key) or fails, the service returns
an evidence-only response: the retrieved context with provenance and a
note that no LLM answer was generated. We never fabricate answers.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.rag.context_builder import ContextBuilder, ContextItem
from src.rag.hybrid_search import hybrid_search
from src.rag.reranker import rerank
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.qa")


class QAAnswer(BaseModel):
    """A complete QA response with provenance."""
    query: str = ""
    answer: str = ""                 # LLM-generated or empty
    mode: str = "evidence"           # "llm" | "evidence"
    llm_model: str = ""              # model name if LLM used
    llm_available: bool = False
    llm_error: str = ""              # error message if LLM failed
    context_items: list[ContextItem] = Field(default_factory=list)
    traceable_count: int = 0
    untraceable_count: int = 0
    # 第二检索源：现场群聊档案（独立库，与技术文件证据分级）
    chat_used: bool = False
    chat_items: list[dict] = Field(default_factory=list)


class QAService:
    """Orchestrates the QA pipeline."""

    SYSTEM_PROMPT = (
        "你是一个工作资料知识库助手（含 CAD 图纸、Word 方案、Excel 清单、"
        "PDF 资料、Project 计划等）。请仅根据提供的上下文回答用户问题。\n"
        "规则：\n"
        "1. 如果上下文足以回答问题，用中文简洁回答，并引用来源（文件名/图层/handle/工作表）。\n"
        "2. 如果上下文不足，明确回答\"上下文中没有找到相关信息\"，不要猜测。\n"
        "3. 不要编造任何不在上下文中出现的数据（数值、位号、尺寸、参数等）。\n"
        "4. 若上下文中的数据相互矛盾，指出矛盾并列出各方来源。\n"
        "5. 上下文分两类：①受控技术文件（图纸/设备表/台账/厂家资料）；②现场群聊摘录"
        "（微信群，属现场沟通口径，未经受控）。引用群聊内容时必须标注「据群聊」并给出发言人与日期；"
        "群聊与技术文件冲突时，以技术文件为准并指出分歧；不得把群聊中的口头计划当成已完成的既成事实。"
    )

    def __init__(self, llm_client=None):
        self.llm = llm_client
        self.context_builder = ContextBuilder()

    def ask(
        self,
        query: str,
        top_k: int = 8,
        max_context_items: int = 10,
        project_id: str = "",
        include_chat: bool = True,
        chat_top_k: int = 6,
    ) -> QAAnswer:
        """Answer a question about the knowledge base.

        Args:
            query: User question (Chinese or mixed).
            top_k: Number of retrieval results to use.
            max_context_items: Max context items shown to LLM.
            project_id: 工程隔离（P1）——检索结果按项目过滤：
                平台级(project_id 空) + 本工程资料 命中；其他工程不命中。
                空串 = 平台级查询（不过滤）。
            include_chat: 是否同时检索「现场群聊档案」（第二检索源，独立库）。
            chat_top_k: 群聊命中条数上限。

        Returns:
            QAAnswer.
        """
        logger.info(f"QA 查询: {query} (project={project_id or '平台'})")

        # 1. Hybrid retrieval (CAD-centric) — P1: 检索层即按工程过滤
        results = hybrid_search(query, top_k=top_k, project_id=project_id)

        # 1.1 Document vector retrieval (Phase 6: cross-format RAG) — 同过滤
        try:
            from src.core.document_rag import query_documents

            doc_results = query_documents(
                query, top_k=max(3, top_k // 2), project_id=project_id)
            for r in doc_results:
                results.append({
                    "content": r.get("content", ""),
                    "source_type": (
                        r.get("metadata", {}).get("source_type", "document")
                        or "document"),
                    "drawing_id": r.get("drawing_id", ""),
                    "handle": r.get("handle", ""),
                    "layer": r.get("layer", ""),
                    "score": float(r.get("score", 0)) * 0.9,
                    "metadata": r.get("metadata", {}),
                })
        except Exception as e:
            logger.warning(f"文档检索失败（不影响 CAD 检索）: {e}")

        # 1.2 Project isolation (P1): 双层检索——保留平台级 + 本工程结果
        if project_id:
            try:
                from src.core.project_filter import filter_by_project

                results = filter_by_project(results, project_id)
            except Exception as e:
                logger.warning(f"项目过滤失败（跳过隔离）: {e}")

        # 2. Rerank (if LLM available we still rerank for context quality)
        results = rerank(query, results, top_k=top_k)

        # 3. Build context
        ctx = self.context_builder.build(results, query)

        answer = QAAnswer(
            query=query,
            mode="evidence",
            context_items=ctx.items,
            traceable_count=ctx.traceable,
            untraceable_count=ctx.untraceable,
        )

        # 3.1 第二检索源：现场群聊档案（独立库；失败静默降级，不影响主检索）
        chat_text = ""
        if include_chat:
            try:
                from src.core.site_chat_search import search_site_chat, format_for_prompt

                chat_hits = search_site_chat(query, top_k=chat_top_k)
                if chat_hits:
                    answer.chat_items = chat_hits
                    answer.chat_used = True
                    chat_text = format_for_prompt(chat_hits)
                    logger.info(f"群聊命中 {len(chat_hits)} 条")
            except Exception as e:
                logger.warning(f"群聊检索不可用（跳过第二源）: {e}")

        # 4. LLM generation (only if configured & available)
        if self.llm is not None and self.llm.available:
            answer.llm_available = True
            answer.llm_model = self.llm.model
            try:
                prompt = self._build_prompt(query, ctx, max_context_items, chat_text)
                ans = self.llm.chat(prompt)
                answer.answer = ans
                answer.mode = "llm"
            except Exception as e:
                logger.warning(f"LLM 生成失败，降级为证据模式: {e}")
                answer.llm_error = str(e)
                answer.mode = "evidence"
        else:
            logger.info("LLM 未配置 API Key，使用证据模式（不生成回答）")

        return answer

    def _build_prompt(self, query: str, ctx, max_items: int, chat_text: str = "") -> list[dict]:
        """Build the chat messages for the LLM."""
        context_text = ctx.to_llm_text(max_items=max_items)
        if not context_text:
            context_text = "（上下文中没有找到任何相关内容）"

        chat_block = f"\n\n{chat_text}" if chat_text else ""
        user_content = (
            f"请回答以下关于 CAD 图纸知识库的问题：\n\n"
            f"问题：{query}\n\n"
            f"【受控技术文件上下文】\n{context_text}"
            f"{chat_block}"
        )
        return [
            self.llm.system_prompt(self.SYSTEM_PROMPT),
            {"role": "user", "content": user_content},
        ]


def ask_question(query: str, top_k: int = 8, project_id: str = "", **kwargs) -> QAAnswer:
    """Convenience wrapper: ask a question with default LLM client."""
    from src.llm import get_llm_client

    qa = QAService(llm_client=get_llm_client())
    return qa.ask(query, top_k=top_k, project_id=project_id, **kwargs)
