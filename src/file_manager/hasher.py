"""File hashing and duplicate detection."""

import hashlib
from pathlib import Path

from src.utils.logger import setup_logger

logger = setup_logger("cadkb.file_manager")


def compute_sha256(file_path: str | Path, chunk_size: int = 8192) -> str:
    """Compute SHA256 hash of a file.
    
    Args:
        file_path: Path to the file.
        chunk_size: Read chunk size in bytes.
        
    Returns:
        Hexadecimal SHA256 string.
    """
    sha256 = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                sha256.update(chunk)
    except Exception as e:
        logger.error(f"Failed to hash file {file_path}: {e}")
        raise
    return sha256.hexdigest()


def compute_file_hash_fast(file_path: str | Path) -> str:
    """Compute a faster hash using file size + first/last 4KB + SHA256.
    
    This is used for quick duplicate detection before full hash.
    
    Args:
        file_path: Path to the file.
        
    Returns:
        A hash string combining size and content samples.
    """
    path = Path(file_path)
    size = path.stat().st_size
    sha256 = hashlib.sha256()
    
    # Update with file size
    sha256.update(str(size).encode())
    
    try:
        with open(path, "rb") as f:
            # First 4KB
            sha256.update(f.read(4096))
            # Last 4KB (if file > 8KB)
            if size > 8192:
                f.seek(-4096, 2)
                sha256.update(f.read(4096))
    except Exception as e:
        logger.error(f"Failed to fast-hash file {file_path}: {e}")
        raise
    
    return f"fast_{sha256.hexdigest()}"
