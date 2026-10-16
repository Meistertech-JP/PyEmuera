"""Replay each measured population independently, including every sort call."""
import argparse,gzip,hashlib,json,sys
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--source',action='store_true');ap.add_argument('--out',type=Path,required=True);args=ap.parse_args()
engine=ROOT if args.source else ROOT/'PyEmuera.pyz';sys.path.insert(0,str(engine))
from pyemuera.collation_portable import PortableNLSBackend
from pyemuera.sort1824 import framework_list_order
p=PortableNLSBackend();rows=[]
for path in sorted((ROOT/'tests/fixtures/r49').glob('*.json.gz')):
 d=json.loads(gzip.decompress(path.read_bytes()))
 if 'oracle' not in d:continue
 o=d['oracle'];values=[bytes.fromhex(h).decode('utf-16-le','surrogatepass') for h in o['inputs_utf16le_hex']]
 bad=[];calls=[];orders=[]
 for i,r in enumerate(o['pairs']):
  actual=p.compare(values[r['left']],values[r['right']])
  if actual!=r['CompareTo_sign']:bad.append({'row':i,'expected':r['CompareTo_sign'],'actual':actual,'left':o['inputs_utf16le_hex'][r['left']],'right':o['inputs_utf16le_hex'][r['right']]})
 for plan,native in zip(d.get('arrays',[]),o['sorts'],strict=True):
  v=[values[i] for i in plan['inputs']]
  for r in native['calls']:
   if p.compare(v[r['left_original_row']],v[r['right_original_row']])!=r['comparison_sign']:calls.append({'case':plan['name'],'call':r})
  with patch('pyemuera.collation1824.compare_strings',p.compare):order=framework_list_order(v,string=True)
  if order!=native['order']:orders.append({'case':plan['name'],'actual':order,'expected':native['order']})
 row={'population':path.name,'fixture_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'pairs':len(o['pairs']),'pair_mismatches':bad,'sorts':len(o['sorts']),'recorded_call_sign_mismatches':calls,'sort_order_mismatches':orders}
 rows.append(row);print(path.name,len(bad),len(calls),len(orders),json.dumps(bad[:2]),flush=True)
report={'schema':'r49-new-framework-replay-1','engine':'source' if args.source else 'final_pyz','pyz_sha256':None if args.source else hashlib.sha256(engine.read_bytes()).hexdigest(),'populations':rows,'passed':all(not(r['pair_mismatches'] or r['recorded_call_sign_mismatches'] or r['sort_order_mismatches']) for r in rows)}
args.out.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
raise SystemExit(0 if report['passed'] else 1)
