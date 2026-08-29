"""Agent-oriented knowledge base query (Phase 7 extension).

Provides structured, evidence-based answers for WorkBuddy / external agents.
Pipeline:
1. Parse user question: extract tag numbers, subsystem codes, intent keywords.
2. Multi-route retrieval: device profile, subsystem drawings, unified search,
   packing lists, elevations.
3. Gap analysis: list missing information needed for a complete answer.
4. Return structured JSON for downstream generation (plans, hoisting schemes,
   acceptance records).

No LLM is used here; the module is read-only and evidence-only.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text

from src.core.device_profile import get_device_profile
from src.core.unified_search import search_all
from src.database.connection import get_session
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.agent_query")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TAG_PATTERNS = [
    re.compile(r"\b[A-Z]{2}\d{4}[A-Z]{2}\d{2,3}\b", re.IGNORECASE),   # e.g. CF0204ME01
    re.compile(r"\b[A-Z]{2}\d{4}[A-Z]{2}\d{2,3}[A-Z]?\d?\b", re.IGNORECASE),
    re.compile(r"\bTK\d{4}[A-Z]{2}\d{2,3}\b", re.IGNORECASE),        # e.g. TK0301ME11
]

SUBSYSTEM_PATTERNS = [
    re.compile(r"\b0?\d{3,4}\b"),                                     # 0203, 0301
    re.compile(r"子系统\s*(\d+)", re.IGNORECASE),
    re.compile(r"子项\s*(\d+)", re.IGNORECASE),
]

INTENT_KEYWORDS = {
    "hoisting": ["吊装", "吊运", "起重", "吊车", "站位", "半径"],
    "schedule": ["周计划", "月计划", "进度", "排期", "施工计划"],
    "acceptance": ["验收", "报验", "检验", "记录表", "试车"],
    "drawing": ["图纸", "图号", "CAD", "DWG", "在哪张图"],
    "spec": ["参数", "规格", "型号", "尺寸", "重量", "外形"],
    "vendor": ["厂家", "供应商", "箱单", "packing", "大一重工"],
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ParsedQuestion:
    raw: str
    tags: list[str] = field(default_factory=list)
    subsystems: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    intent: str = "general"


@dataclass
class AgentQueryResult:
    parsed: ParsedQuestion
    evidence: list[dict[str, Any]] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    suggested_next: list[str] = field(default_factory=list)
    summary: str = ""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _normalize_tag(tag: str) -> str:
    return tag.upper().replace("-", "").replace("_", "").replace(" ", "")


def parse_question(query: str) -> ParsedQuestion:
    """Extract entities and intent from a natural-language question."""
    q = query.strip()
    parsed = ParsedQuestion(raw=q)

    # Tags
    seen_tags = set()
    for pat in TAG_PATTERNS:
        for m in pat.finditer(q):
            t = m.group(0).upper()
            nt = _normalize_tag(t)
            if nt not in seen_tags:
                seen_tags.add(nt)
                parsed.tags.append(t)

    # Subsystem codes
    seen_subs = set()
    for pat in SUBSYSTEM_PATTERNS:
        for m in pat.finditer(q):
            code = m.group(1) if m.lastindex else m.group(0)
            code = code.zfill(4)
            if code not in seen_subs:
                seen_subs.add(code)
                parsed.subsystems.append(code)

    # Intent
    intent_scores = {k: 0 for k in INTENT_KEYWORDS}
    for intent, kws in INTENT_KEYWORDS.items():
        for kw in kws:
            if kw in q:
                intent_scores[intent] += 1
    best = max(intent_scores, key=intent_scores.get)
    parsed.intent = best if intent_scores[best] > 0 else "general"

    # Keywords (simple fallback)
    parsed.keywords = [w for w in re.split(r"[，。！？、\s]+", q) if len(w) >= 2]

    return parsed


# ---------------------------------------------------------------------------
# Retrieval helpers
# ---------------------------------------------------------------------------

def _get_drawings_for_subsystem(subsystem: str, limit: int = 20) -> list[dict[str, Any]]:
    """Subsystem codes are stored in file_relations.relation_type='belongs_to_subsystem'.
    file_a is a file_id; we join through files.drawing_id to drawings.
    """
    session = get_session()
    try:
        rows = session.execute(
            text("""
                SELECT d.drawing_id, d.file_name, fr.file_b AS subsystem_name,
                       f.file_id, f.original_path
                FROM file_relations fr
                JOIN files f ON f.file_id = fr.file_a
                JOIN drawings d ON d.drawing_id = f.drawing_id
                WHERE fr.relation_type = 'belongs_to_subsystem'
                  AND fr.file_b LIKE :sub
                ORDER BY d.file_name
                LIMIT :lim
            """),
            {"sub": f"{subsystem}%", "lim": limit},
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "type": "drawing",
                "drawing_id": r[0],
                "file_name": r[1],
                "subsystem": r[2],
                "sheet_title": "",
                "file_id": r[3],
                "path": r[4],
            })
        return out
    finally:
        session.close()


def _get_packing_by_keyword(keyword: str, limit: int = 10) -> list[dict[str, Any]]:
    session = get_session()
    try:
        q = f"%{keyword}%"
        rows = session.execute(
            text("""
                SELECT packing_no, equip_name, vendor, qty, source_file_id
                FROM packing_items
                WHERE equip_name LIKE :q OR packing_no LIKE :q OR vendor LIKE :q
                ORDER BY packing_no
                LIMIT :lim
            """),
            {"q": q, "lim": limit},
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "type": "packing_item",
                "packing_no": r[0],
                "equip_name": r[1],
                "vendor": r[2],
                "qty": r[3],
                "source_file_id": r[4],
            })
        return out
    finally:
        session.close()


def _get_elevations_for_subsystem(subsystem: str) -> list[dict[str, Any]]:
    session = get_session()
    try:
        rows = session.execute(
            text("""
                SELECT d.file_name, e.datum_elevation, e.datum_type,
                       e.raw_text, e.confidence, e.verified
                FROM elevations e
                JOIN drawings d ON d.drawing_id = e.drawing_id
                JOIN files f ON f.drawing_id = d.drawing_id
                JOIN file_relations fr ON fr.file_a = f.file_id
                WHERE fr.relation_type = 'belongs_to_subsystem'
                  AND fr.file_b LIKE :sub
                ORDER BY e.confidence DESC
            """),
            {"sub": f"{subsystem}%"},
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "type": "elevation",
                "drawing": r[0],
                "datum_elevation": r[1],
                "datum_type": r[2],
                "raw_text": r[3],
                "confidence": r[4],
                "verified": bool(r[5]),
            })
        return out
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Main agent query
# ---------------------------------------------------------------------------

def agent_query(query: str, top_k: int = 8) -> AgentQueryResult:
    """Entry point for agent-oriented knowledge base query."""
    parsed = parse_question(query)
    result = AgentQueryResult(parsed=parsed)
    evidence: list[dict[str, Any]] = []
    gaps: list[str] = []

    logger.info(f"Agent query: {query} | tags={parsed.tags} | subs={parsed.subsystems} | intent={parsed.intent}")

    # 1. Device profile by tag
    for tag in parsed.tags:
        profile = get_device_profile(tag)
        if profile.get("found"):
            evidence.append({
                "type": "device_profile",
                "tag_no": tag,
                "data": profile,
            })
        else:
            gaps.append(f"未找到位号 {tag} 的设备档案")

    # 2. Subsystem drawings
    for sub in parsed.subsystems:
        drawings = _get_drawings_for_subsystem(sub)
        if drawings:
            evidence.append({
                "type": "subsystem_drawings",
                "subsystem": sub,
                "count": len(drawings),
                "drawings": drawings[:10],
            })
        else:
            gaps.append(f"未找到子系统 {sub} 的图纸")

    # 3. Unified search for keywords / generic query
    if parsed.intent not in ("drawing",) or not parsed.tags and not parsed.subsystems:
        try:
            uni = search_all(query, limit=top_k)
            if uni:
                evidence.append({
                    "type": "unified_search",
                    "count": len(uni),
                    "results": uni,
                })
        except Exception as e:
            logger.warning(f"统一搜索失败: {e}")

    # 4. Packing / vendor lookup
    for tag in parsed.tags:
        pk = _get_packing_by_keyword(tag)
        if pk:
            evidence.append({
                "type": "packing_lookup",
                "tag_no": tag,
                "items": pk,
            })
    if parsed.intent == "vendor" and parsed.keywords:
        for kw in parsed.keywords[:3]:
            pk = _get_packing_by_keyword(kw)
            if pk:
                evidence.append({
                    "type": "packing_lookup",
                    "keyword": kw,
                    "items": pk,
                })

    # 5. Elevations for subsystems
    for sub in parsed.subsystems:
        elevs = _get_elevations_for_subsystem(sub)
        if elevs:
            evidence.append({
                "type": "elevations",
                "subsystem": sub,
                "count": len(elevs),
                "items": elevs[:5],
            })

    # 6. Gap analysis & suggested next steps
    if parsed.intent == "hoisting":
        for tag in parsed.tags:
            profile = next((e["data"] for e in evidence if e.get("type") == "device_profile" and e.get("tag_no") == tag), {})
            occs = profile.get("occurrences", [])
            if not occs:
                gaps.append(f"位号 {tag} 缺少出现位置（图纸/坐标）")
            # Check for weight/size info in unified search / documents
            # (heuristic: we cannot know for sure without domain extraction)
            gaps.append(f"位号 {tag} 的重量、外形尺寸、吊装点数据需从设备图/说明书中提取")
        if not parsed.tags:
            gaps.append("吊装方案需要明确设备位号或设备名称")

    elif parsed.intent == "schedule":
        if not parsed.subsystems:
            gaps.append("施工计划需要指定子系统或施工区域")
        gaps.append("计划生成需要 Project/Excel 进度模板或里程碑约束")

    elif parsed.intent == "acceptance":
        for tag in parsed.tags:
            gaps.append(f"位号 {tag} 的验收记录需要现场实测数据（如安装尺寸、振动、温度等）")

    elif parsed.intent == "spec":
        for tag in parsed.tags:
            gaps.append(f"位号 {tag} 的完整参数需核对设备图、说明书、装箱单")

    result.evidence = evidence
    result.gaps = list(set(gaps))

    # Summary
    parts = []
    if parsed.tags:
        parts.append(f"识别到位号：{', '.join(parsed.tags)}")
    if parsed.subsystems:
        parts.append(f"识别到子系统：{', '.join(parsed.subsystems)}")
    parts.append(f"意图：{parsed.intent}")
    parts.append(f"证据条数：{len(evidence)}")
    if result.gaps:
        parts.append(f"信息缺口：{len(result.gaps)} 项")
    result.summary = "；".join(parts)

    result.suggested_next = _suggest_next(parsed, result.gaps)
    return result


def _suggest_next(parsed: ParsedQuestion, gaps: list[str]) -> list[str]:
    """Generate actionable next-step suggestions."""
    out = []
    if parsed.intent == "hoisting":
        out.append("补充设备重量、外形尺寸、重心位置、现场场地条件")
        out.append("查询吊装机械性能表，校核最小吊装半径")
    elif parsed.intent == "schedule":
        out.append("提供 Project/Excel 模板或关键里程碑日期")
        out.append("明确各子系统施工先后顺序约束")
    elif parsed.intent == "acceptance":
        out.append("提供现场实测数据或验收标准规范编号")
        out.append("确认验收记录表模板格式")
    elif parsed.intent == "spec":
        out.append("核对设备图、说明书、装箱单中的参数表")
    if not parsed.tags and parsed.intent in ("hoisting", "spec", "acceptance"):
        out.append("提供具体设备位号以获得更精确的检索结果")
    if gaps:
        out.append("按信息缺口补充资料后重新查询")
    return out


def to_dict(result: AgentQueryResult) -> dict[str, Any]:
    """Serialize result to plain dict."""
    return {
        "parsed": {
            "raw": result.parsed.raw,
            "tags": result.parsed.tags,
            "subsystems": result.parsed.subsystems,
            "keywords": result.parsed.keywords,
            "intent": result.parsed.intent,
        },
        "evidence": result.evidence,
        "gaps": result.gaps,
        "suggested_next": result.suggested_next,
        "summary": result.summary,
    }
