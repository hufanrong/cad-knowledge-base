"""REST API — FastAPI 应用 (Phase 7).

Endpoints:
- GET  /api/health         健康检查（轻量，不查库）
- GET  /api/status         系统状态（完整统计）
- GET  /api/drawings       图纸列表
- GET  /api/drawings/{id}  图纸详情
- GET  /api/search         综合搜索
- POST /api/query          AI 问答（带来源追溯）
- GET  /api/rag?q=...      RAG 混合检索

Run with: cadkb serve  (or uvicorn src.api.app:app)
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.core.config import get_config
from src.database.connection import get_session, init_database
from src.database.repositories import DrawingRepository
from src.index.search_service import SearchService
from src.llm import get_llm_client
from src.qa import QAService
from src.utils.logger import setup_logger

# 现场资料 / 工程实体 路由（第三、四阶段新增，工程隔离）
from src.api.site_api import router as site_router
from src.api.entity_api import router as entity_router
from src.api.report_api import router as report_router

logger = setup_logger("cadkb.api")

# Module-level caches for expensive one-time initializations
_vector_index_cache: Any | None = None
_llm_client_cache: Any | None = None


def _get_cached_vector_index():
    global _vector_index_cache
    if _vector_index_cache is None:
        from src.index.vector_index import VectorIndex
        _vector_index_cache = VectorIndex()
    return _vector_index_cache


def _get_cached_llm_client():
    global _llm_client_cache
    if _llm_client_cache is None:
        _llm_client_cache = get_llm_client()
    return _llm_client_cache


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()
    cfg.ensure_directories()
    init_database()
    logger.info("API 启动完成")
    yield


app = FastAPI(
    title="CAD Knowledge Base API",
    description="本地 CAD 图纸解析与私人知识库系统",
    version="0.7.0",
    lifespan=lifespan,
)

# CORS（为未来 Web/PWA 前端预留，先放开；PWA 上线前补鉴权）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 现场资料 / 工程实体 路由注册
app.include_router(site_router)
app.include_router(entity_router)
app.include_router(report_router)


class QueryRequest(BaseModel):
    """Request body for POST /api/query."""
    query: str = Field(..., description="用户问题")
    top_k: int = Field(8, ge=1, le=50, description="检索结果数")
    project_id: str = Field("", description="工程 id（空=平台级通用查询；非空=该工程 + 平台级双层检索）")
    include_chat: bool = Field(True, description="是否同时检索现场群聊档案（第二检索源，独立库，带出处标注）")
    chat_top_k: int = Field(6, ge=0, le=20, description="群聊命中条数上限")


class QueryResponse(BaseModel):
    """Response for POST /api/query."""
    query: str
    answer: str
    mode: str            # "llm" | "evidence"
    llm_model: str
    llm_available: bool
    llm_error: str = ""
    traceable_count: int
    untraceable_count: int
    context: list[dict]  # provenance-carrying context items
    chat_used: bool = False          # 是否用到了群聊证据
    chat_items: list[dict] = []      # 群聊出处（group/date/time/sender/content）


@app.get("/api/health")
def api_health():
    """Lightweight health check; does not touch the database or vector index."""
    return {"status": "ok"}


@app.get("/api/status")
def api_status():
    """System status (with lazy caching for vector index / LLM)."""
    cfg = get_config()
    init_database()
    session = get_session()
    repo = DrawingRepository(session)
    stats = repo.get_database_stats()
    session.close()

    try:
        vi = _get_cached_vector_index()
        vector_backend = vi.backend
        vector_chunks = vi.count()
    except Exception as e:
        logger.warning(f"Vector index stats unavailable: {e}")
        vector_backend = "unavailable"
        vector_chunks = -1

    try:
        llm = _get_cached_llm_client()
        llm_available = llm.available
        llm_model = llm.model
    except Exception as e:
        logger.warning(f"LLM client unavailable: {e}")
        llm_available = False
        llm_model = "unavailable"

    return {
        "status": "ok",
        "version": "0.7.0",
        "drawings": stats["drawings"],
        "entities": stats["entities"],
        "texts": stats["texts"],
        "equipment": stats["equipment"],
        "relationships": stats["relationships"],
        "vector_backend": vector_backend,
        "vector_chunks": vector_chunks,
        "llm_available": llm_available,
        "llm_model": llm_model,
    }


@app.get("/api/drawings")
def api_drawings(limit: int = Query(20, ge=1, le=200), offset: int = Query(0, ge=0)):
    """List drawings."""
    init_database()
    session = get_session()
    repo = DrawingRepository(session)
    rows = repo.list_drawings(limit=limit, offset=offset)
    session.close()
    return [
        {
            "drawing_id": d.drawing_id,
            "file_name": d.file_name,
            "file_type": d.file_type,
            "parse_status": d.parse_status,
            "entity_count": d.entity_count,
            "text_count": d.text_count,
            "data_completeness": d.data_completeness,
        }
        for d in rows
    ]


@app.get("/api/drawings/{drawing_id}")
def api_drawing_detail(drawing_id: str):
    """Get a drawing's details."""
    init_database()
    session = get_session()
    repo = DrawingRepository(session)
    d = repo.find_by_id(drawing_id)
    if not d:
        session.close()
        raise HTTPException(status_code=404, detail="图纸不存在")
    data = repo.get_drawing_summary(drawing_id)
    data["file_name"] = d.file_name
    data["file_type"] = d.file_type
    session.close()
    return data


