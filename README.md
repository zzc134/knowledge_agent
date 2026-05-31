# Knowledge Agent — 多 Agent 协同知识管理系统

基于 4 个 Agent（Collector/Curator/Librarian/Editor）协同工作的个人知识管理与深度研究助手，支持文档处理、混合检索、长期记忆建模和 Agent 间协商通信。

## 一句话定位

**ChatGPT 直接对话解决不了**——因为需要一个持续增长的个人知识库、自动化收集、兴趣模型随时间演化、跨文档关联发现。

## 核心能力

- **文档处理管线**：HTML/Markdown/Text 解析 → 语义分块 → bge-m3 embedding（1024 维 dense 向量）
- **混合检索**：pgvector 向量检索 + tsvector 全文检索 → RRF 融合 → LLM 重排
- **记忆系统**：短期记忆（会话级）+ 长期记忆（兴趣建模 + 艾宾浩斯启发式衰减）
- **多 Agent 协同**：Collector（抓取）/ Curator（策展）/ Librarian（检索）/ Editor（回答）通过 MessageBus 协商通信
- **评估体系**：MRR / HitRate@5 / NDCG@5 检索质量评估 + Agent 回答质量评估
- **实时监控**：SSE 推送 Agent 间通信，前端可视化协商过程

## 架构概览

```
用户消息 → POST /chat
  ↓
Orchestrator 广播 → 4 个 Agent 各自判断是否参与
  ├─ Collector：抓取 URL / 保存文档 → @curator
  ├─ Curator：查重、评估质量、记录主题 → @librarian
  ├─ Librarian：混合检索知识库 → @editor + @curator
  └─ Editor：综合回答、判断信息充分性 → @user
  ↓
MessageBus → SSE → 前端实时监控面板
```

### 为什么是多 Agent 而不是单 Agent？

每个 Agent 有不同的 system prompt、不同的工具集、不同的模型路由。Librarian 专注检索策略，Editor 专注综合写作，Curator 专注内容质量判断——独立上下文避免了单 Agent 的 prompt 膨胀和视角污染。Agent 之间通过 `@agent名` 动态决定协作对象，不是固定 Workflow。

## 技术选型（每一个都有 why）

| 技术 | 为什么用它 | 为什么不用别的 |
|------|----------|-------------|
| **PostgreSQL + pgvector** | 一个数据库解决：结构化存储 + 向量检索 + 全文检索 | 不用 Milvus/ChromaDB：个人知识库数据量不需要分布式。不用 MySQL：PG 是 2026 新项目默认 |
| **bge-m3** | 原生 dense + sparse 双向量输出，中英双语最优 | 不用 OpenAI embedding：中文效果不如 bge-m3，且需要额外搭 BM25 |
| **自建 Agent 编排** | 可以解释每一行设计决策 | 不用 LangGraph：4 Agent 通信模式自定义，自建展示对协商逻辑的理解 |
| **DeepSeek API** | 兼容 OpenAI SDK，中文能力强，成本可控 | 可替换为 Claude/GPT，改 config.py 即可 |
| **FastAPI + SSE** | Python 原生 async，SSE 单向推送更轻量 | 不用 WebSocket：此场景不需要双向流 |
| **不用 Redis** | 无分布式场景，用户数据不应被当作缓存 | 单用户场景下 PG 完全够用 |

### 模型分级策略

| Agent | 核心任务 | 默认模型 | 选型理由 |
|-------|---------|---------|---------|
| Collector | 抓取网页、解析文档 | deepseek-chat | 任务简单重复，不需要强推理 |
| Curator | 内容分类、质量打分、去重 | deepseek-chat | 需要判断力但不需要深度推理 |
| Librarian | 检索策略决策、相似度判断 | deepseek-chat | 检索质量直接影响下游，值得用强模型 |
| Editor | 综合写作、问答、简报生成 | deepseek-chat | 用户直接看到输出，质量要求最高 |

配置集中在 `backend/config.py`，可按 Agent 独立切换 provider 和 model。

## 快速启动

### 1. 环境准备

```bash
conda create -n knowledge-agent python=3.12 -y
conda activate knowledge-agent
pip install -r backend/requirements.txt
```

### 2. 启动 PostgreSQL + pgvector

```bash
docker compose up -d
# PostgreSQL 运行在 localhost:5432
# 数据库: knowledge_agent / 用户: knowledge / 密码: knowledge123
```

### 3. 配置 API Key

```bash
cp backend/.env.example backend/.env
# 编辑 .env，填入 DEEPSEEK_API_KEY=sk-xxx
```

### 4. 启动后端

```bash
cd backend
uvicorn main:app --reload
# http://localhost:8000/docs 查看 Swagger API 文档
```

### 5. 启动前端

```bash
cd frontend
npm install
npm run dev
# http://localhost:3000
```

### 6. 填充种子数据

