"""All r39 IDs retained; immutable oracle plus reviewed r40 semantic deltas."""
import hashlib,json,unittest
from pathlib import Path
from routing_probe_support import observe
ROOT=Path(__file__).parent/'fixtures'
CASES=json.loads((ROOT/'r39_routing_cases.json').read_text())
EXPECTED=json.loads((ROOT/'r39_routing_expected.json').read_text())
REVIEW=json.loads((ROOT/'r40_routing_reviewed_overrides.json').read_text())
assert hashlib.sha256((ROOT/'r39_routing_expected.json').read_bytes()).hexdigest()==REVIEW['baseline_sha256']
assert sum(map(len,CASES.values()))==2454
for row in REVIEW['rows']:
    assert row['verdict']=='APPROVE_INTENDED' and row['case']==CASES[row['name']][row['index']]
    for change in row['delta']:
        target=EXPECTED[row['name']][row['index']]
        for key in change['path'][:-1]:target=target[key]
        key=change['path'][-1]
        assert target[key]==change['before'],(row['name'],row['index'],change['path'])
        target[key]=change['after']
REVIEW41=json.loads((ROOT/'r41_routing_reviewed_overrides.json').read_text())
assert hashlib.sha256((ROOT/'r40_routing_reviewed_overrides.json').read_bytes()).hexdigest()==REVIEW41['parent_overrides_sha256']
for row in REVIEW41['rows']:
    assert row['verdict']=='APPROVE_INTENDED' and row['case']==CASES[row['name']][row['index']]
    for change in row['delta']:
        target=EXPECTED[row['name']][row['index']]
        for key in change['path'][:-1]:target=target[key]
        key=change['path'][-1]
        assert target[key]==change['before'],(row['name'],row['index'],change['path'])
        target[key]=change['after']
NATIVE54=json.loads((ROOT/'native54_routing_reviewed_overrides_v1.json').read_text())
assert hashlib.sha256((ROOT/'r39_routing_expected.json').read_bytes()).hexdigest()==NATIVE54['baseline_sha256']
assert hashlib.sha256((ROOT/'r41_routing_reviewed_overrides.json').read_bytes()).hexdigest()==NATIVE54['parent_overrides_sha256']
assert NATIVE54['after_raw_state']==[[1000],False,[]]
native54_after=hashlib.sha256(json.dumps([[1000],False,[]],sort_keys=True,ensure_ascii=True,default=str).encode()).hexdigest()
native54_seen=set()
for row in NATIVE54['rows']:
    key=(row['name'],row['index'])
    assert key not in native54_seen and row['case']==CASES[row['name']][row['index']]
    native54_seen.add(key)
    assert row['verdict']=='APPROVE_NATIVE_DEFAULTS_V1'
    assert [change['path'] for change in row['delta']]==[['variables','NEXTCOM'],['variables','PREVCOM']]
    for change in row['delta']:
        assert change['after']==native54_after
        target=EXPECTED[row['name']][row['index']]['variables']
        assert target[change['path'][-1]]==change['before']
        target[change['path'][-1]]=change['after']
assert native54_seen=={(name,index) for name,entries in CASES.items() for index in range(len(entries))}
class RoutingContracts(unittest.TestCase):
    pass
for name,cases in CASES.items():
    def test(self,name=name,cases=cases):
        for i,case in enumerate(cases):
            with self.subTest(case=case):self.assertEqual(observe(name,case),EXPECTED[name][i])
    setattr(RoutingContracts,'test_'+name,test)
