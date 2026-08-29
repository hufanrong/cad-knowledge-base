# CAD Knowledge Base — 本地 CAD 图纸解析与私人知识库系统

> 阶段：Phase 10 (DXF + DWG 解析 + 语义分析 + 空间关系 + 搜索 + RAG + AI 问答 + REST API + 版本兼容 + 图纸比较 + GUI)  
> 日期：2026-08-17  
> 原则：准确性 > 完整性 > 性能 > UI美观；原始数据 > AI推测；可追溯 > 看起来智能

## 项目简介

**CAD Knowledge Base** 是一套面向工业工程场景的本地 CAD 图纸解析与私人知识库系统。
它将 DXF/DWG 图纸解析为结构化数据，自动完成语义分析（图框/标题栏/设备/管道）、
空间关系计算、全文 + 向量混合检索（RAG）、AI 问答（带来源追溯）与图纸差异比较，
并提供 **CLI、REST API、Streamlit GUI** 三种交互方式。

核心特性：

- 🔧 支持 DXF / DWG（R12–R2018，ODA 或 AutoCAD COM 转换）
- 🧠 语义分析：图框 / 标题栏 / 设备位号 / 管道管径，规则推断带置信度
- 🗺️ 空间关系：包含 / 相交 / 邻近 / 标注 / 归属
- 🔍 三种搜索：全文 FTS5 + 结构化 + 空间区域
- 🤖 RAG 混合检索 + 重排序 + AI 问答（LLM 模式 / 证据模式，绝不编造）
- 📊 图纸差异比较（实体 / 文字 / 尺寸 / 语义）
- 🖥️ 三种入口：CLI / REST API / Streamlit GUI
- 🔒 数据全本地存储，API Key 走 `.env`，知识库数据不进 Git

## 环境要求

| 依赖 | 要求 |
|------|------|
| 操作系统 | Windows 10/11、Linux、macOS |
| Python | **3.10 – 3.13**（推荐 3.11+，已验证 3.13） |
| 磁盘空间 | 依赖约 3GB（含 torch CPU 版）；知识库数据另计 |
| 网络 | 首次安装需联网下载依赖；Embedding 模型首次使用时自动下载 |
| 可选 | ODA File Converter（DWG 解析）、Ollama 或 LLM API Key（AI 问答） |

> ⚠️ **torch 说明**：请务必安装 CPU 版，避免下载数 GB 的 CUDA 依赖：
> `pip install torch --index-url https://download.pytorch.org/whl/cpu`

### 依赖锁定策略

- `requirements.txt` 为**顶层依赖**（声明版本下限），跨平台可安装；
- `torch` / `chromadb` 等包存在平台差异，**不使用全局 lock 文件**——跨机一致性
  由「一键脚本（setup.bat/setup.sh）+ Docker 镜像」保证：Docker 镜像内版本
  在构建时即被锁定，换机可复现；
- 如需手动锁定某一环境：`pip freeze > requirements.lock.txt`（仅用于该环境的
  精确复现，不要跨平台共用）。

## 快速开始

### 1. 安装依赖

```bash
cd CAD-Knowledge-Base
pip install -r requirements.txt
```

### 2. 生成测试文件

```bash
python scripts/generate_test_dxf.py tests/fixtures/dxf
# DWG 测试文件（需要 ODA File Converter）
python scripts/generate_test_dwg.py
```

### 3. 运行测试

```bash
python -m pytest tests/ -v
```

### 4. 导入 CAD 文件（DXF 或 DWG）

```bash
# Windows
run.bat import tests/fixtures/dxf/test_all_entities.dxf
run.bat import tests/fixtures/dwg/test_all_entities.dwg

# 或直接用 Python
python -m src.cli.main import tests/fixtures/dxf/test_all_entities.dxf
python -m src.cli.main import tests/fixtures/dwg/test_all_entities.dwg
```

### 5. 查看系统状态

