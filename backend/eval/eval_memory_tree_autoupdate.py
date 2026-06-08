"""验证 load_document 已支持 Memory Tree 自动更新参数。

这个脚本只检查函数签名，不连接数据库。
"""

import ast
from pathlib import Path


def main() -> None:
    loader_path = Path(__file__).resolve().parents[1] / "ingestion" / "loader.py"
    module = ast.parse(loader_path.read_text(encoding="utf-8"))
    func = next(
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "load_document"
    )

    arg_names = [arg.arg for arg in func.args.args]
    assert "update_memory_tree" in arg_names

    defaults = dict(
        zip(
            arg_names[-len(func.args.defaults) :],
            func.args.defaults,
        )
    )
    default_node = defaults["update_memory_tree"]
    assert isinstance(default_node, ast.Constant)
    assert default_node.value is True

    print("load_document(update_memory_tree=True) 已启用")


if __name__ == "__main__":
    main()
