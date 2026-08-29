"""CLI tool for CAD Knowledge Base.

Usage:
    cadkb import <file>              Import a single CAD file
    cadkb import <dir> --recursive   Import all CAD files from a directory
    cadkb inspect <file>             Inspect a file's parse results
    cadkb inspect <file> --entities  Show entities
    cadkb inspect <file> --texts     Show texts
    cadkb inspect <file> --dims      Show dimensions
    cadkb search <query>             Full-text search
    cadkb status                     Show system status
"""

import json
import sys
from pathlib import Path

import click

from src.core.config import get_config
from src.database.connection import get_session, init_database
from src.database.repositories import DrawingRepository
from src.file_manager.importer import import_directory, import_file
from src.file_manager.version_detector import get_file_info
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.cli")


@click.group()
@click.option("--json-output", is_flag=True, help="Output as JSON")
@click.pass_context
def cli(ctx, json_output):
    """CAD Knowledge Base — 本地 CAD 图纸解析与知识库系统."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_output


@cli.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--recursive", "-r", is_flag=True, help="Recursively import directory")
@click.option("--force", "-f", is_flag=True, help="Re-parse even if file exists")
def import_cmd(path, recursive, force):
    """Import CAD file(s) into the knowledge base."""
    p = Path(path)

    if p.is_dir():
        click.echo(f"批量导入: {p}")
        results = import_directory(p, recursive=recursive, force=force)

        success = sum(1 for r in results if r.get("status") == "success")
        duplicates = sum(1 for r in results if r.get("status") == "duplicate")
        errors = sum(1 for r in results if r.get("status") in ("error", "failed"))

        click.echo(f"\n导入完成: {len(results)} 个文件")
        click.echo(f"  成功: {success}")
        click.echo(f"  重复: {duplicates}")
        click.echo(f"  失败: {errors}")

        for r in results:
            status = r.get("status", "unknown")
            name = r.get("file_name", "?")
            msg = r.get("message", "")
            if status == "success":
                click.echo(f"  [{status}] {name} — entities={r.get('entity_count', 0)}")
            else:
                click.echo(f"  [{status}] {name} — {msg}")
    else:
        result = import_file(p, force=force)
        _print_result(result)


@cli.command(name="inspect")
@click.argument("path", type=click.Path(exists=True))
@click.option("--entities", "-e", is_flag=True, help="Show entities")
@click.option("--texts", "-t", is_flag=True, help="Show texts")
@click.option("--dims", "-d", is_flag=True, help="Show dimensions")
@click.option("--semantic", "-s", is_flag=True, help="Show semantic analysis results (图框/标题栏/设备/管道)")
@click.option("--spatial", "-sp", is_flag=True, help="Show spatial relationships (空间关系)")
@click.option("--limit", "-l", default=20, help="Max items to show")
def inspect_cmd(path, entities, texts, dims, semantic, spatial, limit):
    """Inspect a CAD file's information and parse results."""
    p = Path(path)

    # Get file info (without parsing)
    info = get_file_info(p)
    click.echo("=" * 60)
    click.echo("文件信息")
    click.echo("=" * 60)
    click.echo(f"  文件名:     {info.get('file_name', '?')}")
    click.echo(f"  文件大小:   {_format_size(info.get('file_size', 0))}")
    click.echo(f"  文件类型:   {info.get('file_type', '?')}")
    click.echo(f"  CAD 版本:   {info.get('cad_version', '?')} ({info.get('cad_version_name', '?')})")

    # Try to find in database
    init_database()
    session = get_session()
    repo = DrawingRepository(session)

    from src.file_manager.hasher import compute_sha256
    try:
        file_hash = compute_sha256(p)
    except Exception:
        file_hash = ""

    draw = repo.find_by_hash(file_hash) if file_hash else None

    if draw:
        click.echo(f"\n{'=' * 60}")
        click.echo("解析结果")
        click.echo("=" * 60)
        click.echo(f"  Drawing ID:   {draw.drawing_id}")
        click.echo(f"  解析状态:     {draw.parse_status}")
        click.echo(f"  解析器:       {draw.parser} {draw.parser_version}")
        click.echo(f"  单位:         {draw.units}")
        click.echo(f"  实体数:       {draw.entity_count}")
        click.echo(f"  文字数:       {draw.text_count}")
        click.echo(f"  尺寸数:       {draw.dimension_count}")
        click.echo(f"  图层数:       {draw.layer_count}")
        click.echo(f"  块定义:       {draw.block_count}")
        click.echo(f"  布局数:       {draw.layout_count}")
        click.echo(f"  数据完整度:   {draw.data_completeness:.1%}")

        if entities:
            click.echo(f"\n{'=' * 60}")
            click.echo(f"实体列表 (前{limit}个)")
            click.echo("=" * 60)
            ents = repo.get_entities_by_drawing(draw.drawing_id, limit=limit)
            for e in ents:
                click.echo(
                    f"  [{e['entity_type']:12s}] handle={e['handle']:8s} "
                    f"layer={e['layer']:20s} "
                    f"bbox=({e['bbox']['min_x']:.1f},{e['bbox']['min_y']:.1f})-"
                    f"({e['bbox']['max_x']:.1f},{e['bbox']['max_y']:.1f})"
                )

        if texts:
            click.echo(f"\n{'=' * 60}")
            click.echo(f"文字列表 (前{limit}个)")
            click.echo("=" * 60)
            txts = repo.get_texts_by_drawing(draw.drawing_id, limit=limit)
            for t in txts:
                text_preview = t["text_content"][:60]
                click.echo(f"  [{t['text_type']:5s}] layer={t['layer']:15s} | {text_preview}")

        if dims:
            click.echo(f"\n{'=' * 60}")
            click.echo(f"尺寸列表 (前{limit}个)")
            click.echo("=" * 60)
            ds = repo.get_dimensions_by_drawing(draw.drawing_id, limit=limit)
            for d in ds:
                click.echo(
                    f"  [{d['dimension_type']:8s}] value={d['measurement']:10.2f} "
                    f"text={d['text_content']:20s} layer={d['layer']}"
                )

        if semantic:
            _print_semantic(repo, draw.drawing_id)

        if spatial:
            _print_spatial(repo, draw.drawing_id)
    else:
        click.echo("\n  (此文件尚未导入知识库，使用 'cadkb import' 导入)")

    session.close()


