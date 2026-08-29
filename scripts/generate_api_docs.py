"""从 FastAPI app 导出中文离线 Markdown API 手册。"""
from __future__ import annotations

from pathlib import Path

from src.api.app import app

OUT = Path("D:/WorkBuddy/outputs/projects/2026-08-17-14-05-54/CAD-Knowledge-Base/docs/API_MANUAL.md")

# 接口作用说明（中文）
USAGE = {
    "/api/status": "查看系统运行状态、图纸数量、向量索引等统计信息。",
    "/api/drawings": "分页列出知识库中所有 CAD 图纸的元数据。",
    "/api/drawings/{drawing_id}": "按 drawing_id 查询单张图纸的详细摘要。",
    "/api/search": "对 CAD 图纸内容做综合检索（文字、属性、设备等）。",
    "/api/rag": "RAG 混合检索：全文 + 向量 + 结构化 + 重排序。",
    "/api/query": "AI 问答接口，返回答案和可追溯的来源上下文。",
    "/api/compare": "比较两张 CAD 图纸的差异，返回变更清单。",
    "/api/files": "跨格式文件列表/搜索（CAD、Word、Excel、PDF 等）。",
    "/api/files/{file_id}": "查询单个文件的元数据、原始路径和解析产物。",
    "/api/search-all": "统一跨格式搜索：CAD + 文档 + 文件元数据。",
    "/api/projects": "列出系统推断出的全部项目。",
    "/api/projects/{name}/files": "查询某个项目下的所有文件。",
    "/api/documents/{file_id}/content": "获取非 CAD 文档（Word/Excel/PDF）的解析内容。",
    "/api/devices": "列出设备主数据，支持按位号/名称搜索或子系统过滤。",
    "/api/devices/{tag_no}/profile": "按位号返回完整设备档案：跨图位置、箱单、供应商、关联文档。",
}


def schema_type(props: dict) -> str:
    if "$ref" in props:
        return props["$ref"].split("/")[-1]
    t = props.get("type", "any")
    if t == "array":
        items = props.get("items", {})
        return f"数组[{schema_type(items)}]"
    return t


def main():
    spec = app.openapi()
    info = spec.get("info", {})
    lines = [
        f"# {info.get('title', 'API')} 接口手册（中文版）",
        "",
        f"版本：{info.get('version', '-')}",
        "",
        "本文档说明 CAD 知识库对外暴露的 HTTP 接口及其用途。",
        "启动服务后，也可在浏览器访问交互式文档：http://localhost:8000/docs",
        "",
        "## 目录",
        "",
    ]

    paths = spec.get("paths", {})
    for path in sorted(paths):
        for method in sorted(paths[path]):
            anchor = f"{method}-{path.replace('/', '').replace('{', '').replace('}', '')}"
            lines.append(f"- [{method.upper()} {path}](#{anchor}) — {USAGE.get(path, '')}")

    lines.append("")
    lines.append("## 接口详情")
    lines.append("")

    for path in sorted(paths):
        for method in sorted(paths[path]):
            op = paths[path][method]
            lines.append(f"### {method.upper()} {path}")
            lines.append("")

            desc = op.get("description") or op.get("summary", "")
            if desc:
                lines.append(desc)
                lines.append("")

            usage = USAGE.get(path)
            if usage:
                lines.append(f"**作用：** {usage}")
                lines.append("")

            params = op.get("parameters", [])
            if params:
                lines.append("**参数：**")
                lines.append("")
                for p in params:
                    req = "（必填）" if p.get("required") else ""
                    lines.append(
                        f"- `{p['name']}`：{schema_type(p.get('schema', {}))} "
                        f"{p.get('description', '')}{req}"
                    )
                lines.append("")

            body = op.get("requestBody", {})
            if body:
                content = body.get("content", {}).get("application/json", {}).get("schema", {})
                lines.append(f"**请求体：** `{schema_type(content)}`")
                lines.append("")

            resp = op.get("responses", {}).get("200", {})
            if resp:
                content = resp.get("content", {}).get("application/json", {}).get("schema", {})
                lines.append(f"**响应：** `{schema_type(content)}`")
                lines.append("")
            lines.append("---")
            lines.append("")

    schemas = spec.get("components", {}).get("schemas", {})
    if schemas:
        lines.append("## 数据模型")
        lines.append("")
        for name, s in sorted(schemas.items()):
            lines.append(f"### {name}")
            lines.append("")
            req = set(s.get("required", []))
            for prop, props in s.get("properties", {}).items():
                mark = "（必填）" if prop in req else ""
                desc = props.get("description", "")
                lines.append(f"- `{prop}`：{schema_type(props)} {desc}{mark}")
            lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"API 中文手册已生成: {OUT}")


if __name__ == "__main__":
    main()