@app.get("/api/search")
def api_search(
    q: str = Query(..., description="搜索关键词"),
    search_type: str = Query("all"),
    limit: int = Query(20, ge=1, le=100),
):
    """Unified search."""
    init_database()
    svc = SearchService()
    try:
        results = svc.search(query=q, search_type=search_type, limit=limit)
        return [
            {
                "result_type": r.result_type,
                "content": r.content,
                "drawing_id": r.drawing_id,
                "file_name": r.file_name,
                "layer": r.layer,
                "handle": r.handle,
                "score": r.score,
            }
            for r in results
        ]
    finally:
        svc.close()


@app.get("/api/rag")
def api_rag(q: str = Query(..., description="检索问题"), top_k: int = Query(10, ge=1, le=50)):
    """Hybrid RAG retrieval (no LLM)."""
    from src.rag.hybrid_search import hybrid_search
    from src.rag.reranker import rerank

    results = hybrid_search(q, top_k=top_k * 2)
    results = rerank(q, results, top_k=top_k)
    return results


@app.post("/api/query")
def api_query(req: QueryRequest):
    """AI QA with source traceability (P1: project-scoped double-layer retrieval).

    双源检索（2026-11-11）：
      - 源1 受控技术文件（cadkb.db：图纸/设备表/台账/厂家资料）
      - 源2 现场群聊档案（chat_archive.db，独立库，只读；include_chat 开关，默认开）
    群聊结果在回答中以「据群聊」标注，并在 chat_items 里带出处。
    """
    init_database()
    qa = QAService(llm_client=get_llm_client())
    ans = qa.ask(req.query, top_k=req.top_k, project_id=req.project_id,
                 include_chat=req.include_chat, chat_top_k=req.chat_top_k)

    return QueryResponse(
        query=ans.query,
        answer=ans.answer,
        mode=ans.mode,
        llm_model=ans.llm_model,
        llm_available=ans.llm_available,
        llm_error=ans.llm_error,
        traceable_count=ans.traceable_count,
        untraceable_count=ans.untraceable_count,
        context=[
            {
                "content": c.content,
                "source": c.source.model_dump(),
                "data_tier": c.data_tier,
                "confidence": c.confidence,
            }
            for c in ans.context_items
        ],
        chat_used=ans.chat_used,
        chat_items=ans.chat_items,
    )


@app.get("/api/site-chat/search")
def api_site_chat_search(
    q: str = Query(..., description="检索关键词/问题"),
    top_k: int = Query(10, ge=1, le=50),
    group: str = Query("", description="群名称（模糊，可空）"),
    date_from: str = Query("", description="起始日期 YYYY-MM-DD，可空"),
    date_to: str = Query("", description="截止日期 YYYY-MM-DD，可空"),
):
    """现场群聊档案直接检索（独立库，只读，供门户/脚本使用）。"""
    from src.core.site_chat_search import search_site_chat, stats as chat_stats

    if not q.strip():
        raise HTTPException(status_code=400, detail="请输入检索关键词")
    return {
        "query": q,
        "total_available": chat_stats().get("messages", 0),
        "items": search_site_chat(q, top_k=top_k, group=group or None,
                                  date_from=date_from or None,
                                  date_to=date_to or None),
    }


