# CAD 图纸解析与私人知识库系统 — 技术可行性分析报告

> 文档版本：v1.0  
> 日期：2026-08-17  
> 阶段：Step 1 — 技术可行性分析  
> 原则：准确性 > 完整性 > 性能 > UI美观；原始数据 > AI推测；可追溯 > 看起来智能

---

## 目录

1. [当前环境检测结果](#1-当前环境检测结果)
2. [DWG 文件格式与版本体系](#2-dwg-文件格式与版本体系)
3. [DWG 解析技术方案对比](#3-dwg-解析技术方案对比)
4. [DXF 解析技术方案对比](#4-dxf-解析技术方案对比)
5. [数据库选型分析](#5-数据库选型分析)
6. [向量数据库选型分析](#6-向量数据库选型分析)
7. [LLM 与 RAG 技术选型](#7-llm-与-rag-技术选型)
8. [技术选型汇总表](#8-技术选型汇总表)
9. [系统总体架构设计](#9-系统总体架构设计)
10. [项目目录结构](#10-项目目录结构)
11. [统一 CAD 数据 Schema](#11-统一-cad-数据-schema)
12. [数据库 Schema 设计](#12-数据库-schema-设计)
13. [CAD 解析流程设计](#13-cad-解析流程设计)
14. [RAG 混合检索流程设计](#14-rag-混合检索流程设计)
15. [API 接口设计](#15-api-接口设计)
16. [CLI 命令行设计](#16-cli-命令行设计)
17. [测试方案](#17-测试方案)
18. [开发阶段划分](#18-开发阶段划分)
19. [功能分类与决策清单](#19-功能分类与决策清单)
20. [风险与限制](#20-风险与限制)
21. [第一阶段实施计划](#21-第一阶段实施计划)

---

## 1. 当前环境检测结果

### 1.1 硬件与操作系统

| 项目 | 值 |
|------|-----|
| 操作系统 | Windows 11 Home China |
| 平台 | win32 |
| Shell | bash (Git Bash) |

### 1.2 开发工具

| 工具 | 版本 | 状态 |
|------|------|------|
| Python | 3.13.14 | 已安装 |
| pip | 26.1.2 | 已安装 |
| Git | 2.55.0.windows.3 | 已安装 |
| Node.js | v22.22.2 | 已安装 |
| conda | — | 未安装 |

### 1.3 已安装的 Python 包（与项目相关）

| 包 | 版本 | 用途 |
|----|------|------|
| numpy | 2.3.5 | 数值计算 |
| opencv-contrib-python | 4.10.0.84 | 图像处理 |
| pydantic | 2.13.4 | 数据校验 |
| pymupdf (PyMuPDF) | 1.28.2 | PDF 解析 |
| shapely | 2.1.2 | 几何运算 |
| pandas | 3.0.5 | 数据分析 |
| pillow | 12.3.0 | 图像处理 |
| openpyxl | 3.1.5 | Excel 读写 |
| PyYAML | 6.0.2 | YAML 配置 |
| **ezdxf** | **1.4.4** | **DXF 解析（本次安装）** |

### 1.4 CAD 相关软件检测

| 软件 | 状态 | 说明 |
|------|------|------|
| AutoCAD (acad.exe) | **未安装** | 仅有 Autodesk Desktop App 残留，无 AutoCAD 本体 |
| ODA File Converter | **未安装** | 需要单独下载安装 |
| LibreDWG | **未安装** | 需要编译或下载预编译版本 |
| DWG TrueView | **未安装** | Autodesk 免费查看器，可选安装 |

### 1.5 环境检测结论

- Python 3.13 + ezdxf 1.4.4 环境就绪，可立即开始 DXF 解析开发
- **DWG 直接解析能力为零**：无 AutoCAD、无 ODA File Converter、无 LibreDWG
- 第一阶段可立即开展 DXF 解析相关工作
- DWG 解析需要安装 ODA File Converter（推荐）或 LibreDWG

---

## 2. DWG 文件格式与版本体系

### 2.1 DWG 版本与 AutoCAD 版本对应关系

| DWG 版本标识 | AutoCAD 版本 | 年份 | 版本号 |
|-------------|-------------|------|-------|
| AC1.50 | AutoCAD R2.05 | 1985 | — |
| AC2.10 | AutoCAD R2.10 | 1986 | — |
| AC1001 | AutoCAD R2.5 | 1987 | — |
| AC1002 | AutoCAD R2.6 | 1988 | — |
| AC1003 | AutoCAD R9 | 1989 | — |
| AC1004 | AutoCAD R10 | 1989 | — |
| AC1006 | AutoCAD R11/R12 | 1990/1992 | — |
| **AC1009** | **AutoCAD R12/R13** | 1992/1994 | R12 |
| **AC1012** | **AutoCAD R13** | 1994 | R13 |
| **AC1014** | **AutoCAD R14** | 1997 | R14 |
| **AC1015** | **AutoCAD 2000** | 1999 | R2000 |
| AC1018 | AutoCAD 2004 | 2003 | R2004 |
| AC1021 | AutoCAD 2007 | 2006 | R2007 |
| AC1024 | AutoCAD 2010 | 2009 | R2010 |
| AC1027 | AutoCAD 2013 | 2012 | R2013 |
| **AC1032** | **AutoCAD 2018** | 2017 | R2018 |
| AC1042 | AutoCAD 2025 | 2024 | R2025 |

> **关键点**：DWG 文件的前 6 个字节即为版本标识符（如 `AC1032`），可用于快速识别文件版本。

### 2.2 DWG 文件结构概述

DWG 文件是 Autodesk 私有二进制格式，主要结构：

```
DWG File Structure
├── File Header (版本标识 + 加密信息)
├── Section Locator (各 Section 偏移量)
├── Header Variables Section
├── Classes Section
├── Object Map (对象索引)
├── Object Data (所有实体数据)
│   ├── Entities (LINE, CIRCLE, TEXT, ...)
│   ├── Symbol Tables (Layers, Linetypes, Styles, ...)
│   └── Block Definitions
├── AcDb:Template (可选)
├── AcDb:AuxHeader (可选)
└── Preview Image (缩略图 BMP/PNG)
```

### 2.3 DXF 文件结构概述

DXF (Drawing Exchange Format) 是 Autodesk 开放的文本/二进制格式：

```
DXF File Structure
├── HEADER Section (全局变量)
├── CLASSES Section (类定义)
├── TABLES Section (符号表)
│   ├── LAYER
│   ├── LTYPE
│   ├── STYLE
│   ├── DIMSTYLE
│   ├── VIEW
│   ├── UCS
│   ├── APPID
│   └── VPORT
├── BLOCKS Section (块定义)
├── ENTITIES Section (所有实体)
├── OBJECTS Section (非图形对象)
├── THUMBNAILIMAGE Section (缩略图)
└── EOF
```

### 2.4 版本兼容性矩阵

| DWG 版本 | ezdxf 读取 DXF | ODA 转换 | LibreDWG 读取 | 备注 |
|----------|---------------|---------|--------------|------|
| R12 (AC1009) | 支持 | 支持 | 支持 | 最广泛兼容的版本 |
| R13/R14 (AC1012/AC1014) | 支持 | 支持 | 支持 | — |
| R2000 (AC1015) | 支持 | 支持 | 支持 | — |
| R2004 (AC1018) | 支持 | 支持 | 支持 | — |
| R2007 (AC1021) | 支持 | 支持 | 支持 | — |
| R2010 (AC1024) | 支持 | 支持 | 部分支持 | 某些高级实体可能被跳过 |
| R2013 (AC1027) | 支持 | 支持 | 部分支持 | — |
| R2018 (AC1032) | 支持 | 支持 | 部分支持 | 当前最常用版本 |
| R2025 (AC1042) | 需验证 | 支持 | 未知 | 最新版本 |

---

## 3. DWG 解析技术方案对比

### 3.1 方案 A：ODA File Converter（推荐）

| 项目 | 内容 |
|------|------|
| **名称** | ODA File Converter |
| **提供商** | Open Design Alliance (ODA) |
| **类型** | 独立可执行程序，命令行可调用 |
| **能力** | DWG→DXF、DXF→DWG、DWG版本转换、批量处理 |
| **支持版本** | ACAD9 ~ ACAD2018（R2025 需验证最新版） |
| **平台** | Windows / macOS / Linux |
| **许可证** | 免费下载使用，**非商业用途免费**；商业用途需 ODA 会员资格 |
| **费用** | 非商业：免费；商业：ODA 会员费约 $3,000-$37,500/年（取决于会员等级） |
| **离线运行** | 是，完全离线 |
| **数据上传** | 否，全部本地处理 |
| **安装方式** | 下载 .exe 安装程序，默认路径 `C:\Program Files\ODA\ODAFileConverter\` |
| **命令行调用** | `ODAFileConverter.exe <输入目录> <输出目录> <目标版本> <输出格式> <递归> <审计>` |
| **优点** | 免费可用、批量转换、支持版本转换、支持审计修复、命令行可自动化 |
| **缺点** | 非商业限制、按文件夹批量处理（非单文件）、需要安装 |
| **推荐度** | **强烈推荐（作为 DWG→DXF 转换器）** |

> **许可证说明**：根据调研，ODA File Converter 对非商业个人使用免费。如果老板的使用场景属于个人/非商业用途，可以直接免费使用。如果涉及商业用途，需要购买 ODA 会员。**需要老板确认使用场景。**

### 3.2 方案 B：LibreDWG

| 项目 | 内容 |
|------|------|
| **名称** | LibreDWG |
| **提供商** | GNU 项目 |
| **类型** | C 语言库 + 命令行工具 |
| **能力** | 直接读取 DWG、DWG→DXF/JSON/SVG 转换 |
| **支持版本** | 可靠读取 R13-R2018；写入 R13-R2000 |
| **平台** | Windows / Linux / macOS |
| **许可证** | **GNU GPL v3**（传染性许可证） |
| **费用** | 免费 |
| **离线运行** | 是 |
| **安装方式** | 需要编译或下载预编译版本 |
| **Python 绑定** | 有 Python 绑定，但成熟度一般 |
| **优点** | 完全免费、直接读取 DWG、无需 AutoCAD |
| **缺点** | GPL v3 传染性（使用它的软件必须也开源为 GPL）、部分高级实体读取失败、Windows 编译复杂、Python 绑定不成熟 |
| **推荐度** | **不推荐作为主方案**（GPL 限制太严格），可作为备用方案 |

> **GPL v3 风险说明**：如果使用 LibreDWG 解析 DWG，整个系统在法律上可能需要以 GPL v3 开源。老板的系统是私人知识库，虽然不对外发布，但如果未来有任何商业分发场景，会有许可证风险。

### 3.3 方案 C：AutoCAD COM API（pyautocad / win32com）

| 项目 | 内容 |
|------|------|
| **名称** | pyautocad / win32com + AutoCAD |
| **类型** | COM 自动化接口 |
| **能力** | 直接读取 DWG 所有实体、属性、图层、块等 |
| **前提条件** | **必须安装 AutoCAD** |
| **许可证** | 依赖 AutoCAD 许可证 |
| **费用** | AutoCAD 正版约 ¥8,000-¥15,000/年/席位 |
| **优点** | 最完整、最准确的 DWG 解析能力 |
| **缺点** | 必须安装 AutoCAD、价格昂贵、仅 Windows、运行时需要 AutoCAD 进程 |
| **推荐度** | **当前环境不适用**（老板电脑未安装 AutoCAD） |

### 3.4 方案 D：ODA Drawings SDK / Teigha

| 项目 | 内容 |
|------|------|
| **名称** | ODA Drawings SDK (原 Teigha) |
| **类型** | C++ SDK |
| **能力** | 直接读取/修改 DWG，最完整的 DWG 解析能力 |
| **许可证** | ODA 会员专属 |
| **费用** | $3,000-$37,500/年 |
| **优点** | 最强大的 DWG 处理能力、可嵌入应用程序 |
| **缺点** | 需要付费会员、C++ 开发门槛高 |
| **推荐度** | **当前不适用**（费用高、开发门槛高） |

### 3.5 方案 E：DWG 文件头直接解析

| 项目 | 内容 |
|------|------|
| **能力** | 读取文件前 6 字节识别 DWG 版本 |
| **优点** | 无需任何依赖、纯 Python |
| **缺点** | 只能识别版本，不能解析实体内容 |
| **推荐度** | **作为辅助功能**，用于文件导入时的版本识别 |

### 3.6 DWG 解析方案决策

```
推荐架构：

DWG 文件
  │
  ├─ Step 1: 读取文件头 → 识别 DWG 版本（纯 Python，零依赖）
  │
  ├─ Step 2: 调用 ODA File Converter → 转换为 DXF
  │          （如果 ODA 不可用 → 提示用户安装）
  │
  ├─ Step 3: 使用 ezdxf 解析 DXF → 提取所有实体
  │
  └─ Step 4: 生成统一结构化数据
```

**备选路径**：
- 如果用户安装了 AutoCAD → 可选启用 COM API 路径（更准确）
- 如果 ODA 不可用且无 AutoCAD → 只能处理 DXF 文件，DWG 标记为"无法解析"

---

## 4. DXF 解析技术方案对比

### 4.1 ezdxf（强烈推荐）

| 项目 | 内容 |
|------|------|
| **名称** | ezdxf |
| **版本** | 1.4.4（2026-05 发布） |
| **许可证** | MIT License（最宽松的开源许可证之一） |
| **费用** | 免费 |
| **Python 版本** | 3.10+（当前环境 Python 3.13.14 兼容） |
| **支持 DXF 版本** | R12, R2000, R2004, R2007, R2010, R2013, R2018 |
| **平台** | Windows / Linux / macOS |
| **离线运行** | 是 |
| **当前状态** | **已安装在环境中** |

**ezdxf 能力清单**：

| 能力 | 支持情况 | 说明 |
|------|---------|------|
| 读取 DXF | 支持 | `ezdxf.readfile()` |
| 创建 DXF | 支持 | `ezdxf.new()` |
| LINE | 支持 | 起点、终点、长度 |
| CIRCLE | 支持 | 圆心、半径 |
| ARC | 支持 | 圆心、半径、起止角度 |
| POLYLINE | 支持 | 2D/3D 多段线 |
| LWPOLYLINE | 支持 | 轻量多段线 |
| SPLINE | 支持 | 样条曲线（控制点/拟合点） |
| ELLIPSE | 支持 | 椭圆 |
| TEXT | 支持 | 单行文字 |
| MTEXT | 支持 | 多行文字 |
| DIMENSION | 支持 | 尺寸标注（线性、对齐、角度、半径、直径） |
| LEADER | 支持 | 引线标注 |
| HATCH | 支持 | 填充 |
| BLOCK / INSERT | 支持 | 块定义和块引用 |
| ATTRIB / ATTDEF | 支持 | 块属性 |
| LAYER | 支持 | 图层表 |
| LTYPE | 支持 | 线型表 |
| STYLE | 支持 | 文字样式 |
| VIEWPORT | 支持 | 视口（模型空间/图纸空间） |
| LAYOUT | 支持 | 布局 |
| XREF | 部分 | 外部参照信息可读取，但内容需单独解析 |
| 缩略图渲染 | 支持 | `ezdxf[draw]` 附加组件，可渲染为 PNG/SVG/PDF |
| 大文件处理 | 支持 | `iterdxf` 流式处理超大 DXF |

**ezdxf 限制**：
- 不支持直接读取 DWG 文件
- 某些自定义实体（PROXY ENTITY）可能无法完整解析
- 渲染功能需要额外依赖（matplotlib / PySide6）

### 4.2 其他 DXF 解析方案

| 方案 | 许可证 | 优点 | 缺点 | 推荐度 |
|------|--------|------|------|--------|
| dxfgrabber | MIT | 简单 | 功能少、已不维护 | 不推荐 |
| python-dxf | LGPL | 轻量 | 功能有限 | 不推荐 |
| sdxf | Python | 极简 | 功能极少、不维护 | 不推荐 |

### 4.3 DXF 解析方案决策

**ezdxf 是唯一合理的选择**。MIT 许可证、功能完整、活跃维护、Python 3.13 兼容、已安装。

---

## 5. 数据库选型分析

### 5.1 SQLite（推荐）

| 项目 | 内容 |
|------|------|
| **类型** | 嵌入式关系型数据库 |
| **许可证** | Public Domain（公有领域） |
| **费用** | 免费 |
| **Python 集成** | 内置 `sqlite3` 模块，零安装 |
| **ORM** | SQLAlchemy（已验证兼容） |
| **存储方式** | 单文件 `.db` |
| **最大数据库大小** | 281 TB（理论值） |
| **并发** | 读并发支持，写串行（对单人使用足够） |
| **离线运行** | 是 |
| **适用场景** | 单机、个人知识库、中小规模数据 |
| **优点** | 零配置、零安装、零运维、单文件备份、性能足够 |
| **缺点** | 不支持多用户并发写入、大规模数据时性能不如 PostgreSQL |

### 5.2 PostgreSQL（备选）

| 项目 | 内容 |
|------|------|
| **类型** | 客户端/服务器关系型数据库 |
| **许可证** | PostgreSQL License（BSD-like） |
| **费用** | 免费 |
| **优点** | 支持多用户、大规模数据、PostGIS 空间扩展 |
| **缺点** | 需要安装和配置服务器、运维复杂、对个人知识库过重 |
| **推荐度** | 第一阶段不推荐，数据量超过 100 万实体时再考虑迁移 |

### 5.3 数据库方案决策

**第一阶段使用 SQLite**。理由：
1. 零安装、零配置，Python 内置支持
2. 单文件 `.db` 便于备份和迁移
3. 个人知识库场景下性能完全足够
4. 使用 SQLAlchemy ORM，未来可无缝迁移到 PostgreSQL

---

## 6. 向量数据库选型分析

### 6.1 方案对比

| 特性 | Chroma | Qdrant | FAISS |
|------|--------|--------|-------|
| **类型** | 嵌入式数据库 | 服务型数据库 | 算法库 |
| **许可证** | Apache 2.0 | Apache 2.0 | MIT |
| **费用** | 免费 | 免费 | 免费 |
| **Python 集成** | 原生 Python | Python SDK | Python 绑定 |
| **持久化** | 内置 | 内置 | 需手动保存/加载 |
| **元数据过滤** | 支持 | 支持（最强大） | 不支持 |
| **混合检索** | 有限 | 支持稀疏+稠密 | 不支持 |
| **部署方式** | pip install 即用 | Docker / 独立二进制 | pip install 即用 |
| **适合规模** | < 100万向量 | < 1亿向量 | 取决于内存 |
| **生产就绪** | 中等 | 高 | 低（非数据库） |
| **易用性** | 最高 | 高 | 中等 |
| **运维成本** | 零 | 低（需运行服务） | 零 |

### 6.2 向量数据库方案决策

**推荐分阶段选择**：

| 阶段 | 向量库 | 理由 |
|------|--------|------|
| Phase 5-6（搜索/RAG 原型） | **Chroma** | 零配置、Python 原生、适合原型验证 |
| Phase 7+（生产级 AI 接口） | **Qdrant**（可选升级） | 高性能、复杂过滤、生产就绪 |

> **第一阶段不需要向量数据库**。第一阶段只做 DWG/DXF 解析 + SQLite 存储 + 解析报告。向量数据库在 Phase 5 搜索阶段才需要。

---

## 7. LLM 与 RAG 技术选型

### 7.1 Embedding 模型

| 方案 | 类型 | 许可证 | 离线 | 推荐 |
|------|------|--------|------|------|
| BAAI/bge-m3 | 本地模型 | MIT | 是 | 推荐（多语言、性能优秀） |
| BAAI/bge-large-zh-v1.5 | 本地模型 | MIT | 是 | 推荐（中文优化） |
| OpenAI text-embedding-3 | 云端 API | 按量付费 | 否 | 备选 |
| sentence-transformers | 本地模型 | Apache 2.0 | 是 | 备选 |

### 7.2 LLM 接口

| 方案 | 类型 | 离线 | 推荐 |
|------|------|------|------|
| OpenAI API 兼容接口 | 云端 | 否 | 支持任意兼容 OpenAI 的 API |
| Ollama 本地模型 | 本地 | 是 | 推荐（离线、隐私） |
| vLLM | 本地 | 是 | 高级用户可选 |

### 7.3 RAG 框架

| 方案 | 许可证 | 推荐 |
|------|--------|------|
| LangChain | MIT | 备选（较重） |
| LlamaIndex | MIT | 备选 |
| **自研轻量 RAG** | — | **推荐**（更可控、更简单、避免过度依赖） |

### 7.4 LLM/RAG 方案决策

- **第一阶段不涉及 LLM/RAG**
- 后期推荐：本地 Embedding (bge-m3) + Qdrant/Chroma + 自研轻量 RAG + OpenAI 兼容 API 接口
- **所有 LLM 调用都是可选的**，系统核心（解析、存储、检索）不依赖 LLM

---

## 8. 技术选型汇总表

| 项目 | 推荐方案 | 许可证 | 费用 | 离线 | 是否需安装 | 是否需确认 |
|------|---------|--------|------|------|-----------|-----------|
| **DWG→DXF 转换** | ODA File Converter | 非商业免费 | 非商业免费 | 是 | 需安装 | **需确认使用场景** |
| **DXF 解析** | ezdxf 1.4.4 | MIT | 免费 | 是 | 已安装 | 否 |
| **DWG 版本识别** | 纯 Python（读文件头） | — | 免费 | 是 | 无需 | 否 |
| **数据校验** | Pydantic 2.x | MIT | 免费 | 是 | 已安装 | 否 |
| **几何运算** | Shapely | BSD | 免费 | 是 | 已安装 | 否 |
| **数值计算** | NumPy | BSD | 免费 | 是 | 已安装 | 否 |
| **PDF 解析(后期)** | PyMuPDF | AGPL-3.0 | 免费 | 是 | 已安装 | **需确认 AGPL** |
| **图像处理(后期)** | OpenCV | Apache 2.0 | 免费 | 是 | 已安装 | 否 |
| **关系数据库** | SQLite | Public Domain | 免费 | 是 | 内置 | 否 |
| **ORM** | SQLAlchemy | MIT | 免费 | 是 | 需安装 | 否 |
| **向量库(后期)** | Chroma → Qdrant | Apache 2.0 | 免费 | 是 | 需安装 | 否 |
| **Web 框架** | FastAPI | MIT | 免费 | 是 | 需安装 | 否 |
| **CLI 框架** | Click | BSD | 免费 | 是 | 需安装 | 否 |
| **Embedding(后期)** | bge-m3 (本地) | MIT | 免费 | 是 | 需下载模型 | 否 |
| **LLM 接口(后期)** | OpenAI 兼容 API | 取决于提供商 | 按量/免费 | 可离线 | 无需 | **需确认模型选择** |
| **GUI** | Streamlit (Phase 10) | Apache 2.0 | 免费 | 是 | 需安装 | 否 |

---

## 9. 系统总体架构设计

### 9.1 架构总览

```
┌─────────────────────────────────────────────────────────────────┐
│                     CAD Knowledge Base System                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐     │
│  │  CLI     │   │  REST API│   │  GUI     │   │  MCP     │     │
│  │  (Click) │   │ (FastAPI)│   │(Streamlit)│  │ (后期)   │     │
│  └────┬─────┘   └────┬─────┘   └────┬─────┘   └────┬─────┘     │
│       │              │              │              │            │
│       └──────────────┴──────┬──────┴──────────────┘            │
│                             │                                    │
│                    ┌────────▼────────┐                           │
│                    │  Core Service   │                           │
│                    │  (Orchestrator) │                           │
│                    └────────┬────────┘                           │
│                             │                                    │
│  ┌──────────────────────────┼──────────────────────────┐        │
│  │                          │                          │        │
│  ▼                          ▼                          ▼        │
│ ┌─────────┐         ┌─────────────┐         ┌─────────────┐    │
│ │  01     │         │  02         │         │  03         │    │
│ │  File   │────────▶│  CAD        │────────▶│  CAD        │    │
│ │  Manager│         │  Parser     │         │  Normalizer │    │
│ └────┬────┘         └─────────────┘         └──────┬──────┘    │
│      │                                             │            │
│      │              ┌─────────────┐                │            │
│      │              │ 04          │                │            │
│      │              │ Semantic    │◀───────────────┘            │
│      │              │ Analyzer    │                             │
│      │              └──────┬──────┘                             │
│      │                     │                                    │
│      │              ┌──────▼──────┐                             │
│      │              │ 05          │                             │
│      │              │ Spatial     │                             │
│      │              │ Relationship│                             │
│      │              └──────┬──────┘                             │
│      │                     │                                    │
│      │              ┌──────▼──────┐                             │
│      │              │ 06          │                             │
│      │              │ Document    │                             │
│      │              │ Chunker     │                             │
│      │              └──────┬──────┘                             │
│      │                     │                                    │
│      ▼                     ▼                                    │
│ ┌─────────────────────────────────┐                              │
│ │  07 Index                       │                              │
│ │  ├── SQLite (结构化数据)         │                              │
│ │  ├── SQLite FTS5 (全文搜索)     │                              │
│ │  └── Chroma/Qdrant (向量)       │                              │
│ └─────────────┬───────────────────┘                              │
│               │                                                   │
│       ┌───────▼───────┐                                          │
│       │ 08 RAG        │                                          │
│       │  ├── Query    │                                          │
│       │  ├── Hybrid   │                                          │
│       │  ├── Rerank   │                                          │
│       │  └── Context  │                                          │
│       └───────┬───────┘                                          │
│               │                                                   │
│       ┌───────▼───────┐                                          │
│       │ 09 LLM        │                                          │
│       │  (OpenAI API) │                                          │
│       └───────────────┘                                          │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐      │
│  │  10 日志系统 / 数据质量检查 / 缩略图生成 / 版本管理    │      │
│  └────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

### 9.2 数据流

```
CAD 文件 (DWG/DXF)
    │
    ▼
[01 File Manager] ── 文件哈希、版本识别、重复检测
    │
    ▼
[02 CAD Parser] ── DWG→DXF转换(ODA) / DXF直接读取(ezdxf)
    │
    ▼
[03 Normalizer] ── 转换为统一数据模型
    │
    ▼
[04 Semantic Analyzer] ── 图框/标题栏/设备/管道识别
    │
    ▼
[05 Spatial Relationship] ── 空间关系构建
    │
    ▼
[06 Document Chunker] ── 分块
    │
    ▼
[07 Index] ── SQLite + FTS5 + Vector DB
    │
    ▼
[08 RAG] ── 混合检索
    │
    ▼
[09 LLM] ── 回答 + 来源追溯
```

### 9.3 数据分层架构

```
┌─────────────────────────────────┐
│  RAW_DATA       (原始 CAD 数据)  │  ← 从文件直接解析，不可修改
├─────────────────────────────────┤
│  NORMALIZED     (标准化数据)     │  ← 统一 Schema 转换
├─────────────────────────────────┤
│  DERIVED_DATA   (推导数据)       │  ← 计算/推导得出（如周长、面积）
├─────────────────────────────────┤
│  AI_INFERENCE   (AI 推断数据)    │  ← AI 识别/推测，带 confidence
├─────────────────────────────────┤
│  USER_NOTES     (用户标注)       │  ← 用户手动添加的备注
└─────────────────────────────────┘

关键原则：这五层数据绝不能混在一起，每条数据必须标注来源层。
```

---

## 10. 项目目录结构

```
CAD-Knowledge-Base/
│
├── src/
│   ├── __init__.py
│   ├── core/                      # 核心编排
│   │   ├── __init__.py
│   │   ├── orchestrator.py        # 主流程编排
│   │   └── config.py              # 配置管理
│   │
│   ├── file_manager/              # 01 文件管理
│   │   ├── __init__.py
│   │   ├── importer.py            # 文件导入
│   │   ├── scanner.py             # 文件扫描
│   │   ├── hasher.py              # 文件哈希
│   │   ├── version_detector.py    # CAD 版本识别
│   │   └── duplicate_checker.py   # 重复文件检测
│   │
│   ├── parsers/                   # 02 CAD 解析
│   │   ├── __init__.py
│   │   ├── base_parser.py         # 解析器基类
│   │   ├── dxf_parser.py          # DXF 解析 (ezdxf)
│   │   ├── dwg_parser.py          # DWG 解析 (ODA→DXF→ezdxf)
│   │   ├── oda_converter.py       # ODA File Converter 封装
│   │   └── pdf_parser.py          # PDF 解析 (后期)
│   │
│   ├── normalizer/                # 03 数据标准化
│   │   ├── __init__.py
│   │   ├── schema.py              # 统一数据模型 (Pydantic)
│   │   ├── entity_normalizer.py   # 实体标准化
│   │   ├── text_normalizer.py     # 文字标准化
│   │   ├── dimension_normalizer.py# 尺寸标准化
│   │   └── block_normalizer.py    # 块标准化
│   │
│   ├── semantic/                  # 04 语义分析
│   │   ├── __init__.py
│   │   ├── title_block.py         # 标题栏识别
│   │   ├── frame_detector.py      # 图框识别
│   │   ├── equipment_extractor.py # 设备信息提取
│   │   └── pipe_extractor.py      # 管道信息提取
│   │
│   ├── spatial/                   # 05 空间关系
│   │   ├── __init__.py
│   │   ├── bounding_box.py        # 包围盒计算
│   │   ├── relationship.py        # 空间关系构建
│   │   └── proximity.py           # 邻近分析
│   │
│   ├── chunker/                   # 06 文档分块
│   │   ├── __init__.py
│   │   └── chunker.py             # 多级分块
│   │
│   ├── database/                  # 07 数据库
│   │   ├── __init__.py
│   │   ├── models.py              # SQLAlchemy 模型
│   │   ├── connection.py          # 数据库连接
│   │   ├── repositories.py        # 数据访问层
│   │   └── migrations.py          # 数据库迁移
│   │
│   ├── index/                     # 07 索引
│   │   ├── __init__.py
│   │   ├── fulltext.py            # 全文搜索 (SQLite FTS5)
│   │   ├── metadata_index.py      # 元数据索引
│   │   └── vector_index.py        # 向量索引 (后期)
│   │
│   ├── rag/                       # 08 RAG
│   │   ├── __init__.py
│   │   ├── query_analyzer.py      # 查询分析
│   │   ├── hybrid_search.py       # 混合检索
│   │   ├── reranker.py            # 重排序
│   │   └── context_builder.py     # 上下文构建
│   │
│   ├── llm/                       # 09 LLM
│   │   ├── __init__.py
│   │   ├── llm_client.py          # LLM 客户端
│   │   └── prompts.py             # 提示词模板
│   │
│   ├── api/                       # REST API
│   │   ├── __init__.py
│   │   ├── server.py              # FastAPI 服务
│   │   └── routes.py              # API 路由
│   │
│   ├── cli/                       # CLI
│   │   ├── __init__.py
│   │   └── main.py                # Click CLI
│   │
│   ├── thumbnail/                 # 缩略图
│   │   ├── __init__.py
│   │   └── generator.py           # 缩略图生成
│   │
│   ├── quality/                   # 数据质量
│   │   ├── __init__.py
│   │   ├── checker.py             # 质量检查
│   │   └── report.py              # 解析报告
│   │
│   ├── compare/                   # 图纸比较 (后期)
│   │   ├── __init__.py
│   │   └── differ.py              # 差异比较
│   │
│   └── utils/                     # 工具
│       ├── __init__.py
│       ├── logger.py              # 日志
│       ├── geometry.py            # 几何工具
│       └── units.py               # 单位转换
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # pytest 配置
│   ├── test_file_manager.py
│   ├── test_dxf_parser.py
│   ├── test_dwg_parser.py
│   ├── test_normalizer.py
│   ├── test_semantic.py
│   ├── test_spatial.py
│   ├── test_database.py
│   ├── test_quality.py
│   └── fixtures/
│       ├── dwg/                   # 测试 DWG 文件
│       ├── dxf/                   # 测试 DXF 文件
│       └── expected/              # 预期结果
│
├── config/
│   ├── default.yaml               # 默认配置
│   └── logging.yaml               # 日志配置
│
├── docs/
│   ├── 01_Technical_Feasibility_Analysis.md  ← 本文档
│   ├── 02_Architecture_Design.md
│   ├── 03_API_Documentation.md
│   ├── 04_Database_Schema.md
│   ├── 05_CAD_Parsing_Guide.md
│   ├── 06_Troubleshooting.md
│   └── 07_Extension_Guide.md
│
├── scripts/
│   ├── setup.bat                  # 环境初始化
│   ├── install_oda.md             # ODA 安装指南
│   └── generate_test_dxf.py       # 生成测试 DXF 文件
│
├── KnowledgeBase/                 # 知识库数据（git忽略）
│   ├── raw/                       # 原始文件
│   │   ├── dwg/
│   │   ├── dxf/
│   │   ├── pdf/
│   │   └── images/
│   ├── parsed/                    # 解析中间数据
│   ├── normalized/                # 标准化数据
│   ├── metadata/                  # 元数据
│   ├── embeddings/                # 向量数据
│   ├── thumbnails/                # 缩略图
│   ├── indexes/                   # 索引文件
│   ├── database/                  # SQLite 数据库
│   └── logs/                      # 日志
│
├── .env.example                   # 环境变量模板
├── .gitignore                     # Git 忽略
├── requirements.txt               # Python 依赖
├── run.bat                        # Windows 启动脚本
└── README.md                      # 项目说明
```

---

## 11. 统一 CAD 数据 Schema

### 11.1 Drawing（图纸）

```python
class Drawing(BaseModel):
    drawing_id: str                    # UUID
    file_name: str                     # 文件名
    file_path: str                     # 原始文件路径
    file_hash: str                     # SHA256
    file_size: int                     # 字节数
    file_type: str                     # "dwg" | "dxf" | "pdf"
    cad_version: str                   # "AC1032" 等
    cad_version_name: str              # "AutoCAD 2018" 等
    units: str                         # "mm" | "cm" | "m" | "inch" | "feet"
    insunits: int                      # DWG INSUNITS 原始值
    created_time: datetime | None      # 文件创建时间
    modified_time: datetime | None     # 文件修改时间
    parser: str                        # "ezdxf" | "oda+ezdxf" | "autocad_com"
    parser_version: str                # "ezdxf-1.4.4"
    parse_status: str                  # "success" | "partial" | "failed"
    parse_time: datetime               # 解析时间
    entity_count: int                  # 实体总数
    text_count: int                    # 文字总数
    dimension_count: int               # 尺寸总数
    layer_count: int                   # 图层数
    block_count: int                   # 块定义数
    layout_count: int                  # 布局数
    data_completeness: float           # 数据完整度 0~1
```

### 11.2 Layer（图层）

```python
class Layer(BaseModel):
    layer_id: str
    drawing_id: str                    # 关联图纸
    name: str                          # 图层名
    color: int                         # 颜色号
    linetype: str                      # 线型
    lineweight: int                    # 线宽
    is_on: bool                        # 是否打开
    is_frozen: bool                    # 是否冻结
    is_locked: bool                    # 是否锁定
    plot_style: str | None             # 打印样式
    entity_count: int                  # 该图层实体数
```

### 11.3 Block（块定义）

```python
class BlockDefinition(BaseModel):
    block_id: str
    drawing_id: str
    name: str                          # 块名
    base_point: tuple[float, float, float]  # 基点
    is_anonymous: bool                 # 是否匿名块
    is_layout: bool                    # 是否布局块
    entity_count: int                  # 块内实体数
    has_attributes: bool               # 是否有属性定义
    source_file: str
```

### 11.4 Entity（实体）— 统一基类

```python
class CADEntity(BaseModel):
    entity_id: str                     # UUID
    drawing_id: str                    # 关联图纸
    handle: str                        # CAD Handle (如 "1A35")
    entity_type: str                   # "LINE" | "CIRCLE" | "TEXT" | ...
    layer: str                         # 所属图层
    layout: str                        # 所属布局 ("Model" | "Layout1" | ...)
    space: str                         # "model" | "paper"
    block_name: str | None             # 所属块（如嵌套在块内）
    color: int                         # 颜色号 (256 = BYLAYER)
    linetype: str                      # 线型
    lineweight: int                    # 线宽
    bounding_box: BoundingBox          # 包围盒
    coordinates: list[float]           # 坐标点列表（展平）
    properties: dict                   # 类型特定属性
    source_file: str                   # 来源文件
    source_location: SourceLocation    # 来源位置
    data_tier: str                     # "raw" | "normalized" | "derived" | "ai_inference"
```

### 11.5 实体类型特定 Schema

```python
# LINE
class LineProperties(BaseModel):
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    length: float
    angle: float                       # 度

# CIRCLE
class CircleProperties(BaseModel):
    center: tuple[float, float, float]
    radius: float
    circumference: float               # 推导值，标注为 derived
    area: float                        # 推导值，标注为 derived

# ARC
class ArcProperties(BaseModel):
    center: tuple[float, float, float]
    radius: float
    start_angle: float                 # 度
    end_angle: float                   # 度
    arc_length: float                  # 推导值

# TEXT
class TextProperties(BaseModel):
    text: str                          # 文字内容
    position: tuple[float, float, float]
    rotation: float                    # 度
    height: float
    style: str                         # 文字样式
    width_factor: float
    oblique_angle: float

# MTEXT
class MTextProperties(BaseModel):
    text: str                          # 完整文字内容（去除格式码）
    raw_text: str                      # 原始文字（含格式码）
    position: tuple[float, float, float]
    rotation: float
    height: float
    width: float
    attachment_point: int              # 对齐方式
    line_spacing: float

# DIMENSION
class DimensionProperties(BaseModel):
    dimension_type: str                # "linear" | "aligned" | "angular" | "radius" | "diameter"
    measurement: float                 # 测量值
    text: str                          # 标注文字
    defpoint1: tuple[float, float, float]  # 定义点1
    defpoint2: tuple[float, float, float]  # 定义点2
    defpoint3: tuple[float, float, float]  # 定义点3（角度/半径用）
    dimline_point: tuple[float, float, float]  # 尺寸线位置
    style: str                         # 标注样式
    rotation: float

# BLOCK INSERT
class InsertProperties(BaseModel):
    block_name: str                    # 引用的块名
    insert_point: tuple[float, float, float]
    scale_x: float
    scale_y: float
    scale_z: float
    rotation: float                    # 度
    attributes: list[Attribute]        # 属性值列表

# ATTRIB (块属性)
class Attribute(BaseModel):
    tag: str                           # 属性标签
    value: str                         # 属性值
    position: tuple[float, float, float]
    height: float
    rotation: float
    layer: str
    block_name: str                    # 所属块引用名
    insert_position: tuple[float, float, float]  # 块插入位置
```

### 11.6 辅助类型

```python
class BoundingBox(BaseModel):
    min_x: float
    min_y: float
    min_z: float
    max_x: float
    max_y: float
    max_z: float
    width: float                       # 推导值
    height: float                      # 推导值

class SourceLocation(BaseModel):
    file: str                          # 文件名
    layout: str                        # 布局
    handle: str                        # Entity Handle
    layer: str                         # 图层
    coordinates: str                   # 人类可读坐标 "X=1000 Y=2000"

class SpatialRelationship(BaseModel):
    entity_a_id: str
    entity_b_id: str
    relationship_type: str             # "near" | "intersects" | "contains" | "belongs_to" | "annotates" | "references"
    distance: float | None             # 距离（near 类型时）
    confidence: float                  # 0~1
    source: str                        # "computed" | "rule_based"
```

---

## 12. 数据库 Schema 设计

### 12.1 SQLite 表结构

```sql
-- 图纸表
CREATE TABLE drawings (
    drawing_id TEXT PRIMARY KEY,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_hash TEXT NOT NULL UNIQUE,
    file_size INTEGER NOT NULL,
    file_type TEXT NOT NULL,
    cad_version TEXT,
    cad_version_name TEXT,
    units TEXT,
    insunits INTEGER,
    created_time TEXT,
    modified_time TEXT,
    parser TEXT,
    parser_version TEXT,
    parse_status TEXT NOT NULL,
    parse_time TEXT NOT NULL,
    entity_count INTEGER DEFAULT 0,
    text_count INTEGER DEFAULT 0,
    dimension_count INTEGER DEFAULT 0,
    layer_count INTEGER DEFAULT 0,
    block_count INTEGER DEFAULT 0,
    layout_count INTEGER DEFAULT 0,
    data_completeness REAL DEFAULT 0,
    thumbnail_path TEXT,
    raw_data_path TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- 图层表
CREATE TABLE layers (
    layer_id TEXT PRIMARY KEY,
    drawing_id TEXT NOT NULL REFERENCES drawings(drawing_id),
    name TEXT NOT NULL,
    color INTEGER,
    linetype TEXT,
    lineweight INTEGER,
    is_on INTEGER DEFAULT 1,
    is_frozen INTEGER DEFAULT 0,
    is_locked INTEGER DEFAULT 0,
    entity_count INTEGER DEFAULT 0,
    UNIQUE(drawing_id, name)
);

-- 块定义表
CREATE TABLE block_definitions (
    block_id TEXT PRIMARY KEY,
    drawing_id TEXT NOT NULL REFERENCES drawings(drawing_id),
    name TEXT NOT NULL,
    base_point TEXT,                   -- JSON: [x, y, z]
    is_anonymous INTEGER DEFAULT 0,
    is_layout INTEGER DEFAULT 0,
    entity_count INTEGER DEFAULT 0,
    has_attributes INTEGER DEFAULT 0,
    UNIQUE(drawing_id, name)
);

-- 实体表（核心表）
CREATE TABLE entities (
    entity_id TEXT PRIMARY KEY,
    drawing_id TEXT NOT NULL REFERENCES drawings(drawing_id),
    handle TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    layer TEXT,
    layout TEXT,
    space TEXT,
    block_name TEXT,
    color INTEGER,
    linetype TEXT,
    lineweight INTEGER,
    bbox_min_x REAL,
    bbox_min_y REAL,
    bbox_min_z REAL,
    bbox_max_x REAL,
    bbox_max_y REAL,
    bbox_max_z REAL,
    coordinates TEXT,                  -- JSON: [[x,y,z], ...]
    properties TEXT,                   -- JSON: 类型特定属性
    source_file TEXT,
    source_handle TEXT,
    source_layer TEXT,
    data_tier TEXT DEFAULT 'raw',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY(drawing_id) REFERENCES drawings(drawing_id)
);

-- 文字实体表（从 entities 表中提取，便于全文搜索）
CREATE TABLE texts (
    text_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES entities(entity_id),
    drawing_id TEXT NOT NULL REFERENCES drawings(drawing_id),
    text_content TEXT NOT NULL,
    position TEXT,                     -- JSON: [x, y, z]
    rotation REAL,
    height REAL,
    text_type TEXT,                    -- "TEXT" | "MTEXT"
    layer TEXT,
    layout TEXT,
    block_name TEXT,
    handle TEXT
);

-- 尺寸实体表
CREATE TABLE dimensions (
    dimension_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES entities(entity_id),
    drawing_id TEXT NOT NULL REFERENCES drawings(drawing_id),
    dimension_type TEXT,
    measurement REAL,
    text_content TEXT,
    defpoint1 TEXT,
    defpoint2 TEXT,
    defpoint3 TEXT,
    dimline_point TEXT,
    style TEXT,
    layer TEXT,
    layout TEXT,
    handle TEXT
);

-- 块属性表
CREATE TABLE block_attributes (
    attrib_id TEXT PRIMARY KEY,
    drawing_id TEXT NOT NULL REFERENCES drawings(drawing_id),
    insert_entity_id TEXT REFERENCES entities(entity_id),
    block_name TEXT NOT NULL,
    tag TEXT NOT NULL,
    value TEXT,
    position TEXT,
    height REAL,
    rotation REAL,
    layer TEXT,
    insert_position TEXT
);

-- 空间关系表
CREATE TABLE spatial_relationships (
    rel_id TEXT PRIMARY KEY,
    drawing_id TEXT NOT NULL REFERENCES drawings(drawing_id),
    entity_a_id TEXT NOT NULL REFERENCES entities(entity_id),
    entity_b_id TEXT NOT NULL REFERENCES entities(entity_id),
    relationship_type TEXT NOT NULL,
    distance REAL,
    confidence REAL,
    source TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

-- 布局表
CREATE TABLE layouts (
    layout_id TEXT PRIMARY KEY,
    drawing_id TEXT NOT NULL REFERENCES drawings(drawing_id),
    name TEXT NOT NULL,
    layout_type TEXT,                  -- "model" | "paper"
    tab_order INTEGER,
    viewport_count INTEGER DEFAULT 0,
    plot_settings TEXT                 -- JSON
);

-- 视口表
CREATE TABLE viewports (
    viewport_id TEXT PRIMARY KEY,
    drawing_id TEXT NOT NULL REFERENCES drawings(drawing_id),
    layout_name TEXT NOT NULL,
    view_center TEXT,                  -- JSON: [x, y]
    view_height REAL,
    view_width REAL,
    scale REAL,
    target_point TEXT,
    direction TEXT
);

-- 解析日志表
CREATE TABLE parse_logs (
    log_id TEXT PRIMARY KEY,
    drawing_id TEXT REFERENCES drawings(drawing_id),
    timestamp TEXT NOT NULL,
    level TEXT NOT NULL,               # "INFO" | "WARNING" | "ERROR"
    operation TEXT,
    message TEXT,
    details TEXT                       -- JSON
);

-- 文件版本历史表
CREATE TABLE drawing_revisions (
    revision_id TEXT PRIMARY KEY,
    drawing_id TEXT NOT NULL REFERENCES drawings(drawing_id),
    revision_number TEXT,
    revision_label TEXT,               -- "Rev.A", "V2", etc.
    file_hash TEXT NOT NULL,
    file_size INTEGER,
    modified_time TEXT,
    changes_summary TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

### 12.2 全文搜索索引（SQLite FTS5）

```sql
-- 文字内容全文索引
CREATE VIRTUAL TABLE texts_fts USING fts5(
    text_content,
    drawing_id UNINDEXED,
    entity_id UNINDEXED,
    layer UNINDEXED,
    layout UNINDEXED,
    tokenize='unicode61'               -- 支持中文分词（基本）
);

-- 块属性全文索引
CREATE VIRTUAL TABLE attributes_fts USING fts5(
    tag,
    value,
    drawing_id UNINDEXED,
    block_name UNINDEXED,
    tokenize='unicode61'
);

-- 图纸元数据全文索引
CREATE VIRTUAL TABLE drawings_fts USING fts5(
    file_name,
    notes,
    drawing_id UNINDEXED
);
```

### 12.3 索引设计

```sql
CREATE INDEX idx_entities_drawing ON entities(drawing_id);
CREATE INDEX idx_entities_type ON entities(entity_type);
CREATE INDEX idx_entities_layer ON entities(layer);
CREATE INDEX idx_entities_handle ON entities(handle);
CREATE INDEX idx_entities_bbox ON entities(bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y);
CREATE INDEX idx_texts_drawing ON texts(drawing_id);
CREATE INDEX idx_texts_layer ON texts(layer);
CREATE INDEX idx_dimensions_drawing ON dimensions(drawing_id);
CREATE INDEX idx_attributes_drawing ON block_attributes(drawing_id);
CREATE INDEX idx_attributes_block ON block_attributes(block_name);
CREATE INDEX idx_relationships_drawing ON spatial_relationships(drawing_id);
CREATE INDEX idx_relationships_type ON spatial_relationships(relationship_type);
```

---

## 13. CAD 解析流程设计

### 13.1 文件导入与识别流程

```
用户输入文件
    │
    ▼
┌─────────────────────┐
│ Step 1: 文件存在检查 │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Step 2: 计算文件哈希  │  SHA256
│ (SHA256)            │
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Step 3: 重复检测     │  查询数据库是否已有相同 hash
└─────────┬───────────┘
          │
          ├─ 已存在 → 返回已有 drawing_id，跳过解析
          │
          ▼
┌─────────────────────┐
│ Step 4: 文件类型检测  │  扩展名 + 文件头 magic bytes
└─────────┬───────────┘
          │
          ├─ .dxf → 直接进入 DXF 解析
          ├─ .dwg → 进入 DWG 处理流程
          ├─ .pdf → 标记为后期支持
          └─ 其他 → 标记为不支持
          │
          ▼
┌─────────────────────┐
│ Step 5: CAD 版本检测  │  读取文件头前 6 字节
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│ Step 6: 选择解析器    │
└─────────┬───────────┘
          │
          ▼
   进入解析流程
```

### 13.2 DWG 解析流程

```
DWG 文件
    │
    ▼
┌──────────────────────┐
│ 读取文件头 (前6字节)   │  → 识别 DWG 版本 (AC1032 等)
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│ 检查 ODA File Converter│  → 是否已安装？
│ 是否可用              │
└──────────┬───────────┘
           │
           ├─ 可用 →
           │   ┌──────────────────────┐
           │   │ 调用 ODA 转换为 DXF   │  ODAFileConverter.exe <in> <out> ACAD2018 DXF 0 1
           │   └──────────┬───────────┘
           │              │
           │              ▼
           │   ┌──────────────────────┐
           │   │ 使用 ezdxf 解析 DXF  │
           │   └──────────┬───────────┘
           │
           ├─ 不可用 →
           │   ┌──────────────────────┐
           │   │ 检查 AutoCAD COM     │  → 是否安装 AutoCAD？
           │   └──────────┬───────────┘
           │              │
           │              ├─ 可用 → 通过 COM API 读取
           │              │
           │              └─ 不可用 →
           │                  ┌──────────────────────┐
           │                  │ 记录失败             │
           │                  │ status = "failed"    │
           │                  │ error = "ODA和AutoCAD均不可用"│
           │                  │ recommendation =     │
           │                  │   "请安装ODA File Converter"│
           │                  └──────────────────────┘
           │
           ▼
   解析结果 → 标准化 → 入库
```

### 13.3 DXF 解析流程（ezdxf）

```python
# 伪代码
def parse_dxf(file_path: str) -> ParseResult:
    doc = ezdxf.readfile(file_path)
    
    result = ParseResult()
    
    # 1. 提取 HEADER 变量
    header = doc.header
    result.cad_version = header.get("$ACADVER", "unknown")
    result.units = detect_units(header)
    
    # 2. 提取图层
    for layer in doc.layers:
        result.layers.append(normalize_layer(layer))
    
    # 3. 提取块定义
    for block in doc.blocks:
        if not block.name.startswith("*"):  # 跳过匿名块
            result.blocks.append(normalize_block(block))
    
    # 4. 提取布局和视口
    for layout in doc.layouts:
        result.layouts.append(normalize_layout(layout))
    
    # 5. 遍历模型空间实体
    msp = doc.modelspace()
    for entity in msp:
        normalized = normalize_entity(entity, space="model")
        result.entities.append(normalized)
        
        if entity.dxftype() in ("TEXT", "MTEXT"):
            result.texts.append(normalize_text(entity))
        elif entity.dxftype() == "DIMENSION":
            result.dimensions.append(normalize_dimension(entity))
        elif entity.dxftype() == "INSERT":
            result.inserts.append(normalize_insert(entity))
            # 提取块属性
            if entity.attribs:
                for attrib in entity.attribs:
                    result.attributes.append(normalize_attribute(attrib, entity))
    
    # 6. 遍历图纸空间实体
    for layout in doc.layouts:
        if layout.name == "Model":
            continue
        for entity in layout:
            normalized = normalize_entity(entity, space="paper", layout=layout.name)
            result.entities.append(normalized)
    
    # 7. 计算包围盒
    for entity in result.entities:
        entity.bounding_box = compute_bbox(entity)
    
    # 8. 数据质量检查
    result.quality_report = run_quality_checks(result)
    
    return result
```

### 13.4 实体标准化映射表

| ezdxf 实体类型 | 统一 entity_type | 特殊处理 |
|---------------|-----------------|---------|
| LINE | LINE | 计算 length, angle |
| CIRCLE | CIRCLE | 计算 circumference, area (标记为 derived) |
| ARC | ARC | 计算 arc_length (标记为 derived) |
| LWPOLYLINE | LWPOLYLINE | 展开顶点 |
| POLYLINE | POLYLINE | 区分 2D/3D |
| SPLINE | SPLINE | 保存控制点和拟合点 |
| ELLIPSE | ELLIPSE | 保存长轴/短轴比 |
| TEXT | TEXT | 保存文字内容、位置 |
| MTEXT | MTEXT | 去除格式码，保存纯文本+原始文本 |
| DIMENSION | DIMENSION | 根据 dimtype 区分子类型 |
| LEADER | LEADER | 保存引线点 |
| MLEADER | MLEADER | 多重引线 |
| HATCH | HATCH | 保存边界路径和填充图案 |
| INSERT | INSERT | 关联块定义，提取属性 |
| ATTDEF | ATTDEF | 块属性定义 |
| POINT | POINT | 点 |
| SOLID / 3DSOLID | SOLID | 实体 |
| VIEWPORT | VIEWPORT | 视口信息 |
| TOLERANCE | TOLERANCE | 形位公差 |
| UNKNOWN/proxy | PROXY | 保存原始数据，标记为不可解析 |

---

## 14. RAG 混合检索流程设计

### 14.1 混合检索架构

```
用户问题："φ4.5×45m酸化窑筒体有多重？"
    │
    ▼
┌─────────────────────────────────┐
│ Query Analyzer (查询分析器)      │
│ ├── 提取关键词: "酸化窑","筒体"  │
│ ├── 提取参数: φ4.5, 45m, 重量   │
│ ├── 提取意图: 查询设备重量       │
│ └── 生成结构化查询条件           │
└───────────────┬─────────────────┘
                │
    ┌───────────┼───────────┐
    │           │           │
    ▼           ▼           ▼
┌────────┐ ┌────────┐ ┌────────────┐
│ 关键词  │ │ 结构化  │ │ 向量搜索   │
│ 搜索    │ │ 搜索    │ │ (后期)    │
│(FTS5)  │ │(SQL)   │ │           │
└───┬────┘ └───┬────┘ └─────┬──────┘
    │          │             │
    └──────────┼─────────────┘
               │
               ▼
    ┌──────────────────┐
    │ 结果合并 + 去重   │
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐
    │ Rerank (重排序)  │
    │ 按相关性排序      │
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐
    │ Context Builder  │
    │ 构建上下文        │
    │ ├── 原始数据      │
    │ ├── 来源信息      │
    │ └── 置信度        │
    └────────┬─────────┘
             │
             ▼
    ┌──────────────────┐
    │ LLM 生成回答     │
    │ + 来源追溯       │
    └──────────────────┘
```

### 14.2 搜索策略

| 搜索类型 | 引擎 | 适用场景 | 实现阶段 |
|---------|------|---------|---------|
| 关键词搜索 | SQLite FTS5 | "酸化窑"、"MILL-001" | Phase 5 |
| 结构化搜索 | SQLite SQL | 按图号、设备编号、图层、类型 | Phase 5 |
| 空间搜索 | SQLite + Shapely | "附近的文字"、"区域内的实体" | Phase 5 |
| 向量搜索 | Chroma/Qdrant | 语义相似查询 | Phase 6 |
| 混合搜索 | 以上组合 | 综合查询 | Phase 6 |

### 14.3 来源追溯规则

每条返回给 LLM 的上下文必须包含：

```json
{
  "content": "φ4500×45000",
  "source": {
    "file": "酸化窑总图.dwg",
    "drawing_id": "uuid-xxx",
    "layout": "Model",
    "entity_handle": "A23F",
    "entity_type": "DIMENSION",
    "layer": "标注",
    "coordinates": "X=1000 Y=2000"
  },
  "data_tier": "raw",
  "confidence": 1.0
}
```

如果无法追溯来源，LLM 回答中必须标注：
> "无法确认该数据来源。"

---

## 15. API 接口设计

### 15.1 REST API

| 方法 | 路径 | 说明 | 阶段 |
|------|------|------|------|
| POST | /api/import | 导入文件 | Phase 1 |
| POST | /api/import/batch | 批量导入 | Phase 1 |
| GET | /api/drawings | 图纸列表 | Phase 1 |
| GET | /api/drawings/{id} | 图纸详情 | Phase 1 |
| GET | /api/drawings/{id}/entities | 图纸实体列表 | Phase 1 |
| GET | /api/drawings/{id}/texts | 图纸文字列表 | Phase 1 |
| GET | /api/drawings/{id}/dimensions | 图纸尺寸列表 | Phase 1 |
| GET | /api/drawings/{id}/layers | 图纸图层列表 | Phase 1 |
| GET | /api/drawings/{id}/blocks | 图纸块列表 | Phase 1 |
| GET | /api/drawings/{id}/report | 解析报告 | Phase 1 |
| GET | /api/drawings/{id}/thumbnail | 缩略图 | Phase 2 |
| GET | /api/entities/{id} | 实体详情 | Phase 1 |
| GET | /api/entities/{id}/relationships | 实体空间关系 | Phase 4 |
| GET | /api/search | 综合搜索 | Phase 5 |
| POST | /api/query | AI 问答 | Phase 6 |
| POST | /api/compare | 图纸比较 | Phase 9 |
| GET | /api/metadata | 系统元数据 | Phase 1 |
| GET | /api/status | 系统状态 | Phase 1 |

### 15.2 请求/响应示例

```json
// POST /api/import
// Request:
{
  "file_path": "C:/drawings/酸化窑总图.dwg"
}
// Response:
{
  "drawing_id": "uuid-xxx",
  "file_name": "酸化窑总图.dwg",
  "file_type": "dwg",
  "cad_version": "AC1032",
  "parse_status": "success",
  "entity_count": 15382,
  "data_completeness": 0.963
}

// GET /api/search?q=酸化窑&type=all
// Response:
{
  "results": [
    {
      "type": "text",
      "content": "酸化窑 φ4.5×45m",
      "drawing_id": "uuid-xxx",
      "file_name": "酸化窑总图.dwg",
      "handle": "2F31",
      "layer": "标题栏"
    }
  ],
  "total": 15
}
```

### 15.3 MCP 接口（后期）

| 工具名 | 说明 |
|--------|------|
| search_cad | 搜索 CAD 图纸 |
| get_drawing | 获取图纸信息 |
| get_entity | 获取实体详情 |
| get_dimensions | 获取尺寸标注 |
| get_text | 获取文字内容 |
| get_equipment | 获取设备信息 |
| get_drawing_metadata | 获取图纸元数据 |
| compare_drawings | 比较两张图纸 |

---

## 16. CLI 命令行设计

```bash
# 文件导入
cadkb import <file_path>              # 导入单个文件
cadkb import <directory> --recursive  # 批量导入

# 解析
cadkb parse <file_path>               # 解析单个文件
cadkb parse --all --force             # 重新解析所有文件

# 查看信息
cadkb inspect <file_path>             # 查看文件解析结果
cadkb inspect <file_path> --entities  # 查看实体列表
cadkb inspect <file_path> --texts     # 查看文字
cadkb inspect <file_path> --dims      # 查看尺寸
cadkb inspect <file_path> --blocks    # 查看块

# 搜索
cadkb search "酸化窑"                  # 关键词搜索
cadkb search "酸化窑" --type text     # 限定类型
cadkb search "φ4500" --layer 标注     # 限定图层

# AI 问答（后期）
cadkb query "φ4500酸化窑直径是多少"
cadkb query "第3段筒体长度是多少"

# 图纸比较（后期）
cadkb compare A.dwg B.dwg

# 索引管理
cadkb rebuild-index                   # 重建索引
cadkb rebuild-index --fulltext        # 仅重建全文索引

# 系统状态
cadkb status                          # 系统状态
cadkb status --detail                 # 详细状态

# 配置
cadkb config show                     # 查看配置
cadkb config set <key> <value>        # 设置配置项
```

---

## 17. 测试方案

### 17.1 测试文件准备

```
tests/fixtures/
├── dxf/
│   ├── test_r12.dxf                  # R12 版本测试文件
│   ├── test_r2000.dxf               # R2000 版本
│   ├── test_r2018.dxf               # R2018 版本
│   ├── test_all_entities.dxf        # 包含所有实体类型的测试文件
│   ├── test_blocks.dxf              # 包含块和属性的测试文件
│   ├── test_dimensions.dxf          # 包含各种尺寸标注
│   ├── test_layouts.dxf             # 包含多个布局和视口
│   ├── test_title_block.dxf         # 包含标题栏
│   ├── test_chinese_text.dxf        # 包含中文文字
│   └── test_large.dxf               # 大文件性能测试
├── dwg/
│   └── (需要真实 DWG 文件)
└── expected/
    ├── test_all_entities.json       # 预期解析结果
    └── ...
```

### 17.2 测试覆盖

| 测试项 | 说明 | 优先级 |
|--------|------|--------|
| DWG 版本识别 | 读取文件头，识别 AC1032 等 | P0 |
| DXF R12 解析 | 基本实体解析 | P0 |
| DXF R2018 解析 | 最新版本实体解析 | P0 |
| LINE 实体 | 起点/终点/长度/角度 | P0 |
| CIRCLE 实体 | 圆心/半径/周长/面积 | P0 |
| ARC 实体 | 圆心/半径/角度 | P0 |
| LWPOLYLINE 实体 | 顶点列表 | P0 |
| POLYLINE 实体 | 2D/3D 多段线 | P1 |
| SPLINE 实体 | 控制点/拟合点 | P1 |
| TEXT 实体 | 文字内容/位置/高度 | P0 |
| MTEXT 实体 | 多行文字/格式码处理 | P0 |
| DIMENSION 实体 | 各类尺寸/测量值 | P0 |
| LEADER 实体 | 引线点 | P1 |
| HATCH 实体 | 边界/填充图案 | P1 |
| INSERT 实体 | 块引用/属性 | P0 |
| ATTRIB 提取 | 块属性 tag/value | P0 |
| 图层提取 | 图层表完整信息 | P0 |
| 块定义提取 | 块定义和内部实体 | P0 |
| 布局提取 | 模型空间/图纸空间 | P0 |
| 视口提取 | 视口信息 | P1 |
| 包围盒计算 | 所有实体包围盒 | P0 |
| 中文文字处理 | MTEXT 中文内容 | P0 |
| 大文件性能 | 10000+ 实体解析 | P1 |
| 数据质量报告 | 完整度计算 | P0 |
| 重复文件检测 | SHA256 比对 | P0 |
| 文件哈希计算 | SHA256 一致性 | P0 |

### 17.3 测试文件生成策略

由于当前环境缺少真实 DWG 测试文件，第一阶段采用以下策略：

1. **使用 ezdxf 生成测试 DXF 文件**（`scripts/generate_test_dxf.py`）
   - 程序化生成包含所有实体类型的 DXF 文件
   - 生成不同版本的 DXF 文件
   - 生成包含中文文字的 DXF 文件

2. **明确标注**："当前缺少真实 DWG 测试文件"

3. **提供获取真实测试文件的方法**：
   - 使用 AutoCAD 创建测试文件（如果有许可证）
   - 从公开 CAD 示例库下载
   - ODA File Converter 转换 DXF→DWG 生成

4. **绝不假装测试成功**：如果测试文件不存在，测试报告明确标注 "SKIP: 缺少测试文件"

---

## 18. 开发阶段划分

| 阶段 | 名称 | 核心功能 | 依赖 | 预计工作量 |
|------|------|---------|------|-----------|
| **Phase 1** | **基础文件管理 + DXF 解析** | 文件导入/哈希/版本识别 + ezdxf 解析 + 统一 Schema + SQLite 存储 + 解析报告 | 无 | 中 |
| Phase 2 | DWG 解析支持 | ODA File Converter 集成 + DWG→DXF 自动转换 + 缩略图生成 | Phase 1 + ODA | 中 |
| Phase 3 | 语义分析 | 图框识别 + 标题栏提取 + 设备/管道信息识别 | Phase 1-2 | 大 |
| Phase 4 | 空间关系 | 包围盒 + 邻近分析 + 空间关系图 | Phase 1 | 中 |
| Phase 5 | 搜索系统 | 全文搜索(FTS5) + 结构化搜索 + 空间搜索 + CLI search | Phase 1-4 | 中 |
| Phase 6 | RAG 系统 | Embedding + 向量库 + 混合检索 + Rerank | Phase 5 | 大 |
| Phase 7 | AI 接口 | LLM 集成 + 上下文构建 + 来源追溯 + REST API | Phase 6 | 大 |
| Phase 8 | CAD 版本兼容 | 多版本测试 + 兼容性修复 + AutoCAD COM 备选路径 | Phase 2 | 中 |
| Phase 9 | 图纸差异比较 | 实体级别 diff + 几何/文字/尺寸差异 + 比较报告 | Phase 1-4 | 大 |
| Phase 10 | GUI | Streamlit 界面 + 图纸浏览 + 数据查询 + AI 问答 | Phase 7 | 中 |

### 18.1 各阶段交付物

| 阶段 | 交付物 | 验收标准 |
|------|--------|---------|
| Phase 1 | 可运行的 CLI + DXF 解析 + SQLite | 能导入 DXF、解析实体、存储、生成报告 |
| Phase 2 | DWG 解析支持 | 能导入 DWG（需 ODA）、自动转换、解析 |
| Phase 3 | 语义分析模块 | 能识别标题栏、提取设备信息 |
| Phase 4 | 空间关系图 | 能查询实体间空间关系 |
| Phase 5 | 搜索系统 | 能通过 CLI/API 搜索文字、尺寸、设备 |
| Phase 6 | RAG 系统 | 能进行混合检索，返回带来源的结果 |
| Phase 7 | AI 问答 | 能回答图纸相关问题，附带来源追溯 |
| Phase 8 | 版本兼容 | 支持 R12-R2018 各版本 DWG/DXF |
| Phase 9 | 图纸比较 | 能比较两张图纸的差异 |
| Phase 10 | GUI | Streamlit 界面可用 |

---

## 19. 功能分类与决策清单

### 19.1 可免费实现（无需任何确认）

- [x] DXF 文件解析（ezdxf，MIT 许可证）
- [x] DWG 文件版本识别（纯 Python 读文件头）
- [x] 文件哈希计算（SHA256）
- [x] 重复文件检测
- [x] 统一数据模型（Pydantic）
- [x] SQLite 数据库存储
- [x] 全文搜索（SQLite FTS5）
- [x] 结构化搜索（SQL）
- [x] 空间关系计算（Shapely）
- [x] 解析报告生成
- [x] CLI 工具（Click）
- [x] REST API（FastAPI）
- [x] 日志系统
- [x] 数据质量检查

### 19.2 需要安装软件（免费）

- [ ] **ODA File Converter** — DWG→DXF 转换的必需工具
  - 费用：非商业用途免费
  - 安装方式：下载 .exe 安装
  - 影响：不安装则无法解析 DWG 文件（只能解析 DXF）
  - **需要老板确认：使用场景是否属于非商业用途**
  
- [ ] **Chroma / Qdrant** — 向量数据库（Phase 5-6 才需要）
  - 费用：免费
  - 安装方式：`pip install chromadb`
  - 影响：不安装则无向量搜索功能（关键词搜索仍可用）

### 19.3 需要老板确认的决策点

| # | 决策点 | 说明 | 影响 | 建议 |
|---|--------|------|------|------|
| 1 | **ODA File Converter 使用场景** | ODA 对非商业用途免费，商业用途需会员($3000+/年) | 决定是否能免费使用 ODA | 确认使用场景 |
| 2 | **PyMuPDF 许可证** | PyMuPDF (PyPDF) 使用 AGPL-3.0 许可证，比 MIT 严格 | 如果系统对外发布，可能需要购买商业许可证 | Phase 3 PDF 解析时再确认；可替换为 pdfminer.six (MIT) |
| 3 | **LLM 模型选择** | 云端(OpenAI/百炼) vs 本地(Ollama) | 影响隐私和成本 | 建议支持两种模式，默认本地 |
| 4 | **AutoCAD 安装** | 是否安装 AutoCAD 作为备选解析路径 | 费用 ¥8000+/年 | 第一阶段不安装，用 ODA 替代 |
| 5 | **数据备份策略** | 知识库数据的备份方式 | 数据安全 | 建议定期复制 .db 文件 |

### 19.4 可能需要商业 SDK / 付费

| 项目 | 费用 | 替代方案 | 是否必须 |
|------|------|---------|---------|
| ODA Drawings SDK | $3,000+/年 | ODA File Converter (非商业免费) | 否 |
| AutoCAD 许可证 | ¥8,000+/年 | ODA File Converter | 否 |
| ODA 商业会员 | $3,000+/年 | 非商业免费使用 | 视用途 |

---

## 20. 风险与限制

### 20.1 技术风险

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|---------|
| ODA File Converter 不支持某些 DWG 版本 | 部分 DWG 无法解析 | 低 | 支持 LibreDWG 作为备选 |
| ezdxf 无法解析 PROXY ENTITY | 部分自定义实体丢失 | 中 | 标记为"不可解析"，保存原始数据 |
| 大文件性能问题 | 50000+ 实体图纸解析慢 | 中 | 使用 iterdxf 流式处理 |
| 中文文字编码问题 | 乱码 | 低 | ezdxf 支持 Unicode，测试验证 |
| ODA 转换丢失数据 | 转换后 DXF 与原 DWG 不一致 | 低 | 数据质量检查 + 完整度报告 |
| MTEXT 格式码处理不完整 | 文字内容提取不准确 | 中 | 保留 raw_text + cleaned_text |

### 20.2 已知限制

1. **DWG 解析依赖外部工具**：ezdxf 不能直接读 DWG，必须依赖 ODA File Converter 或 AutoCAD
2. **ODA 许可证灰色地带**：非商业用途免费，但"非商业"的定义需要老板自行判断
3. **LibreDWG 的 GPL 限制**：如果使用 LibreDWG，系统需要 GPL v3 开源
4. **无 AutoCAD**：当前环境无 AutoCAD，COM API 路径不可用
5. **缺少真实测试文件**：第一阶段使用程序生成的测试 DXF，真实 DWG 测试需要后续补充

---

## 21. 第一阶段实施计划

### 21.1 范围

```
DWG/DXF 文件导入
    ↓
文件识别（类型 + 版本）
    ↓
DXF 解析（ezdxf）
    ↓
CAD 实体解析（所有支持的实体类型）
    ↓
统一 Schema 转换
    ↓
SQLite 保存
    ↓
解析报告生成
```

### 21.2 第一阶段交付物清单

1. **项目骨架**：目录结构、配置文件、.gitignore、.env.example、requirements.txt
2. **文件管理模块**：
   - 文件导入
   - SHA256 哈希
   - DWG/DXF 文件类型检测
   - DWG 版本识别（读文件头）
   - 重复文件检测
3. **DXF 解析模块**：
   - 基于 ezdxf 的完整解析器
   - 支持所有主要实体类型
   - 模型空间 + 图纸空间
   - 图层、块定义、块引用、块属性
   - 尺寸标注（所有子类型）
   - MTEXT 格式码清理
4. **数据标准化模块**：
   - Pydantic 数据模型
   - 实体标准化
   - 包围盒计算
5. **数据库模块**：
   - SQLite 表创建
   - SQLAlchemy ORM
   - 数据写入
6. **质量检查模块**：
   - 实体/文字/尺寸/图层/块计数检查
   - 数据完整度计算
   - 解析报告生成
7. **CLI 工具**：
   - `cadkb import`
   - `cadkb inspect`
   - `cadkb status`
8. **测试文件**：
   - 程序生成测试 DXF 文件
   - 单元测试
9. **文档**：
   - README.md
   - 架构说明
   - 安装说明

### 21.3 第一阶段不包含

- DWG 解析（需要 ODA File Converter，Phase 2）
- 语义分析（图框/标题栏识别，Phase 3）
- 空间关系（Phase 4）
- 搜索系统（Phase 5）
- RAG/AI 问答（Phase 6-7）
- GUI（Phase 10）
- 图纸比较（Phase 9）

---

## 附录 A：DWG 版本标识快速识别代码

```python
DWG_VERSION_MAP = {
    b"AC1.50": "AutoCAD R2.05",
    b"AC2.10": "AutoCAD R2.10",
    b"AC1001": "AutoCAD R2.5",
    b"AC1002": "AutoCAD R2.6",
    b"AC1003": "AutoCAD R9",
    b"AC1004": "AutoCAD R10",
    b"AC1006": "AutoCAD R11/R12",
    b"AC1009": "AutoCAD R12/R13",
    b"AC1012": "AutoCAD R13",
    b"AC1014": "AutoCAD R14",
    b"AC1015": "AutoCAD 2000",
    b"AC1018": "AutoCAD 2004",
    b"AC1021": "AutoCAD 2007",
    b"AC1024": "AutoCAD 2010",
    b"AC1027": "AutoCAD 2013",
    b"AC1032": "AutoCAD 2018",
    b"AC1042": "AutoCAD 2025",
}

def detect_dwg_version(file_path: str) -> tuple[str, str]:
    """读取 DWG 文件头识别版本。
    返回 (version_code, version_name)。
    """
    with open(file_path, "rb") as f:
        header = f.read(6)
    version_code = header.decode("ascii", errors="replace")
    version_name = DWG_VERSION_MAP.get(header, f"Unknown ({version_code})")
    return version_code, version_name
```

## 附录 B：ODA File Converter 命令行调用

```bash
# 语法:
# ODAFileConverter.exe <输入目录> <输出目录> <目标版本> <输出格式> <递归> <审计>

# DWG → DXF (ACAD2018)
ODAFileConverter.exe "C:\input" "C:\output" ACAD2018 DXF 0 1

# 参数说明:
#   输入目录:   包含 DWG 文件的文件夹（不支持单文件）
#   输出目录:   输出 DXF 的文件夹
#   目标版本:   ACAD9, ACAD10, ACAD12, ACAD13, ACAD14,
#              ACAD2000, ACAD2004, ACAD2007, ACAD2010, ACAD2013, ACAD2018
#   输出格式:   DWG, DXF, DGN
#   递归:       0=不递归, 1=递归子目录
#   审计:       0=不审计, 1=审计修复
```

## 附录 C：requirements.txt（第一阶段）

```
# CAD 解析
ezdxf[draw]>=1.4.0          # DXF 解析 + 渲染

# 数据模型与校验
pydantic>=2.0               # 数据模型

# 数据库
sqlalchemy>=2.0             # ORM
# sqlite3 为 Python 内置，无需安装

# CLI
click>=8.0                  # 命令行框架

# API (后期)
# fastapi>=0.100             # REST API
# uvicorn>=0.20              # ASGI 服务器

# 几何运算 (已安装)
# shapely>=2.0
# numpy>=1.24

# 日志
colorlog>=6.0               # 彩色日志

# 配置
pyyaml>=6.0                 # YAML 配置 (已安装)

# 测试
pytest>=7.0                 # 单元测试
pytest-cov>=4.0             # 测试覆盖率

# 后期依赖 (第一阶段不需要)
# chromadb>=0.4              # 向量数据库 (Phase 5-6)
# openai>=1.0                # LLM API (Phase 7)
# streamlit>=1.28            # GUI (Phase 10)
```

---

> **下一步行动**：等待老板确认以下关键决策点后，开始 Phase 1 开发：
> 1. ODA File Converter 的使用场景是否属于非商业用途？
> 2. 是否同意使用 PyMuPDF（AGPL 许可证）用于后期 PDF 解析，或改用 pdfminer.six（MIT）？
> 3. 第一阶段是否直接开始（DXF 解析部分不需要任何额外安装）？