```bash
python -m src.cli.main status
```

### 6. 搜索

```bash
python -m src.cli.main search "酸化窑"
```

### 7. 检视文件

```bash
python -m src.cli.main inspect tests/fixtures/dxf/test_all_entities.dxf --texts
python -m src.cli.main inspect tests/fixtures/dxf/test_all_entities.dxf --entities
python -m src.cli.main inspect tests/fixtures/dxf/test_all_entities.dxf --dims
```

## CLI 命令一览

| 命令 | 说明 |
|------|------|
| `cadkb import <file>` | 导入单个 CAD 文件 |
| `cadkb import <dir> -r` | 递归导入目录下所有 CAD 文件 |
| `cadkb import <file> -f` | 强制重新导入（忽略重复） |
| `cadkb inspect <file>` | 查看文件信息和解析结果 |
| `cadkb inspect <file> --entities` | 查看实体列表 |
| `cadkb inspect <file> --texts` | 查看文字列表 |
| `cadkb inspect <file> --dims` | 查看尺寸列表 |
| `cadkb inspect <file> --semantic` | 查看语义分析结果(图框/标题栏/设备/管道) |
| `cadkb inspect <file> --spatial` | 查看空间关系 |
| `cadkb search <query>` | 统一搜索(全文+结构化) |
| `cadkb search <query> --type equipment` | 结构化搜索(设备/文字/属性/标题栏字段等) |
| `cadkb search-region --min-x .. --max-y ..` | 空间区域搜索 |
| `cadkb rag <query>` | RAG 混合检索(全文+向量+结构化+重排序) |
| `cadkb query <问题>` | AI 问答（LLM 生成 + 来源追溯 / 证据模式） |
| `cadkb rebuild-index --embeddings` | 重建向量索引 |
| `cadkb compare A.dwg B.dwg` | 比较两张图纸差异 |
| `cadkb gui` | 启动 Streamlit 图形界面 |
| `cadkb serve` | 启动 REST API |
| `cadkb status` | 系统状态 |

## 支持的实体类型

| 实体 | 解析 | 说明 |
|------|------|------|
| LINE | 支持 | 起点/终点/长度/角度 |
| CIRCLE | 支持 | 圆心/半径/周长/面积 |
| ARC | 支持 | 圆心/半径/起止角/弧长 |
| LWPOLYLINE | 支持 | 顶点列表/闭合状态 |
| POLYLINE | 支持 | 2D/3D 多段线 |
| SPLINE | 支持 | 控制点/拟合点 |
| ELLIPSE | 支持 | 中心/长轴/短轴比 |
| TEXT | 支持 | 文字内容/位置/高度/旋转 |
| MTEXT | 支持 | 多行文字(去除格式码) + 保留原始文本 |
| DIMENSION | 支持 | 线性/对齐/角度/半径/直径 |
| LEADER | 支持 | 引线点 |
| HATCH | 支持 | 边界路径/填充图案 |
| INSERT | 支持 | 块引用/缩放/旋转 |
| ATTRIB | 支持 | 块属性 tag/value |
| POINT | 支持 | 点坐标 |
| VIEWPORT | 支持 | 视口信息 |

## 数据分层

所有数据严格区分层级，绝不混淆：

| 层级 | 说明 | 示例 |
|------|------|------|
| RAW | 从 CAD 文件直接读取 | 直径=4500mm |
| NORMALIZED | 转换为统一 Schema | entity_type=DIMENSION, measurement=4500 |
| DERIVED | 计算推导得出 | 圆周长=14137mm |
| AI_INFERENCE | AI 识别/推测 | 设备类型=回转窑 (confidence=0.82) |
| USER_NOTE | 用户手动标注 | 用户添加的备注 |

## 目录结构

