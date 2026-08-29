"""数据校核页：标高校核 + 候选关系确认（阶段 2 人工闭环）。"""

from __future__ import annotations

import sqlite3
from datetime import datetime

DB = r"D:/WorkBuddy/work/data/knowledge_base/database/cadkb.db"


def _conn():
    con = sqlite3.connect(DB)
    con.execute("PRAGMA busy_timeout=60000")
    return con


def render(st):
    st.header("✅ 数据校核")
    st.caption("规则抽取结果的人工确认闭环：标高基准校核 + 设备↔箱单候选关系确认。")

    tab1, tab2 = st.tabs(["标高基准校核", "设备↔箱单候选确认"])
    with tab1:
        _render_elevation(st)
    with tab2:
        _render_candidates(st)


def _render_elevation(st):
    con = _conn()
    cur = con.cursor()
    total = cur.execute("SELECT COUNT(*) FROM elevations").fetchone()[0]
    done = cur.execute("SELECT COUNT(*) FROM elevations WHERE verified != 0").fetchone()[0]
    st.progress(done / max(total, 1), text=f"已校核 {done}/{total}")

    f = st.radio("筛选", ["未校核", "仅绝对标高", "全部"], horizontal=True, key="elev_filter")
    sql = ("SELECT e.elevation_id, d.file_name, e.datum_elevation, e.datum_type, "
           "e.raw_text, e.confidence, e.verified FROM elevations e "
           "LEFT JOIN drawings d ON d.drawing_id=e.drawing_id")
    if f == "未校核":
        sql += " WHERE e.verified=0"
    elif f == "仅绝对标高":
        sql += " WHERE e.datum_type='absolute'"
    sql += " ORDER BY e.datum_type='absolute' DESC, e.confidence DESC LIMIT 60"
    rows = cur.execute(sql).fetchall()

    st.caption(f"显示 {len(rows)} 条（confirmed=确认基准正确；rejected=抽取错误）")
    for r in rows:
        eid, fn, datum, dtype, raw, conf, verified = r
        mark = {0: "⬜", 1: "✅", -1: "❌"}.get(verified, "⬜")
        c1, c2, c3, c4 = st.columns([4, 2, 4, 2])
        c1.write(f"{mark} **{(fn or '?')[:38]}**")
        c2.write(f"`{datum if datum is not None else '—'}` ({dtype})")
        c3.caption((raw or "")[:90])
        if verified == 0:
            if c4.button("确认", key=f"ev_ok_{eid}"):
                _set_elevation(eid, 1)
                st.rerun()
            if c4.button("拒绝", key=f"ev_no_{eid}"):
                _set_elevation(eid, -1)
                st.rerun()
        else:
            c4.write("已校核" if verified == 1 else "已拒绝")
    con.close()


def _set_elevation(eid, v):
    con = _conn()
    con.execute("UPDATE elevations SET verified=?, verified_by='manual', verified_at=? WHERE elevation_id=?",
                (v, datetime.now().isoformat(" "), eid))
    con.commit()
    con.close()


def _render_candidates(st):
    con = _conn()
    cur = con.cursor()
    stat = cur.execute(
        "SELECT status, COUNT(*) FROM relation_candidates GROUP BY status").fetchall()
    st.write("状态分布：" + " | ".join(f"**{s}** {n}" for s, n in stat))

    packs = cur.execute(
        "SELECT target_key, COUNT(*) c FROM relation_candidates WHERE status='pending' "
        "GROUP BY target_key ORDER BY c DESC").fetchall()
    if not packs:
        st.success("没有待确认的候选关系。")
        con.close()
        return
    choice = st.selectbox("选择箱单（按待确认数排序）",
                          [f"{p[0]}（{p[1]} 条）" for p in packs])
    pack_no = choice.split("（")[0]

    rows = cur.execute(
        "SELECT cand_id, entity_key, evidence, confidence FROM relation_candidates "
        "WHERE target_key=? AND status='pending' ORDER BY entity_key LIMIT 80", (pack_no,)).fetchall()
    st.caption(f"箱单 {pack_no}：{len(rows)} 条待确认候选（位号 ↔ 箱单）")

    c_bulk, _ = st.columns([2, 6])
    if c_bulk.button("本箱单全部确认", key=f"rc_all_ok_{pack_no}"):
        _set_candidates_bulk([r[0] for r in rows], "confirmed")
        st.rerun()
    if c_bulk.button("本箱单全部拒绝", key=f"rc_all_no_{pack_no}"):
        _set_candidates_bulk([r[0] for r in rows], "rejected")
        st.rerun()

    for cid, tag, ev, conf in rows:
        c1, c2, c3 = st.columns([3, 5, 2])
        c1.write(f"`{tag}`")
        c2.caption(ev[:80])
        b1, b2 = c3.columns(2)
        if b1.button("✓", key=f"rc_ok_{cid}", help="确认关联"):
            _set_candidate(cid, "confirmed")
            st.rerun()
        if b2.button("✗", key=f"rc_no_{cid}", help="拒绝关联"):
            _set_candidate(cid, "rejected")
            st.rerun()
    con.close()


def _set_candidate(cid, status):
    con = _conn()
    con.execute("UPDATE relation_candidates SET status=?, confirmed_by='manual', confirmed_at=? WHERE cand_id=?",
                (status, datetime.now().isoformat(" "), cid))
    con.commit()
    con.close()


def _set_candidates_bulk(cids, status):
    if not cids:
        return
    con = _conn()
    con.executemany(
        "UPDATE relation_candidates SET status=?, confirmed_by='manual', confirmed_at=? WHERE cand_id=?",
        [(status, datetime.now().isoformat(" "), cid) for cid in cids]
    )
    con.commit()
    con.close()
