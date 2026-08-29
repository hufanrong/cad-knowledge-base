"""Image document parser — Phase 4.

Extracts: dimensions, format, EXIF metadata (date/camera/...) and
optionally OCR text (pytesseract, marked source=ocr + confidence).

Output: ParsedDocument.
"""

from __future__ import annotations

from pathlib import Path

from src.normalizer.schema import ParsedDocument, ParsedSection
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.parsers.image")

try:
    from PIL import Image, ExifTags

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class ImageParser:
    """Parse image files (metadata + optional OCR)."""

    name = "image_parser"

    def parse(self, file_path: str | Path) -> ParsedDocument:
        path = Path(file_path)
        result = ParsedDocument(
            source_file=path.name,
            source_type="image",
            parser=self.name,
        )
        result.title = path.stem

        if not PIL_AVAILABLE:
            result.parse_status = "failed"
            result.errors.append("Pillow 未安装")
            return result

        try:
            img = Image.open(str(path))
            meta = {
                "format": img.format or "",
                "mode": img.mode or "",
                "width": img.width,
                "height": img.height,
                "size_bytes": path.stat().st_size,
            }
            # EXIF
            exif = img._getexif()
            if exif:
                exif_map = {}
                for tag_id, value in exif.items():
                    tag = ExifTags.TAGS.get(tag_id, str(tag_id))
                    if isinstance(value, (str, int, float)):
                        exif_map[tag] = value
                    elif tag in ("DateTimeOriginal", "DateTime",
                                 "DateTimeDigitized"):
                        exif_map[tag] = str(value)
                if exif_map:
                    meta["exif"] = exif_map
            result.metadata = meta
            img.close()
        except Exception as e:
            result.parse_status = "failed"
            result.errors.append(f"图片读取失败: {e}")
            return result

        # Optional OCR
        try:
            import pytesseract

            text = pytesseract.image_to_string(
                str(path), lang="chi_sim+eng")
            text = text.strip()
            if text:
                result.source = "ocr"
                result.confidence = 0.85  # tesseract 无逐字置信度时用保守值
                for line in text.splitlines():
                    line = line.strip()
                    if line:
                        result.sections.append(ParsedSection(
                            level=0, text=line))
                result.content = text
                result.markdown = f"# {result.title}\n\n> ⚠️ OCR 内容 (置信度 85%)\n\n```\n{text}\n```"
        except ImportError:
            result.errors.append("OCR 未安装（pytesseract），仅保存元数据")
        except Exception as e:
            logger.warning(f"图片 OCR 失败: {path.name} - {e}")

        if not result.content:
            result.content = result.title
            result.markdown = f"# {result.title}\n\n"
            result.parse_status = "partial"

        logger.info(f"图片解析完成: {path.name} ({meta.get('width')}x"
                    f"{meta.get('height')}, source={result.source})")
        return result


def parse_image(file_path: str | Path) -> ParsedDocument:
    """Convenience wrapper."""
    return ImageParser().parse(file_path)
