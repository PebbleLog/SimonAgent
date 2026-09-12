from collections.abc import Callable

from .context import ContextManager
from .exceptions import SessionNotFoundError
from .loop import agent_turn
from .memory import MEMORY
from .session import Session, SessionManager
from ..tools.trace import TRACER


_HELP = """可用命令：
  /new          创建新会话
  /list         列出所有会话
  /switch <id>  切换到指定会话（支持唯一前缀）
  /trace [n]    查看最近 n 条工具调用记录（默认 10 条）
  /help         显示本帮助
  /exit         退出（或 Ctrl+D / Ctrl+C）"""


class AgentRunner:
    """终端交互边界：路由命令、控制单轮事务并持久化成功会话。"""

    def __init__(self, session_manager: SessionManager | None = None):
        self.session_manager = session_manager or SessionManager()
        self._activate(self.session_manager.create())

    def _activate(self, session: Session) -> None:
        self.session = session
        self.context = ContextManager(session.history)

    def _cmd_new(self, _arg: str) -> None:
        self._activate(self.session_manager.create())
        print(f"[已创建新会话]: {self.session.id}")

    def _cmd_list(self, _arg: str) -> None:
        sessions = self.session_manager.list()
        if not sessions:
            print("[暂无历史会话]")
        else:
            print("所有会话（* 为当前会话）：")
            for session in sessions:
                mark = "*" if session.id == self.session.id else " "
                print(f" {mark} {session.id}  ({len(session.history)} 条消息)  {session.preview()}")
        if all(session.id != self.session.id for session in sessions):
            print(f" * {self.session.id}  (0 条消息)  (空会话，尚未保存)")

    def _cmd_switch(self, arg: str) -> None:
        if not arg:
            print("[用法]: /switch <会话id>")
            return
        try:
            session = self.session_manager.load(arg)
        except SessionNotFoundError as exc:
            print(f"[切换失败]: {exc}")
            return
        self._activate(session)
        print(f"[已切换到会话]: {session.id}  ({len(session.history)} 条消息)  {session.preview()}")

    def _cmd_trace(self, arg: str) -> None:
        try:
            limit = int(arg) if arg else 10
            if limit < 1:
                raise ValueError
        except ValueError:
            print("[用法]: /trace [正整数条数]")
            return
        entries = TRACER.recent(limit)
        if not entries:
            print("[暂无工具调用记录]")
            return
        print(f"最近 {len(entries)} 条工具调用：")
        for entry in entries:
            print(" " + TRACER.format_entry(entry))

    def _handle_command(self, user_input: str) -> bool:
        command, _, raw_arg = user_input.partition(" ")
        command, arg = command.lower(), raw_arg.strip()
        if command == "/exit":
            print("[已退出]")
            return False
        if command == "/help":
            print(_HELP)
            return True

        handlers: dict[str, Callable[[str], None]] = {
            "/new": self._cmd_new,
            "/list": self._cmd_list,
            "/switch": self._cmd_switch,
            "/trace": self._cmd_trace,
        }
        handler = handlers.get(command)
        if handler is None:
            print(f"[未知命令]: {command}（输入 /help 查看可用命令）")
        else:
            handler(arg)
        return True

    def _run_turn(self, user_input: str) -> None:
        checkpoint = len(self.context)
        user_message = {"role": "user", "content": user_input}
        self.context.add_user_message(user_input)
        MEMORY.append_history(user_message)
        try:
            agent_turn(self.context)
        except KeyboardInterrupt:
            self.context.rollback(checkpoint)
            print("\n[本轮已中断，已回滚未完成的记录]")
            return
        except Exception as exc:
            self.context.rollback(checkpoint)
            print(f"[本轮对话出错，已回滚未完成的记录]: {exc}")
            return

        try:
            self.session_manager.save(self.session)
        except Exception as exc:
            print(f"[会话保存失败，本轮记录未持久化]: {exc}")

    def run(self) -> None:
        print(f"[当前会话]: {self.session.id}（输入 /help 查看会话命令）")
        while True:
            try:
                user_input = input("你: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[已退出]")
                return
            if not user_input:
                continue
            if user_input.startswith("/"):
                if not self._handle_command(user_input):
                    return
                continue
            self._run_turn(user_input)
