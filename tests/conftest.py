"""Test fixtures and configuration for pytest."""

import os
import sys
from pathlib import Path

import pytest

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Redirect logs BEFORE any src module is imported (collection phase):
# the real KB lives under D:/WorkBuddy (may be read-only in sandbox),
# so all logger output during collection/tests must go to a fresh
# temp dir (project KnowledgeBase/logs may be file-locked by the host).
import tempfile

os.environ.setdefault(
    "CADKB_LOG_DIR", tempfile.mkdtemp(prefix="cadkb_test_logs_")
)
os.environ.setdefault("CADKB_LOG_FILE", "cadkb_test.log")


@pytest.fixture(autouse=True)
def isolate_kb_dirs(monkeypatch):
    """Keep tests away from the real knowledge base (D:/CADKnowledgeBase).

    Redirects storage dirs into the project-local KnowledgeBase so tests
    never write to the user's real permanent KB. db_path is left to the
    individual test fixtures (temp_db / imported_db / app).
    """
    from src.core.config import get_config

    cfg = get_config()
    base = PROJECT_ROOT / "KnowledgeBase"

    monkeypatch.setattr(cfg, "kb_root", base)
    monkeypatch.setattr(cfg, "raw_dir", base / "raw")
    monkeypatch.setattr(cfg, "parsed_dir", base / "parsed")
    monkeypatch.setattr(cfg, "normalized_dir", base / "normalized")
    monkeypatch.setattr(cfg, "metadata_dir", base / "metadata")
    monkeypatch.setattr(cfg, "thumbnails_dir", base / "thumbnails")
    monkeypatch.setattr(cfg, "embeddings_dir", base / "embeddings")
    # NOTE: logs_dir is intentionally NOT overridden here — it stays on
    # the temp dir set via CADKB_LOG_DIR in this module, because the
    # project KnowledgeBase/logs may be file-locked by the host.
    if hasattr(cfg, "temp_dir"):
        monkeypatch.setattr(cfg, "temp_dir", base / "Temp")
    yield


# Test data paths
TEST_DXF_DIR = PROJECT_ROOT / "tests" / "fixtures" / "dxf"
TEST_DWG_DIR = PROJECT_ROOT / "tests" / "fixtures" / "dwg"


@pytest.fixture
def test_dxf_all():
    """Path to the comprehensive test DXF file."""
    return TEST_DXF_DIR / "test_all_entities.dxf"


@pytest.fixture
def test_dxf_simple():
    """Path to the simple test DXF file."""
    return TEST_DXF_DIR / "test_simple.dxf"


@pytest.fixture
def test_dxf_r12():
    """Path to the R12 test DXF file."""
    return TEST_DXF_DIR / "test_r12.dxf"


@pytest.fixture
def test_dxf_r2000():
    """Path to the R2000 test DXF file."""
    return TEST_DXF_DIR / "test_r2000.dxf"


@pytest.fixture
def test_dwg_all():
    """Path to the comprehensive test DWG file."""
    return TEST_DWG_DIR / "test_all_entities.dwg"


@pytest.fixture
def test_dwg_simple():
    """Path to the simple test DWG file."""
    return TEST_DWG_DIR / "test_simple.dwg"


@pytest.fixture
def test_dwg_r12():
    """Path to the R12 test DWG file."""
    return TEST_DWG_DIR / "test_r12.dwg"


@pytest.fixture
def test_dwg_r2000():
    """Path to the R2000 test DWG file."""
    return TEST_DWG_DIR / "test_r2000.dwg"


@pytest.fixture
def test_dxf_r2004():
    """Path to the R2004 test DXF file."""
    return TEST_DXF_DIR / "test_r2004.dxf"


@pytest.fixture
def test_dxf_r2007():
    """Path to the R2007 test DXF file."""
    return TEST_DXF_DIR / "test_r2007.dxf"


@pytest.fixture
def test_dxf_r2010():
    """Path to the R2010 test DXF file."""
    return TEST_DXF_DIR / "test_r2010.dxf"


@pytest.fixture
def test_dxf_r2013():
    """Path to the R2013 test DXF file."""
    return TEST_DXF_DIR / "test_r2013.dxf"


@pytest.fixture
def test_dwg_r2004():
    """Path to the R2004 test DWG file."""
    return TEST_DWG_DIR / "test_r2004.dwg"


@pytest.fixture
def test_dwg_r2007():
    """Path to the R2007 test DWG file."""
    return TEST_DWG_DIR / "test_r2007.dwg"


@pytest.fixture
def test_dwg_r2010():
    """Path to the R2010 test DWG file."""
    return TEST_DWG_DIR / "test_r2010.dwg"


@pytest.fixture
def test_dwg_r2013():
    """Path to the R2013 test DWG file."""
    return TEST_DWG_DIR / "test_r2013.dwg"


@pytest.fixture
def temp_db(tmp_path):
    """Use a temporary database for testing."""
    from src.core.config import get_config
    config = get_config()
    config.db_path = tmp_path / "test.db"
    config.ensure_directories()
    return config.db_path
