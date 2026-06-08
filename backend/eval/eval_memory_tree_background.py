"""验证 Memory Tree 自动更新已后台化。

这个脚本只做源码级检查，不连接数据库。
"""

import ast
from pathlib import Path


def main() -> None:
    loader_path = Path(__file__).resolve().parents[1] / "ingestion" / "loader.py"
    source = loader_path.read_text(encoding="utf-8")
    module = ast.parse(source)
    func = next(
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "load_document"
    )

    arg_names = [arg.arg for arg in func.args.args]
    assert "memory_tree_background" in arg_names

    defaults = dict(
        zip(
            arg_names[-len(func.args.defaults) :],
            func.args.defaults,
        )
    )
    default_node = defaults["memory_tree_background"]
    assert isinstance(default_node, ast.Constant)
    assert default_node.value is True

    assert "schedule_memory_tree_update" in source
    assert "asyncio.create_task" in source
    print("Memory Tree 自动更新已默认后台执行")


if __name__ == "__main__":
    main()
