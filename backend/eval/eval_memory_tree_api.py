"""验证 Memory Tree API 路由已注册。

这个脚本只做源码级检查，不启动 FastAPI。
"""

from pathlib import Path


def main() -> None:
    main_path = Path(__file__).resolve().parents[1] / "main.py"
    source = main_path.read_text(encoding="utf-8")

    required_routes = [
        '@app.get("/memory/tree")',
        '@app.get("/memory/tree/search")',
        '@app.get("/memory/tree/{node_id}")',
    ]
    for route in required_routes:
        assert route in source, f"missing route: {route}"

    assert source.index('@app.get("/memory/tree/search")') < source.index(
        '@app.get("/memory/tree/{node_id}")'
    )

    print("Memory Tree API 路由已注册")


if __name__ == "__main__":
    main()
