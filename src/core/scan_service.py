"""Directory re-scan service (Phase 5).

scan_directory():
  scan → detect type → hash → compare against registry:
    - never seen hash     → import (new file)
    - same hash + path    → skip (already known)
    - same hash, new path → register additional source
    - different hash      → new version (content changed)

Original files are NEVER moved/deleted/modified.
"""

from __future__ import annotations

from pathlib import Path

from src.file_manager.hasher import compute_sha256
from src.file_manager.importer import import_file
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.scan")


def scan_directory(
    dir_path: str | Path,
    recursive: bool = True,
    import_new: bool = True,
) -> dict:
    """Scan a directory and sync it with the knowledge base.

    Args:
        dir_path: Directory to scan.
        recursive: Include subdirectories.
        import_new: If True, import new/changed files (else dry-run).

    Returns:
        Summary: {scanned, new, unchanged, changed, skipped, errors,
                  by_type: {...}}
    """
    path = Path(dir_path).resolve()
    if not path.is_dir():
        return {"error": f"目录不存在: {path}"}

    # Collect candidate files (CAD + documents + images)
    from src.file_manager.importer import DOC_EXTENSIONS

    exts = {".dwg", ".dxf"} | DOC_EXTENSIONS
    if recursive:
        files = [f for f in path.rglob("*")
                 if f.is_file() and f.suffix.lower() in exts]
    else:
        files = [f for f in path.iterdir()
                 if f.is_file() and f.suffix.lower() in exts]

    # Load registry hashes
    from src.database.connection import get_session
    from src.database.models import FileModel

    session = get_session()
    known = {
        r.sha256: r.file_id for r in session.query(
            FileModel.sha256, FileModel.file_id).all()
    }
    session.close()

    stats = {
        "scanned": len(files),
        "new": 0, "unchanged": 0, "changed": 0,
        "skipped": 0, "errors": 0,
        "by_type": {},
    }
    details = {"new": [], "changed": [], "unchanged": [], "skipped": []}

    for f in files:
        ext = f.suffix.lower()
        stats["by_type"][ext] = stats["by_type"].get(ext, 0) + 1

        try:
            fhash = compute_sha256(f)
        except Exception:
            stats["errors"] += 1
            continue

        if fhash in known:
            # Same content -> check if this path is a known source
            from src.core.file_registry import FileRegistry

            reg = FileRegistry()
            try:
                sources = reg.list_sources(known[fhash])
                if str(f) in sources:
                    stats["unchanged"] += 1
                    details["unchanged"].append(str(f))
                else:
                    # Same content, new location -> register as source
                    reg.register_file(f)
                    stats["unchanged"] += 1
                    details["unchanged"].append(f"{f} (新来源)")
            finally:
                reg.close()
            continue

        # New content (or never seen)
        if import_new:
            try:
                result = import_file(f)
                if result.get("status") in ("success", "duplicate"):
                    stats["new"] += 1
                    details["new"].append(str(f))
                else:
                    stats["errors"] += 1
                    details["skipped"].append(
                        f"{f} ({result.get('message', '?')})")
            except Exception as e:
                stats["errors"] += 1
                details["skipped"].append(f"{f} ({e})")
        else:
            stats["new"] += 1
            details["new"].append(f"{f} (dry-run)")

    logger.info(
        f"扫描完成: {path.name} — 扫描 {stats['scanned']}, "
        f"新 {stats['new']}, 未变 {stats['unchanged']}, "
        f"错误 {stats['errors']}")
    return {**stats, "details": details}