class AgentQueryRequest(BaseModel):
    """Request body for POST /api/agent/query."""
    query: str = Field(..., description="自然语言问题，例如：0203 子系统 CF0204ME01 吊装方案")
    top_k: int = Field(8, ge=1, le=50, description="检索结果数量")
    project_id: str = Field("", description="工程 id（空=平台级通用查询；非空=该工程 + 平台级双层检索）")


@app.post("/api/agent/query")
def api_agent_query(req: AgentQueryRequest):
    """Agent-oriented structured query: parses intent/entities, retrieves evidence,
    and lists information gaps. No LLM is used; safe for external agents."""
    from src.core.agent_query import agent_query, to_dict

    init_database()
    result = agent_query(req.query, top_k=req.top_k, project_id=req.project_id)
    return to_dict(result)


class GenerateRequest(BaseModel):
    """Request body for POST /api/generate."""
    doc_type: str = Field(..., description="文档类型: acceptance / hoisting / weekly / monthly")
    tag_no: str | None = Field(None, description="设备位号，acceptance/hoisting 必填")
    site_data: dict[str, Any] = Field(default_factory=dict, description="现场数据/约束（JSON 对象）")
    items: list[dict[str, Any]] = Field(default_factory=list, description="weekly/monthly 计划项")
    project_id: str = Field("", description="工程 id（空=平台级通用查询；非空=该工程 + 平台级双层检索）")
    output_path: str = Field("", description="输出目录（默认 CAD-KB 输出区；portal 传工程 04_输出/<日期>）")


