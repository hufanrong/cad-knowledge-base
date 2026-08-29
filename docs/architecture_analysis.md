# 架构分析报告：WorkBuddy 私人资料库多格式扩展

> 日期：2026-08-18
> 性质：**纯分析，未修改任何代码**
> 范围：现有 CAD-Knowledge-Base 系统 → 扩展为多格式（Word/Excel/PDF/Project/图片/通用文件）统一资料库

---

## 一、当前系统架构

### 1.1 程序与项目位置（实测确认）

```
D:\WorkBuddy\                                          ← WorkBuddy 程序根（真实数据）
├── program\                                           ← 程序文件
├── work\                                              ← 应用数据
│   ├── data\                                          ←   memory / skills / logs / sessions / workbuddy.db
│   ├── roaming\  appdata-local\  key-fallback\  updater\
└── outputs\projects\<会话id>\CAD-Knowledge-Base\      ← 当前项目工作区（= D:\hufanrong\Documents\workBudd\...\CAD-Knowledge-Base，同一目录）
```

当前 CAD 项目代码实际路径：
`D:\WorkBuddy\outputs\projects\2026-08-17-14-05-54\CAD-Knowledge-Base\`

### 1.2 当前资料库实际路径（实测确认）

```
D:\CADKnowledgeBase\                                   ← 现有资料库数据（独立根目录）
├── database\cadkb.db      (3.3 GB, SQLite，191 张图纸 / 327 万实体)
├── embeddings\            (Chroma 向量索引, 22.5 万块)
├── raw\                   ← ⚠️ 存在但为空（见 §3.4 关键缺口）
├── parsed\ normalized\ metadata\ thumbnails\ logs\
```

### 1.3 项目代码结构

```
CAD-Knowledge-Base/
├── src/
│   ├── core/config.py          # 配置（YAML + 环境变量 CADKB_*）
│   ├── database/               # models.py (SQLAlchemy) + repositories.py + connection.py(FTS5)
│   ├── file_manager/           # importer.py + hasher.py + version_detector.py
│   ├── parsers/                # dxf_parser / dwg_parser / oda_converter / autocad_com
│   ├── normalizer/schema.py    # Pydantic 统一模型 + FileType/ParseStatus 枚举
│   ├── semantic/               # 图框/标题栏/设备/管道（带置信度）
│   ├── spatial/                # 空间关系（near/contains/annotates）
│   ├── index/                  # search_service（FTS+结构化+空间）+ vector_index（Chroma）+ index_manager
│   ├── rag/                    # hybrid_search + reranker + context_builder
│   ├── qa/qa_service.py        # AI 问答（LLM/证据双模式，来源追溯）
│   ├── api/app.py              # FastAPI（status/drawings/search/rag/query/compare）
│   ├── cli/main.py             # Click（import/parse/query/rag/compare/serve/gui/...）
│   ├── gui/                    # Streamlit（导入/浏览/搜索/问答/比较）
│   ├── compare/differ.py       # 图纸差异比较
│   ├── chunker/                # 向量分块
│   └── utils/                  # 日志
├── config/default.yaml         # 路径配置（当前指向 D:/CADKnowledgeBase）
├── docs/  scripts/  tests/  run.bat
```

---

## 二、现有功能盘点（可复用基础）

| # | 能力 | 实现 | 状态 |
|---|------|------|------|
| 1 | DXF 解析 | ezdxf（实体/文字/尺寸/图层/块/布局） | ✅ 生产可用 |
| 2 | DWG 解析 | ODA 转换 + ezdxf；AutoCAD COM 备选 | ✅ 生产可用 |
| 3 | 多版本兼容 | R12~R2018 版本识别 + 兼容矩阵测试 | ✅ |
| 4 | 语义分析 | 图框/标题栏/设备/管道，带置信度字段 | ✅ |
| 5 | 空间关系 | 几何邻近/包含/标注 3 类关系 | ✅ |
| 6 | 全文搜索 | SQLite FTS5（unicode61） | ✅（中文分词弱，见风险 R3） |
| 7 | 向量检索/RAG | Chroma + bge-small-zh + 混合检索 + 重排序 | ✅ |
| 8 | AI 问答 | LLM 模式 + 证据模式，来源追溯 | ✅ |
| 9 | 文件去重 | SHA256 + find_by_hash + duplicate 状态 | ✅ 已实现 |
| 10 | 图纸比较 | 实体/文字/尺寸/语义 diff | ✅ |
| 11 | REST API | FastAPI 7 端点 | ✅ |
| 12 | GUI | Streamlit 5 页面 + 缩略图 | ✅ |
| 13 | 日志 | colorlog 滚动日志 | ✅ |

---

## 三、对照需求的关键缺口分析

### 3.1 文件类型识别 — 部分满足，需扩展

现状：`version_detector.py` 仅按**扩展名** + DWG 魔数（前 6 字节 `AC`）判断。

| 需求 | 现状 | 缺口 |
|------|------|------|
| 扩展名判断 | ✅ dwg/dxf/pdf/image | ❌ 无 word/excel/project/通用格式 |
| MIME 判断 | ❌ 无 | 需新增（mimetypes/magic 库） |
| Magic Number | ⚠️ 仅 DWG | 需新增 docx(`PK`)/xlsx(`PK`)/pdf(`%PDF`)/mpp/图片 等 |
| 防伪装 | ❌ 无 | 需"扩展名 vs 实际格式"交叉校验 |

### 3.2 统一 File ID — 部分满足，需统一

现状：`drawing_id` = UUID（如 `78087768-b3aa-...`），CAD 专用。

需求：统一 `file_id`（如 `WB-20260818-000001` 或 UUID），全库唯一、稳定、可追溯。

方案：保留现有 `drawing_id` 不动（兼容），**新增通用 `files` 表**，`drawing_id` 作为 CAD 子类型的外键关联。

### 3.3 原始文件副本 — ❌ 核心缺口（未实现）

实测确认：`D:\CADKnowledgeBase\raw\dwg\` **为空**；`importer.py` 无任何 `shutil.copy`。

现状：导入只保存 `file_path`（原始路径引用）——**一旦原文件移动/删除，副本即失效**。

需求：原始文件 → SHA256 → 复制副本到 `OriginalFiles\<类型>\` → 数据库记录 `original_path` + `archive_path`。

### 3.4 路径解耦 — ⚠️ 半满足

- ✅ `file_path` 保存原始绝对路径
- ❌ 无 `archive_path`（资料库副本路径）
- ❌ 无"多来源"记录（同一 SHA256 多路径只记一条）

### 3.5 版本管理 — ⚠️ 表存在但未启用

- 已有 `DrawingRevisionModel` 表（revision_id/drawing_id/file_hash/...），**但 importer 从未写入**
- 需启用：文件变化（新 SHA256）→ 生成新版本记录 + 保留旧副本/旧解析

### 3.6 项目关联 — ❌ 无

无 project 概念。需新增：
- `projects` 表（project_id/name/confidence/source）
- 项目推断来源：文件名前缀、标题栏字段、Word 标题、Excel 内容、路径关键词、用户指定
- **原则：推断必须带置信度，无法确定则 project=null（不猜测）**

### 3.7 文件间关联 — ❌ 无

需新增 `file_relations` 表（file_a/file_b/relation_type/confidence/source），relation_type 如 `same_project`/`same_equipment`/`same_material`。

### 3.8 多格式解析 — ❌ 全缺

`_select_parser()` 中 PDF/IMAGE 返回 None，Word/Excel/Project 无入口。需新建 5 类解析器（见 §六）。

### 3.9 统一搜索 — ⚠️ 半满足

SearchService 只覆盖 CAD（drawings/texts/equipment/dimensions）。需扩展为跨格式统一搜索。

### 3.10 API — ⚠️ 半满足

现有 7 个 CAD 端点；需新增 `search_files/search_by_project/get_file/get_related_files` 等统一接口。

---

## 四、可复用 vs 需新增/修改 清单

### ✅ 直接复用（不修改）
- `hasher.py`（SHA256 + 快速哈希）
- `parsers/base_parser.py`（BaseParser 接口）
- `semantic/`（标题栏/设备识别可反哺项目推断）
- `spatial/`、`compare/`、`chunker/`、`qa/`（CAD 侧保持不动）
- 向量索引/重排序/RAG 基础设施（新增格式解析后可接入同一通道）

### 🔧 需要修改（扩展现有架构，非重构）
| 文件 | 修改点 |
|------|--------|
| `normalizer/schema.py` | FileType 枚举扩展（DOCX/XLSX/PDF/PROJECT/...）+ 统一 File/Project 模型 |
| `database/models.py` | 新增 files/file_sources/projects/file_relations/versions 表（**保留现有表**） |
| `file_manager/version_detector.py` | 全格式识别：扩展名 + MIME + Magic Number |
| `file_manager/importer.py` | 通用化：副本复制、file_id、多来源、版本检测、多解析器路由 |
| `index/search_service.py` | 统一跨格式搜索 + 按项目/设备/材料检索 |
| `core/config.py` + `default.yaml` | 目录体系迁移（见 §七） |
| `api/app.py` | 新增统一接口端点 |
| `cli/main.py` | 新增 scan/import-any/查询命令 |

### ➕ 需要新增
- `src/parsers/word_parser.py` / `excel_parser.py` / `pdf_parser.py` / `project_parser.py` / `image_parser.py` / `generic_parser.py`
- `src/core/file_registry.py`（归档副本 + 版本 + file_id 管理）
- `src/core/project_inference.py`（项目推断 + 置信度）
- `src/core/file_relations.py`（文件关联发现）
- 新 DB 迁移脚本（SQLite 新增表，兼容旧库）

---

## 五、潜在风险

| # | 风险 | 等级 | 应对 |
|---|------|------|------|
| R1 | 现有库 **3.3GB / 191 图纸**，schema 升级必须无损兼容 | 高 | 只加表不删改；SQLite ALTER/新建表 + 启动时自动迁移；升级前整库备份 |
| R2 | FTS5 `unicode61` 对中文按字符切分，跨格式中文搜索精度弱 | 中 | 保持现状（CAD 已接受）；新增格式的搜索可叠加向量检索补偿；不替换现有索引 |
| R3 | `.doc`/`.xls` 旧二进制格式解析依赖（xlrd 停维护、doc 无纯 Python 方案） | 中 | 优先支持 docx/xlsx；旧格式经 LibreOffice 转换或标记"暂不可解析"（保留副本，不伪造） |
| R4 | `.mpp` 无轻量纯 Python 库：mpxj 需 JVM，MS Project COM 需装软件 | 中 | 检测本机 MS Project COM（复用 autocad_com 模式）；无则保留副本 + 标记"暂不可解析"，提示用户 |
| R5 | 扫描型 PDF/图片 OCR 依赖 Tesseract/PaddleOCR（较重） | 中 | OCR 可选安装；**强制标记 source=OCR + confidence**，不伪装成原始文字 |
| R6 | 原始文件副本会占磁盘（文件多且大） | 低 | D 盘余 770GB 充足；同 SHA256 只存一份实体副本（多来源仅记记录） |
| R7 | 隐私要求：不自动上传云端 | 合规 | 全部本地处理；LLM 保持可选、api_key 留空即离线（当前即如此） |
| R8 | 新增依赖未经确认安装 | 合规 | 所有新依赖先列清单 → 老板确认 → 再安装（遵循现有安全流程） |

---

## 六、多格式解析方案（Phase 3/4 实施建议）

| 格式 | 库/方案 | 提取内容 | 输出 | 降级策略 |
|------|---------|---------|------|---------|
| **Word .docx** | python-docx | 标题/正文/表格/图片说明/页眉页脚/属性 | JSON+MD+TXT | .doc 用 LibreOffice 转换或标记不可解析 |
| **Excel .xlsx/.xlsm/.csv** | openpyxl + csv + pandas | 工作簿/Sheet/表头/单元格/合并单元格/公式/隐藏Sheet | **结构化 JSON**(workbook/sheet/headers/rows) + MD | .xls 经 LibreOffice 转 xlsx 或 xlrd |
| **PDF 文字型** | pypdf/pdfplumber + PyMuPDF | 标题/正文/表格/页码 | TXT+JSON | 提取失败则走 OCR |
| **PDF 扫描型** | pytesseract（可选）/PaddleOCR | OCR 文本 | TXT，**标记 source=OCR + confidence** | 未装 OCR → 保留副本 + 标记 |
| **Project .mpp** | ①本机 MS Project COM ②mpxj(JVM) | 项目名/任务/WBS/工期/前置/资源/里程碑 | JSON+MD | 不可解析 → 副本 + "暂不可解析"提示 |
| **图片** | PIL 元数据 + pytesseract OCR | EXIF/尺寸/OCR 文本 | JSON+TXT | OCR 可选 |
| **通用** | 内置 | txt/xml/json/html/rtf 文本提取；pptx 用 python-pptx | TXT+JSON | 无法解析 → 副本 + 元数据 + Hash |

**统一原则**：任何格式即使无法解析，也**必须**：保存原始副本 + 文件元数据 + SHA256（"不因无法解析而拒绝纳入"）。

---

## 七、文件归档方案（归入 WorkBuddy 体系）

用户要求：资料库作为 **WorkBuddy 子目录**，不放在 `D:\` 根。

实测 WorkBuddy 结构：程序根 `D:\WorkBuddy\`，应用数据在 `D:\WorkBuddy\work\data\`。

**推荐归档位置**（与 WorkBuddy 数据体系一致）：

```
D:\WorkBuddy\
└── work\
    └── data\
        └── knowledge_base\                ← 新资料库根（WorkBuddy 数据体系内）
            ├── OriginalFiles\             ← 原始副本（按类型，SHA256 去重）
            │   ├── CAD\  Word\  Excel\  PDF\  Project\  Images\  Other\
            ├── ParsedData\                ← 解析结果（JSON/MD/TXT）
            │   ├── CAD\  Word\  Excel\  PDF\  Project\  Other\
            ├── Database\cadkb.db          ← 数据库（合并现有 3.3GB 库）
            ├── VectorDB\                  ← Chroma 向量（现有 embeddings\ 迁入）
            ├── Index\                     ← FTS/搜索索引
            ├── Preview\                   ← 缩略图/预览
            ├── Logs\
            └── Temp\
