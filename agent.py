"""SimonAgent 的命令行入口。

请在项目父目录运行：
    python -m SimonAgent.agent

入口通过包内相对导入使用 core 层公开的接口，不关心 AgentRunner 的内部存放位置。
"""

from .core import AgentRunner


def main() -> None:
    """创建并启动一个交互式 Agent 会话。"""
    AgentRunner().run()


if __name__ == "__main__":
    main()
