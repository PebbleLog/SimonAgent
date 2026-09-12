"""基于 AST 白名单的受限数学表达式计算器。"""
import ast
import math
import operator

# 计算器面向 LLM 生成的表达式，需要同时限制输入规模和结果规模，
# 避免超长 AST 或超大幂运算占用过多 CPU / 内存。
_MAX_EXPRESSION_CHARS = 200
_MAX_AST_NODES = 60
_MAX_DEPTH = 12
_MAX_POWER = 100
_MAX_ABS_RESULT = 1e100

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
}

_FUNCTIONS = {
    "abs": (abs, 1, 1),
    "round": (round, 1, 2),
    "min": (min, 1, 10),
    "max": (max, 1, 10),
    "sqrt": (math.sqrt, 1, 1),
}


def _check_result(value: int | float) -> int | float:
    """拒绝非有限值和异常巨大的中间结果。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("计算结果不是有效数字")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("计算结果不是有限数")
    if abs(value) > _MAX_ABS_RESULT:
        raise ValueError("计算结果过大")
    return value


def _eval(node: ast.AST, depth: int = 0) -> int | float:
    """递归求值 AST 节点，遇到白名单外的语法直接抛 ValueError。"""
    if depth > _MAX_DEPTH:
        raise ValueError("表达式嵌套层级过深")

    if isinstance(node, ast.Expression):
        return _eval(node.body, depth + 1)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError(f"不支持的常量: {node.value!r}")
        return _check_result(node.value)
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval(node.left, depth + 1)
        right = _eval(node.right, depth + 1)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_POWER:
            raise ValueError(f"幂指数绝对值不能超过 {_MAX_POWER}")
        return _check_result(_BIN_OPS[type(node.op)](left, right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _check_result(_UNARY_OPS[type(node.op)](_eval(node.operand, depth + 1)))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        function = _FUNCTIONS.get(node.func.id)
        if function is None or node.keywords:
            raise ValueError(f"不支持的函数: {node.func.id}")
        callable_, min_args, max_args = function
        if not min_args <= len(node.args) <= max_args:
            raise ValueError(f"函数 {node.func.id} 的参数数量不正确")
        args = [_eval(arg, depth + 1) for arg in node.args]
        return _check_result(callable_(*args))
    raise ValueError(f"不支持的表达式语法: {ast.dump(node)}")


def calculate(expression: str) -> str:
    """求值数学表达式，返回字符串结果；任何失败都返回错误说明而不是抛出。"""
    expression = expression.strip()
    if not expression:
        return "Error: 表达式为空"
    if len(expression) > _MAX_EXPRESSION_CHARS:
        return f"Error: 表达式不能超过 {_MAX_EXPRESSION_CHARS} 个字符"

    try:
        tree = ast.parse(expression, mode="eval")
        if sum(1 for _ in ast.walk(tree)) > _MAX_AST_NODES:
            raise ValueError("表达式过于复杂")
        result = _eval(tree)
    except ZeroDivisionError:
        return f"Error: 除数为 0 -> {expression}"
    except (TypeError, ValueError, SyntaxError) as exc:
        return f"Error: 无法计算表达式 '{expression}': {exc}"
    except OverflowError:
        return f"Error: 计算结果溢出 -> {expression}"

    # 整数结果去掉 .0，输出更干净
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return f"{expression} = {result}"
