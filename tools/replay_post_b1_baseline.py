"""Replay frozen r49 prefix oracle against source; output detailed JSON and summary.

Usage: python replay_post_b1_baseline.py --repo <clone> --out <new directory>
Outputs may contain lone surrogates, represented exclusively as hexadecimal units.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

PIN = '4d6b753a4c511480931862550e2e86f9e4d1476f3f7bf7424974f574dee18672'
ap = argparse.ArgumentParser()
ap.add_argument('--repo', type=Path, required=True)
ap.add_argument('--out', type=Path, required=True)
args = ap.parse_args()
if args.out.exists():
    raise SystemExit('output already exists; refusing overwrite')
root = args.repo.resolve()
sys.path.insert(0, str(root))
sys.dont_write_bytecode = True
from pyemuera.collation_portable import PortableNLSBackend, _utf16_units
from pyemuera.collation_jamo import jamo_class, consume_jamo_cluster

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

fixture = root / 'tests/fixtures/r49/prefix_alignment.json.gz'
digest = sha(fixture)
if digest != PIN:
    raise SystemExit('fixture SHA mismatch: ' + digest)
oracle = json.loads(gzip.decompress(fixture.read_bytes()))['oracle']
values = [bytes.fromhex(h).decode('utf-16-le', 'surrogatepass') for h in oracle['inputs_utf16le_hex']]
keys = [bytes.fromhex(h) for h in oracle['sort_keys_hex']]

class Traced(PortableNLSBackend):
    def __init__(self):
        super().__init__()
        self.trace = []
    def _separator_jamo_sign(self, *a):
        v = super()._separator_jamo_sign(*a); self.trace.append(['separator_jamo_sign', v]); return v
    def _leading_run_ignorable_cluster_equal(self, *a):
        v = super()._leading_run_ignorable_cluster_equal(*a); self.trace.append(['leading_run_ignorable_cluster_equal', v]); return v
    def _leading_ignorable_jamo_sign(self, *a):
        v = super()._leading_ignorable_jamo_sign(*a); self.trace.append(['leading_ignorable_jamo_sign', v]); return v
    def _make_key(self, *a, **kw):
        self.trace.append(['make_key', kw]); return super()._make_key(*a, **kw)

b = Traced()
def unit(u):
    item = {'unit': f'{u:04X}', 'script_weight': b._weight(u)[0]}
    if u in b._jamo:
        r = b._jamo[u]
        item.update(jamo_class=jamo_class(u).name, old=bool(r[0]), nearest_l=r[1], nearest_v=r[2], nearest_t=r[3], extra_weight=r[4])
    return item

def describe(s):
    us = list(_utf16_units(s)); result = [unit(u) for u in us]
    clusters=[]; i=0
    while i < len(us):
        if us[i] in b._jamo:
            elements, n = consume_jamo_cluster(us, i, b._jamo, b._weight)
            clusters.append({'start_utf16':i, 'length':n, 'units':[f'{x:04X}' for x in us[i:i+n]], 'elements_hex':[x.hex() for x in elements]})
            i += n
        else: i += 1
    prefix=[]
    for u in us:
        if b._weight(u)[0] not in (0,6): break
        prefix.append(unit(u))
    return {'utf16le_hex':s.encode('utf-16-le','surrogatepass').hex(), 'units':result, 'leading_ignorable_or_punctuation':prefix, 'clusters':clusters}

details=[]; counts=Counter(); modern=Counter(); api_disagree=0
for index, row in enumerate(oracle['pairs']):
    left, right = values[row['left']], values[row['right']]
    actual=b.compare(left,right); expected=row['CompareTo_sign']
    first=next((ord(c) for c in left if ord(c) in b._jamo),None)
    is_modern=first is not None and 0x1100 <= first <= 0x1112
    counts['pairs']+=1; counts['match' if actual==expected else 'mismatch']+=1
    if is_modern: modern['pairs']+=1; modern['match' if actual==expected else 'mismatch']+=1
    if any(row.get(k,expected)!=expected for k in ('CompareInfo_None_sign','NLS_sign')): api_disagree+=1
    if actual == expected: continue
    lu=list(_utf16_units(left)); ru=list(_utf16_units(right)); pos=0
    while pos < min(len(lu),len(ru)) and lu[pos]==ru[pos]: pos+=1
    b.trace=[]; repeated=b.compare(left,right); trace=b.trace[:]
    assert repeated==actual
    lk,rk=keys[row['left']],keys[row['right']]; sortsign=(lk>rk)-(lk<rk)
    ld,rd=describe(left),describe(right)
    labels=[]
    for desc in (ld,rd):
        units=desc['units']; classes=[u.get('jamo_class') for u in units]
        if any(u.get('old') and u.get('jamo_class')=='LEADING' for u in units): labels.append('old_leading')
        for c in desc['clusters']:
            if any(u in ('115F','1160') for u in c['units']): labels.append('filler_cluster' if c['length']>1 else 'filler_single')
        if any(u['script_weight'] in (0,6) for u in units): labels.append('ignorable_or_punctuation')
        for i in range(len(units)-1):
            a1=units[i].get('jamo_class'); a2=units[i+1].get('jamo_class')
            if a1 and a2 and {'LEADING':0,'VOWEL':1,'TRAILING':2}[a2] <= {'LEADING':0,'VOWEL':1,'TRAILING':2}[a1]: labels.append('class_repeat_or_reversal')
        if len(desc['clusters'])>1: labels.append('multiple_clusters')
        if any(u['script_weight'] not in (0,6) and 'jamo_class' not in u for u in units): labels.append('ordinary_non_jamo')
    labels.append('shared_raw_jamo_prefix' if any(x in b._jamo for x in lu[:pos]) else 'no_shared_raw_jamo_prefix')
    if sortsign!=expected: labels.append('framework_sortkey_vs_direct_diff')
    labels=sorted(set(labels))
    details.append({'oracle_file':'tests/fixtures/r49/prefix_alignment.json.gz','oracle_sha256':digest,'pair_index_zero_based':index,'pair_number_one_based':index+1,'group':row['group'],'left_index':row['left'],'right_index':row['right'],'expected_compareto':expected,'compareinfo':row['CompareInfo_None_sign'],'nls':row.get('NLS_sign'),'portable':actual,'framework_sortkey_sign_bytewise':sortsign,'first_different_utf16_index_zero_based':pos,'first_different_left':unit(lu[pos]) if pos<len(lu) else None,'first_different_right':unit(ru[pos]) if pos<len(ru) else None,'left':ld,'right':rd,'trace':trace,'labels':labels})

label_counts=Counter(label for d in details for label in d['labels'])
branches=Counter(next((x[0] for x in d['trace'] if (x[0]=='separator_jamo_sign' and x[1] is not None) or (x[0]=='leading_run_ignorable_cluster_equal' and x[1]) or (x[0]=='leading_ignorable_jamo_sign' and x[1] is not None)),'key_fallback') for d in details)
sources=['pyemuera/collation_portable.py','pyemuera/collation_jamo.py','pyemuera/resources/nls_ja_windows10.json','pyemuera/resources/nls_ja_windows10.bin.zlib']
summary={'fixture_sha256':digest,'git_head':subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip(),'python':sys.version,'platform':platform.platform(),'source_sha256':{s:sha(root/s) for s in sources},'oracle_metadata':{k:v for k,v in oracle.items() if k not in ('inputs_utf16le_hex','sort_keys_hex','pairs','sorts')},'counts':dict(counts),'modern_left':dict(modern),'api_sign_disagreements':api_disagree,'labels_overlap':dict(label_counts),'branches':dict(branches),'examples_by_label':{label:next(d['pair_index_zero_based'] for d in details if label in d['labels']) for label in label_counts}}
args.out.mkdir(parents=True,exist_ok=False)
(args.out/'mismatches.json').write_text(json.dumps(details,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
(args.out/'summary.json').write_text(json.dumps(summary,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=True,indent=2))
