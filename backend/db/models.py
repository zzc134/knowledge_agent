import uuid
from datetime import datetime
from sqlalchemy import String, Text, Float, Integer, DateTime, ForeignKey, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector
from .database import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    chunks: Mapped[list["Chunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    dense_embedding: Mapped[list[float]] = mapped_column(Vector(1024), nullable=True)
    metadata_: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tsv: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    document: Mapped["Document"] = relationship(back_populates="chunks")


class UserInterest(Base):
    __tablename__ = "user_interests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    topic: Mapped[str] = mapped_column(String(200), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    memory_type: Mapped[str] = mapped_column(String(20), default="preference")
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    is_dormant: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)




class MemoryNode(Base):
    """Memory Tree 的摘要节点。

    原始资料仍然存在 chunks 表里，MemoryNode 只存 L1/L2/更高层的摘要。
    tree_type 用来区分三类树：
    - source: 按来源组织，例如 markdown、html、gmail
    - topic: 按主题组织，例如 topic:agent-memory
    - global: 按时间线组织，例如 day:2026-06-07
    """

    __tablename__ = "memory_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # 树类型：source / topic / global
    tree_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # 层级：L1 是最贴近原始 chunk 的摘要，L2/L3 是更高层概览
    level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # 稳定业务键，用于增量更新和去重，例如 topic:agent-memory、source:markdown、day:2026-06-07
    key: Mapped[str] = mapped_column(String(300), nullable=False, index=True)

    # 给 Agent 和前端看的短标题
    title: Mapped[str] = mapped_column(String(500), nullable=False)

    # 该节点覆盖内容的摘要文本，是 Tree Retriever 第一阶段检索的主要内容
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    # 摘要的向量，用于先检索高层记忆节点，再下钻到原始 chunk
    dense_embedding: Mapped[list[float] | None] = mapped_column(Vector(1024), nullable=True)

    # 时间范围主要给 Global Tree 使用；Source/Topic Tree 可以为空
    time_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    time_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 额外信息，例如来源类型、主题关键词、生成摘要时使用的 chunk 数量
    metadata_: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 从当前节点指向子节点或原始 chunk 的边
    child_edges: Mapped[list["MemoryEdge"]] = relationship(
        back_populates="parent_node",
        foreign_keys="MemoryEdge.parent_node_id",
        cascade="all, delete-orphan",
    )

    # 指向当前节点的上层边；Topic Tree 可能有多个父节点，所以这里保留列表
    parent_edges: Mapped[list["MemoryEdge"]] = relationship(
        back_populates="child_node",
        foreign_keys="MemoryEdge.child_node_id",
    )


class MemoryEdge(Base):
    """Memory Tree 的关系边。

    一条边可以表达两种关系：
    - node -> node: 高层摘要节点下钻到低层摘要节点
    - node -> chunk: 摘要节点下钻到原始 chunk

    child_node_id 和 chunk_id 二选一使用。
    """

    __tablename__ = "memory_edges"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))

    # 父节点：从哪个 MemoryNode 开始下钻
    parent_node_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("memory_nodes.id"),
        nullable=False,
        index=True,
    )

    # 子摘要节点：用于 node -> node 的层级关系
    child_node_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("memory_nodes.id"),
        nullable=True,
        index=True,
    )

    # 原始 chunk：用于 node -> chunk 的证据关系
    chunk_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("chunks.id"),
        nullable=True,
        index=True,
    )

    # 关系类型：contains / summarizes / references，后续可按关系类型控制下钻策略
    relation_type: Mapped[str] = mapped_column(String(30), nullable=False, default="contains")

    # 关系权重：Topic Tree 中一个 chunk 属于多个主题时，用权重表示相  关性
    weight: Mapped[float] = mapped_column(Float, default=1.0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    parent_node: Mapped[MemoryNode] = relationship(
        back_populates="child_edges",
        foreign_keys=[parent_node_id],
    )
    child_node: Mapped[MemoryNode | None] = relationship(
        back_populates="parent_edges",
        foreign_keys=[child_node_id],
    )
    chunk: Mapped[Chunk | None] = relationship()


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    from_agent: Mapped[str] = mapped_column(String(50), nullable=False)
    to_agent: Mapped[str] = mapped_column(String(50), nullable=False)
    msg_type: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    round_num: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
