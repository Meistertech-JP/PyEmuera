"""Replay the historical r44 pure-refactor contract against its sealed bytes.

The r45 candidate is tested separately against received Framework signs and
new metadata failure injection. Historical AST/read-order equivalence applies
to the r44 named-index refactor, whose exact source is archived here.
"""
from functools import lru_cache
import hashlib
from pathlib import Path
import sys
import types


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tests/fixtures/r45_collation/collation_jamo_r44.py.txt"
SHA256 = "2fcc9a1edc94ea6a16f965b138a8b12bc34e289b501b7ca4d3647527156f41a1"


@lru_cache(maxsize=1)
def historical_r44_module():
    raw = SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SHA256:
        raise ValueError("Sealed r44 Jamo source pin differs")
    name = "_r45_historical_r44_jamo_refactor"
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(raw, "ARCHIVED_R44/pyemuera/collation_jamo.py", "exec"), module.__dict__)
    return module
