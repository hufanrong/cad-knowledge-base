# -*- coding: utf-8 -*-
"""FTS5 查询构造：把自由文本变成语法安全、可用的 MATCH 表达式。

背景（2026-11-12 线上故障定位）
------------------------------------------------------------------
1. **语法崩溃**：`search_service` / `unified_search` 把用户问句原样塞进
   `MATCH ?`。FTS5 会把 `-` `:` `(` `)` `*` `"` 以及 AND/OR/NOT 当语法，
   于是 `9-2箱里装的是什么设备？` 被解析成 `9 MINUS 2箱里…`，
   `2箱里…` 当成列名 → `no such column`，整条通道抛异常后静默返回空。
   带连字符的位号/箱号（`9-2`、`P01-xxx`、`NE150-1#`）全中招。

2. **分词器限制（改查询救不回来）**：四张 FTS 表都是
   `tokenize='unicode61'`，该分词器把**连续汉字整体当成一个 token**，
   既不切词也不支持子串。实测 `texts_fts`（1,206,476 行）：
   `球磨机` → 0 条、`磨机` → 0 条、`石灰乳` → 4 条（仅当正文里它独立成词）。
   所以中文语义召回只能靠向量通道，本模块不试图解决。

做法
------------------------------------------------------------------
剥掉全部 FTS5 语法字符，只保留「汉字串」和「英数串」，逐 token 加双引号
后以 OR 连接。每个 token 都是索引里的完整词，**不会引入子串垃圾命中**。

- 强 token：汉字串（≥2 字）、含字母的英数串（≥2 位，如 `NE150`/`AW05`）
- 弱 token：单字汉字、纯数字短串 → 存在强 token 时丢弃；
  只有弱 token 时直接返回空串，让调用方跳过 FTS（否则 `9`/`2` 会把
  几万条无关正文拉进来）

实测取舍（2026-11-12）：曾试验「后缀前缀 `"xxx"*` + OR」可把中文召回
从 0 拉到 1572 条，但 bm25 被大量子串带偏，Top1 是「备」「泵」这类
单字文档——对证据库属污染，违反「宁可缺，不可编」，故不启用。
"""

from __future__ import annotations

import re
import unicodedata

_CJK = r"\u4e00-\u9fff"
_TOKEN_RE = re.compile(rf"[{_CJK}]+|[0-9A-Za-z]+")
_CJK_RE = re.compile(rf"[{_CJK}]+")
_ALPHA_RE = re.compile(r"[A-Za-z]")


def _quote(token: str) -> str:
    """加双引号（内部引号翻倍转义），中和一切 FTS5 语法字符。"""
    return '"%s"' % token.replace('"', '""')


def build_match(query: str) -> str:
    """构造 FTS5 安全 MATCH 串。

    Returns:
        可直接用于 `MATCH ?` 的表达式；若问句里没有可用 token（例如只有
        「9-2」这种弱 token），返回空串——调用方应据此跳过 FTS，
        而不是把空串塞进 MATCH（空串同样会抛语法错）。
    """
    text = unicodedata.normalize("NFKC", str(query or ""))
    strong: list[str] = []
    for tok in _TOKEN_RE.findall(text):
        if _CJK_RE.fullmatch(tok):
            if len(tok) >= 2:
                strong.append(tok)
        elif len(tok) >= 2 and _ALPHA_RE.search(tok):
            strong.append(tok)

    if not strong:
        return ""

    seen: set[str] = set()
    parts: list[str] = []
    for tok in strong:
        quoted = _quote(tok)
        if quoted not in seen:
            seen.add(quoted)
            parts.append(quoted)
    return " OR ".join(parts)
