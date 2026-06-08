"""验证 ingestion topic metadata 的轻量脚本。

这个脚本不连接数据库，只检查 topics 规范化和写入 metadata 的目标形状。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ingestion.topics import normalize_topics


def main() -> None:
    raw_topics = [" Agent Memory ", "RAG", "rag", "", "Memory Tree"]
    topics = normalize_topics(raw_topics)
    metadata = {
        "title": "Agent Memory 设计指南",
        "source_type": "markdown",
        "source_url": None,
        "topics": topics,
    }

    print("输入 topics:", raw_topics)
    print("规范化 topics:", topics)
    print("chunk metadata 示例:", metadata)

    assert topics == ["agent memory", "rag", "memory tree"]
    assert metadata["topics"] == topics


if __name__ == "__main__":
    main()
