"""现场群聊检索（site chat archive）——问答链路的第二检索源。

与 chat_memory.py（助手对话记忆）无关：本模块检索的是
「工程现场微信群聊档案」chat_archive.db（由 site_data/chat_archive.py 维护）。

设计原则
--------
1. 只读：不写入、不修改档案库；
2. 可降级：档案库缺失或损坏时返回空列表，绝不影响主检索；
3. 口径隔离：返回结果带 group/date/sender，供回答时标注“现场沟通”出处，
   与技术文件（图纸/台账）证据分级，冲突时以技术文件为准。
"""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

from src.utils.logger import setup_logger

logger = setup_logger("cadkb.site_chat")

DEFAULT_CHAT_DB = Path(
    r"D:\WorkBuddy\Projects\PRJ-2026-001_Manono\02_数据库\chat_archive\chat_archive.db"
)

_SPLIT_RE = re.compile(r"[\s,，。；;、:：/\\|()（）\[\]【】<>《》\"'“”‘’]+")
_ALNUM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-_.／/]{1,}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")

# 疑问词/虚词：切词前剔除，避免把整句当成一个检索词
_STOP_PHRASES = (
    "什么时候", "什么时间", "什么位置", "在哪里", "在哪", "何时", "能否", "能不能",
    "是否可以", "可以", "是否", "有没有", "有无", "多少", "怎么", "怎么样", "为什么",
    "哪个", "哪些", "请问", "麻烦", "帮我看", "看一下", "一下", "怎么样",
    "吗", "呢", "吧", "啊", "的", "了", "和", "与", "及", "以及", "请", "帮我",
)


def get_chat_db_path() -> Path:
    return Path(os.environ.get("CADKB_SITE_CHAT_DB", str(DEFAULT_CHAT_DB)))


def available() -> bool:
    p = get_chat_db_path()
    return p.exists() and p.stat().st_size > 1024


def _connect() -> sqlite3.Connection | None:
    if not available():
        return None
    try:
        con = sqlite3.connect(f"file:{get_chat_db_path()}?mode=ro", uri=True, timeout=3)
        return con
    except Exception as e:  # pragma: no cover
        logger.warning(f"群聊档案库打开失败: {e}")
        return None


# 行业同义词/别名：现场口语与图纸术语常不一致，检索时双向补齐
SYNONYMS = {
    "收尘器": ["除尘器", "收尘"],
    "除尘器": ["收尘器", "除尘"],
    "卸料器": ["卸料阀", "星型卸料器"],
    "卸料阀": ["卸料器"],
    "自吸泵": ["提升泵"],
    "提升泵": ["自吸泵"],
    "立磨": ["立式磨", "立磨机"],
    "立磨机": ["立磨"],
    "皮带机": ["胶带输送机", "皮带"],
    "胶带输送机": ["皮带机"],
    "风机": ["鼓风机"],
    "鼓风机": ["风机"],
    "窑尾": ["预热器"],
    "预热器": ["窑尾"],
}


def _terms(query: str) -> list[tuple[str, float]]:
    """把自然语言问题切成检索词并加权（无分词库时的轻量策略）。

    权重：位号/编码 3.0 > 中文短语 2.0~2.5 > 3 字滑窗 1.0。
    3 字滑窗保证长句也能命中（trigram FTS 天然支持子串）。
    """
    q = query or ""
    scored: list[tuple[str, float]] = []

    # 1) 位号 / 编码 / 规格：P01-DC-01M、0506、DN200、MNN-HN-342
    for m in _ALNUM_RE.finditer(q):
        tok = m.group().strip("-_./／")
        if len(tok) >= 3:
            scored.append((tok, 3.0))

    # 2) 中文：先剔除疑问词与虚词，再按 2~5 字词组 / 3 字滑窗铺开
    clean = q
    for s in _STOP_PHRASES:
        clean = clean.replace(s, " ")
    for m in _CJK_RE.finditer(clean):
        seg = m.group()
        if len(seg) < 2:
            continue
        if len(seg) <= 3:
            scored.append((seg, 2.0))
        elif len(seg) <= 5:
            # 4~5 字短语：整段优先，再铺 3 字窗 + 2 字窗，避免专名（如“西安三瑞”）整体匹配失败
            scored.append((seg, 2.0))
            for i in range(len(seg) - 2):
                scored.append((seg[i:i + 3], 0.8))
            for i in range(len(seg) - 1):
                scored.append((seg[i:i + 2], 0.5))
        else:
            scored.append((seg, 2.5))          # 整段（精确子串优先级高）
            for i in range(len(seg) - 2):
                scored.append((seg[i:i + 3], 1.0))

    # 3) 行业同义词补齐（如 收尘器↔除尘器、提升泵↔自吸泵）
    for key, alts in SYNONYMS.items():
        if key in q:
            for alt in alts:
                if alt not in q:
                    scored.append((alt, 1.8))

    # 去重保权（同词取最高权重），按权重降序截断
    best: dict[str, float] = {}
    for tok, w in scored:
        if tok not in best or w > best[tok]:
            best[tok] = w
    ranked = sorted(best.items(), key=lambda kv: (kv[1], len(kv[0])), reverse=True)
    return ranked[:14]


