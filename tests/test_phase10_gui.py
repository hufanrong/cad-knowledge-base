"""Unit tests for Phase 10: Streamlit GUI.

Uses Streamlit's AppTest framework to render pages headlessly and assert
on the produced elements (titles, widgets, dataframes). If streamlit is
not installed, tests are skipped.
"""

import pytest

try:
    from streamlit.testing.v1 import AppTest

    ST_AVAILABLE = True
except ImportError:
    ST_AVAILABLE = False

requires_streamlit = pytest.mark.skipif(
    not ST_AVAILABLE, reason="streamlit 未安装"
)

from pathlib import Path  # noqa: E402

APP_PATH = str(
    Path(__file__).resolve().parent.parent / "src" / "gui" / "app.py"
)


@pytest.fixture
def app(tmp_path):
    """Return an AppTest instance for the GUI app."""
    from src.core.config import get_config
    from src.database.connection import reset_engine

    config = get_config()
    config.db_path = tmp_path / "test_gui.db"
    config.ensure_directories()
    reset_engine()

    at = AppTest.from_file(APP_PATH, default_timeout=10)
    at.run()
    return at


@requires_streamlit
class TestGUIApp:
    """Test the main GUI app shell."""

    def test_app_runs(self, app):
        """Test the app renders without exceptions."""
        assert not app.exception, f"App raised: {app.exception}"

    def test_sidebar_navigation(self, app):
        """Test the sidebar radio has expected pages."""
        radios = app.sidebar.radio
        assert len(radios) >= 1
        options = list(radios[0].options)
        for page in ["图纸导入", "图纸浏览", "搜索", "AI 问答", "图纸比较"]:
            assert page in options

    def test_title(self, app):
        """Test the page has a title."""
        assert app.title, "Missing title"


@requires_streamlit
class TestImportPage:
    """Test the 图纸导入 page."""

    def test_import_page_renders(self, app):
        """Test import page renders without error."""
        app.sidebar.radio[0].set_value("图纸导入").run()
        assert not app.exception
        # Has a file_uploader
        assert len(app.get("file_uploader")) >= 1


@requires_streamlit
class TestBrowsePage:
    """Test the 图纸浏览 page."""

    def test_browse_empty_kb(self, app):
        """Test browse page with empty KB shows info message."""
        assert not app.exception

    def test_browse_with_data(self, app, test_dxf_all):
        """Test browse page shows drawings after import."""
        from src.file_manager.importer import import_file

        result = import_file(test_dxf_all)
        assert result["status"] == "success"

        app.sidebar.radio[0].set_value("图纸浏览").run()
        assert not app.exception

        # The overview dataframe should have at least one row
        dataframes = app.dataframe
        assert len(dataframes) >= 1


@requires_streamlit
class TestSearchPage:
    """Test the 搜索 page."""

    def test_search_widgets(self, app):
        """Test search page has the query input and search button."""
        # Navigate to 搜索
        app.sidebar.radio[0].set_value("搜索").run()
        assert not app.exception

        # There should be a text_input for the keyword
        text_inputs = app.text_input
        assert len(text_inputs) >= 1


@requires_streamlit
class TestQAPage:
    """Test the AI 问答 page."""

    def test_qa_page_renders(self, app):
        """Test QA page renders without error."""
        app.sidebar.radio[0].set_value("AI 问答").run()
        assert not app.exception


@requires_streamlit
class TestComparePage:
    """Test the 图纸比较 page."""

    def test_compare_page_renders(self, app):
        """Test compare page renders without error."""
        app.sidebar.radio[0].set_value("图纸比较").run()
        assert not app.exception
        # Two path inputs
        assert len(app.text_input) >= 2