def _print_spatial(repo, drawing_id: str, limit: int = 30):
    """Print spatial relationships (Phase 4)."""
    click.echo(f"\n{'=' * 60}")
    click.echo(f"空间关系 (前{limit}条)")
    click.echo("=" * 60)

    rels = repo.get_relationships_by_drawing(drawing_id, limit=limit)
    if not rels:
        click.echo("  (无空间关系)")
        return

    for r in rels:
        a = r["entity_a_type"] or "?"
        b = r["entity_b_type"] or "?"
        dist = f"dist={r['distance']:.1f}" if r["distance"] is not None else "dist=0"
        click.echo(
            f"  [{r['relationship_type']:10s}] {a:12s} → {b:12s} "
            f"{dist} conf={r['confidence']:.2f}"
        )


def _print_semantic(repo, drawing_id: str):
    """Print semantic analysis results (Phase 3)."""
    click.echo(f"\n{'=' * 60}")
    click.echo("语义分析结果")
    click.echo("=" * 60)

    # 图框
    frames = repo.get_frames_by_drawing(drawing_id)
    if frames:
        click.echo("\n[图框]")
        for f in frames:
            click.echo(
                f"  {f['width']:.0f}x{f['height']:.0f} 图层={f['layer']} "
                f"置信度={f['confidence']:.2f} 源={f['source']}"
            )
    else:
        click.echo("\n[图框] (未识别)")

    # 标题栏
    tbs = repo.get_title_blocks_by_drawing(drawing_id)
    if tbs:
        click.echo("\n[标题栏]")
        for tb in tbs:
            click.echo(f"  区域 {tb['width']:.0f}x{tb['height']:.0f} 置信度={tb['confidence']:.2f}")
            for fl in tb["fields"]:
                click.echo(
                    f"    {fl['key']}: {fl['value']!r} "
                    f"(conf={fl['confidence']:.2f})"
                )
    else:
        click.echo("\n[标题栏] (未识别)")

    # 设备
    eqs = repo.get_equipment_by_drawing(drawing_id)
    if eqs:
        click.echo("\n[设备]")
        for e in eqs:
            click.echo(
                f"  {e['equipment_no'] or '?'} | {e['equipment_name'] or '?'} "
                f"块={e['block_name']} 置信度={e['confidence']:.2f}"
            )
    else:
        click.echo("\n[设备] (未识别)")

    # 管道
    pipes = repo.get_pipes_by_drawing(drawing_id)
    if pipes:
        click.echo("\n[管道]")
        for pp in pipes:
            click.echo(
                f"  {pp['pipe_no'] or '?'} 管径={pp['diameter'] or '?'} "
                f"材质={pp['material'] or '?'} 置信度={pp['confidence']:.2f}"
            )
    else:
        click.echo("\n[管道] (未识别)")


