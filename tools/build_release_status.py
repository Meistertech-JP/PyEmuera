"""Generate current release inventory from registry and recorded test outcomes.

Writes release metadata outside the source tree, so executable hashes do not form
a cycle. Historical source audits are never reclassified by this script.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pyemuera import __version__
from pyemuera.registry import COMMAND_SPECS, FUNCTION_SPECS, SYNTAX_SPECS, fingerprint
from pyemuera.dispatcher import describe_binding
from pyemuera.builtins import describe_value_binding


def generate(reports, beta_accepted=False):
    populations = []
    for path in reports:
        data = json.loads(path.read_text(encoding='utf-8'))
        if data['version'] != __version__:
            raise ValueError('test report version differs: ' + path.name)
        if data.get('missing_baseline_ids'):
            raise ValueError('missing baseline test IDs: ' + path.name)
        counts = dict(collections.Counter(r['outcome'] for r in data['results'].values()))
        if len(data['results']) != data['tests'] or sum(counts.values()) != data['tests']:
            raise ValueError('incomplete outcome inventory: ' + path.name)
        populations.append({
            'report': path.name, 'report_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'python': data['python'], 'pyz_sha256': data['pyz_sha256'],
            'tests': data['tests'], 'outcomes': counts,
            'skips': {k: v['reason'] for k, v in data['results'].items() if v['outcome'] == 'SKIP'},
            'failures': [k for k, v in data['results'].items() if v['outcome'] in ('FAIL', 'ERROR')],
            'test_inventory_sha256': hashlib.sha256(
                ('\n'.join(sorted(data['test_ids'])) + '\n').encode()).hexdigest(),
        })
    if beta_accepted and (not populations or any(p['failures'] for p in populations)):
        raise ValueError('beta acceptance needs reviewed reports without unexplained failures')
    return {
        'schema': 'pyemuera-release-status-1', 'engine_version': __version__,
        'display_name': 'PyEmuera 3.0.0 Beta 1',
        'formal_a10_release_gate': False, 'beta_release_gate': beta_accepted,
        'full_compatibility': False, 'published': False,
        'definition_counts': {'commands': len(COMMAND_SPECS), 'functions': len(FUNCTION_SPECS),
                              'syntax': len(SYNTAX_SPECS)},
        'language_specs_sha256': fingerprint(),
        'runtime_bindings': {n: describe_binding(n) for n in COMMAND_SPECS},
        'expression_runtime_bindings': {n: describe_value_binding(n) for n in FUNCTION_SPECS},
        'test_populations': populations,
        'scope': 'Registration inventory and recorded regressions; no combined compatibility rate.',
        'acceptance_scope': 'Beta gate also requires the separate release integrity and acceptance records.',
        'historical_audits': ['SOURCE_AUDIT_1824.json', 'SOURCE_AUDIT_1824_v24.json'],
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tests', type=Path, action='append', required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--beta-accepted', action='store_true')
    a = p.parse_args()
    if a.out.resolve() == ROOT or ROOT in a.out.resolve().parents:
        p.error('--out must be outside the source tree')
    result = generate(a.tests, a.beta_accepted)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(a.out)


if __name__ == '__main__':
    main()
