"""Per-VM cache ownership and lazy-creation contracts.

This module contains immutable descriptions and small lifecycle operations.
It does not retain VM instances, parse expressions, evaluate values, mutate
bindings, inspect files or consume RNG. Historical attribute names remain
stable for Python embedders and lightweight adapters.

An absent lazy validation cache differs from a created empty cache. Creation
still happens at the original caller's position, before validation; a failed
validation leaves that empty set but never inserts its failed key. Resource
catalog state has a separate absent/None/Location contract and is not a set.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CacheContract:
    attribute: str
    owner: str
    creator: str
    key: str
    dependencies: tuple[str, ...]
    creation: str
    failure: str


SYNTAX_CACHE_ATTRIBUTES = (
    "_expression_cache",
    "_assignment_cache",
    "_loop_cache",
)

LAZY_VALIDATION_CACHE_ATTRIBUTES = (
    "_r13_command_argument_cache",
    "_r33_character_argument_cache",
    "_parameter_argument_cache",
    "_expression_argument_type_cache",
    "_form_type_cache",
)

VM_CACHE_CONTRACTS = (
    CacheContract(
        "_expression_cache", "VM", "VM.__init__/expression_node/compile_arguments",
        "source text", ("macro expansion", "loaded expression plans"),
        "eager per-instance dict", "parse failure does not insert a node",
    ),
    CacheContract(
        "_assignment_cache", "VM", "VM.__init__/_assignment",
        "assignment source text", ("macro expansion", "assignment syntax"),
        "eager per-instance dict", "syntax failure does not insert a plan; runtime failure may retain a syntax plan",
    ),
    CacheContract(
        "_loop_cache", "VM", "VM.__init__/_execute_loop",
        "FOR source text", ("split argument syntax",),
        "eager per-instance dict", "invalid argument count does not insert; live reference/value failures may retain the tuple",
    ),
    CacheContract(
        "_r13_command_argument_cache", "VM", "command_arguments.lazy",
        "(function.uid, command, raw argument)",
        ("macros", "function declarations", "variable/CSV descriptor metadata", "command contract"),
        "absent or None becomes a per-instance set at first owned validation",
        "failed key absent; created empty set survives",
    ),
    CacheContract(
        "_r33_character_argument_cache", "VM", "command_arguments.lazy(character_terms)",
        "(function.uid, command, raw argument)",
        ("macros", "function declarations", "variable/CSV descriptor metadata", "character builder contract"),
        "absent or None becomes a per-instance set after frame/key selection",
        "failed key absent; created empty set survives",
    ),
    CacheContract(
        "_parameter_argument_cache", "VM", "parameter_arguments.lazy",
        "(function.uid, command, raw argument)",
        ("macros", "function declarations", "variable/CSV descriptor metadata"),
        "absent or None becomes a per-instance set after frame/function selection",
        "failed key absent; successful reduced plans precede key insertion",
    ),
    CacheContract(
        "_expression_argument_type_cache", "VM", "expression_arguments.validate_runtime",
        "(function.uid, function name, tuple(AST operands))",
        ("FORM macros", "function signatures", "private/global/CSV descriptor metadata", "method contract"),
        "absent or None becomes a per-instance set only on full-VM validation path",
        "failed key absent; declaration initialization does not add successful keys",
    ),
    CacheContract(
        "_form_type_cache", "VM", "formatting.validate_types",
        "(function.uid, raw FORM text)",
        ("macros", "function signatures", "private/global/CSV descriptor metadata"),
        "absent or None becomes a per-instance set only with an active frame",
        "failed key absent; validation precedes every substitution side effect",
    ),
    CacheContract(
        "_resource_catalog_checked", "VM", "resources1824.function",
        "one catalog snapshot per VM", ("game root", "resource CSV bytes", "program encoding"),
        "absent=unscanned; None=scan complete with no active declaration; Location=active declaration",
        "scan error leaves it absent; an active snapshot survives the query's Unsupported result",
    ),
)


def successful_validation_cache(vm, attribute):
    """Get/create the caller-owned set without changing validation timing.

    Do not prepopulate all caches, coerce an existing object or publish a
    successful key here. Callers retain skip gates, frame selection, validation
    ordering and key insertion. A SimpleNamespace needs no extra VM methods.
    """
    cache = getattr(vm, attribute, None)
    if cache is None:
        cache = set()
        setattr(vm, attribute, cache)
    return cache


def clear_syntax_caches(vm):
    """Clear the eager syntax dictionaries in their historical order/identity."""
    for attribute in SYNTAX_CACHE_ATTRIBUTES:
        getattr(vm, attribute).clear()


def clear_validation_caches(vm):
    """Invalidate already-created checks after an explicit metadata change.

    Keep absent and explicit-None states intact. Mutate existing sets in place
    so a caller retaining one sees its invalidation. Resource scans depend on
    root/CSV bytes, not expression macros, and remain their separate snapshot.
    """
    for attribute in LAZY_VALIDATION_CACHE_ATTRIBUTES:
        cache = getattr(vm, attribute, None)
        if cache is not None:
            cache.clear()