```bash
# 创建测试脚本
python -c "
import asyncio
from backend.ingestion.loader import load_document
from backend.db.database import init_db

async def seed():
    await init_db()
    await load_document(
        title='Agent Memory 设计指南',
        content='## Agent 记忆系统设计\n\nAgent 的记忆系统分为短期记忆和长期记忆两个层次...',
        source_type='markdown',
    )
    await load_document(
        title='混合检索设计',
        content='## RRF 融合算法\n\nReciprocal Rank Fusion 是混合检索的标准做法...',
        source_type='markdown',
    )
    print('种子数据已入库')

asyncio.run(seed())
"
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/chat` | POST | 用户对话，自动路由到合适的 Agent |
| `/negotiate` | POST | 多 Agent 协商，返回完整通信记录 |
| `/negotiate/stream` | GET | SSE 实时流，前端监控面板数据源 |
| `/memory/interests` | GET | 查询用户长期兴趣 |

## 项目结构

```
zzc_knowledge_agent/
├── README.md                   # 项目说明
├── docker-compose.yml          # PostgreSQL + pgvector 一键启动
├── benchmark/
│   └── compare.py              # pgvector vs ChromaDB 对比实验
├── backend/
│   ├── main.py                 # FastAPI 入口 + SSE 端点
│   ├── config.py               # 全局配置（模型路由/embedding/检索/记忆参数）
│   ├── requirements.txt
│   ├── core/
│   │   ├── llm.py              # LLM 调用封装（llm_call/llm_chat/重试）
│   │   ├── message_bus.py      # Agent 间消息通信总线
│   │   └── orchestrator.py     # 多 Agent 协商引擎
│   ├── agents/
│   │   ├── base.py             # Agent 基类（think_and_act 循环）
│   │   ├── collector.py        # Collector：抓取 URL + 入库
│   │   ├── curator.py          # Curator：查重 + 质量评估
│   │   ├── librarian.py        # Librarian：混合检索
│   │   └── editor.py           # Editor：综合回答
│   ├── ingestion/
│   │   ├── parser.py           # HTML/MD/Text 解析
│   │   ├── chunker.py          # 语义分块（段落边界 + overlap）
│   │   ├── embedder.py         # bge-m3 embedding 生成
│   │   └── loader.py           # 文档入库编排
│   ├── retrieval/
│   │   ├── hybrid_search.py    # Dense + Sparse + RRF 融合
│   │   ├── reranker.py         # LLM 重排（1-5 打分 + 理由）
│   │   └── retriever.py        # 检索编排入口
│   ├── memory/
│   │   ├── short_term.py       # 会话级短期记忆
│   │   ├── long_term.py        # 用户兴趣建模
│   │   └── decay.py            # 艾宾浩斯启发式衰减
│   ├── context/
│   │   └── assembler.py        # 上下文分层装配（prefix cache 优化）
│   ├── db/
│   │   ├── models.py           # 4 张表：documents/chunks/user_interests/agent_messages
│   │   ├── database.py         # SQLAlchemy async 连接
│   │   └── init.sql            # pgvector 扩展初始化
│   └── eval/
│       ├── eval_retrieval.py   # 检索质量：MRR/HitRate@5/NDCG@5
│       ├── eval_agent.py       # Agent 质量：来源标注率/相关性
│       ├── eval_memory.py      # 记忆系统：衰减/捕获测试
│       ├── test_queries.json   # 50 个测试查询（5 类意图）
│       └── agent_test_cases.json
└── frontend/
    ├── package.json
    └── src/
        ├── app/
        │   ├── page.tsx            # 主页面：三栏布局
        │   ├── layout.tsx
        │   └── globals.css
        ├── components/
        │   ├── AgentMonitor.tsx     # SSE 实时 Agent 通信面板
        │   ├── AgentStatusBar.tsx   # 顶部状态栏
        │   ├── SessionSidebar.tsx   # 会话侧边栏
        │   ├── DocumentUpload.tsx   # 文档拖拽上传
        │   └── MemoryViewer.tsx     # 长期记忆可视化
        └── lib/
            ├── api.ts               # 后端 API 封装
            └── storage.ts           # localStorage 会话持久化
```

## 面试话题索引

| 话题 | 能展开的内容 |
|------|-----------|
| 为什么这个场景 | 个人知识管理天然需要多步检索+持续记忆+跨源整合，ChatGPT 对话解决不了 |
| 为什么多 Agent | Agent 之间有查重协商、资源协商、矛盾标注——不是 Workflow |
| 模型分级的依据 | 按任务复杂度 × 调用频率 × 成本做工程决策，config.py 一行改模型 |
| 为什么 bge-m3 | 原生 dense+sparse 双向量，一个模型服务两路召回 |
| 为什么 pgvector | 个人知识库百万级 chunk 以下，HNSW + tsvector 完全够用，少一套基础设施 |
| 为什么自建编排 | 4 Agent 协商模式自定义，自建展示对通信逻辑的理解 |
| RRF 为什么 k=60 | 只用排名不用绝对值，天然适合异构检索结果融合 |
| 记忆系统设计 | 事实型/偏好型分类 + 4 种写入触发 + 衰减 + prefix cache 友好 |
| eval 怎么做 | 检索 MRR/NDCG + Agent 来源标注率 + 记忆衰减测试 |
