"""核心层异常边界；具体底层异常通过 ``raise ... from`` 保留原因链。"""


class AgentError(Exception):
    """SimonAgent 可预期业务异常的基类。"""


class ConfigError(AgentError):
    """运行配置缺失或格式错误。"""


class PersistenceError(AgentError):
    """本地持久化操作失败。"""


class SessionNotFoundError(PersistenceError):
    """会话不存在、ID 不合法或会话文件无法恢复。"""


class ToolExecutionError(AgentError):
    """工具执行失败。"""


class SkillNotFoundError(AgentError):
    """请求的 Skill 不存在。"""


class MemoryStoreError(PersistenceError):
    """记忆持久化失败。"""


class AgentStepLimitError(AgentError):
    """单轮 Agent 执行超过安全步数。"""
