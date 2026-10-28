"""Inventory public comparison and trace pairs without opening sealed holdouts.

Writes a reproducible index and audit manifest; never generates or opens holdouts.
Unsupported candidate containers remain visible in the audit. See the separate
record for coverage limits and proposed generation protocol.
"""
import argparse
import ast
import gzip
import hashlib
import itertools
import json
import os
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RECORDS = ROOT.parent / 'post-b1-jamo-records' / 'oracle'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def valid_hex(s):
    if not isinstance(s, str) or len(s) % 4 or re.fullmatch(r'[0-9a-fA-F]*', s) is None:
        raise ValueError('invalid UTF-16LE hex length/type')
    bytes.fromhex(s)
    return s.lower()

def enc(s):
    return s.encode('utf-16le', 'surrogatepass').hex()

def pair(a, b):
    return tuple(sorted((valid_hex(a), valid_hex(b))))

def integer(v):
    return isinstance(v, int) and not isinstance(v, bool)

def at(values, i):
    if not integer(i) or i < 0 or i >= len(values):
        raise ValueError('index outside inputs')
    return values[i]

def files(base):
    # Prune before directory enumeration or file opening. All holdouts, not
    # just indexed-v2, are excluded to avoid accidental disclosure.
    for directory, dirs, names in os.walk(base, followlinks=False):
        dirs[:] = sorted(x for x in dirs if 'holdout' not in x.lower() and not (Path(directory)/x).is_symlink())
        for name in sorted(names):
            p = Path(directory)/name
            if 'holdout' not in name.lower() and not p.is_symlink():
                yield p

def label(p):
    return p.relative_to(ROOT.parent).as_posix()

