"""A cached Pratt parser. No Python eval/exec and no access to host objects."""

from __future__ import annotations
from dataclasses import dataclass
from functools import lru_cache
import re
import math
from typing import Any
from .errors import EraError
from .ast_nodes import IncrementNode
from .text import quoted_end, conditional_end

MASK = (1 << 64) - 1


def i64(value: int) -> int:
    if type(value) is int and -(1 << 63) <= value < (1 << 63):
        return value
    value = int(value) & MASK
    return value - (1 << 64) if value >= (1 << 63) else value


def integer(value: Any) -> int:
    if not isinstance(value, int):
        raise EraError(f"Integer required, got {type(value).__name__}", code="E_TYPE")
    return value


def truncdiv(a: int, b: int) -> int:
    if b == 0:
        raise EraError("Division by zero", code="E_ARITH")
    if a == -(1 << 63) and b == -1:
        raise EraError("Int64 division overflow", code="E_ARITH")
    return (-1 if (a < 0) != (b < 0) else 1) * (abs(a) // abs(b))


# ERB differs from Python/C: each of these two operator groups has ONE precedence.
BP = {
    '?': 5,
    '&&': 10,
    '||': 10,
    '^^': 10,
    '!&': 10,
    '!|': 10,
    '&': 20,
    '|': 20,
    '^': 20,
    '==': 30,
    '!=': 30,
    '<': 40,
    '>': 40,
    '<=': 40,
    '>=': 40,
    '<<': 50,
    '>>': 50,
    '+': 60,
    '-': 60,
    '*': 70,
    '/': 70,
    '%': 70,
}
# LexicalAnalyzer.ReadSingleIdentifier separator set in src1824. Punctuation
# such as U+FF0F is identifier data, not the ASCII division operator.
_ID_ATOM = r"[^ \t\r\n\u3000+\-*/%=!<>|&^~?#(){}\[\],:$\\'\"@.;]+"
IDENT = re.compile(r'(?![0-9])' + _ID_ATOM + r'(?:@' + _ID_ATOM + r')?')
NUMBER = re.compile(
    r'0[xX][0-9a-fA-F]*(?:[pP][+-]?[0-9a-fA-F]*)?|0[bB][0-9]*(?:[pPeE][+-]?[0-9]*)?|[0-9]+(?:[pPeE][+-]?[0-9]*)?'
)


def _number_token(text):
    """LexicalAnalyzer.ReadInt64: digits bind before unary operators.

    Decimal significands are signed Int64 tokens; radix 2/16 tokens may use
    all 64 bits. Arithmetic wrapping belongs to operators, never decimal
    token acceptance. p/e scaling uses the source's Double/Int32 route.
    """
    base = 16 if text[:2].lower() == '0x' else 2 if text[:2].lower() == '0b' else 10
    digits = text[2:] if base != 10 else text
    split = re.search('[pP]' if base == 16 else '[pPeE]', digits)
    significand = digits[: split.start()] if split else digits
    exponent = digits[split.end() :] if split else None

    def fail(message):
        raise EraError(message, code='E_SYNTAX', diagnostic_message=message)

    def read(value):
        if base == 2 and any(c not in '01+-' for c in value):
            fail('二進法表記の中で使用できない文字が使われています')
        if not value or value in ('+', '-'):
            fail('"' + value + '"は整数値に変換できません')
        significant = value.lstrip('+-').lstrip('0')
        limit = 19 if base == 10 else 16 if base == 16 else 64
        if len(significant) > limit:
            fail('"' + value + '"は64ビット符号付き整数の範囲を超えています')
        number = int(value, base)
        if (base == 10 and not -(1 << 63) <= number < (1 << 63)) or (
            base != 10 and not 0 <= number < (1 << 64)
        ):
            fail('"' + value + '"は64ビット符号付き整数の範囲を超えています')
        return i64(number)

    value = read(significand)
    if exponent is not None:
        power = read(exponent)
        power = ((power + (1 << 31)) % (1 << 32)) - (1 << 31)
        if power:
            try:
                scaled = float(value) * math.pow(
                    2 if split[0].lower() == 'p' else 10, power
                )
            except OverflowError:
                scaled = math.inf
            if (
                not math.isfinite(scaled)
                or scaled > float((1 << 63) - 1)
                or scaled < float(-(1 << 63))
            ):
                fail('"' + text + '"は64ビット符号付整数の範囲を超えています')
            # CLR unchecked conv.i8 at the rounded positive 2^63 boundary.
            value = -(1 << 63) if scaled >= float(1 << 63) else int(scaled)
    return value


@dataclass(frozen=True)
class Token:
    kind: str
    value: Any
    pos: int


def tokenize(text: str) -> list[Token]:
    out, i = [], 0
    while i < len(text):
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if text.startswith('\\@', i):
            end = conditional_end(text, i)
            out.append(Token('FORM', text[i:end], i))
            i = end
            continue
        fmt = text.startswith('@"', i)
        if fmt:
            end = quoted_end(text, i, True)
            out.append(Token('FORM', text[i + 2 : end - 1], i))
            i = end
            continue
        if c == '"':
            start = i
            end = quoted_end(text, i)
            i += 1
            chars = []
            while i < end - 1:
                if text[i] == '\\' and i + 1 < end - 1:
                    chars.append(
                        {'n': '\n', 'r': '\r', 't': '\t', 's': ' ', 'S': '　'}.get(
                            text[i + 1], text[i + 1]
                        )
                    )
                    i += 2
                else:
                    chars.append(text[i])
                    i += 1
            i = end
            out.append(Token('STR', ''.join(chars), start))
            continue
        m = NUMBER.match(text, i)
        if m:
            s = m.group()
            i = m.end()
            out.append(Token('NUM', _number_token(s), m.start()))
            continue
        m = IDENT.match(text, i)
        if m:
            out.append(Token('ID', m.group().upper(), i))
            i = m.end()
            continue
        op = text[i : i + 2]
        if op in BP or op in ('++', '--'):
            out.append(Token(op, op, i))
            i += 2
            continue
        if c in '+-*/%&|^~!<>()?:#,' or c == ':':
            out.append(Token(c, c, i))
            i += 1
            continue
        raise EraError(
            f"Unexpected expression character {c!r} at column {i+1}: {text}",
            code="E_SYNTAX",
        )
    out.append(Token('EOF', '', len(text)))
    return out


# AST nodes are immutable tuples to make expression caching safe across runtimes.
class Parser:
    def __init__(self, text: str):
        self.tokens, self.i, self.text = tokenize(text), 0, text

    @property
    def tok(self):
        return self.tokens[self.i]

    def take(self, kind=None):
        t = self.tok
        if kind and t.kind != kind:
            raise EraError(
                f"Expected {kind}, got {t.kind} at column {t.pos+1}: {self.text}",
                code="E_SYNTAX",
            )
        self.i += 1
        return t

    def expression(self, minimum=0, allow_index=True, allow_postfix=True):
        t = self.take()
        if t.kind in ('NUM', 'STR'):
            node = ('lit', t.value)
        elif t.kind == 'FORM':
            node = ('form', t.value)
        elif t.kind in ('+', '-', '!', '~'):
            node = ('unary', t.kind, self.expression(80, allow_index))
        elif t.kind in ('++', '--'):
            target = self.expression(90, allow_index)
            if target[0] != 'var':
                raise EraError(
                    'Increment requires an integer variable', code='E_REFERENCE'
                )
            node = ('inc', target, 1 if t.kind == '++' else -1, False)
        elif t.kind == '(':
            node = self.expression()
            self.take(')')
        elif t.kind == 'ID':
            if self.tok.kind == '(':
                self.take('(')
                args = []
                if self.tok.kind != ')':
                    while True:
                        args.append(
                            ('missing',)
                            if self.tok.kind in (',', ')')
                            else self.expression()
                        )
                        if self.tok.kind != ',':
                            break
                        self.take(',')
                self.take(')')
                node = ('call', t.value, tuple(args))
            else:
                indices = []
                if allow_index:
                    while self.tok.kind == ':':
                        self.take(':')
                        if self.tok.kind in ('+', '-', '!', '~', '++', '--'):
                            raise EraError(
                                '変数の引数の読み取り中に予期しない演算子を発見しました',
                                code='E_SYNTAX',
                            )
                        # Native ReduceVariableArgument consumes one primary; the
                        # following ++/-- belongs to the completed reference.
                        indices.append(self.expression(80, False, False))
                node = ('var', t.value, tuple(indices))
        else:
            raise EraError(
                f"Expected expression at column {t.pos+1}: {self.text}", code="E_SYNTAX"
            )
        if allow_postfix and self.tok.kind in ('++', '--') and minimum <= 90:
            if node[0] != 'var':
                raise EraError(
                    'Increment requires an integer variable', code='E_REFERENCE'
                )
            op = self.take().kind
            node = ('inc', node, 1 if op == '++' else -1, True)
        while self.tok.kind in BP and BP[self.tok.kind] >= minimum:
            op = self.take().kind
            priority = BP[op]
            if op == '?':
                yes = self.expression()
                self.take('#')
                no = self.expression(priority)
                node = ('ternary', node, yes, no)
            else:
                node = ('binary', op, node, self.expression(priority + 1))
        return node


@lru_cache(maxsize=131072)
def parse(text: str):
    p = Parser(text.strip())
    ast = p.expression()
    p.take('EOF')
    return ast


@lru_cache(maxsize=131072)
def parse_case_condition(text: str):
    """CASE uses the same tokens/Pratt parser as all expressions.

    ExpressionParser.reduceCaseExpression recognizes IdentifierWord IS/TO;
    StringWord and formatted-string tokens never act as these keywords.
    """
    p = Parser(text.strip())
    if p.tok.kind == 'ID' and p.tok.value == 'IS':
        p.take()
        op = p.take()
        if op.kind not in BP or op.kind == '?':
            raise EraError('CASE IS requires a binary operator', code='E_SYNTAX')
        rhs = p.expression()
        p.take('EOF')
        return ('is', op.kind, rhs)
    left = p.expression()
    if p.tok.kind == 'ID' and p.tok.value == 'TO':
        p.take()
        right = p.expression()
        p.take('EOF')
        return ('range', left, right)
    p.take('EOF')
    return ('value', left)


def apply_binary(op: str, a, b):
    if op in ('==', '!=', '<', '>', '<=', '>='):
        if type(a) is not type(b):
            raise EraError("Cannot compare a string and an integer", code="E_TYPE")
        if op == '==':
            return int(a == b)
        if op == '!=':
            return int(a != b)
        if op == '<':
            return int(a < b)
        if op == '>':
            return int(a > b)
        if op == '<=':
            return int(a <= b)
        return int(a >= b)
    if op == '+' and isinstance(a, str) and isinstance(b, str):
        if len(a) + len(b) > 10_000_000:
            raise EraError("String size limit", code="E_LIMIT")
        return a + b
    if op == '*' and isinstance(a, str) and isinstance(b, int):
        if b < 0 or len(a) * b > 10_000_000:
            raise EraError("Invalid string repetition", code="E_LIMIT")
        return a * b
    a, b = integer(a), integer(b)
    if op == '+':
        return i64(a + b)
    if op == '-':
        return i64(a - b)
    if op == '*':
        return i64(a * b)
    if op == '/':
        return truncdiv(a, b)
    if op == '%':
        return a - truncdiv(a, b) * b
    if op == '<<':
        return i64(a << (b & 63))
    if op == '>>':
        return a >> (b & 63)
    if op == '&':
        return i64(a & b)
    if op == '|':
        return i64(a | b)
    if op == '^':
        return i64(a ^ b)
    if op == '&&':
        return int(bool(a) and bool(b))
    if op == '||':
        return int(bool(a) or bool(b))
    if op == '!&':
        return int(not (bool(a) and bool(b)))
    if op == '!|':
        return int(not (bool(a) or bool(b)))
    if op == '^^':
        return int(bool(a) != bool(b))
    raise EraError(f"Unknown operator {op}")


def evaluate(node, vm):
    kind = node[0]
    if kind == 'lit':
        return node[1]
    if kind == 'form':
        return vm.format(node[1])
    if kind == 'missing':
        return None
    if kind == 'var':
        return vm.read_node(node)
    if kind == 'inc':
        if getattr(vm, 'initializing_declarations', False):
            raise EraError(
                'Increment is not a constant initializer', code='E_DECLARATION'
            )
        increment: IncrementNode = node
        _, target, delta, postfix = increment
        ref = vm.ref_node(target)
        old = integer(ref.get())
        new = i64(old + delta)
        ref.set(new)
        return old if postfix else new
    if kind == 'call':
        return vm.call_expr(node[1], node[2])
    if kind == 'ternary':
        return evaluate(node[2] if integer(evaluate(node[1], vm)) else node[3], vm)
    if kind == 'unary':
        val = integer(evaluate(node[2], vm))
        op = node[1]
        if op == '+':
            return val
        if op == '-':
            # v24 MinusInt reads the operand again after its MinValue check.
            if val == -(1 << 63):
                vm.console.write(
                    '整数型最小値(-9223372036854775808)は-を取っても値は変化しません',
                    True,
                )
            return i64(-integer(evaluate(node[2], vm)))
        if op == '!':
            return int(not val)
        return i64(~val)
    if kind == 'binary':
        # OperatorMethod.DivIntInt/ModIntInt evaluate and validate RHS first.
        if node[1] in ('/', '%'):
            right = integer(evaluate(node[3], vm))
            if right == 0:
                raise EraError('Division by zero', code='E_ARITH')
            return apply_binary(node[1], evaluate(node[2], vm), right)
        op, a = node[1], evaluate(node[2], vm)
        if op in ('&&', '!&') and integer(a) == 0:
            return int(op == '!&')
        if op in ('||', '!|') and integer(a) != 0:
            return int(op == '||')
        return apply_binary(op, a, evaluate(node[3], vm))
    raise EraError(f"Invalid AST node: {kind}")
