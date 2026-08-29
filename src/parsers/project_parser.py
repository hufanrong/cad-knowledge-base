"""Microsoft Project (.mpp) parser — Phase 4.

Priority:
1. MS Project COM via pywin32 (win32com) — verified on this machine.
   Extracts: project name, tasks, WBS, IDs, start/finish, duration,
   predecessors, resources, owners, status, %complete, milestones, links.
   Uses FileOpen (Application 层) + ActiveProject — 实测 comtypes 与
   Projects.Open 在本机因 MS Project 类型库注册异常均不可用，
   win32com 的 Application.FileOpen 是唯一可用入口。
2. Fallback: mpxj via JVM (optional; not assumed).
3. If neither is usable: keep the archive copy + mark "暂不可解析"
   (never fabricate data).

Output: ParsedDocument (JSON + Markdown).
"""

from __future__ import annotations

from pathlib import Path

from src.normalizer.schema import ParsedDocument, ParsedSection, TableData
from src.utils.logger import setup_logger

logger = setup_logger("cadkb.parsers.project")


def _pywin32_available() -> bool:
    try:
        import win32com.client  # noqa: F401
        return True
    except ImportError:
        return False


def is_ms_project_available() -> bool:
    """Check whether MS Project COM is registered (without launching)."""
    import winreg
    try:
        winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"MSProject.Application")
        return True
    except FileNotFoundError:
        return False
    except Exception:
        return False


class ProjectParser:
    """Parse .mpp via MS Project COM (or mark unsupported)."""

    name = "project_parser"

    def parse(self, file_path: str | Path) -> ParsedDocument:
        path = Path(file_path)
        result = ParsedDocument(
            source_file=path.name,
            source_type="project",
            parser=self.name,
        )
        result.title = path.stem

        if not _pywin32_available():
            result.parse_status = "pending"
            result.errors.append("pywin32 未安装，无法解析 MPP")
            return result

        if not is_ms_project_available():
            result.parse_status = "pending"
            result.errors.append(
                "未检测到 Microsoft Project。已保留文件副本，标记为暂不可解析。"
                "安装 MS Project 或通过 Project 导出 XML 后重新导入。")
            return result

        # Try COM (win32com FileOpen 路线)
        try:
            return self._parse_via_com(path, result)
        except Exception as e:
            logger.warning(f"MPP COM 解析失败: {path.name} - {e}")
            result.parse_status = "pending"
            result.errors.append(
                f"COM 解析失败: {e}。已保留副本，标记为暂不可解析。")
            return result

    # ── MS Project COM (win32com) ───────────────────────────────────

    def _parse_via_com(self, path: Path, result: ParsedDocument) -> ParsedDocument:
        import win32com.client

        app = win32com.client.Dispatch("MSProject.Application")
        try:
            app.Visible = False
            app.DisplayAlerts = False
            # 本机 MS Project 类型库注册异常：Projects.Open 不可用，
            # 唯一可用入口是 Application.FileOpen + ActiveProject（实测 902 任务成功）。
            app.FileOpen(str(path))
            proj = app.ActiveProject

            # Project metadata
            result.title = proj.Name or path.stem
            result.metadata = {
                "project_name": proj.Name,
                "task_count": proj.Tasks.Count,
            }
            try:
                result.metadata["status"] = str(proj.StatusDate or "")
            except Exception:
                pass

            # Tasks
            rows: list[list[str]] = []
            header = ["编号", "WBS", "任务名称", "开始", "完成",
                      "工期(天)", "前置任务", "负责人", "完成%", "里程碑"]
            for i in range(1, proj.Tasks.Count + 1):
                try:
                    t = proj.Tasks(i)
                    if t is None:
                        continue
                    milestone = ""
                    try:
                        if t.Milestone:
                            milestone = "是"
                    except Exception:
                        pass
                    rows.append([
                        str(getattr(t, "ID", "")),
                        str(getattr(t, "WBS", "")),
                        str(getattr(t, "Name", "")),
                        str(getattr(t, "Start", ""))[:10],
                        str(getattr(t, "Finish", ""))[:10],
                        str(round(getattr(t, "Duration", 0) or 0, 1)),
                        str(getattr(t, "Predecessors", "")),
                        str(getattr(t, "ResourceNames", "")),
                        str(getattr(t, "PercentComplete", 0)),
                        milestone,
                    ])
                except Exception:
                    continue

            if rows:
                result.tables.append(TableData(
                    sheet="任务列表", headers=header, rows=rows))

            # Milestones summary
            milestones = [r for r in rows if r[9] == "是"]
            result.metadata["milestone_count"] = len(milestones)

            try:
                app.FileClose(False)
            except Exception:
                pass
            result.parse_status = "success"
            result.content = self._build_content(result)
            result.markdown = self._build_markdown(result)
            logger.info(
                f"MPP 解析完成: {path.name} (任务 {len(rows)}, "
                f"里程碑 {len(milestones)})")
            return result
        finally:
            try:
                app.Quit()
            except Exception:
                pass

    # ── output ───────────────────────────────────────────────────────

    def _build_content(self, result: ParsedDocument) -> str:
        lines = [f"项目: {result.title}"]
        for td in result.tables:
            if td.headers:
                lines.append(" | ".join(td.headers))
            for row in td.rows:
                lines.append(" | ".join(row))
        return "\n".join(lines)

    def _build_markdown(self, result: ParsedDocument) -> str:
        lines = [f"# {result.title}", ""]
        for k, v in result.metadata.items():
            lines.append(f"- {k}: {v}")
        for td in result.tables:
            lines.append(f"\n## {td.sheet}")
            if td.headers:
                lines.append("| " + " | ".join(td.headers) + " |")
                lines.append("|" + "|".join(["---"] * len(td.headers)) + "|")
            for row in td.rows:
                lines.append("| " + " | ".join(row) + " |")
        return "\n".join(lines)


def parse_project(file_path: str | Path) -> ParsedDocument:
    """Convenience wrapper."""
    return ProjectParser().parse(file_path)
