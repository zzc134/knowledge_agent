# Memory Tree 实施步骤

## 目标

把当前的“长期兴趣记忆”扩展成一个本地优先的层级记忆层，让 Agent 可以先读取用户历史数据的高层摘要，再按需下钻到原始 chunk。

第一版不替换现有检索系统，而是在现有 `documents` / `chunks` / `UserInterest` 之上新增 Memory Tree 索引。

## 第一步：定义 Memory Tree 数据模型

新增两类表：

- `memory_nodes`：存储 Source Tree、Topic Tree、Global Tree 中的摘要节点。
- `memory_edges`：存储节点之间、节点与原始 chunk 之间的关系。

建议字段：

```text
MemoryNode
- id
- tree_type: source | topic | global
- level: 1 | 2 | 3
- key: source/document/topic/day/week/month 的稳定标识
- title
- summary
- dense_embedding
- time_start
- time_end
- metadata
- created_at
- updated_at

MemoryEdge
- id
- parent_node_id
- child_node_id
- chunk_id
- relation_type: contains | summarizes | references
- weight
- created_at
```

现有 `chunks` 作为 L0 原始记忆，不重复存储原文。

## 第二步：实现 Tree Builder

新增 `backend/memory/tree_builder.py`。

职责：

- 从现有 `documents` 和 `chunks` 读取 L0 数据。
- 按来源构建 Source Tree。
- 按主题构建 Topic Tree。
- 按时间构建简化版 Global Tree。
- 调用 LLM 生成 L1 / L2 摘要。
- 为摘要节点生成 embedding。
- 写入 `memory_nodes` 和 `memory_edges`。

第一版先做离线批处理，不做复杂实时增量：

```bash
cd backend
python -m memory.build_tree
```

后续再接入文档入库流程，实现新文档入库后自动更新相关树。

## 第三步：构建 Source Tree

Source Tree 按数据来源组织。

第一版使用现有字段：

- `Document.source_type`
- `Document.source_url`
- `Document.id`

层级建议：

```text
source_type
  -> document
      -> chunk group summary
          -> raw chunks
```

用途：

- 让 Agent 快速知道某个来源里有什么。
- 支持按文档、网站、笔记库等来源下钻。

## 第四步：构建 Topic Tree

Topic Tree 按主题或实体组织。

第一版可以用简单策略提取 topic：

- 文档标题关键词。
- chunk 中高频名词或技术词。
- LLM 从 chunk group 中抽取 3 到 5 个主题。
- 复用现有 `UserInterest.topic` 作为候选主题。

Topic Tree 不强行做严格树，因为一个 chunk 可能属于多个主题。用 `memory_edges` 表示多对多关系更合适。

层级建议：

```text
topic:agent-memory
  -> topic-level summary
      -> related chunk group summaries
          -> raw chunks
```

用途：

- 解决 Agent 面对用户问题时不知道从哪里开始的问题。
- 让 Agent 先读主题概览，再取相关原文证据。

## 第五步：构建简化 Global Tree

Global Tree 用于跨来源时间线。

第一版只做 day/week 两层：

```text
week:2026-W23
  -> day:2026-06-07
      -> chunk group summaries
          -> raw chunks
```

用途：

- 支持“最近我关注了什么”“这周有哪些重要内容”这类问题。
- 后续可扩展到 month、quarter、project timeline。

## 第六步：实现 Tree Retriever

新增 `backend/memory/tree_retriever.py`。

检索流程：

```text
用户 query
  -> 检索 memory_nodes 摘要节点
  -> 选择相关 Source / Topic / Global 节点
  -> 沿 memory_edges 下钻到 child nodes 和 raw chunks
  -> 复用现有 reranker 对 chunk 排序
  -> 返回摘要路径 + 原始证据
```

返回结构建议：

```python
{
    "memory_path": [
        {"level": 2, "title": "...", "summary": "..."},
        {"level": 1, "title": "...", "summary": "..."},
    ],
    "chunks": [...],
}
```

这样 Editor 可以同时拿到“概览”和“证据”。

## 第七步：接入 Agent 上下文

扩展 `backend/context/assembler.py`。

上下文顺序建议：

```text
1. Agent 静态 system prompt
2. 用户长期兴趣 UserInterest
3. Memory Tree 相关摘要
4. 当前会话短期记忆
5. 下钻得到的原始 chunks
6. 当前用户 query
```

注意：

- 长期兴趣和高层摘要变化较慢，放前面，利于 prefix cache。
- 原始 chunks 和当前 query 每次变化大，放后面。
- 当前 `BaseAgent.think_and_act()` 还没有使用 `assemble_context`，需要同步接线。

## 第八步：改造回答链路

优先改 Editor 的 `answer_with_search`。

旧流程：

```text
query -> retrieve chunks -> LLM answer
```

新流程：

```text
query -> tree_retrieve summaries/chunks -> LLM answer
```

第一版可以保留回退：

- Tree Retriever 有结果：使用 Memory Tree 结果。
- Tree Retriever 无结果：回退到现有 `retrieval.retrieve()`。

## 第九步：增加评估脚本

新增或扩展 `backend/eval/eval_memory.py`。

至少验证：

- 能从 chunk 构建 L1/L2 摘要节点。
- Source Tree 能按文档下钻到原始 chunk。
- Topic Tree 能召回相关主题。
- Tree Retriever 比 flat retrieval 更容易返回高层概览。
- 空库、无 embedding、无摘要时能优雅回退。

## 第十步：分阶段上线

建议分三期：

### Phase 1：最小可用 Memory Tree

- 新增 `memory_nodes` / `memory_edges`。
- 构建 Source Tree 和 Topic Tree。
- 支持离线批处理构建。
- Tree Retriever 可返回摘要和 chunks。

### Phase 2：接入 Agent

- `Editor.answer_with_search` 使用 Tree Retriever。
- `assemble_context` 注入长期兴趣和 Memory Tree 摘要。
- 保留现有 flat retrieval 回退。

### Phase 3：增量更新和 Global Tree

- 文档入库后自动更新相关节点。
- 加入 day/week Global Tree。
- 前端 MemoryViewer 展示树状记忆。

## 第一版成功标准

- 用户问一个冷启动问题时，Agent 能先引用相关主题/来源摘要，而不是只返回零散 chunks。
- Agent 回答中能体现“概览 -> 证据”的层次。
- 旧的 `/memory/interests` 和现有检索流程不被破坏。
- 空库或构建失败时，系统仍能回退到原有检索。