```
CAD-Knowledge-Base/
├── src/
│   ├── core/           # 配置管理
│   ├── file_manager/   # 文件导入/哈希/版本识别
│   ├── parsers/        # DXF/DWG 解析器 + ODA 封装
│   ├── semantic/       # 语义分析(图框/标题栏/设备/管道)
│   ├── spatial/        # 空间关系(邻近/包含/标注)
│   ├── normalizer/     # 统一数据 Schema (Pydantic)
│   ├── database/       # SQLite + SQLAlchemy ORM
│   ├── chunker/        # 文档分块(RAG)
│   ├── index/          # 搜索系统 + 向量索引
│   ├── rag/            # 混合检索 + 重排序
│   ├── utils/          # 日志/几何/单位工具
│   └── cli/            # 命令行工具
├── tests/              # 单元测试
├── config/             # 配置文件
├── scripts/            # 脚本
├── docs/               # 文档
├── KnowledgeBase/      # 知识库数据(git忽略)
├── requirements.txt
├── .env.example
├── .gitignore
└── run.bat
```

## DWG 文件支持

支持 DXF 和 DWG 两种格式。DWG 通过 ODA File Converter（免费，非商业用途）转换为 DXF 后解析：

1. 下载安装：https://www.opendesign.com/guestfiles/oda_file_converter
2. 系统自动检测安装路径（`D:\ODA\ODAFileConverter\ODAFileConverter.exe` 或标准安装目录）
3. 无需手动配置，`cadkb status` 可查看检测状态

DWG 解析流程：`DWG → ODA 转换 → DXF → ezdxf 解析 → 统一 Schema`。
版本信息从原始 DWG 文件头读取（不会因转换丢失），数据完整度与 DXF 解析一致。

## 语义分析 (Phase 3)

导入后自动运行语义分析，识别以下信息（全部为规则推断，带置信度，绝不编造）：

| 功能 | 说明 | CLI |
|------|------|-----|
| 图框识别 | 识别图纸外框矩形（4 条 LINE 或闭合 LWPOLYLINE） | `inspect --semantic` |
| 标题栏提取 | 提取图框右下角标题栏键值（图号/图纸名称/比例/设计等） | `inspect --semantic` |
| 设备识别 | 从块属性(EQUIP_NO/EQUIP_NAME)识别设备位号和名称 | `inspect --semantic` |
| 管道识别 | 从文字识别管径(DN100/φ4500)/材质/管线号 | `inspect --semantic` |

所有结果存储于独立表（`drawing_frames`/`title_blocks`/`equipment`/`pipes`），
每条记录含 `confidence` 和 `source="rule_based"` 标注。

## 空间关系 (Phase 4)

导入后自动计算实体间空间关系（确定性计算，`source="computed"`）：

| 关系类型 | 含义 | 示例 |
|---------|------|------|
| contains | 实体 A 完全包含实体 B | 图框包含设备块 |
| intersects | 两个实体包围盒相交 | 线条交叉 |
| near | 实体距离在阈值内 | 相邻设备 |
| annotates | 文字标注临近实体 | 设备标签标注设备 |
| belongs_to | 属性属于块引用 | ATTRIB 属于 INSERT |

查询方式：`inspect --spatial`，支持按关系类型过滤。

## 搜索系统 (Phase 5)

统一搜索服务 `src/index/search_service.py`，三种搜索模式：

| 搜索类型 | 引擎 | 命令 |
|---------|------|------|
| 全文搜索 | SQLite FTS5（文字/属性/图纸名） | `cadkb search "酸化窑"` |
| 结构化搜索 | SQL（设备/标题栏字段/尺寸/实体类型） | `cadkb search MILL --type equipment` |
| 空间搜索 | SQL（区域内实体） | `cadkb search-region --min-x 0 --min-y 0 --max-x 1500 --max-y 1500` |

CLI 过滤选项：`--type`（结果类型）、`--layer`（图层）、`--entity-type`（实体类型）。

**每条结果都带来源追溯**：drawing_id / file_name / handle / 图层 / 坐标。

