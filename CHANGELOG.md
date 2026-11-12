# Changelog

本项目版本记录遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)（主版本.次版本.修订号）。

## [0.1.0] - 2026-08-29

首个公开发布版本（对应本地 Phase 1–10 全部完成）。

### Added

- **CAD 解析**：DXF（ezdxf）与 DWG（ODA File Converter / AutoCAD COM 双路径）解析，
  支持 R12–R2018 版本兼容；实体类型覆盖 LINE/CIRCLE/ARC/多段线/SPLINE/ELLIPSE/
  TEXT/MTEXT/DIMENSION/LEADER/HATCH/INSERT/ATTRIB/POINT/VIEWPORT
- **语义分析**：图框识别、标题栏键值提取、设备位号识别、管道管径识别（规则推断带置信度）
- **空间关系**：包含 / 相交 / 邻近 / 标注 / 归属 五种关系自动计算
- **搜索系统**：SQLite FTS5 全文 + 结构化 + 空间区域三种模式，结果带来源追溯
- **RAG 混合检索**：全文 + 向量（Chroma + bge 中文模型）+ 结构化加权合并 + 重排序，
  向量库不可用时自动降级
- **AI 问答**：LLM 模式 / 证据模式双通道，回答强制带来源追溯，绝不编造
- **图纸比较**：实体 / 文字 / 尺寸 / 语义四类差异检测
- **三种交互入口**：CLI（click）、REST API（FastAPI）、GUI（Streamlit）
- **工程配套**：Dockerfile + docker-compose、GitHub Actions CI、一键安装脚本
  （setup.bat / setup.sh）、环境变量配置模板（.env.example）

### Changed

- 无（首个版本）

### Fixed

- 无（首个版本）

### Security

- 敏感数据（图纸 / 数据库 / 密钥）全部通过 .gitignore 与 .dockerignore 隔离，
  不入库、不入镜像；API Key 仅通过环境变量注入

## [Unreleased]

### Added

- **装箱单解析：PDF 通道**（`scripts/parse_vendor_packing.py`）
  支持有文字层 PDF 的表格提取（`pdfplumber.extract_tables`），无表格时回退按行切分。
  新增 2257 箱结构化记录，含三边尺寸、净重、毛重、体积。
- **装箱单解析：OCR 通道**（`--ocr`）
  Tesseract `chi_sim+eng` 处理扫描件 PDF 与 JPG/PNG 签收单；OCR 原文落
  `packing_ocr_raw` 留痕（404 页 / 161 文件），便于人工复核与二次提取。
  实测结论：装箱号可稳定识别，尺寸/重量/明细不可靠 —— **只写箱号，其余留 NULL**。
- **箱号映射表**（`scripts/build_box_aliases.py` → `packing_box_aliases`）
  解决「厂家箱号 ↔ 物流单证箱号」双编号混淆（如石灰乳厂家 `2#` = 单证 `9-2`）。
  三种匹配方式：人工确认（种子，附证据）/ 尺寸+名称自动匹配 / 扫描件顺序推断。
  红线：达不到阈值不写，一对多冲突只报告不定案。
- **验收核查脚本**（`scripts/verify_packing.py`）
  一键核查装箱总览、OCR 留痕、验收点、映射表，并支持按箱号反查（按供应商分组）。
- **夜间向量重建运行器**（`scripts/ops/rebuild_vector_nightly.py`）
  按「停 API → `rebuild-index --embeddings` → 重启 → 自检」四步跑，规避重建期间
  API 进程持有同一 Chroma 目录导致的 sqlite 锁冲突；日志
  `MASTER/logs/rebuild_vector.log`，配套计划任务 `WB_RebuildVector`。

### Fixed

- **FTS5 查询语法崩溃**：问句原样塞进 `MATCH ?`，`-` 被 FTS5 当语法解析
  （`9-2箱里装的是什么设备？` → `no such column: 2箱里…`），导致全文通道整条
  抛异常后静默返回空；带连字符的位号/箱号（`9-2`、`P01-xxx`、`NE150-1#`）全部中招。
  新增 `src/core/fts_query.py:build_match()`：剥掉语法字符、逐 token 加双引号、
  以 OR 连接；无强 token（如仅「9-2」）时返回空串让调用方跳过查询，避免噪声。
  已接入 `search_service`（3 处）、`unified_search`（2 处）、`repositories`（1 处）。
- **向量索引加载把 API 进程打崩**：旧 `VectorDB/` 的 HNSW 文件为旧格式/头部损坏，
  chromadb 1.5.9 按损坏 header 分配天文数字内存 →
  `memory allocation of 33554432 bytes failed`，进程被 abort、`/api/status` 直接断连。
  `config/default.yaml` 的 `embeddings_dir` 切到新的空库 `VectorDB_v2/`，
  旧目录原样保留备查。
- PDF/OCR 文本中的 CJK 康熙部首与部首补充区字形（`箱⻓`、`⽑重`、`⽯灰`）导致
  表头列名匹配全部失配，尺寸仅解析出 1 列。加入 NFKC + 部首映射表后，
  PDF 箱子尺寸三边完整率由 152/2257 提升至 2257/2257。
- 长路径（>260 字符）下图片/PDF 打开失败（FileNotFoundError），统一加 `\\?\` 前缀。
- 厂家复用模板未更新导致箱号错写（`装箱清单-8` 内文仍写 `箱号：1#`），
  按文件名序号纠正并留痕。

### Known Issues

- 四张 FTS 表（`texts_fts` / `attributes_fts` / `drawings_fts` / `documents_fts`）
  均为 `tokenize='unicode61'`，该分词器把连续汉字整体当成一个 token，中文既不分词
  也不支持子串：实测 1,206,476 行下 `球磨机` → 0 条、`磨机` → 0 条、
  `石灰乳` → 4 条（仅独立成词时命中）。**中文语义召回只能靠向量通道**；
  彻底解决需将分词器换为 `trigram` 并重建索引，代价待评估。
