"""ODA File Converter command-line wrapper.

Encapsulates ODAFileConverter.exe command-line interface for DWG <-> DXF
conversion. ODA File Converter is free for non-commercial use
(https://www.opendesign.com/guestfiles/oda_file_converter).

Command-line syntax:
    ODAFileConverter <InputFolder> <OutputFolder> <OutputVersion> <OutputFormat> <Recurse> <Audit>

Examples:
    ODAFileConverter C:\\in C:\\out ACAD2018 DXF 0 1

Important notes:
- ODA operates on FOLDERS, not individual files.
- It identifies files matching the input filter (*.dwg;*.dxf by default)
  and converts all of them.
- The converter exits 0 even if conversion had issues, so we must verify
  the output file exists after conversion (with timeout).
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from src.core.config import get_config
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.parsers.oda")

# Version identifiers accepted by ODA File Converter
# Maps from DWG version code (file header) to ODA output version
ODA_OUTPUT_VERSIONS = {
    "AC1009": "ACAD12",   # AutoCAD R12
    "AC1012": "ACAD13",   # AutoCAD R13
    "AC1014": "ACAD14",   # AutoCAD R14
    "AC1015": "ACAD2000", # AutoCAD 2000
    "AC1018": "ACAD2004", # AutoCAD 2004
    "AC1021": "ACAD2007", # AutoCAD 2007
    "AC1024": "ACAD2010", # AutoCAD 2010
    "AC1027": "ACAD2013", # AutoCAD 2013
    "AC1032": "ACAD2018", # AutoCAD 2018
}


def find_oda_converter() -> str | None:
    """Locate the ODAFileConverter.exe executable."""
    config = get_config()
    return config.find_oda_converter()


def is_oda_available() -> bool:
    """Check if ODA File Converter is installed and usable."""
    return find_oda_converter() is not None


class ODAConverter:
    """Wrapper around the ODAFileConverter command-line interface."""

    def __init__(self, exe_path: str | None = None, timeout: float = 120.0):
        """Initialize with an optional explicit executable path.

        Args:
            exe_path: Path to ODAFileConverter.exe. If None, auto-detect.
            timeout: Maximum seconds to wait for conversion to complete.
        """
        self.exe_path = exe_path or find_oda_converter()
        self.timeout = timeout
        if self.exe_path:
            self.exe_path = str(Path(self.exe_path))

    def is_available(self) -> bool:
        """Check if the converter executable exists."""
        return bool(self.exe_path) and Path(self.exe_path).exists()

    def convert_dwg_to_dxf(
        self,
        dwg_path: str | Path,
        output_dir: str | Path,
        output_version: str = "ACAD2018",
        audit: bool = True,
        wait_poll_interval: float = 0.5,
    ) -> Path | None:
        """Convert a single DWG file to DXF.

        ODA works on folders, so this method creates a temporary input
        folder containing just the target file, runs the converter, and
        returns the path to the generated DXF (or None on failure).

        Args:
            dwg_path: Path to the DWG file.
            output_dir: Directory where the DXF will be written.
            output_version: ODA version code (e.g., "ACAD2018").
            audit: Enable ODA audit/repair during conversion.
            wait_poll_interval: Seconds between output existence checks.

        Returns:
            Path to the generated DXF file, or None if conversion failed.

        Raises:
            RuntimeError: If ODA converter is not available.
            TimeoutError: If conversion does not finish within timeout.
        """
        if not self.is_available():
            raise RuntimeError(
                "ODA File Converter 未安装。请从 https://www.opendesign.com/guestfiles/oda_file_converter "
                "下载安装（非商业用途免费）。"
            )

        dwg_path = Path(dwg_path).resolve()
        if not dwg_path.exists():
            raise FileNotFoundError(f"DWG 文件不存在: {dwg_path}")

        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        # ODA converts entire folders. Use a temp input dir with a copy.
        import tempfile

        with tempfile.TemporaryDirectory(prefix="cadkb_oda_in_") as tmp_in:
            # Copy the DWG into the temp input folder
            copied = Path(tmp_in) / dwg_path.name
            shutil.copy2(dwg_path, copied)

            # Expected output file: same name with .dxf extension
            expected_out = output_dir / (dwg_path.stem + ".dxf")

            # Remove stale output if it exists from a previous run
            if expected_out.exists():
                expected_out.unlink()

            exit_code = self._run_converter(
                input_folder=tmp_in,
                output_folder=str(output_dir),
                output_version=output_version,
                output_format="DXF",
                recurse=False,
                audit=audit,
            )

            if exit_code != 0:
                logger.error(f"ODA 转换失败，退出码: {exit_code} (输入: {dwg_path.name})")
                return None

            # ODA may exit 0 before the file is fully written; poll for it
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                if expected_out.exists() and expected_out.stat().st_size > 0:
                    return expected_out
                time.sleep(wait_poll_interval)

            raise TimeoutError(
                f"ODA 转换超时（{self.timeout}s）: {dwg_path.name} -> {expected_out}"
            )

    def convert_directory(
        self,
        input_dir: str | Path,
        output_dir: str | Path,
        output_version: str = "ACAD2018",
        output_format: str = "DXF",
        recurse: bool = True,
        audit: bool = True,
    ) -> int:
        """Convert all matching files in a directory.

        Args:
            input_dir: Source directory.
            output_dir: Destination directory.
            output_version: ODA version code.
            output_format: "DXF", "DWG", or "DGN".
            recurse: Process subdirectories.
            audit: Enable audit/repair.

        Returns:
            Number of output files produced.
        """
        if not self.is_available():
            raise RuntimeError("ODA File Converter 未安装。")

        input_dir = Path(input_dir).resolve()
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        exit_code = self._run_converter(
            input_folder=str(input_dir),
            output_folder=str(output_dir),
            output_version=output_version,
            output_format=output_format,
            recurse=recurse,
            audit=audit,
        )
        if exit_code != 0:
            logger.error(f"ODA 批量转换失败，退出码: {exit_code}")
            return 0

        ext = ".dxf" if output_format.upper() == "DXF" else ".dwg"
        results = list(output_dir.glob(f"*{ext}"))
        return len(results)

    def _run_converter(
        self,
        input_folder: str,
        output_folder: str,
        output_version: str,
        output_format: str,
        recurse: bool,
        audit: bool,
    ) -> int:
        """Run ODAFileConverter.exe with the given arguments."""
        args = [
            self.exe_path,
            input_folder,
            output_folder,
            output_version,
            output_format,
            "1" if recurse else "0",
            "1" if audit else "0",
        ]
        logger.info(f"ODA 转换: {Path(input_folder).name} -> {Path(output_folder).name} ({output_version} {output_format})")

        # ODA GUI converter returns immediately after queueing; use subprocess
        # with a hard timeout to avoid hangs.
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            return proc.returncode
        except subprocess.TimeoutExpired:
            logger.error(f"ODA 转换进程超时（{self.timeout}s）")
            return -1
        except OSError as e:
            logger.error(f"无法启动 ODA 转换器: {e}")
            return -1


def convert_dwg_to_dxf(
    dwg_path: str | Path,
    output_dir: str | Path,
    output_version: str = "ACAD2018",
) -> Path | None:
    """Convenience function: convert a DWG file to DXF.

    Returns path to generated DXF or None on failure.
    """
    converter = ODAConverter()
    return converter.convert_dwg_to_dxf(dwg_path, output_dir, output_version)
