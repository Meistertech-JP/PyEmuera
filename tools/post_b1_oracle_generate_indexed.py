"""Generate a reproducible Framework oracle from the extended pair index.

The final holdout is sealed after measurement and must not be used for tuning.
Existing directories are never overwritten. See --help for required arguments.
"""
import argparse
import collections
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
from pathlib import Path

import post_b1_pairs_inventory as inventory

ROOT = Path(__file__).resolve().parents[1]

def sha(data):
    return hashlib.sha256(data).hexdigest()

def filehash(path):
    return sha(path.read_bytes())

def dump(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True)+'\n').encode('utf-8'))

def index_bytes(keys):
    return ''.join(a+'\t'+b+'\n' for a,b in sorted(keys)).encode('ascii')

def read_index(raw):
    keys = set()
    for line in raw.decode('ascii').splitlines():
        fields=line.split('\t')
        if len(fields)!=2 or inventory.pair(*fields)!=tuple(fields):
            raise ValueError('invalid canonical index row')
        if tuple(fields) in keys: raise ValueError('duplicate index row')
        keys.add(tuple(fields))
    if raw != index_bytes(keys): raise ValueError('index is not sorted/canonical')
    return keys

def generate(seed, count, existing, other, max_attempts):
    rng = random.Random(seed)
    old = [chr(x) for x in list(range(0x1113,0x115f))+list(range(0xa960,0xa97d))]
    modern = [chr(x) for x in range(0x1100,0x1113)]
    vowels = [chr(x) for x in range(0x1161,0x1176)]
    tails = [chr(x) for x in range(0x11a8,0x11c3)]
    fillers=['\u115f','\u1160']
    seps=['','-','\u00ad','\u0000','、','A','日']
    prefixes=['','a','日本','-','\u00ad']
    suffixes=['','z','語','0','\u115f','\u1160']
    result=[]; keys=set(); rejects=collections.Counter(); attempts=0
    while len(result)<count:
        attempts+=1
        if attempts>max_attempts: raise RuntimeError('candidate attempt limit exceeded')
        mode=len(result)%8
        pre,post=rng.choice(prefixes),rng.choice(suffixes)
        l,v,t=rng.choice(old),rng.choice(vowels),rng.choice(tails)
        l2,v2=rng.choice(old+modern),rng.choice(vowels)
        sep=rng.choice(seps)
        variants=[(l+v+t,l2+v+t),(l+v+t,l+v2+t),
                  (l+sep+v+t,l+v+sep+t),(l+rng.choice(fillers)+v,l+v),
                  (rng.choice(fillers)+l+v,l+v+rng.choice(fillers)),
                  (l+l2+v+t,l+v+l2+t),(l+v+t+sep+l2,l+v+sep+t+l2),
                  (l+v+'日'+t,l+v2+'日'+t)]
        a,b=(pre+x+post for x in variants[mode])
        key=inventory.pair(inventory.enc(a),inventory.enc(b))
        if a==b: rejects['identical']+=1; continue
        if key in existing: rejects['existing']+=1; continue
        if key in other: rejects['other_population']+=1; continue
        if key in keys: rejects['same_population']+=1; continue
        keys.add(key); result.append((a,b))
    # Explicit, independently recomputed invariants (not only rejection logic).
    verified=[inventory.pair(inventory.enc(a),inventory.enc(b)) for a,b in result]
    if len(set(verified))!=count or set(verified)&existing or set(verified)&other:
        raise RuntimeError('pair uniqueness/overlap verification failed')
    return result,set(verified),{'attempts':attempts,'rejected':dict(rejects),
        'unique_undirected_pairs':len(set(verified)),'existing_overlap':len(set(verified)&existing),
        'other_population_overlap':len(set(verified)&other)}

