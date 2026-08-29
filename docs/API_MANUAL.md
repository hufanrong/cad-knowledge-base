# CAD Knowledge Base API 接口手册（中文版）

版本：0.7.0

本文档说明 CAD 知识库对外暴露的 HTTP 接口及其用途。
启动服务后，也可在浏览器访问交互式文档：http://localhost:8000/docs

## 目录

- [POST /api/agent/query](#post-apiagentquery) — 
- [POST /api/compare](#post-apicompare) — 比较两张 CAD 图纸的差异，返回变更清单。
- [GET /api/devices](#get-apidevices) — 列出设备主数据，支持按位号/名称搜索或子系统过滤。
- [GET /api/devices/{tag_no}/profile](#get-apidevicestag_noprofile) — 按位号返回完整设备档案：跨图位置、箱单、供应商、关联文档。
- [GET /api/documents/{file_id}/content](#get-apidocumentsfile_idcontent) — 获取非 CAD 文档（Word/Excel/PDF）的解析内容。
- [GET /api/drawings](#get-apidrawings) — 分页列出知识库中所有 CAD 图纸的元数据。
- [GET /api/drawings/{drawing_id}](#get-apidrawingsdrawing_id) — 按 drawing_id 查询单张图纸的详细摘要。
- [GET /api/files](#get-apifiles) — 跨格式文件列表/搜索（CAD、Word、Excel、PDF 等）。
- [GET /api/files/{file_id}](#get-apifilesfile_id) — 查询单个文件的元数据、原始路径和解析产物。
- [POST /api/generate](#post-apigenerate) — 
- [GET /api/health](#get-apihealth) — 
- [GET /api/projects](#get-apiprojects) — 列出系统推断出的全部项目。
- [GET /api/projects/{name}/files](#get-apiprojectsnamefiles) — 查询某个项目下的所有文件。
- [POST /api/query](#post-apiquery) — AI 问答接口，返回答案和可追溯的来源上下文。
- [GET /api/rag](#get-apirag) — RAG 混合检索：全文 + 向量 + 结构化 + 重排序。
- [GET /api/search](#get-apisearch) — 对 CAD 图纸内容做综合检索（文字、属性、设备等）。
- [GET /api/search-all](#get-apisearch-all) — 统一跨格式搜索：CAD + 文档 + 文件元数据。
- [GET /api/status](#get-apistatus) — 查看系统运行状态、图纸数量、向量索引等统计信息。

## 接口详情

### POST /api/agent/query

Agent-oriented structured query: parses intent/entities, retrieves evidence,
and lists information gaps. No LLM is used; safe for external agents.

**请求体：** `AgentQueryRequest`

**响应：** `any`

---

### POST /api/compare

Compare two drawings and return a difference report.

**作用：** 比较两张 CAD 图纸的差异，返回变更清单。

**请求体：** `CompareRequest`

**响应：** `any`

---

### GET /api/devices

列出设备主数据，支持按子系统或关键词搜索。

**作用：** 列出设备主数据，支持按位号/名称搜索或子系统过滤。

**参数：**

- `q`：string 位号/名称关键词
- `subsystem`：string 子系统编号过滤
- `limit`：integer 

**响应：** `any`

---

### GET /api/devices/{tag_no}/profile

按位号返回完整设备档案（跨图位置、箱单、文档）。

**作用：** 按位号返回完整设备档案：跨图位置、箱单、供应商、关联文档。

**参数：**

- `tag_no`：string （必填）

**响应：** `any`

---

### GET /api/documents/{file_id}/content

文档解析内容（用于 Agent 进一步分析）。

**作用：** 获取非 CAD 文档（Word/Excel/PDF）的解析内容。

**参数：**

- `file_id`：string （必填）

**响应：** `any`

---

### GET /api/drawings

List drawings.

**作用：** 分页列出知识库中所有 CAD 图纸的元数据。

**参数：**

- `limit`：integer 
- `offset`：integer 

**响应：** `any`

---

### GET /api/drawings/{drawing_id}

Get a drawing's details.

**作用：** 按 drawing_id 查询单张图纸的详细摘要。

**参数：**

- `drawing_id`：string （必填）

**响应：** `any`

---

### GET /api/files

统一文件列表/搜索（跨格式元数据）。

**作用：** 跨格式文件列表/搜索（CAD、Word、Excel、PDF 等）。

**参数：**

- `q`：string 关键词（空=全部）
- `source_type`：string cad/word/excel/pdf/project/image/other
- `limit`：integer 
- `offset`：integer 

**响应：** `any`

---

### GET /api/files/{file_id}

文件详情（含解析产物路径）。

**作用：** 查询单个文件的元数据、原始路径和解析产物。

**参数：**

- `file_id`：string （必填）

**响应：** `any`

---

### POST /api/generate

Generate engineering documents (acceptance record, hoisting plan, schedule).

**请求体：** `GenerateRequest`

**响应：** `any`

---

### GET /api/health

Lightweight health check; does not touch the database or vector index.

**响应：** `any`

---

### GET /api/projects

列出全部推断项目。

**作用：** 列出系统推断出的全部项目。

**响应：** `any`

---

### GET /api/projects/{name}/files

指定项目的全部文件（CAD+文档）。

**作用：** 查询某个项目下的所有文件。

**参数：**

- `name`：string （必填）
- `limit`：integer 

**响应：** `any`

---

### POST /api/query

AI QA with source traceability.

**作用：** AI 问答接口，返回答案和可追溯的来源上下文。

**请求体：** `QueryRequest`

**响应：** `any`

---

### GET /api/rag

Hybrid RAG retrieval (no LLM).

**作用：** RAG 混合检索：全文 + 向量 + 结构化 + 重排序。

**参数：**

- `q`：string 检索问题（必填）
- `top_k`：integer 

**响应：** `any`

---

### GET /api/search

Unified search.

**作用：** 对 CAD 图纸内容做综合检索（文字、属性、设备等）。

**参数：**

- `q`：string 搜索关键词（必填）
- `search_type`：string 
- `limit`：integer 

**响应：** `any`

---

### GET /api/search-all

跨格式统一搜索（CAD + 文档 + 文件元数据）。

**作用：** 统一跨格式搜索：CAD + 文档 + 文件元数据。

**参数：**

- `q`：string 统一搜索关键词（必填）
- `source_type`：string 过滤类型
- `limit`：integer 

**响应：** `any`

---

### GET /api/status

System status (with lazy caching for vector index / LLM).

**作用：** 查看系统运行状态、图纸数量、向量索引等统计信息。

**响应：** `any`

---

## 数据模型

### AgentQueryRequest

- `query`：string 自然语言问题，例如：0203 子系统 CF0204ME01 吊装方案（必填）
- `top_k`：integer 检索结果数量

### CompareRequest

- `file_a`：string 第一张图纸路径（必填）
- `file_b`：string 第二张图纸路径（必填）

### GenerateRequest

- `doc_type`：string 文档类型: acceptance / hoisting / weekly / monthly（必填）
- `tag_no`：any 设备位号，acceptance/hoisting 必填
- `site_data`：object 现场数据/约束（JSON 对象）
- `items`：数组[object] weekly/monthly 计划项

### HTTPValidationError

- `detail`：数组[ValidationError] 

### QueryRequest

- `query`：string 用户问题（必填）
- `top_k`：integer 检索结果数

### ValidationError

- `loc`：数组[any] （必填）
- `msg`：string （必填）
- `type`：string （必填）
- `input`：any 
- `ctx`：object 
