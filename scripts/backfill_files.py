"""Backfill existing CAD drawings into the unified file registry (Phase 2).

Reads all existing `drawings` rows and registers them into `files`:
- Dedup by SHA256 (existing drawings already carry file_hash)
- Copies an archive copy into OriginalFiles/CAD/ IF the original file
  still exists at the recorded path (skip gracefully otherwise)
- Links drawing_id <-> file_id

Run:  python -m src.scripts.backfill_files
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from src.core.file_registry import FileRegistry, source_type_for_file  # noqa: E402
from src.database.connection import get_session, init_database  # noqa: E402
from src.database.models import DrawingModel, FileModel  # noqa: E402
from src.normalizer.schema import ParseStatus  # noqa: E402
from src.utils.logger import setup_logger  # noqa: E402

logger = setup_logger("cadkb.backfill")


def backfill() -> dict:
    init_database()
    session = get_session()
    reg = FileRegistry(session=session)

    drawings = session.query(DrawingModel).order_by(
        DrawingModel.created_at).all()
    total = len(drawings)
    registered = 0
    duplicates = 0
    skipped = 0
    errors = 0

    print(f"共 {total} 张图纸待回溯登记...")

    for d in drawings:
        # Already registered?
        exists = (
            session.query(FileModel)
            .filter(FileModel.drawing_id == d.drawing_id)
            .first()
        )
        if exists:
            duplicates += 1
            continue

        path = Path(d.file_path)
        if not path.exists():
            # Original file gone: register metadata-only (no archive copy)
            try:
                rec = reg.register_metadata_only(
                    original_name=d.file_name,
                    original_path=d.file_path,
                    sha256=d.file_hash,
                    file_type=d.file_type,
                    file_size=d.file_size,
                    drawing_id=d.drawing_id,
                    parser=d.parser or "unknown",
                    parse_status=(d.parse_status or ParseStatus.PENDING.value),
                )
                if rec:
                    registered += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.warning(f"登记失败 {d.file_name}: {e}")
                errors += 1
            continue

        # Original exists: normal registration (archives a copy)
        try:
            result = reg.register_file(
                path,
                drawing_id=d.drawing_id,
                parser=d.parser or "unknown",
                parse_status=(d.parse_status or ParseStatus.PENDING.value),
            )
            if result.get("status") in ("success", "duplicate"):
                registered += 1
            else:
                skipped += 1
        except Exception as e:
            logger.warning(f"登记异常 {d.file_name}: {e}")
            errors += 1

    reg.close()
    session.close()

    summary = {
        "total": total,
        "registered": registered,
        "duplicates": duplicates,
        "skipped": skipped,
        "errors": errors,
    }
    print(f"回溯完成: 总 {total} | 新登记 {registered} | 已存在 {duplicates} "
          f"| 跳过 {skipped} | 错误 {errors}")
    return summary


if __name__ == "__main__":
    backfill()
