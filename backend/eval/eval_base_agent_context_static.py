"""源码级验证 BaseAgent 已接入 context assembler。"""

from pathlib import Path


def main() -> None:
    source = (
        Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("agents", "base.py")
        .read_text(encoding="utf-8")
    )

    assert "_build_initial_messages" in source
    assert "assemble_context" in source
    assert "tools_description=self.tools_description()" in source
    assert "user_query=user_message" in source
    print("BaseAgent 已接入 context assembler")


if __name__ == "__main__":
    main()