@cli.command()
@click.argument("query")
@click.option("--type", "search_type", default="all",
              type=click.Choice(["all", "text", "attribute", "equipment", "title_field", "entity", "drawing", "dimension"]),
              help="Result type filter")
@click.option("--layer", default=None, help="Filter by layer name")
@click.option("--entity-type", "entity_type", default=None, help="Filter by entity type (e.g. LINE)")
@click.option("--limit", "-l", default=20, help="Max results")
def search(query, search_type, layer, entity_type, limit):
    """Unified search: full-text + structured + spatial."""
    from src.index.search_service import SearchService

    svc = SearchService()
    try:
        results = svc.search(
            query=query,
            search_type=search_type,
            layer=layer,
            entity_type=entity_type,
            limit=limit,
        )
    finally:
        svc.close()

    click.echo(f"搜索: '{query}' (type={search_type}) — 找到 {len(results)} 条结果")
    click.echo("=" * 60)

    for r in results:
        loc = f"({r.x:.0f},{r.y:.0f})" if r.x is not None and r.y is not None else ""
        click.echo(f"  [{r.result_type:12s}] {r.content[:80]}")
        details = []
        if r.layer:
            details.append(f"图层={r.layer}")
        if r.file_name:
            details.append(f"文件={r.file_name}")
        if r.handle:
            details.append(f"handle={r.handle}")
        if loc:
            details.append(f"坐标={loc}")
        if details:
            click.echo(f"      {' | '.join(details)}")
        click.echo()

    if not results:
        click.echo("  (无结果)")


@cli.command(name="search-region")
@click.option("--min-x", type=float, required=True, help="Region min X")
@click.option("--min-y", type=float, required=True, help="Region min Y")
@click.option("--max-x", type=float, required=True, help="Region max X")
@click.option("--max-y", type=float, required=True, help="Region max Y")
@click.option("--type", "entity_types", multiple=True, help="Entity types to include (repeatable)")
@click.option("--limit", "-l", default=50, help="Max results")
def search_region(min_x, min_y, max_x, max_y, entity_types, limit):
    """Search entities inside a spatial region."""
    from src.index.search_service import search_in_region

    results = search_in_region(
        min_x=min_x, min_y=min_y, max_x=max_x, max_y=max_y,
        entity_types=list(entity_types) if entity_types else None,
        limit=limit,
    )

    click.echo(f"区域搜索: ({min_x},{min_y})-({max_x},{max_y}) — 找到 {len(results)} 条结果")
    click.echo("=" * 60)
    for r in results:
        click.echo(f"  [{r.result_type:8s}] {r.content}")
        details = []
        if r.file_name:
            details.append(f"文件={r.file_name}")
        if r.handle:
            details.append(f"handle={r.handle}")
        if details:
            click.echo(f"      {' | '.join(details)}")


@cli.command()
@click.argument("query")
@click.option("--top-k", "-k", default=10, help="Max results")
@click.option("--no-rerank", is_flag=True, help="Skip re-ranking")
def rag(query, top_k, no_rerank):
    """RAG 混合检索：全文 + 向量 + 结构化 + 重排序."""
    from src.rag.hybrid_search import hybrid_search
    from src.rag.reranker import rerank

    results = hybrid_search(query, top_k=top_k * 2)
    if not no_rerank:
        results = rerank(query, results, top_k=top_k)

    click.echo(f"RAG 检索: '{query}' — 返回 {len(results)} 条结果")
    click.echo("=" * 60)
    for r in results:
        click.echo(f"  [{r['source_type']:12s}] {r['content'][:80]}")
        details = []
        if r.get("layer"):
            details.append(f"图层={r['layer']}")
        if r.get("handle"):
            details.append(f"handle={r['handle']}")
        if r.get("file_name"):
            details.append(f"文件={r['file_name']}")
        if r.get("fts_score") is not None or r.get("vector_score") is not None:
            fts = r.get("fts_score") if r.get("fts_score") is not None else 0.0
            vec = r.get("vector_score") if r.get("vector_score") is not None else 0.0
            details.append(f"FTS={fts:.2f} 向量={vec:.2f}")
        details.append(f"得分={r.get('relevance', r.get('score', 0)):.3f}")
        if details:
            click.echo(f"      {' | '.join(details)}")
        click.echo()

    if not results:
        click.echo("  (无结果)")


