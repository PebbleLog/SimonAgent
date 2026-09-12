"""测试公共工具：伪造流式客户端与消息对象（离线，不触达真实 API）。"""
from types import SimpleNamespace


def text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def tool_use_block(name: str, tool_input: dict, block_id: str = "t1"):
    return SimpleNamespace(type="tool_use", id=block_id, name=name, input=tool_input)


def fake_message(blocks: list, stop_reason: str):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class FakeStream:
    """模拟 anthropic messages.stream() 的上下文管理器。"""

    def __init__(self, message, deltas=("测试回复",)):
        self._message = message
        self._deltas = deltas

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    @property
    def text_stream(self):
        return iter(self._deltas)

    def get_final_message(self):
        return self._message


class FakeMessages:
    """按队列依次返回预定的流式响应。"""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls = 0

    def stream(self, **kwargs):
        message = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        deltas = tuple(b.text for b in message.content if b.type == "text")
        return FakeStream(message, deltas or ("(无文本)",))


class FakeClient:
    def __init__(self, responses: list):
        self.messages = FakeMessages(responses)


class MemoryStub:
    """屏蔽记忆落盘副作用，避免测试污染真实记忆文件。"""

    def append_history(self, message):
        pass

    def read_memory(self):
        return ""

    def read_user(self):
        return ""

    def read_today_episode(self):
        return ""
