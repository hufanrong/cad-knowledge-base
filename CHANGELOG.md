# Changelog

本项目版本记录遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)（主版本.次版本.修订号）。

## [Unreleased]

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
