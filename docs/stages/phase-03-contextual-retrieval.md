# 阶段 3：结构感知索引与 Contextual Retrieval

## 1. 阶段目标

实现从 MCP markdown 到 LanceDB 向量库的索引构建流程，包括 metadata 解析、结构感知切块、规则化 chunk context、bge-m3 embedding 和本地向量写入。

## 2. 做了什么

新增文件：

- `fin_report_agent/retrieval/metadata.py`
- `fin_report_agent/retrieval/chunker.py`
- `fin_report_agent/retrieval/contextual.py`
- `fin_report_agent/retrieval/embeddings.py`
- `fin_report_agent/retrieval/store.py`
- `fin_report_agent/retrieval/ingest.py`
- `tests/test_retrieval_pipeline.py`

新增 tool：

- `index_filing_markdown`：把下载后的 markdown 建成结构感知向量索引。

## 3. 怎么实现

索引流程：

1. `parse_metadata_file(path)` 读取 markdown，并解析顶部 metadata table。
2. `chunk_markdown(markdown, metadata)` 移除 metadata header，按 markdown heading 和 SEC Item 标题切 section。
3. section 内部再按段落和表格块切成 blocks，尽量保留表格完整。
4. chunk 目标长度约 4200 字符，过长时带 500 字符 overlap。
5. `attach_context(chunks)` 为每个 chunk 生成规则上下文。
6. `EmbeddingModel.embed_texts()` 对 `context_text + chunk.text` 生成向量。
7. `LanceDBChunkStore.add_records()` 写入 `filing_chunks` 表。

metadata 标准字段：

- `company_name`
- `ticker`
- `cik`
- `requested_year`
- `form`
- `filed_date`
- `report_period`
- `accession_number`
- `source_path`

chunk 字段：

- `chunk_id`
- `text`
- `context_text`
- `indexed_text`
- `section_path`
- `page_start`
- `page_end`
- `token_count`

## 4. 关键决策

- Contextual Retrieval 第一版使用规则生成，不调用 LLM。
- token 数先用字符数粗估，不引入 tokenizer。
- 表格行作为连续块保留。
- embedding 默认 `BAAI/bge-m3`，并使用 `local_files_only=True`。
- LanceDB 和 sentence-transformers 放入 `retrieval` extra。

## 5. 决策原因

- 规则 context 可复现、可测试，符合教学项目“每一步都能解释”的要求。
- 粗估 token 足够支撑第一版切块，避免为了精确 token 引入额外复杂度。
- 财报表格常包含关键数字，不能被随意拆断。
- 本地模型加载遵守 `CODEX.md` 中“本机 hf 缓存已有模型”的设定，不自动联网下载。
- 重依赖放入 extra 可以让阶段 1、5、6 的测试快速运行，同时保留完整检索能力。

## 6. 验证方式

运行：

```bash
uv run pytest tests/test_retrieval_pipeline.py
```

覆盖：

- MCP markdown header 能解析出公司、ticker、年份和表单。
- chunker 能识别 `Item 7` section。
- context 以 `[Chunk context]` 开头，并包含公司信息。

完整测试：

```bash
uv run pytest
```

结果：

```text
13 passed
```

语法验证：

```bash
uv run python -m compileall fin_report_agent
```

通过。

## 7. 后续事项

- 在安装 `uv sync --extra retrieval` 且本地 Hugging Face 缓存存在后，可对真实 10-K 执行索引构建。
- 后续可增加 LLM 生成 chunk context，但第一版保留规则生成。

