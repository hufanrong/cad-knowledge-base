# -*- coding: utf-8 -*-
"""migrate_manono_exclusive_fix.py — 补齐剩余 42,204 个平台级 chunks。

修复上一版的分页 bug：Chroma 的 offset 分页在"边取边改"时漂移。
正确做法：阶段1 收集全部 project_id='' 的 id+metadata（不改动），
阶段2 统一 update。收集与更新各 3000/批。
"""
from __future__ import annotations

import sys
from src.index.vector_index import VectorIndex

BATCH = 3000


def collect() -> tuple[list[str], list[dict]]:
    print("[1/3] 收集剩余 project_id='' chunks ...")
    vi = VectorIndex()
    vi.count()
    col = vi._collection
    ids_all: list[str] = []
    metas_all: list[dict] = []
    offset = 0
    while True:
        r = col.get(where={"project_id": ""}, limit=BATCH, offset=offset,
                    include=["metadatas"])
        ids = r.get("ids", [])
        metas = r.get("metadatas", [])
        if not ids:
            break
        ids_all.extend(ids)
        metas_all.extend(metas)
        print(f"      已收集 {len(ids_all)} / ? (offset={offset})", flush=True)
        if len(ids) < BATCH:
            break
        offset += BATCH
    print(f"      共收集 {len(ids_all)} 个待更新")
    return ids_all, metas_all


def update_all(ids_all: list[str], metas_all: list[dict]) -> None:
    print("[2/3] 统一更新 project_id -> 'manono' ...")
    vi = VectorIndex()
    vi.count()
    col = vi._collection
    done = 0
    for i in range(0, len(ids_all), BATCH):
        batch_ids = ids_all[i:i + BATCH]
        new_metas = []
        for m in metas_all[i:i + BATCH]:
            m = dict(m or {})
            m["project_id"] = "manono"
            new_metas.append(m)
        col.update(ids=batch_ids, metadatas=new_metas)
        done += len(batch_ids)
        print(f"      已更新 {done} / {len(ids_all)}", flush=True)


def verify() -> None:
    print("[3/3] 验证 ...")
    vi = VectorIndex()
    vi.count()
    col = vi._collection
    # 先收集空串（不改动，结果集稳定）
    plat = 0
    offset = 0
    while True:
        r = col.get(where={"project_id": ""}, limit=BATCH, offset=offset,
                    include=["metadatas"])
        ids = r.get("ids", [])
        plat += len(ids)
        if len(ids) < BATCH:
            break
        offset += BATCH
    man = 0
    offset = 0
    while True:
        r = col.get(where={"project_id": "manono"}, limit=BATCH, offset=offset,
                    include=["metadatas"])
        ids = r.get("ids", [])
        man += len(ids)
        if len(ids) < BATCH:
            break
        offset += BATCH
    print(f"      剩余 project_id=''  = {plat}（应为 0）")
    print(f"      project_id=manono  = {man}")
    print(f"      向量库总数          = {col.count()}")


def main() -> int:
    ids_all, metas_all = collect()
    if not ids_all:
        print("没有剩余待更新 chunks，跳过。")
        verify()
        return 0
    update_all(ids_all, metas_all)
    verify()
    print("\n补齐完成 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