@cli.command(name="rebuild-index")
@click.option("--embeddings", "emb", is_flag=True, help="Rebuild vector embeddings index")
def rebuild_index(emb):
    """Rebuild indexes (vector embeddings)."""
    if emb:
        from src.index.index_manager import rebuild_vector_index

        click.echo("重建向量索引...")
        n = rebuild_vector_index()
        click.echo(f"完成: 索引 {n} 个块")


@cli.command()
@click.argument("file_a", type=click.Path(exists=True))
@click.argument("file_b", type=click.Path(exists=True))
def compare(file_a, file_b):
    """比较两张 CAD 图纸的差异."""
    from src.file_manager.version_detector import detect_file_type
    from src.normalizer.schema import FileType

    def parse_file(path):
        from src.file_manager.version_detector import get_file_info
        info = get_file_info(path)
        ft = info["file_type"]
        if ft == FileType.DWG.value:
            from src.parsers.dwg_parser import DWGParser
            result = DWGParser().parse(path)
        else:
            from src.parsers.dxf_parser import DXFParser
            result = DXFParser().parse(path)
        if result.drawing.parse_status != "success":
            click.echo(f"解析失败: {path} — {result.errors}")
            return None
        from src.semantic import analyze
        analyze(result)
        return result

    click.echo(f"比较: {file_a} vs {file_b}")
    click.echo("=" * 60)

    result_a = parse_file(file_a)
    result_b = parse_file(file_b)
    if result_a is None or result_b is None:
        return

    from src.compare import compare_drawings

    report = compare_drawings(
        result_a, result_b,
        file_name_a=Path(file_a).name,
        file_name_b=Path(file_b).name,
    )

    s = report.summary
    click.echo(f"变更总数: {report.total_changes}")
    click.echo()
    click.echo("实体差异:")
    click.echo(f"  新增: {s['entities']['added']}  删除: {s['entities']['removed']}  修改: {s['entities']['modified']}")
    for e in report.entity_added[:20]:
        click.echo(f"    [+新增] [{e.entity_type}] {e.detail}")
    for e in report.entity_removed[:20]:
        click.echo(f"    [-删除] [{e.entity_type}] {e.detail}")
    for e in report.entity_modified[:20]:
        click.echo(f"    [~修改] [{e.entity_type}] handle={e.handle} {e.detail}")

    click.echo()
    click.echo("文字差异:")
    click.echo(f"  新增: {s['texts']['added']}  删除: {s['texts']['removed']}  修改: {s['texts']['modified']}")
    for t in report.texts_added[:20]:
        click.echo(f"    [+新增] {t.new_content!r} (layer={t.layer})")
    for t in report.texts_removed[:20]:
        click.echo(f"    [-删除] {t.old_content!r} (layer={t.layer})")
    for t in report.texts_modified[:20]:
        click.echo(f"    [~修改] {t.old_content!r} → {t.new_content!r} (layer={t.layer})")

    click.echo()
    click.echo("尺寸差异:")
    click.echo(f"  新增: {s['dimensions']['added']}  删除: {s['dimensions']['removed']}  修改: {s['dimensions']['modified']}")

    click.echo()
    click.echo("语义差异:")
    click.echo(f"  设备新增: {s['equipment']['added']}  设备删除: {s['equipment']['removed']}  标题栏字段变更: {s['title_fields']}")
    for e in report.equipment_added[:10]:
        click.echo(f"    [+设备] {e}")
    for e in report.equipment_removed[:10]:
        click.echo(f"    [-设备] {e}")
    for t in report.title_field_changes[:10]:
        click.echo(f"    [~标题栏] [{t.detail}] {t.old_content!r} → {t.new_content!r}")


