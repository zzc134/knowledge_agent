"""源码级验证 context assembler 已注入 Memory Tree 段。

这个脚本不导入后端依赖，适合在缺少数据库依赖的环境里运行。
"""

from pathlib import Path


def main() -> None:
    source = (
        Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("context", "assembler.py")
        .read_text(encoding="utf-8")
    )

    assert "## Memory Tree 相关摘要" in source
    assert "retrieve_from_memory_tree" in source
    assert "_build_memory_tree_text" in source
    assert "memory_tree_text" in source
    print("context assembler 已包含 Memory Tree 摘要段")


if __name__ == "__main__":
    main()