## RAG 混合检索 (Phase 6)

三层检索 + 重排序：

```
查询 → [FTS5 关键词] + [向量语义检索] + [结构化检索]
                     ↓
            结果合并 + 去重（加权评分）
                     ↓
               Rerank 重排序
                     ↓
             带来源追溯的结果
```

| 组件 | 实现 |
|------|------|
| 分块 | `src/chunker/` — 文字/属性/标题栏/设备/管道 → DocumentChunk（带来源） |
| 向量库 | Chroma（`KnowledgeBase/embeddings/`），不可用时自动降级 n-gram 内存索引 |
| Embedding | BAAI/bge-small-zh-v1.5（本地模型，中文语义），首次使用自动下载 |
| 混合检索 | `src/rag/hybrid_search.py` — FTS+向量+结构化 加权合并 |
| 重排序 | `src/rag/reranker.py` — 词法重叠 + 来源先验 + 多样性 |

CLI：
```bash
cadkb rag "回转窑直径"          # 混合检索 + 重排序
cadkb rebuild-index --embeddings  # 重建向量索引
cadkb status                      # 显示向量索引状态
```

**不编造原则**：检索结果只返回数据库中的真实内容，每条带来源追溯
（drawing_id/file_name/handle/图层），得分仅为相关度排序，不生成新内容。

## AI 问答 (Phase 7)

RAG 检索 → 上下文构建 → LLM 生成 → **来源追溯**：

```
用户问题 → [混合检索 + 重排序]
                ↓
      [上下文构建（每条带来源）]
                ↓
      [LLM 生成回答] 或 [证据模式]
                ↓
      回答 + 来源追溯列表
```

| 组件 | 实现 |
|------|------|
| LLM 客户端 | `src/llm/client.py` — OpenAI 兼容 API（`config/default.yaml` 配 `llm.base_url/api_key/model`） |
| 上下文构建 | `src/rag/context_builder.py` — 每条上下文带 file/drawing_id/handle/图层 |
| QA 编排 | `src/qa/qa_service.py` — 混合检索 → 上下文 → LLM → 追溯 |
| REST API | `src/api/app.py` — FastAPI（`/api/query`、`/api/rag`、`/api/search`、`/api/status`） |

**两种模式**：
- **LLM 模式**：配置了 `llm.api_key` 时，LLM 基于检索上下文生成回答，引用来源
- **证据模式**：未配置 API Key 或 LLM 失败时，仅展示检索证据（带来源），**不生成回答**，绝不编造

配置示例（`config/default.yaml`）：
```yaml
llm:
  base_url: "https://api.openai.com/v1"    # 或阿里云百炼等兼容端点
  api_key: ""                              # 填入你的 API Key
  model: "gpt-4o-mini"
```

CLI：
```bash
cadkb query "酸化窑直径是多少"     # AI 问答（带来源追溯）
cadkb serve                        # 启动 REST API (http://127.0.0.1:8000)
```

REST API 端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 系统状态（含向量索引/LLM 状态） |
| GET | `/api/drawings` | 图纸列表 |
| GET | `/api/search?q=...` | 综合搜索 |
| GET | `/api/rag?q=...` | RAG 混合检索 |
| POST | `/api/query` | AI 问答（带来源追溯） |

## 开发路线图

| 阶段 | 功能 | 状态 |
|------|------|------|
| Phase 1 | DXF 解析 + SQLite + CLI | **已完成** |
| Phase 2 | DWG 解析(ODA) | **已完成** |
| Phase 3 | 语义分析(图框/标题栏/设备/管道) | **已完成** |
| Phase 4 | 空间关系 | **已完成** |
| Phase 5 | 搜索系统(全文+结构化+空间) | **已完成** |
| Phase 6 | RAG(向量检索+混合检索+重排序) | **已完成** |
| Phase 7 | AI 问答 + 来源追溯 + REST API | **已完成** |
| Phase 8 | CAD 版本兼容 | **已完成** |
| Phase 9 | 图纸差异比较 | **已完成** |
| Phase 10 | GUI (Streamlit) | **已完成** |

