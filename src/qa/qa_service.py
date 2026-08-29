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


class QAService:
    """Orchestrates the QA pipeline."""

    SYSTEM_PROMPT = (
        "你是一个工作资料知识库助手（含 CAD 图纸、Word 方案、Excel 清单、"
        "PDF 资料、Project 计划等）。请仅根据提供的上下文回答用户问题。\n"
        "规则：\n"
        "1. 如果上下文足以回答问题，用中文简洁回答，并引用来源（文件名/图层/handle/工作表）。\n"
        "2. 如果上下文不足，明确回答\"上下文中没有找到相关信息\"，不要猜测。\n"
        "3. 不要编造任何不在上下文中出现的数据（数值、位号、尺寸、参数等）。\n"
        "4. 若上下文中的数据相互矛盾，指出矛盾并列出各方来源。"
    )

    def __init__(self, llm_client=None):
        self.llm = llm_client
        self.context_builder = ContextBuilder()

    def ask(
        self,
        query: str,
        top_k: int = 8,
        max_context_items: int = 10,
    ) -> QAAnswer:
        """Answer a question about the knowledge base.

        Args:
            query: User question (Chinese or mixed).
            top_k: Number of retrieval results to use.
            max_context_items: Max context items shown to LLM.

        Returns:
            QAAnswer.
        """
        logger.info(f"QA 查询: {query}")

        # 1. Hybrid retrieval (CAD-centric)
        results = hybrid_search(query, top_k=top_k)

        # 1.1 Document vector retrieval (Phase 6: cross-format RAG)
        try:
            from src.core.document_rag import query_documents

            doc_results = query_documents(query, top_k=max(3, top_k // 2))
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

        # 4. LLM generation (only if configured & available)
        if self.llm is not None and self.llm.available:
            answer.llm_available = True
            answer.llm_model = self.llm.model
            try:
                prompt = self._build_prompt(query, ctx, max_context_items)
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

    def _build_prompt(self, query: str, ctx, max_items: int) -> list[dict]:
        """Build the chat messages for the LLM."""
        context_text = ctx.to_llm_text(max_items=max_items)
        if not context_text:
            context_text = "（上下文中没有找到任何相关内容）"

        user_content = (
            f"请回答以下关于 CAD 图纸知识库的问题：\n\n"
            f"问题：{query}\n\n"
            f"可用上下文：\n{context_text}"
        )
        return [
            self.llm.system_prompt(self.SYSTEM_PROMPT),
            {"role": "user", "content": user_content},
        ]


def ask_question(query: str, top_k: int = 8, **kwargs) -> QAAnswer:
    """Convenience wrapper: ask a question with default LLM client."""
    from src.llm import get_llm_client

    qa = QAService(llm_client=get_llm_client())
    return qa.ask(query, top_k=top_k, **kwargs)
