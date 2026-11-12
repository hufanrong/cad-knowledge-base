"""Configuration management for CAD Knowledge Base."""

import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Load .env if exists
_env_path = PROJECT_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


class Config:
    """Global configuration loaded from YAML + environment variables."""

    def __init__(self):
        self._yaml_config: dict = {}
        self._load_yaml()

        # Database
        db_path = os.environ.get(
            "CADKB_DB_PATH",
            self._yaml_get("database.path", "KnowledgeBase/database/cadkb.db"),
        )
        self.db_path = self._resolve_path(db_path)

        # Storage
        kb_root = os.environ.get(
            "CADKB_KB_ROOT",
            self._yaml_get("storage.root", "KnowledgeBase"),
        )
        self.kb_root = self._resolve_path(kb_root)
        self.raw_dir = self._resolve_path(
            self._yaml_get("storage.raw_dir", "KnowledgeBase/raw")
        )
        self.parsed_dir = self._resolve_path(
            self._yaml_get("storage.parsed_dir", "KnowledgeBase/parsed")
        )
        self.normalized_dir = self._resolve_path(
            self._yaml_get("storage.normalized_dir", "KnowledgeBase/normalized")
        )
        self.metadata_dir = self._resolve_path(
            self._yaml_get("storage.metadata_dir", "KnowledgeBase/metadata")
        )
        self.thumbnails_dir = self._resolve_path(
            self._yaml_get("storage.thumbnails_dir", "KnowledgeBase/thumbnails")
        )
        self.embeddings_dir = self._resolve_path(
            self._yaml_get("storage.embeddings_dir", "KnowledgeBase/embeddings")
        )
        self.logs_dir = self._resolve_path(
            os.environ.get(
                "CADKB_LOG_DIR",
                self._yaml_get("storage.logs_dir", "KnowledgeBase/logs"),
            )
        )
        self.temp_dir = self._resolve_path(
            self._yaml_get("storage.temp_dir", "KnowledgeBase/Temp")
        )

        # ODA File Converter
        self.oda_exe_path = os.environ.get(
            "CADKB_ODA_PATH", self._yaml_get("oda.exe_path", "")
        )
        self.oda_output_version = self._yaml_get("oda.output_version", "ACAD2018")
        self.oda_audit = self._yaml_get("oda.audit", True)

        # Parser
        self.strip_mtext_codes = self._yaml_get("parser.strip_mtext_codes", True)
        self.save_raw_mtext = self._yaml_get("parser.save_raw_mtext", True)
        self.max_entities = self._yaml_get("parser.max_entities", 0)

        # Quality
        self.min_completeness = self._yaml_get("quality.min_completeness", 0.5)
        self.check_coordinates = self._yaml_get("quality.check_coordinates", True)
        self.check_units = self._yaml_get("quality.check_units", True)

        # LLM (Phase 7) — OpenAI-compatible API
        self.llm_base_url = os.environ.get(
            "CADKB_LLM_BASE_URL", self._yaml_get("llm.base_url", "https://api.openai.com/v1")
        )
        self.llm_api_key = os.environ.get(
            "CADKB_LLM_API_KEY", self._yaml_get("llm.api_key", "")
        )
        self.llm_model = os.environ.get(
            "CADKB_LLM_MODEL", self._yaml_get("llm.model", "gpt-4o-mini")
        )
        self.llm_max_tokens = self._yaml_get("llm.max_tokens", 800)
        self.llm_temperature = self._yaml_get("llm.temperature", 0.2)
        # 请求超时（秒）。DeepSeek 等长回答 + 大上下文场景 30s 偏紧，且客户端无重试，
        # 超时即失败；默认 60s，可用 CADKB_LLM_TIMEOUT 覆盖。
        try:
            self.llm_timeout = float(
                os.environ.get("CADKB_LLM_TIMEOUT", self._yaml_get("llm.timeout", 60))
            )
        except (TypeError, ValueError):
            self.llm_timeout = 60.0

        # Logging
        self.log_level = os.environ.get(
            "CADKB_LOG_LEVEL", self._yaml_get("logging.level", "INFO")
        )
        self.log_format = self._yaml_get(
            "logging.format",
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        self.log_date_format = self._yaml_get("logging.date_format", "%Y-%m-%d %H:%M:%S")
        self.log_file_enabled = self._yaml_get("logging.file_enabled", True)

    def _load_yaml(self):
        config_path = PROJECT_ROOT / "config" / "default.yaml"
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                self._yaml_config = yaml.safe_load(f) or {}

    def _yaml_get(self, key: str, default=None):
        """Get nested value from YAML config using dot notation."""
        keys = key.split(".")
        val = self._yaml_config
        for k in keys:
            if isinstance(val, dict) and k in val:
                val = val[k]
            else:
                return default
        return val

    def _resolve_path(self, path_str: str) -> Path:
        """Resolve a path relative to project root if not absolute."""
        p = Path(path_str)
        if p.is_absolute():
            return p
        return PROJECT_ROOT / p

    def ensure_directories(self):
        """Create all required directories if they don't exist."""
        dirs = [
            self.kb_root,
            self.raw_dir,
            self.raw_dir / "CAD",
            self.raw_dir / "Word",
            self.raw_dir / "Excel",
            self.raw_dir / "PDF",
            self.raw_dir / "Project",
            self.raw_dir / "Images",
            self.raw_dir / "Other",
            self.parsed_dir,
            self.normalized_dir,
            self.metadata_dir,
            self.thumbnails_dir,
            self.embeddings_dir,
            self.logs_dir,
            self.temp_dir,
            self.db_path.parent,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    def find_oda_converter(self) -> Optional[str]:
        """Try to find ODA File Converter executable."""
        # Check configured path
        if self.oda_exe_path and Path(self.oda_exe_path).exists():
            return self.oda_exe_path

        # Common install locations on Windows
        candidates = [
            r"D:\ODA\ODAFileConverter\ODAFileConverter.exe",
            r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe",
            r"C:\Program Files\ODA\ODAFileConverter 25.6.0\ODAFileConverter.exe",
            r"C:\Program Files\ODA\ODAFileConverter 25.1.0\ODAFileConverter.exe",
            r"C:\Program Files (x86)\ODA\ODAFileConverter\ODAFileConverter.exe",
        ]
        for c in candidates:
            if Path(c).exists():
                return c

        return None


# Singleton config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get the global Config singleton."""
    global _config
    if _config is None:
        _config = Config()
    return _config