---

**全部 10 个阶段已完成。** 项目里程碑：

- 解析：DXF (ezdxf) + DWG (ODA/AutoCAD COM) + 多版本兼容 (R12-R2018)
- 语义：图框/标题栏/设备/管道识别 + 空间关系图
- 检索：全文 FTS5 + 结构化 + 空间 + RAG 混合检索 + 重排序
- 智能：AI 问答（LLM/证据双模式）+ 来源追溯 + 图纸比较
- 交互：CLI + REST API + Streamlit GUI
- 原则：准确性 > 完整性 > 性能；原始数据 > AI 推测；可追溯 > 看起来智能

## CAD 版本兼容 (Phase 8)

支持 R12 ~ R2018 各版本 DWG/DXF，通过版本兼容性矩阵测试验证：

| DWG 版本 | 标识 | 版本识别 | DXF 解析 | DWG 解析(ODA) | 导入+语义 |
|---------|------|---------|---------|--------------|----------|
| R12 | AC1009 | ✅ | ✅ | ✅ | ✅ |
| R2000 | AC1015 | ✅ | ✅ | ✅ | ✅ |
| R2004 | AC1018 | ✅ | ✅ | ✅ | ✅ |
| R2007 | AC1021 | ✅ | ✅ | ✅ | ✅ |
| R2010 | AC1024 | ✅ | ✅ | ✅ | ✅ |
| R2013 | AC1027 | ✅ | ✅ | ✅ | ✅ |
| R2018 | AC1032 | ✅ | ✅ | ✅ | ✅ |

> R13 (AC1012)/R14 (AC1014) 因 ezdxf 不支持生成对应 DXF 而跳过测试，但版本识别和 ODA 转换均支持。

**转换备选路径**：ODA 不可用时自动尝试 **AutoCAD COM**（`src/parsers/autocad_com.py`，
需要安装 AutoCAD），两者均不可用时返回明确错误——绝不编造数据。

## 图纸差异比较 (Phase 9)

比较两张 CAD 图纸，输出结构化差异报告：

```
cadkb compare A.dwg B.dwg
```

| 差异类别 | 检测内容 |
|---------|---------|
| 实体差异 | 按几何签名匹配，标记新增/删除/修改（类型+图层+坐标） |
| 文字差异 | 按位置匹配，检测内容修改/新增/删除 |
| 尺寸差异 | 尺寸值/文本变化 |
| 语义差异 | 设备新增/删除、标题栏字段变更 |

每条差异记录携带 handle/图层 来源，全部确定性计算（`src/compare/differ.py`）。
REST API：`POST /api/compare`。

## 图形界面 GUI (Phase 10)

Streamlit 图形界面，五个页面：

```
cadkb gui        # 启动 (http://localhost:8501)
```

| 页面 | 功能 |
|------|------|
| **图纸导入** | 上传 DXF/DWG 单文件导入，或输入目录批量导入（含子目录/强制覆盖选项） |
| **图纸浏览** | 图纸列表 + 缩略图预览 + 详情（实体/文字/尺寸/语义分析/空间关系） |
| **搜索** | 综合搜索（关键词+类型过滤）+ 空间区域搜索（bbox） |
| **AI 问答** | RAG 检索 + 来源追溯（LLM 模式 / 证据模式） |
| **图纸比较** | 选择两张图纸，展示实体/文字/尺寸/语义差异 |

缩略图通过 ezdxf[draw] 渲染（`src/gui/thumbnail.py`），DWG 自动经 ODA/AutoCAD 转换后渲染。

## 图纸导入

三种导入方式：

