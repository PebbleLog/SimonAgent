import logging
from typing import Any

from .compactor import compact_history
from .config import (
    AGENT_MAX_OUTPUT_TOKENS,
    AGENT_MAX_STEPS,
    MODEL,
    SOUL_PATH,
    client,
    get_model,
)
from .context import ContextManager
from .memory import MEMORY
from .skill import SKILL_LOADER
from ..tools.registry import TOOLS, execute_tool


logger = logging.getLogger(__name__)
_DEFAULT_CLIENT = client
_DEFAULT_SOUL = "你是一个乐于助人的 AI 助手，使用中文回复。"
_TOOL_GUIDANCE = """【工具使用原则】
- 能直接可靠回答时，不为展示能力调用工具。
- 遇到专业工作流时，先用 load_skill 加载最相关的技能。
- 实时网络信息使用 web_search；需要核对原文时，再用 fetch_webpage。
- 分析当前项目时先用 search_workspace 定位，再用 read_workspace_file 阅读上下文。
- 精确数学计算使用 calculator。
- 工具返回 Error 时不要编造成功结果，应说明失败或选择可靠替代方案。"""


def _load_soul() -> str:
    try:
        return SOUL_PATH.read_text(encoding="utf-8").strip() or _DEFAULT_SOUL
    except OSError as exc:
        logger.warning("人设文件读取失败，使用默认人设：%s", exc)
        return _DEFAULT_SOUL


def _memory_sections() -> tuple[str, str, str]:
    snapshot = getattr(MEMORY, "snapshot", None)
    if callable(snapshot):
        state = snapshot()
        return state.long_term, state.user_profile, state.today_episode
    return MEMORY.read_memory(), MEMORY.read_user(), MEMORY.read_today_episode()


def build_system_prompt() -> str:
    """用最新人设、记忆与技能清单组装本次模型调用的系统提示词。"""
    long_term, user_profile, today_episode = _memory_sections()
    sections = (
        _load_soul(),
        _TOOL_GUIDANCE,
        f"【长期记忆 MEMORY.md】\n{long_term}",
        f"【用户画像 USER.md】\n{user_profile}",
        f"【今日情景记忆】\n{today_episode or '(今天还没有压缩出的情景记忆)'}",
        f"当前可用技能：\n{SKILL_LOADER.get_descriptions()}",
    )
    return "\n\n".join(section.strip() for section in sections)


def _resolve_model() -> str:
    return MODEL or (get_model() if client is _DEFAULT_CLIENT else "test-model")


def _stream_message(context: ContextManager, model_name: str) -> tuple[Any, bool]:
    streamed = False
    with client.messages.stream(
        model=model_name,
        max_tokens=AGENT_MAX_OUTPUT_TOKENS,
        system=build_system_prompt(),
        tools=TOOLS,
        messages=context.get_messages(),
    ) as stream:
        for delta in stream.text_stream:
            if not streamed:
                print("[Agent]: ", end="", flush=True)
                streamed = True
            print(delta, end="", flush=True)
        message = stream.get_final_message()
    if streamed:
        print("\n")
    return message, streamed


def _block_value(block: Any, field: str, default: Any = None) -> Any:
    return block.get(field, default) if isinstance(block, dict) else getattr(block, field, default)


def _execute_tool_calls(blocks: Any) -> list[dict[str, Any]]:
    results = []
    for block in blocks or ():
        if _block_value(block, "type") != "tool_use":
            continue
        executable = block
        if isinstance(block, dict):
            from types import SimpleNamespace

            executable = SimpleNamespace(name=block.get("name"), input=block.get("input"))
        results.append({
            "type": "tool_result",
            "tool_use_id": _block_value(block, "id", "missing-id"),
            "content": execute_tool(executable),
        })
    return results


def agent_turn(context: ContextManager, *, max_steps: int = AGENT_MAX_STEPS) -> None:
    """运行一轮有限步的“模型判断—工具执行—结果回填”循环。"""
    if max_steps < 1:
        raise ValueError("max_steps 必须大于 0")

    model_name = _resolve_model()
    for _ in range(max_steps):
        message, streamed = _stream_message(context, model_name)
        content = getattr(message, "content", [])
        context.add_assistant_message(content)
        MEMORY.append_history({"role": "assistant", "content": content})

        if getattr(message, "stop_reason", None) != "tool_use":
            if not streamed:
                print("[Agent]: (模型未返回文本内容)\n")
            context.replace(compact_history(context.get_messages()))
            return

        tool_results = _execute_tool_calls(content)
        if not tool_results:
            logger.warning("模型声明 tool_use，但没有提供有效工具调用")
            return
        context.add_tool_results(tool_results)
        MEMORY.append_history({"role": "user", "content": tool_results})

    notice = f"本轮已达到最大执行步数（{max_steps}），为避免循环调用工具已停止。"
    content = [{"type": "text", "text": notice}]
    context.add_assistant_message(content)
    MEMORY.append_history({"role": "assistant", "content": content})
    print(f"[Agent]: {notice}\n")