@cli.command(name="device")
@click.argument("tag_or_query")
@click.option("--search", "search_mode", is_flag=True, help="搜索模式（按关键词列出设备）")
@click.option("--subsystem", "-s", default=None, help="按子系统过滤")
@click.option("--limit", "-l", default=20, help="最大结果数")
def device_cmd(tag_or_query, search_mode, subsystem, limit):
    """查看设备档案：cadkb device <位号>；搜索用 --search。"""
    from src.core.device_profile import get_device_profile, list_devices_by_subsystem, search_devices

    if search_mode:
        rows = search_devices(tag_or_query, limit=limit)
        click.echo(f"设备搜索 '{tag_or_query}' — {len(rows)} 条")
        for d in rows:
            click.echo(f"  {d['tag_no']:16s} | {d['category'] or '':10s} | {d['subsystem_no'] or '':6s} | {d['name'][:30]}")
        return

    if subsystem:
        rows = list_devices_by_subsystem(subsystem, limit=limit)
        click.echo(f"子系统 {subsystem} 设备 — {len(rows)} 条")
        for d in rows:
            click.echo(f"  {d['tag_no']:16s} | {d['category'] or '':10s} | {d['name'][:30]} | 跨 {d['drawing_count']} 图")
        return

    profile = get_device_profile(tag_or_query)
    if not profile["found"]:
        click.echo(f"未找到位号: {tag_or_query}")
        return

    click.echo("=" * 60)
    click.echo(f"设备档案: {profile['tag_no']} ({profile['category'] or '未知类别'})")
    click.echo("=" * 60)
    click.echo(f"  名称:       {profile['name']}")
    click.echo(f"  子系统:     {profile['subsystem_no']}")
    click.echo(f"  跨图数:     {profile['drawing_count']}")
    click.echo(f"  标注点数:   {profile['occurrence_count']}")
    click.echo(f"  置信度:     {profile['confidence']:.2f}")

    click.echo("\n出现位置:")
    for occ in profile["occurrences"][:limit]:
        preview = "[有预览]" if occ["preview_path"] else "[无预览]"
        elev = f" 标高={occ['elevation']['datum_elevation']}" if occ.get("elevation") else ""
        click.echo(f"  {occ['drawing_name'][:45]:45s} ({occ['x']:.0f}, {occ['y']:.0f}) {preview}{elev}")

    if profile["packing_lists"]:
        click.echo(f"\n箱单/供应商 ({len(profile['packing_lists'])} 条):")
        for p in profile["packing_lists"][:limit]:
            status = "待确认" if p["status"] == "pending" else p["status"]
            click.echo(f"  {p['packing_no']:16s} | {p['vendor'][:16]:16s} | {p['equip_name'][:25]} | [{status}]")

    if profile["documents"]:
        click.echo(f"\n关联文档 ({len(profile['documents'])} 条):")
        for d in profile["documents"][:limit]:
            status = "待确认" if d["status"] == "pending" else d["status"]
            click.echo(f"  [{d['file_type']:6s}] {d['file_name'][:40]} | [{status}]")

    if profile["pending_confirmations"]:
        click.echo(f"\n注意: {profile['pending_confirmations']} 条候选关系待人工确认")


@cli.command()
@click.argument("query")
@click.option("--top-k", "-k", default=8, help="Retrieval results to use")
def query(query, top_k):
    """AI 问答（RAG 检索 + LLM 生成，带来源追溯）."""
    from src.qa import ask_question

    init_database()
    ans = ask_question(query, top_k=top_k)

    click.echo(f"问题: {query}")
    click.echo("=" * 60)

    if ans.mode == "llm":
        click.echo(f"[AI 回答] ({ans.llm_model})")
        click.echo(ans.answer)
    else:
        click.echo("[证据模式] 未配置 LLM API Key 或 LLM 不可用，仅展示检索证据：")
        if ans.llm_error:
            click.echo(f"  (LLM 错误: {ans.llm_error})")

    click.echo()
    click.echo(f"来源追溯: {ans.traceable_count} 条可追溯 / {ans.untraceable_count} 条无法追溯")
    click.echo("-" * 60)
    for i, item in enumerate(ans.context_items, start=1):
        src = item.source
        loc = ""
        if src.file:
            loc += f"文件={src.file}"
        if src.layer:
            loc += f" 图层={src.layer}"
        if src.entity_handle:
            loc += f" handle={src.entity_handle}"
        if not loc:
            loc = "无法追溯来源"
        click.echo(f"  {i}. {item.content[:70]}")
        click.echo(f"     {loc}")

    if ans.untraceable_count > 0:
        click.echo("\n  注意: 部分上下文无法确认来源。")