@app.post("/api/generate")
def api_generate(req: GenerateRequest):
    """Generate engineering documents (acceptance record, hoisting plan, schedule)."""
    from src.core.document_generator import SiteData, generate_document

    init_database()
    site = SiteData()
    if req.site_data:
        site.actual_values = req.site_data
        site.crane_model = req.site_data.get("crane_model", "")
        site.crane_radius = req.site_data.get("crane_radius", "")
        site.boom_length = req.site_data.get("boom_length", "")
        site.lifting_weight = req.site_data.get("lifting_weight", "")
        site.weather = req.site_data.get("weather", "")
        site.inspectors = req.site_data.get("inspectors", "")
        site.inspection_date = req.site_data.get("inspection_date", "")
        site.remarks = req.site_data.get("remarks", "")

    try:
        path = generate_document(
            req.doc_type,
            tag_no=req.tag_no,
            site_data=site,
            items=req.items,
            output_path=req.output_path or None,
            project_id=req.project_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成失败: {e}")

    return {"status": "ok", "file_path": str(path), "doc_type": req.doc_type}


class CompareRequest(BaseModel):
    """Request body for POST /api/compare."""
    file_a: str = Field(..., description="第一张图纸路径")
    file_b: str = Field(..., description="第二张图纸路径")


@app.post("/api/compare")
def api_compare(req: CompareRequest):
    """Compare two drawings and return a difference report."""
    from pathlib import Path

    from src.compare import compare_drawings
    from src.file_manager.version_detector import get_file_info

    def parse_file(path: Path):
        info = get_file_info(path)
        ft = info["file_type"]
        if ft == "dwg":
            from src.parsers.dwg_parser import DWGParser
            result = DWGParser().parse(path)
        else:
            from src.parsers.dxf_parser import DXFParser
            result = DXFParser().parse(path)
        if result.drawing.parse_status != "success":
            raise HTTPException(status_code=422, detail=f"解析失败: {path} — {result.errors}")
        from src.semantic import analyze
        analyze(result)
        return result

    pa = Path(req.file_a)
    pb = Path(req.file_b)
    if not pa.exists() or not pb.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    try:
        ra = parse_file(pa)
        rb = parse_file(pb)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

    report = compare_drawings(ra, rb, pa.name, pb.name)
    return {
        "drawing_a": pa.name,
        "drawing_b": pb.name,
        "summary": report.summary,
        "total_changes": report.total_changes,
        "entity_added": [e.model_dump() for e in report.entity_added],
        "entity_removed": [e.model_dump() for e in report.entity_removed],
        "entity_modified": [e.model_dump() for e in report.entity_modified],
        "texts_added": [t.model_dump() for t in report.texts_added],
        "texts_removed": [t.model_dump() for t in report.texts_removed],
        "texts_modified": [t.model_dump() for t in report.texts_modified],
        "dimensions_added": [d.model_dump() for d in report.dimensions_added],
        "dimensions_removed": [d.model_dump() for d in report.dimensions_removed],
        "dimensions_modified": [d.model_dump() for d in report.dimensions_modified],
        "equipment_added": report.equipment_added,
        "equipment_removed": report.equipment_removed,
        "title_field_changes": [t.model_dump() for t in report.title_field_changes],
    }


# ═══ Phase 6: 统一 Agent/多格式接口 ═════════════════════════════════

@app.get("/api/files")
def api_files(
    q: str = Query("", description="关键词（空=全部）"),
    source_type: str = Query("", description="cad/word/excel/pdf/project/image/other"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """统一文件列表/搜索（跨格式元数据）。"""
    init_database()
    from src.core.file_registry import FileRegistry

    reg = FileRegistry()
    try:
        if q:
            results = reg.search_files(q, limit=limit)
        else:
            results = reg.list_files(
                source_type=source_type or None, limit=limit, offset=offset)
        return {"count": len(results), "files": results}
    finally:
        reg.close()


@app.get("/api/files/{file_id}")
def api_file_detail(file_id: str):
    """文件详情（含解析产物路径）。"""
    init_database()
    from src.core.agent_api import get_file, get_original_file, get_parsed_data

    rec = get_file(file_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"file_id 不存在: {file_id}")
    parsed = get_parsed_data(file_id)
    return {
        **rec,
        "original_file": get_original_file(file_id),
        "parsed_data": parsed if "error" not in parsed else None,
    }


@app.get("/api/search-all")
def api_search_all(
    q: str = Query(..., description="统一搜索关键词"),
    source_type: str = Query("", description="过滤类型"),
    limit: int = Query(30, ge=1, le=100),
    project_id: str = Query("", description="工程 id（空=平台级通用查询；非空=该工程 + 平台级双层检索）"),
):
    """跨格式统一搜索（CAD + 文档 + 文件元数据）。"""
    init_database()
    from src.core.unified_search import search_all

    return search_all(
        q, limit=limit,
        source_types=[source_type] if source_type else None,
        project_id=project_id,
    )


@app.get("/api/projects")
def api_projects():
    """列出全部推断项目。"""
    init_database()
    from src.core.agent_api import search_projects

    return search_projects()


@app.get("/api/projects/{name}/files")
def api_project_files(name: str, limit: int = Query(100, ge=1, le=500)):
    """指定项目的全部文件（CAD+文档）。"""
    init_database()
    from src.core.agent_api import search_by_project

    files = search_by_project(name, limit=limit)
    if not files:
        return {"project": name, "files": []}
    return {"project": name, "count": len(files), "files": files}


@app.get("/api/documents/{file_id}/content")
def api_document_content(file_id: str):
    """文档解析内容（用于 Agent 进一步分析）。"""
    init_database()
    from src.core.agent_api import get_parsed_data

    data = get_parsed_data(file_id)
    if "error" in data:
        raise HTTPException(status_code=404, detail=data["error"])
    return data


# ═══ Phase 3: 设备档案 API ════════════════════════════════════════

@app.get("/api/devices")
def api_devices(
    q: str = Query("", description="位号/名称关键词"),
    subsystem: str = Query("", description="子系统编号过滤"),
    limit: int = Query(50, ge=1, le=500),
):
    """列出设备主数据，支持按子系统或关键词搜索。"""
    from src.core.device_profile import list_devices_by_subsystem, search_devices

    if q:
        return {"query": q, "devices": search_devices(q, limit=limit)}
    return {"subsystem": subsystem, "devices": list_devices_by_subsystem(subsystem or None, limit=limit)}


@app.get("/api/devices/{tag_no}/profile")
def api_device_profile(tag_no: str, project_id: str = Query("", description="工程 id（空=平台级；非空=该工程+平台级双层）")):
    """按位号返回完整设备档案（跨图位置、箱单、文档）。"""
    from src.core.device_profile import get_device_profile

    profile = get_device_profile(tag_no, project_id=project_id)
    if not profile["found"]:
        raise HTTPException(status_code=404, detail=f"未找到位号: {tag_no}")
    return profile
