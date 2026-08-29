"""Base parser interface for all CAD file parsers."""

from abc import ABC, abstractmethod
from pathlib import Path

from src.normalizer.schema import ParseResult


class BaseParser(ABC):
    """Abstract base class for all CAD file parsers."""
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Parser name (e.g., 'ezdxf', 'oda+ezdxf')."""
        ...
    
    @property
    @abstractmethod
    def version(self) -> str:
        """Parser version string."""
        ...
    
    @property
    @abstractmethod
    def supported_types(self) -> list[str]:
        """List of supported file types (e.g., ['dxf'])."""
        ...
    
    @abstractmethod
    def can_parse(self, file_path: str | Path) -> bool:
        """Check if this parser can handle the given file."""
        ...
    
    @abstractmethod
    def parse(self, file_path: str | Path) -> ParseResult:
        """Parse the CAD file and return structured data.
        
        Args:
            file_path: Path to the CAD file.
            
        Returns:
            ParseResult containing all extracted data.
        """
        ...