@cli.command(name="agent-query")
@click.argument("query")
@click.option("--top-k", "-k", default=8, help="检索结果数量")
@click.option("--json-output", "-j", is_flag=True, help="输出 JSON")
def agent_query_cmd(query, top_k, json_output):
    """Agent 结构化查询（位号/子系统/意图识别 + 证据 + 缺口）."""
    from src.core.agent_query import agent_query, to_dict

    init_database()
    result = agent_query(query, top_k=top_k)
    data = to_dict(result)

    if json_output:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return

    click.echo(f"问题: {query}")
    click.echo("=" * 60)
    click.echo(data["summary"])
    click.echo()

    if data["gaps"]:
        click.echo("【信息缺口】")
        for g in data["gaps"]:
            click.echo(f"  - {g}")
        click.echo()

    click.echo(f"【证据】共 {len(data['evidence'])} 类")
    for ev in data["evidence"]:
        t = ev.get("type", "unknown")
        if t == "device_profile":
            prof = ev.get("data", {})
            click.echo(f"  [设备档案] {prof.get('tag_no')} | "
                       f"出现 {len(prof.get('occurrences', []))} 次 | "
                       f"文档 {len(prof.get('documents', []))} 份")
        elif t == "subsystem_drawings":
            click.echo(f"  [子系统图纸] {ev.get('subsystem')} 共 {ev.get('count')} 张")
            for d in ev.get("drawings", [])[:5]:
                click.echo(f"      - {d.get('file_name')}")
        elif t == "unified_search":
            click.echo(f"  [统一搜索] {ev.get('count')} 条结果")
            for r in ev.get("results", [])[:3]:
                click.echo(f"      - {r.get('file_name', '?')}: {r.get('snippet', '')[:50]}")
        elif t == "packing_lookup":
            tag = ev.get("tag_no") or ev.get("keyword")
            click.echo(f"  [箱单查询] {tag}: {len(ev.get('items', []))} 条")
            for it in ev.get("items", [])[:3]:
                click.echo(f"      - {it.get('packing_no')} {it.get('equip_name')} ({it.get('vendor')})")
        elif t == "elevations":
            click.echo(f"  [标高] 子系统 {ev.get('subsystem')} 共 {ev.get('count')} 条")
        else:
            click.echo(f"  [{t}] {json.dumps(ev, ensure_ascii=False)[:120]}")

    if data["suggested_next"]:
        click.echo()
        click.echo("【建议下一步】")
        for s in data["suggested_next"]:
            click.echo(f"  - {s}")


@cli.command()
@click.option("--host", default="127.0.0.1", help="Bind host")
@click.option("--port", "-p", default=8000, help="Bind port")
@click.option("--reload", is_flag=True, help="Auto-reload on code changes")
def serve(host, port, reload):
    """启动 REST API 服务."""
    import uvicorn

    config = get_config()
    config.ensure_directories()
    click.echo(f"启动 REST API: http://{host}:{port}")
    click.echo("  文档:  http://{host}:{port}/docs".format(host=host, port=port))
    uvicorn.run("src.api.app:app", host=host, port=port, reload=reload)


@cli.command()
@click.option("--port", "-p", default=8501, help="Streamlit port")
@click.option("--headless", is_flag=True, help="Run without auto-opening browser")
def gui(port, headless):
    """启动 Streamlit 图形界面."""
    import subprocess
    import sys

    from src.core.config import PROJECT_ROOT

    config = get_config()
    config.ensure_directories()

    cmd = [
        sys.executable, "-m", "streamlit", "run",
        str(PROJECT_ROOT / "src" / "gui" / "app.py"),
        "--server.port", str(port),
    ]
    if headless:
        cmd.append("--server.headless")
        cmd.append("true")

    click.echo(f"启动 GUI: http://localhost:{port}")
    click.echo("按 Ctrl+C 停止")
    subprocess.run(cmd)