def stats() -> dict:
    con = _connect()
    if con is None:
        return {"available": False, "db": str(get_chat_db_path())}
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT count(*), count(DISTINCT group_name), min(msg_date), max(msg_date) "
            "FROM chat_messages")
        total, groups, first, last = cur.fetchone()
        cur.execute("SELECT group_name, msg_count FROM chat_groups ORDER BY msg_count DESC")
        detail = [{"group": g, "count": c} for g, c in cur.fetchall()]
        return {"available": True, "db": str(get_chat_db_path()), "messages": total,
                "groups": groups, "first_date": first, "last_date": last, "detail": detail}
    except Exception as e:
        logger.warning(f"群聊档案库统计失败: {e}")
        return {"available": False, "db": str(get_chat_db_path()), "error": str(e)}
    finally:
        con.close()


def search_site_chat(
    query: str,
    top_k: int = 6,
    group: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict]:
    """在群聊档案中检索与问题相关的消息。

    命中数（多词命中累加）优先，其次按时间倒序。数据库不可用时返回 []。
    """
    con = _connect()
    if con is None:
        return []
    terms = _terms(query)
    if not terms:
        con.close()
        return []

    base_where, base_params = [], []
    if group:
        base_where.append("m.group_name LIKE ?")
        base_params.append(f"%{group}%")
    if date_from:
        base_where.append("m.msg_date >= ?")
        base_params.append(date_from)
    if date_to:
        base_where.append("m.msg_date <= ?")
        base_params.append(date_to)
    extra_sql = (" AND " + " AND ".join(base_where)) if base_where else ""

    hits: dict[int, dict] = {}
    cur = con.cursor()
    try:
        for tok, weight in terms:
            rows = []
            if len(tok) >= 3:
                # FTS5 trigram：任意子串命中
                try:
                    rows = cur.execute(
                        "SELECT m.msg_id, m.group_name, m.msg_date, m.msg_time, m.sender, "
                        "m.msg_type, m.content, m.attach_name "
                        "FROM chat_fts f JOIN chat_messages m ON m.msg_id = f.rowid "
                        f"WHERE f.content MATCH ?{extra_sql} "
                        "ORDER BY m.msg_date DESC, m.msg_time DESC LIMIT ?",
                        [f'"{tok}"'] + base_params + [top_k * 6],
                    ).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            if not rows:
                like = f"%{tok}%"
                rows = cur.execute(
                    "SELECT m.msg_id, m.group_name, m.msg_date, m.msg_time, m.sender, "
                    "m.msg_type, m.content, m.attach_name "
                    "FROM chat_messages m "
                    f"WHERE (m.content LIKE ? OR m.attach_name LIKE ?){extra_sql} "
                    "ORDER BY m.msg_date DESC, m.msg_time DESC LIMIT ?",
                    [like, like] + base_params + [top_k * 6],
                ).fetchall()
            for r in rows:
                d = hits.get(r[0])
                if d:
                    d["matches"] += 1
                    d["score"] += weight
                else:
                    hits[r[0]] = {
                        "msg_id": r[0], "group": r[1], "date": r[2], "time": r[3],
                        "sender": r[4], "type": r[5], "content": (r[6] or ""),
                        "attach_name": r[7] or "", "matches": 1, "score": weight,
                    }
    except Exception as e:  # pragma: no cover
        logger.warning(f"群聊检索失败（降级为空）: {e}")
        return []
    finally:
        con.close()

    ranked = sorted(hits.values(),
                    key=lambda x: (round(x["score"], 3), x["date"] or "", x["time"] or ""),
                    reverse=True)[:top_k]
    for d in ranked:
        d["content"] = (d["content"] or "").strip()[:400]
        d["score"] = round(d["score"], 2)
    return ranked


def format_for_prompt(items: list[dict], max_items: int = 6, max_chars: int = 200) -> str:
    """把命中消息拼成给 LLM 的上下文块（带出处，明确证据等级）。"""
    if not items:
        return ""
    lines = []
    for i, d in enumerate(items[:max_items], 1):
        body = " ".join((d.get("content") or "").split())[:max_chars]
        attach = f"（附件：{d['attach_name']}）" if d.get("attach_name") else ""
        lines.append(
            f"{i}) {d.get('date', '')} {d.get('time', '')} | {d.get('group', '')} | "
            f"{d.get('sender', '')}：{body}{attach}"
        )
    head = ("【现场群聊摘录】（来源：项目微信群，属现场沟通口径，非受控技术文件；"
            "与图纸/设备表/台账等正式文件冲突时，以正式文件为准，并说明分歧）")
    return head + "\n" + "\n".join(lines)
