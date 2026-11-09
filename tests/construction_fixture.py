"""Minimal construction fixture: execute the real VM constructor exactly once.

Only game declaration/loading adapters are suppressed, before the test installs
its explicit neutral data/read/call hooks. No evaluator or selection is mocked.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from pyemuera import load_arguments, runtime

CONSTRUCTIONS = []
COMPOSITE_PROOFS = []
# Future full suites use the proposed entry by default. The frozen36 runner
# explicitly sets this to pyemuera.runtime; no source-shape inference is used.
EXPECTED_CLOSURE_ENTRY_MODULE = 'pyemuera.closure_entry'


def construct_vm(cls, backend, *, expected_entry_module=None):
    if cls is runtime.VM:
        expected = expected_entry_module or (
            EXPECTED_CLOSURE_ENTRY_MODULE if backend == 'closures' else 'pyemuera.runtime')
    else:
        # Custom subclasses and historical assignment fixtures are explicit
        # reference adapters, never evidence that the current entry was used.
        assert expected_entry_module is not None, 'Specify custom/frozen fixture entry'
        expected = expected_entry_module
    vm = cls.__new__(cls)
    data = SimpleNamespace(root=Path('.'), variables={}, config={})
    program = SimpleNamespace(load_errors=[])
    console = SimpleNamespace()
    with patch.object(cls, '_initialize_declarations', lambda self: None), \
         patch.object(load_arguments, 'compile_arguments', lambda self: None):
        cls.__init__(vm, program, data, console, seed=12345, expression_backend=backend)
    entry = vm.eval_node
    assert entry.__func__.__module__ == expected, ('wrong selected entry', expected)
    assert entry.__self__ is vm
    if cls is runtime.VM and backend == 'closures' and expected == 'pyemuera.closure_entry':
        from pyemuera import closure_entry
        expected_function = closure_entry.eval_node
    else:
        expected_function = cls.eval_node
    assert entry.__func__ is expected_function, 'wrong bound function identity'
    # Never execute an expression here: callers may already have installed
    # observable or raising helpers. Composite execution has a separate test.
    CONSTRUCTIONS.append((cls.__module__, backend, entry.__func__.__module__))
    return vm