@cli.command()
def status():
    """Show system status."""
    config = get_config()
    config.ensure_directories()
    init_database()

    session = get_session()
    repo = DrawingRepository(session)
    stats = repo.get_database_stats()

    oda_path = config.find_oda_converter()

    click.echo("=" * 60)
    click.echo("CAD Knowledge Base — 系统状态")
    click.echo("=" * 60)
    click.echo(f"  项目路径:     {Path.cwd()}")
    click.echo(f"  数据库:       {config.db_path}")
    click.echo(f"  知识库路径:   {config.kb_root}")
    click.echo()
    click.echo("数据统计:")
    click.echo(f"  图纸数:       {stats['drawings']}")
    click.echo(f"  实体数:       {stats['entities']}")
    click.echo(f"  文字数:       {stats['texts']}")
    click.echo(f"  尺寸数:       {stats['dimensions']}")
    click.echo(f"  图层数:       {stats['layers']}")
    click.echo(f"  块定义:       {stats['blocks']}")
    click.echo(f"  块属性:       {stats['attributes']}")
    click.echo()
    click.echo("语义分析统计:")
    click.echo(f"  图框:         {stats.get('frames', 0)}")
    click.echo(f"  标题栏:       {stats.get('title_blocks', 0)}")
    click.echo(f"  标题栏字段:   {stats.get('title_block_fields', 0)}")
    click.echo(f"  设备:         {stats.get('equipment', 0)}")
    click.echo(f"  管道:         {stats.get('pipes', 0)}")
    click.echo(f"  空间关系:     {stats.get('relationships', 0)}")
    click.echo()
    click.echo("环境检测:")
    click.echo(f"  ODA File Converter: {'已安装' if oda_path else '未安装'}")
    if oda_path:
        click.echo(f"    路径: {oda_path}")
    else:
        click.echo("    DWG 解析不可用，请安装 ODA File Converter")
        click.echo("    下载: https://www.opendesign.com/guestfiles/oda_file_converter")
    click.echo(f"  DXF 解析器:   ezdxf (已安装)")
    try:
        from src.index.vector_index import VectorIndex

        vi = VectorIndex()
        click.echo(f"  向量索引:     {vi.backend} ({vi.count()} 块)")
    except Exception:
        click.echo("  向量索引:     未初始化")

    session.close()


def _print_result(result: dict):
    """Print an import result."""
    status = result.get("status", "unknown")
    if status == "success":
        click.echo("=" * 60)
        click.echo("导入成功")
        click.echo("=" * 60)
        click.echo(f"  文件名:       {result.get('file_name', '?')}")
        click.echo(f"  Drawing ID:   {result.get('drawing_id', '?')}")
        click.echo(f"  文件类型:     {result.get('file_type', '?')}")
        click.echo(f"  CAD 版本:     {result.get('cad_version_name', '?')}")
        click.echo(f"  实体数:       {result.get('entity_count', 0)}")
        click.echo(f"  文字数:       {result.get('text_count', 0)}")
        click.echo(f"  尺寸数:       {result.get('dimension_count', 0)}")
        click.echo(f"  图层数:       {result.get('layer_count', 0)}")
        click.echo(f"  块定义:       {result.get('block_count', 0)}")
        click.echo(f"  数据完整度:   {result.get('data_completeness', 0):.1%}")

        qr = result.get("quality_report")
        if qr:
            click.echo()
            click.echo("质量报告:")
            for line in qr.split("\n"):
                click.echo(f"  {line}")
    elif status == "duplicate":
        click.echo(f"文件已存在: {result.get('file_name', '?')}")
        click.echo(f"  {result.get('message', '')}")
    else:
        click.echo(f"导入失败: {result.get('file_name', '?')}")
        click.echo(f"  {result.get('message', '')}")


def _format_size(size: int) -> str:
    """Format file size in human-readable form."""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.1f} GB"


def main():
    """Entry point for the CLI."""
    cli(obj={})


# ─── Phase 5: 统一搜索 / 项目 / 重新扫描 ─────────────────────────────

@cli.command(name="search-all")
@click.argument("query")
@click.option("--limit", "-l", default=20, help="Max results")
@click.option("--source-type", default=None,
              help="Filter: cad/word/excel/pdf/project/image/other")
def search_all_cmd(query, limit, source_type):
    """统一搜索：跨 CAD/Word/Excel/PDF/Project/图片。"""
    from src.core.unified_search import search_all

    source_types = [source_type] if source_type else None
    results = search_all(query, limit=limit, source_types=source_types)
    if not results:
        click.echo(f"未找到与 '{query}' 相关的内容")
        return
    click.echo(f"统一搜索 '{query}' — 返回 {len(results)} 条结果\n")
    for r in results:
        click.echo(
            f"  [{r['source_type']}] {r['file_name'][:50]}")
        if r.get("snippet"):
            click.echo(f"       {r['snippet'][:80]}")
        click.echo(f"       匹配: {r.get('match_type')} | "
                   f"file_id={str(r.get('file_id') or r.get('drawing_id'))[:12]}")
        if r.get("project_id") or r.get("project"):
            click.echo(f"       项目: {r.get('project') or r.get('project_id')}")