```

**迁移方案**（老板确认后执行）：
1. 将现有 `D:\CADKnowledgeBase\*`（3.3GB）整体移动到 `D:\WorkBuddy\work\data\knowledge_base\`
2. 更新 `config/default.yaml` 路径（保持环境变量 `CADKB_*` 覆盖能力）
3. 旧目录移动**非删除**（移动成功后留备份确认，稳定后再清理——沿用历史迁移经验）

> 注：不采用"原位置不动+新位置再建"双份方案，避免数据分裂。

---

## 八、数据库升级方案

**原则：只增不改、无损迁移、启动自动迁移、升级前备份。**

新增表（现有 drawings/entities/texts/... 全部不动）：

```sql
-- 统一文件表（全格式）
files (
  file_id TEXT PK,            -- WB-20260818-000001 或 UUID
  sha256 TEXT UNIQUE NOT NULL,
  original_name TEXT, original_path TEXT,
  archive_path TEXT,          -- OriginalFiles 内副本路径
  file_type TEXT, source_type TEXT,   -- cad/word/excel/pdf/project/image/other
  file_size INT, created_time, modified_time, import_time,
  project_id TEXT, category TEXT, tags TEXT,
  parser TEXT, parse_status TEXT, parse_time TEXT,
  extra JSON
)
-- 多来源（同 hash 多个原始路径）
file_sources (source_id PK, file_id FK, original_path, found_time)
-- 项目
projects (project_id PK, name, confidence FLOAT, source TEXT, created_at)
-- 文件关联
file_relations (rel_id PK, file_a FK, file_b FK, relation_type, confidence, source)
-- 版本（复用/扩展 drawing_revisions 模式）
file_versions (version_id PK, file_id FK, version_no INT, sha256, archive_path, parse_status, created_at)
-- CAD 桥接
drawing_id 保留；files.file_id 关联到 drawings.drawing_id（CAD 文件）
```

---

## 九、开发路线（对齐用户 Phase 1-6）

| 阶段 | 内容 | 产出 |
|------|------|------|
| **Phase 1** | 架构分析（本文档） | ✅ 已完成 |
| **Phase 2** | 统一数据模型 + 数据库迁移（新表）+ FileID + 副本归档 + 去重/多来源 + 版本 | 数据层就绪，CAD 功能回归测试通过 |
| **Phase 3** | Word / Excel / PDF 解析器 + 结构化入库 + MD 生成 | 三格式可导入、可搜索 |
| **Phase 4** | Project(.mpp) 解析（COM 检测 + 降级方案）+ 图片/通用格式 | 全格式覆盖 |
| **Phase 5** | 统一搜索 + 项目关联（置信度）+ 文件关联 + 重新扫描 | 跨格式检索、按项目/设备/材料查询 |
| **Phase 6** | VectorDB/RAG/LLM/Agent 统一接口（search_files/search_by_project/get_file/...） | 大模型统一调用 |

**每阶段验收**：现有 124 个测试保持全绿 + 新增测试 + 老板实际文件验证。

---

## 十、结论与待确认事项

系统扩展**不需要重构**：现有架构（importer 管道 + Pydantic schema + SQLAlchemy + FTS/向量/RAG）可平滑扩展，CAD 能力完全保留。

实施前需老板确认：

1. **资料库位置**：迁移到 `D:\WorkBuddy\work\data\knowledge_base\`（推荐）还是其它 WorkBuddy 子目录？
2. **迁移方式**：现有 `D:\CADKnowledgeBase` 3.3GB 是否同意移动到新位置（移动非删除，可回退）？
3. **依赖安装**：python-docx / openpyxl / pypdf / pdfplumber / python-pptx / Pillow 等为解析必需；OCR(Tesseract/PaddleOCR)、mpxj(JVM)、MS Project COM 为可选——是否按默认清单安装必需项？
4. **开发节奏**：按 Phase 2→6 逐阶段推进，每阶段完成即回归测试 + 展示，是否 OK？
5. **File ID 格式**：`WB-YYYYMMDD-NNNNNN` 还是 UUID？（两者皆可，建议 WB 格式便于人读）
