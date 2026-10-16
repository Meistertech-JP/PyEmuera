"""Type contracts for the existing immutable tuple AST.

A typed layout makes increment fields explicit without changing construction,
identity, caching or tuple-specialized evaluation. A NamedTuple variant was
tried during development; production nodes stay exact tuples pending performance
validation. No runtime conversion or per-node wrapper allocation is performed.
"""

from typing import Any, Literal, TypeAlias


IncrementNode: TypeAlias = tuple[Literal['inc'], Any, int, bool]