def population(folder, name, seed, count, existing, other, exe, max_attempts):
    folder.mkdir()
    pairs,keys,check=generate(seed,count,existing,other,max_attempts)
    values=list(dict.fromkeys(x for row in pairs for x in row)); ids={v:i for i,v in enumerate(values)}
    inputs=''.join(inventory.enc(v)+'\n' for v in values).encode('ascii')
    directions=[(ids[a],ids[b]) for a,b in pairs for a,b in ((a,b),(b,a))]
    lines=''.join('generated\t%d\t%d\n'%p for p in directions).encode('ascii')
    (folder/'inputs.txt').write_bytes(inputs); (folder/'pairs.tsv').write_bytes(lines)
    (folder/'arrays.json').write_bytes(b'[]\n')
    run=subprocess.run([str(exe),str(folder/'inputs.txt'),str(folder/'pairs.tsv'),str(folder/'arrays.json'),str(folder/'oracle.json')],capture_output=True,text=True,encoding='utf-8',errors='replace')
    if run.returncode: raise RuntimeError('Framework probe failed: '+run.stderr)
    raw=(folder/'oracle.json').read_bytes(); result=json.loads(raw.decode('utf-8-sig'))
    rows=result['pairs']; observed=[(r['left'],r['right']) for r in rows]
    if result['inputs_utf16le_hex']!=inputs.decode('ascii').splitlines() or observed!=directions or len(result['sort_keys_hex'])!=len(values):
        raise RuntimeError('probe result does not match input plan')
    if any(r.get(k) not in (-1,0,1) for r in rows for k in ('CompareTo_sign','CompareInfo_None_sign','NLS_sign')):
        raise RuntimeError('invalid comparison sign')
    c=collections.Counter(observed)
    if len(c)!=2*count or any(c[(b,a)]!=1 or n!=1 for (a,b),n in c.items()):
        raise RuntimeError('reverse direction validation failed')
    environment={k:v for k,v in result.items() if k not in ('inputs_utf16le_hex','sort_keys_hex','pairs','sorts')}
    files={p.name:filehash(p) for p in (folder/'inputs.txt',folder/'pairs.tsv',folder/'arrays.json',folder/'oracle.json')}
    report={'name':name,'seed':seed,'directed_pairs':len(rows),'unique_inputs':len(values),
            'checks':check,'reverse_directions_exactly_once':True,'file_sha256':files,
            'framework_environment':environment,'probe_stdout':run.stdout.strip()}
    dump(folder/'manifest.json',report)
    report['manifest_sha256']=filehash(folder/'manifest.json')
    # The seal is a procedural boundary and read-only hint, not cryptographic access control.
    if name=='final_holdout':
        dump(folder/'SEALED.json',{'state':'SEALED','rule':'No tuning, result exploration or reading after sealing','manifest_sha256':report['manifest_sha256']})
        for p in (folder/'inputs.txt',folder/'pairs.tsv',folder/'arrays.json',folder/'oracle.json',folder/'manifest.json',folder/'SEALED.json'):
            os.chmod(p,0o444)
    return keys,report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path,help='new output directory, never overwritten')
    parser.add_argument('--development-seed',required=True,type=int)
    parser.add_argument('--holdout-seed',required=True,type=int)
    parser.add_argument('--count',type=int,default=1500,help='unordered pairs per population')
    parser.add_argument('--max-attempts',type=int,default=1000000)
    parser.add_argument('--csc',required=True,type=Path,help='Framework csc.exe')
    parser.add_argument('--probe-source',type=Path,default=ROOT/'tools/post_b1_oracle_probe.cs')
    parser.add_argument('--index',type=Path,help='optional frozen pairs.tsv from previous run')
    parser.add_argument('--inventory-manifest',type=Path,help='required with --index; frozen inventory.json')
    parser.add_argument('--include-local-records',action='store_true',help='also index optional local records when constructing a new index')
    args=parser.parse_args()
    if args.development_seed==args.holdout_seed or args.count<=0 or args.max_attempts<args.count:
        parser.error('seeds must differ, count positive and attempts >= count')
    if bool(args.index)!=bool(args.inventory_manifest): parser.error('--index and --inventory-manifest must be supplied together')
    if args.index and args.include_local_records: parser.error('--include-local-records cannot be combined with a frozen index')
    out=args.output.resolve(); csc=args.csc.resolve(); probe=args.probe_source.resolve()
    if out.exists(): raise SystemExit('output exists; refusing overwrite')
    if any(out==base or base in out.parents for base in (ROOT/'tests/fixtures',ROOT/'verification',inventory.RECORDS)) or 'holdout' in str(out).lower():
        raise SystemExit('output location may not be an indexed source or holdout')
    if not csc.is_file() or not probe.is_file(): raise SystemExit('missing compiler or probe source')
    if args.index:
        # Refuse even accidental use of a sealed population as an index.
        if any('holdout' in str(p.resolve()).lower() for p in (args.index,args.inventory_manifest)): raise SystemExit('holdout paths forbidden')
        raw=args.index.read_bytes(); source_manifest=json.loads(args.inventory_manifest.read_text(encoding='utf-8-sig'))
        if source_manifest['index_sha256']!=sha(raw): raise SystemExit('index hash mismatch')
        existing=read_index(raw)
        if source_manifest['unique_undirected_pairs']!=len(existing): raise SystemExit('index count mismatch')
    else:
        inv=inventory.Inventory().build(include_local_records=args.include_local_records)
        fatal=[x for x in inv.unresolved if x.get('reason')!='null operand: not a UTF-16 string pair']
        if fatal: raise SystemExit('index has unresolved non-null rows; refusing generation')
        # The source hash manifest is checked again before generating candidates.
        for source in inv.sources:
            p=ROOT.parent/source['path']
            if filehash(p)!=source['sha256']: raise SystemExit('inventory source changed: '+source['path'])
        existing=inv.keys; raw=index_bytes(existing)
        source_manifest={'schema':'post-b1-pairs-inventory-v1','index_sha256':sha(raw),
            'unique_undirected_pairs':len(existing),'row_counts':dict(inv.counts),
            'sources':inv.sources,'unresolved':inv.unresolved,'scope':'recognized schemas only; excludes holdout paths',
            'inventory_tool_sha256':filehash(Path(inventory.__file__))}
    # Atomic directory creation protects all expected files from overwrite.
    out.mkdir(parents=True,exist_ok=False)
    (out/'existing_pairs.tsv').write_bytes(raw); dump(out/'inventory.json',source_manifest)
    exe=out/'post_b1_oracle_probe.exe'
    compile_cmd=[str(csc),'/nologo','/optimize+','/reference:System.Web.Extensions.dll','/out:'+str(exe),str(probe)]
    compiled=subprocess.run(compile_cmd,capture_output=True,text=True,encoding='utf-8',errors='replace')
    if compiled.returncode: raise RuntimeError('Framework compile failed: '+compiled.stdout+' '+compiled.stderr)
    generator_hash=filehash(Path(__file__)); probe_hash=filehash(probe)
    dev,dev_report=population(out/'development','development',args.development_seed,args.count,existing,set(),exe,args.max_attempts)
    hold,hold_report=population(out/'final_holdout','final_holdout',args.holdout_seed,args.count,existing,dev,exe,args.max_attempts)
    # Do not read any final_holdout file after population() seals it.
    if dev & hold: raise RuntimeError('cross-population verification failed')
    summary={'schema':'post-b1-indexed-generator-v1','status':'holdout_sealed',
       'development':dev_report,'final_holdout':hold_report,'cross_population_overlap':len(dev&hold),
       'existing_index_sha256':sha(raw),'inventory_manifest_sha256':filehash(out/'inventory.json'),
       'source_count':len(source_manifest['sources']),'unresolved_count':len(source_manifest['unresolved']),
       'generator_sha256':generator_hash,'inventory_tool_sha256':filehash(Path(inventory.__file__)),
       'probe_source_sha256':probe_hash,'probe_exe_sha256':filehash(exe),'compiler_sha256':filehash(csc),
       'compiler_path':str(csc),'compiler_arguments':['/nologo','/optimize+','/reference:System.Web.Extensions.dll'],
       'compile_stdout':compiled.stdout.strip(),'python':sys.version,'platform':platform.platform(),
       'count_per_population':args.count,'max_attempts':args.max_attempts,
       'scope':'recognized indexed schemas only; all paths containing holdout excluded; sealed indexed-v2 overlap unknown',
       'reproduction':'same Python version, generator, probe, frozen index and seeds; Framework output also requires identical Framework/NLS environment'}
    dump(out/'run_manifest.json',summary)
    print(json.dumps({'status':summary['status'],'index_pairs':len(existing),'existing_index_sha256':sha(raw),
       'development_pairs':len(dev),'holdout_pairs':len(hold),'existing_overlap':0,'cross_population_overlap':len(dev&hold),
       'run_manifest_sha256':filehash(out/'run_manifest.json')}))

if __name__=='__main__': main()