class Inventory:
    def __init__(self):
        self.keys = set()
        self.sources = []
        self.unresolved = []
        self.counts = Counter()

    def add(self, a, b, kind):
        self.keys.add(pair(a, b))
        self.counts[kind] += 1

    def problem(self, path, loc, reason, count=None):
        self.unresolved.append({'path': label(path), 'location': loc, 'reason': reason, 'rows': count})

    def scan(self, path, obj):
        # Companion sources are matched explicitly, never by a guessed index.
        if path.name == 'hangul-framework.json':
            companion = path.parent/'hangul_inputs.txt'
            vals = companion.read_text(encoding='utf-8-sig').splitlines()
            for row in obj['pairs']:
                self.add(at(vals,row['l']), at(vals,row['r']), 'hangul_indexed')
            return
        plan = None
        if path.name == 'sort_modern.json.gz' and path.parent.name == 'r47':
            plan = json.loads(gzip.decompress((path.parent/'sort_plan.json.gz').read_bytes()))
            plan = {x['name']: x['inputs_utf16le_hex'] for x in plan}
        def trace(rows, values, loc, lfield, rfield):
            for n, row in enumerate(rows):
                try:
                    self.add(at(values, row[lfield]), at(values, row[rfield]), 'sort_calls')
                except (KeyError, TypeError, ValueError, IndexError) as e:
                    self.problem(path, loc+'/'+str(n), 'unresolved sort call: '+str(e), 1)
        def walk(x, loc='', parent=None):
            if isinstance(x, list):
                for i, v in enumerate(x):
                    if isinstance(v, (dict,list)): walk(v, loc+'/'+str(i), parent)
                return
            if not isinstance(x, dict): return
            values = x.get('inputs_utf16le_hex')
            for field in ('pairs','comparisons','cases'):
                rows = x.get(field)
                if not isinstance(rows,list): continue
                for i,row in enumerate(rows):
                    try:
                        a=b=None
                        if isinstance(row,dict) and 'left_utf16le_hex' in row and 'right_utf16le_hex' in row:
                            a,b=row['left_utf16le_hex'],row['right_utf16le_hex']
                        elif isinstance(row,dict) and isinstance(values,list) and ('left_index' in row or 'left' in row):
                            a,b=at(values,row.get('left_index',row.get('left'))),at(values,row.get('right_index',row.get('right')))
                        elif isinstance(row,(list,tuple)) and len(row)>=2 and isinstance(values,list):
                            a,b=at(values,row[0]),at(values,row[1])
                        elif isinstance(row,dict) and isinstance(row.get('left'),str) and isinstance(row.get('right'),str):
                            a,b=enc(row['left']),enc(row['right'])
                        if a is not None and b is not None: self.add(a,b,'explicit_pairs')
                        elif field in ('pairs','comparisons'):
                            self.problem(path,loc+'/'+field+'/'+str(i),'unsupported pair row',1)
                    except (KeyError,TypeError,ValueError,IndexError) as e:
                        self.problem(path,loc+'/'+field+'/'+str(i),'invalid pair: '+str(e),1)
            sorts = x.get('sorts')
            if isinstance(sorts,list):
                arrays = parent.get('arrays') if isinstance(parent,dict) else None
                byname = {a['name']:a for a in arrays if isinstance(a,dict) and 'name' in a} if isinstance(arrays,list) else {}
                for i,s in enumerate(sorts):
                    calls=s.get('calls') if isinstance(s,dict) else None
                    if not isinstance(calls,list) or not calls: continue
                    a=byname.get(s.get('name'))
                    try:
                        if not a or not isinstance(values,list): raise ValueError('missing array plan or input table')
                        ordered=[at(values,j) for j in a['inputs']]
                        trace(calls,ordered,loc+'/sorts/'+str(i)+'/calls','left_original_row','right_original_row')
                    except (KeyError,TypeError,ValueError) as e: self.problem(path,loc+'/sorts/'+str(i),str(e),len(calls))
            cases=x.get('cases')
            if isinstance(cases,list):
                for i,c in enumerate(cases):
                    if not isinstance(c,dict) or not isinstance(c.get('calls'),list) or not c['calls']: continue
                    v=plan.get(c.get('name')) if plan is not None else c.get('inputs_utf16le_hex')
                    if not isinstance(v,list): self.problem(path,loc+'/cases/'+str(i),'sort calls without input plan',len(c['calls'])); continue
                    if plan is not None: trace(c['calls'],v,loc+'/cases/'+str(i)+'/calls','left_original_row','right_original_row')
                    else:
                        original=c.get('original_index')
                        if not isinstance(original,list) or len(original)!=len(v) or len(set(original))!=len(original):
                            self.problem(path,loc+'/cases/'+str(i),'invalid original_index mapping',len(c['calls'])); continue
                        mapping=dict(zip(original,v))
                        traces=[('calls',c['calls'])]
                        for sub in ('list_comparison','direct_string'):
                            if isinstance(c.get(sub),dict) and isinstance(c[sub].get('calls'),list): traces.append((sub+'/calls',c[sub]['calls']))
                        for sub,calls in traces:
                            for n,call in enumerate(calls):
                                try:
                                    if 'left_utf16le_hex' in call and 'right_utf16le_hex' in call:
                                        left,right=call['left_utf16le_hex'],call['right_utf16le_hex']
                                        if left is None or right is None: raise ValueError('null operand: not a UTF-16 string pair')
                                        self.add(left,right,'sort_calls')
                                    else:
                                        left,right=call['left_original_index'],call['right_original_index']
                                        if left == -1 or right == -1: raise ValueError('null operand: not a UTF-16 string pair')
                                        self.add(mapping[left],mapping[right],'sort_calls')
                                except (KeyError,TypeError,ValueError) as e: self.problem(path,loc+'/cases/'+str(i)+'/'+sub+'/'+str(n),str(e),1)
            for k,v in x.items():
                if isinstance(v,dict): walk(v,loc+'/'+k,x)
                elif isinstance(v,list) and k not in ('pairs','comparisons','cases','sorts','calls','arrays'):
                    for i,item in enumerate(v):
                        if isinstance(item,dict): walk(item,loc+'/'+k+'/'+str(i),x)
        walk(obj)

    def indexed_tsv(self, plan, inputs):
        values=inputs.read_text(encoding='utf-8-sig').splitlines()
        for n,line in enumerate(plan.read_text(encoding='utf-8-sig').splitlines()):
            try:
                parts=line.split('\t'); a,b=map(int,parts[:2]); self.add(at(values,a),at(values,b),'indexed_tsv')
            except (ValueError,IndexError) as e: self.problem(plan,'line/'+str(n+1),str(e),1)

    def array_superset(self, values):
        # All within-array pairs are exclusions, not observed comparison calls.
        values = [valid_hex(value) for value in values]
        for a, b in itertools.combinations_with_replacement(values, 2):
            self.add(a, b, 'conservative_array_pairs')

    def sort_plan_superset(self, plan, inputs):
        values = inputs.read_text(encoding='utf-8-sig').splitlines()
        lines = plan.read_text(encoding='utf-8-sig').splitlines()
        if not lines:
            raise ValueError('empty sort plan')
        groups = []
        for line in lines:
            fields = line.split('\t')
            if len(fields) != 2 or not fields[0] or not fields[1]:
                raise ValueError('invalid sort plan row')
            groups.append([valid_hex(at(values, int(i))) for i in fields[1].split(',')])
        for group in groups:
            self.array_superset(group)

    def native_six_superset(self, obj):
        if (not isinstance(obj, dict) or obj.get('schema') != 'r50-arraysort-received-native-six-v1'
                or not isinstance(obj.get('cases'), list) or len(obj['cases']) != 6):
            raise ValueError('unexpected native-six schema or case count')
        groups = []
        for case in obj['cases']:
            vals = case['input_utf16le_hex']
            if not isinstance(vals, list) or not integer(case['count']) or len(vals) != case['count']:
                raise ValueError('native-six input count mismatch')
            if vals != [enc(s) for s in case['input_values']]:
                raise ValueError('native-six input mapping mismatch')
            groups.append([valid_hex(v) for v in vals])
        for group in groups:
            self.array_superset(group)

    def native_plan_superset(self, obj):
        if not isinstance(obj, dict):
            raise ValueError('invalid native plan')
        cases = obj['cases']
        if not isinstance(cases, list) or not cases:
            raise ValueError('missing native plan cases')
        groups = []
        for case in cases:
            values = case['input']
            if not isinstance(values, list):
                raise ValueError('invalid native plan input')
            if values and all(integer(v) for v in values):
                continue  # Numeric-only cases are not string comparisons.
            if not all(isinstance(v, str) for v in values):
                raise ValueError('mixed or unsupported native plan input')
            # Include the whole array, even sentinels outside the sort range.
            groups.append([enc(v) for v in values])
        for group in groups:
            self.array_superset(group)

    def reviewed_test_pair(self, path):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        expected = ('\u115f\u11a8', '\u11a8')
        matches = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == 'test_placeholder_shape_does_not_invent_boundary_order':
                for call in ast.walk(node):
                    if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                            and call.func.attr == 'compare' and len(call.args) == 2
                            and all(isinstance(arg, ast.Constant) and isinstance(arg.value, str) for arg in call.args)):
                        matches.append(tuple(arg.value for arg in call.args))
        if matches != [expected]:
            raise ValueError('reviewed test comparison changed or is ambiguous')
        self.add(enc(expected[0]), enc(expected[1]), 'reviewed_test_pairs')

    def extra_public_sources(self):
        # Require the discovered non-symlink source entries, and recheck hashes
        # before opening the selected sources a second time.
        discovered = {entry['path']: entry for entry in self.sources}
        def checked(path):
            entry = discovered.get(label(path))
            if entry is None or path.is_symlink() or digest(path.read_bytes()) != entry['sha256']:
                raise ValueError('missing, changed or excluded source: '+label(path))
            return path
        root = ROOT/'tests'/'fixtures'
        plans = [('r43_collation','hangul_inputs.txt','windows_jamo_sort_orders.tsv'),
                 ('r44_collation_boundaries','inputs_utf16hex.txt','sort_orders.tsv'),
                 ('r45_collation/extra_windows','inputs_utf16hex.txt','sort_orders.tsv')]
        for folder, ins, plan in plans:
            p = root/folder/plan
            try:
                self.sort_plan_superset(checked(p), checked(root/folder/ins))
            except (OSError, UnicodeError, ValueError, TypeError, KeyError) as e:
                self.problem(p, '/', 'conservative sort plan: '+str(e))
        for p, handler in [(root/'r50/arraysort-native-six.json', self.native_six_superset),
                           (ROOT/'verification/r50/native-arraysort/plans.json', self.native_plan_superset)]:
            try:
                handler(json.loads(checked(p).read_text(encoding='utf-8-sig')))
            except (OSError, UnicodeError, ValueError, TypeError, KeyError) as e:
                self.problem(p, '/', 'conservative array source: '+str(e))
        p = ROOT/'tests/test_r47_compatibility.py'
        try:
            if p.is_symlink() or not p.is_file():
                raise ValueError('reviewed test source missing or symlink')
            raw = p.read_bytes()
            self.sources.append({'path':label(p), 'sha256':digest(raw), 'bytes':len(raw), 'status':'reviewed test source'})
            self.reviewed_test_pair(p)
            if digest(p.read_bytes()) != digest(raw):
                raise ValueError('reviewed test source changed')
        except (OSError, UnicodeError, ValueError, SyntaxError) as e:
            self.problem(p, '/', 'reviewed test pair: '+str(e))

    def build(self, include_local_records=False):
        # A public checkout must not depend on a private sibling directory.
        # Prior local records can be included explicitly before making new sets.
        roots=[ROOT/'tests'/'fixtures',ROOT/'verification']
        if include_local_records:
            roots.append(RECORDS)
        for base in roots:
            if not base.is_dir():
                self.unresolved.append({'path':str(base),'reason':'root missing'}); continue
            for p in files(base):
                raw=p.read_bytes(); entry={'path':label(p),'sha256':digest(raw),'bytes':len(raw),'status':'non-json unclassified'}
                self.sources.append(entry)
                if not (p.name.endswith('.json') or p.name.endswith('.json.gz')): continue
                try:
                    obj=json.loads((gzip.decompress(raw) if p.suffix=='.gz' else raw).decode('utf-8-sig'))
                    before=dict(self.counts); self.scan(p,obj)
                    entry['status']='json scanned'; entry['extracted']={k:self.counts[k]-before.get(k,0) for k in self.counts if self.counts[k]-before.get(k,0)}
                except (ValueError,UnicodeError,OSError,KeyError,TypeError) as e:
                    entry['status']='json failed'; self.problem(p,'/',str(e))
        root=ROOT/'tests'/'fixtures'
        for directory,ins,plans in [('r43_collation','windows_unseen_inputs_utf16hex.txt','windows_unseen_pairs.tsv'),('r44_collation_boundaries','inputs_utf16hex.txt','pairs.tsv'),('r45_collation/extra_windows','inputs_utf16hex.txt','pairs.tsv'),('r45_collation/sortkey_neighbors','inputs_utf16hex.txt','pairs.tsv')]:
            try: self.indexed_tsv(root/directory/plans,root/directory/ins)
            except (OSError,ValueError) as e: self.problem(root/directory/plans,'/',str(e))
        self.extra_public_sources()
        return self

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--include-local-records', action='store_true',
                        help='also index the optional sibling post-b1-jamo-records/oracle directory')
    args=parser.parse_args()
    out=args.output.resolve()
    if out.exists(): raise SystemExit('output exists; refusing overwrite')
    # Avoid recursively ingesting the output, and never write into a holdout.
    if 'holdout' in str(out).lower() or any(out == b or b in out.parents for b in (ROOT/'tests'/'fixtures',ROOT/'verification',RECORDS)):
        raise SystemExit('unsafe output location')
    inv=Inventory().build(include_local_records=args.include_local_records)
    out.mkdir(parents=True)
    index=(''.join(a+'\t'+b+'\n' for a,b in sorted(inv.keys))).encode('ascii')
    (out/'pairs.tsv').write_bytes(index)
    roots=[ROOT/'tests'/'fixtures',ROOT/'verification'] + ([RECORDS] if args.include_local_records else [])
    report={'schema':'post-b1-pairs-inventory-v1','tool_sha256':digest(Path(__file__).read_bytes()),'roots':[label(root) for root in roots],'excluded':'all paths containing holdout, including indexed-v2 sealed holdout','scope':'recognized schemas, selected conservative public array supersets and one reviewed test pair; not exhaustive','unique_undirected_pairs':len(inv.keys),'row_counts':dict(inv.counts),'index_sha256':digest(index),'sources':inv.sources,'unresolved':inv.unresolved}
    (out/'inventory.json').write_text(json.dumps(report,ensure_ascii=True,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('unique_undirected_pairs','row_counts','index_sha256')})); print('unresolved:',len(inv.unresolved),'files:',len(inv.sources))

if __name__=='__main__': main()