@cli.command(name="project")
@click.option("--list", "list_flag", is_flag=True, help="List all projects")
@click.option("--files", "files_of", default=None,
              help="Show files of a project name")
@click.option("--limit", "-l", default=50)
def project_cmd(list_flag, files_of, limit):
    """项目管理：列出推断出的项目或查看项目内文件。"""
    from src.core.project_inference import list_projects
    from src.core.unified_search import search_by_project

    if files_of:
        results = search_by_project(files_of, limit=limit)
        click.echo(f"项目 '{files_of}' 的文件（{len(results)}）:")
        for r in results:
            click.echo(f"  [{r['source_type']}] {r['file_name'][:55]}")
        return

    projects = list_projects()
    if not projects:
        click.echo("暂无项目（自动推断需置信度≥0.5）")
        return
    click.echo(f"共 {len(projects)} 个项目:\n")
    for p in projects:
        click.echo(
            f"  {p['name']} | 置信度 {p['confidence']:.2f} "
            f"| 来源 {p['source']} | 文件 {p['file_count']}")


@cli.command(name="export")
@click.option("--subsystem", "-s", default=None, help="按子系统过滤")
@click.option("--output", "-o", required=True, type=click.Path(), help="输出 Excel 路径")
def export_cmd(subsystem, output):
    """批量导出设备档案到 Excel。"""
    from src.core.export_service import export_device_profiles

    path = export_device_profiles(output, subsystem_no=subsystem)
    click.echo(f"导出完成: {path}")


@cli.command(name="generate")
@click.argument("doc_type", type=click.Choice(["acceptance", "hoisting", "weekly", "monthly"]))
@click.argument("tag_no", required=False)
@click.option("--output", "-o", type=click.Path(), help="输出文件路径（默认 Temp/generated/）")
@click.option("--data", "-d", default=None, help="JSON 格式现场数据，例如 '{\"重量\":\"10t\",\"水平度\":\"0.05\"}'")
def generate_cmd(doc_type, tag_no, output, data):
    """生成工程文档：acceptance(验收记录) / hoisting(吊装方案) / weekly(周计划) / monthly(月计划)."""
    from src.core.document_generator import SiteData, generate_document

    site_data = SiteData()
    if data:
        try:
            payload = json.loads(data)
            if isinstance(payload, dict):
                site_data.actual_values = payload
                site_data.crane_model = payload.get("crane_model", "")
                site_data.crane_radius = payload.get("crane_radius", "")
                site_data.boom_length = payload.get("boom_length", "")
                site_data.lifting_weight = payload.get("lifting_weight", "")
                site_data.weather = payload.get("weather", "")
                site_data.inspectors = payload.get("inspectors", "")
                site_data.inspection_date = payload.get("inspection_date", "")
                site_data.remarks = payload.get("remarks", "")
        except json.JSONDecodeError:
            click.echo("错误: --data 必须是 JSON 字符串")
            return

    try:
        path = generate_document(doc_type, tag_no=tag_no, site_data=site_data, output_path=output)
        click.echo(f"生成完成: {path}")
    except Exception as e:
        click.echo(f"生成失败: {e}")


@cli.command(name="scan")
@click.argument("path", type=click.Path(exists=True))
@click.option("--recursive", "-r", is_flag=True, default=True,
              help="Include subdirectories")
@click.option("--dry-run", is_flag=True,
              help="Only report, don't import")
def scan_cmd(path, recursive, dry_run):
    """重新扫描文件夹：新文件导入 / 未变跳过 / 新来源登记。"""
    from src.core.scan_service import scan_directory

    result = scan_directory(path, recursive=recursive,
                            import_new=not dry_run)
    if "error" in result:
        click.echo(f"错误: {result['error']}")
        return
    click.echo(f"扫描目录: {path}")
    click.echo(f"  扫描文件: {result['scanned']}")
    click.echo(f"  新导入: {result['new']}")
    click.echo(f"  未变化: {result['unchanged']}")
    click.echo(f"  错误: {result['errors']}")
    if result.get("by_type"):
        click.echo(f"  类型分布: {result['by_type']}")
    if not dry_run and result["details"].get("new"):
        click.echo("\n新导入文件:")
        for f in result["details"]["new"][:10]:
            click.echo(f"  + {f}")


if __name__ == "__main__":
    main()
