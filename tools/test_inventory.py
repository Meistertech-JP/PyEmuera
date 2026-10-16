"""Bind a unittest run to its discovered IDs and all Python test sources.

Full identical modules containing discovered tests are accidental duplicates.
Shared helper text alone is allowed. Paths are package-relative, so a clean ZIP
extraction can reproduce the same fingerprint without reusing import caches.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
import unittest


def _cases(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _cases(item)
        else:
            yield item


def source_files(root):
    return [{'path':path.relative_to(root).as_posix(),
             'bytes':path.stat().st_size,
             'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted((root/'tests').rglob('*.py'))
            if '__pycache__' not in path.parts]


def support_files(root):
    """Bind byte fixtures and reviewed expectation overlays to the test run."""
    return [{'path':path.relative_to(root).as_posix(),
             'bytes':path.stat().st_size,
             'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in sorted((root/'tests'/'fixtures').rglob('*'))
            if path.is_file() and '__pycache__' not in path.parts]


def snapshot(root, suite):
    root=Path(root).resolve()
    ids=[]
    counts=Counter()
    for case in _cases(suite):
        ids.append(case.id())
        module=sys.modules[case.__class__.__module__]
        counts[Path(module.__file__).resolve().relative_to(root).as_posix()]+=1
    if len(ids)!=len(set(ids)):
        raise ValueError('Duplicate discovered unittest IDs')
    sources=source_files(root)
    identical=defaultdict(list)
    for entry in sources:
        if counts[entry['path']]:
            identical[entry['sha256']].append(entry['path'])
    duplicates=[paths for paths in identical.values() if len(paths)>1]
    if duplicates:
        raise ValueError('Duplicate complete test modules: '+repr(duplicates))
    value={'schema':'PyEmuera-unittest-inventory-1','tests':len(ids),
           'test_ids':ids,'files':sources,'fixture_files':support_files(root),
           'cases_by_file':dict(sorted(counts.items()))}
    value['fingerprint']=hashlib.sha256(json.dumps(value,sort_keys=True,
        ensure_ascii=True,separators=(',',':')).encode()).hexdigest()
    return value


def discover(root):
    return unittest.TestLoader().discover(str(Path(root)/'tests'))


def validate_report(root, report, suite=None):
    current=snapshot(root,discover(root) if suite is None else suite)
    if report.get('test_inventory')!=current:
        raise ValueError('Test collection differs from the tested source/ID snapshot')
    if report.get('executed_test_ids')!=current['test_ids']:
        raise ValueError('Executed tests differ from discovered tests')
    if report.get('tests')!=current['tests']:
        raise ValueError('Reported count differs from the discovered collection')
    return current