```bash
# 1. CLI：单文件
python -m src.cli.main import "图纸.dwg"

# 2. CLI：批量目录
python -m src.cli.main import "图纸目录" --recursive

# 3. GUI：启动后进入「图纸导入」页面
python -m src.cli.main gui
```

导入后自动执行：解析 → 语义分析（图框/标题栏/设备/管道）→ 空间关系 → 向量索引。
重复文件自动跳过（`--force` 强制覆盖）。

## 技术栈

| 项目 | 技术 | 许可证 |
|------|------|--------|
| DXF 解析 | ezdxf 1.4.4 | MIT |
| DWG 转换 | ODA File Converter 27.1 | 免费(非商业) |
| 数据模型 | Pydantic 2.x | MIT |
| 数据库 | SQLite + SQLAlchemy | Public Domain / MIT |
| CLI | Click | BSD |
| 几何运算 | Shapely | BSD |
| 日志 | colorlog | MIT |
| 向量库 | Chroma 1.5 | Apache 2.0 |
| Embedding | bge-small-zh-v1.5 | MIT |
| 语义模型 | sentence-transformers + torch(CPU) | Apache 2.0 / BSD |
| REST API | FastAPI + uvicorn | MIT |
| GUI | Streamlit + matplotlib + pandas | Apache 2.0 / custom / BSD |
| LLM 接口 | OpenAI 兼容 API（可配置） | 视提供商 |

## 新电脑部署（快速搭建）

### 方式 A：裸机安装（推荐，最灵活）

```bash
# 1. 克隆仓库
git clone https://github.com/<your-name>/cad-knowledge-base.git
cd cad-knowledge-base

# 2. 一键安装（自动创建虚拟环境 + 安装依赖 + 生成 .env）
# Windows:
setup.bat
# Linux / macOS:
# bash setup.sh

# 3. 按需编辑 .env（数据库路径 / ODA 路径 / LLM 配置，见 .env.example 注释）

# 4. 启动
python -m src.cli.main status        # CLI：查看状态
python -m src.cli.main gui           # GUI：Streamlit 界面 (http://localhost:8501)
python -m src.cli.main serve         # API：REST 服务 (http://127.0.0.1:8000)
```

> 首次导入会触发 Embedding 模型下载（约 100MB，一次性）。

### 方式 B：Docker 部署（推荐服务器/无环境场景）

```bash
docker compose up -d --build
# API: http://localhost:8000   GUI: http://localhost:8501
# 数据持久化在 ./data 卷（Docker 方式无需手动装 Python 环境）
```

### 环境变量（.env）

复制 `.env.example` 为 `.env` 后按需修改，所有敏感配置与路径均通过环境变量注入，
**不硬编码在代码中**。核心变量：

| 变量 | 说明 |
|------|------|
| `CADKB_DB_PATH` | SQLite 数据库文件路径 |
| `CADKB_KB_ROOT` | 知识库数据根目录（原始文件 / 解析结果 / 向量库） |
| `CADKB_ODA_PATH` | ODA File Converter 路径（DWG 解析，留空自动检测） |
| `CADKB_LLM_BASE_URL` / `CADKB_LLM_API_KEY` / `CADKB_LLM_MODEL` | LLM 配置（不配置则进入证据模式） |

### 目录说明

```
├── src/             # 全部源代码（Python 包）
├── scripts/         # 运维/数据脚本（导入、索引、备份等）
├── tests/           # 单元测试
├── config/          # 默认配置 (default.yaml)
├── docs/            # 文档
├── KnowledgeBase/   # 运行时数据（git 忽略，不入库）
├── requirements.txt # 顶层依赖（含版本约束）
├── setup.bat/.sh    # 一键安装脚本
├── Dockerfile       # 容器镜像定义
└── docker-compose.yml
```

## 安全说明

- 所有数据本地存储，不上传任何文件到第三方服务器
- API Key 通过 .env 文件管理，不硬编码
- .gitignore 已配置，知识库数据和数据库不会被提交
- 配置文件和密钥分离
