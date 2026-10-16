"""Select a snapshot by final-history digest, never by concatenation or name.

Pure offline tool: validates all output files and declared generation order.
Missing session/order/content evidence produces an incomplete capture.
"""
from pathlib import Path
import json,hashlib,sys
sys.dont_write_bytecode=True

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read_json(path):return json.loads(path.read_bytes().decode('utf-8-sig'))
def write_json(path,value):
    data=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    with path.open('xb') as stream:stream.write(data)

def select_capture(evidence):
    evidence=Path(evidence);folder=evidence/'py-run/.pyemuera/logs'
    files=sorted(folder.glob('*.txt'));rows=[]
    for path in files:
        path.read_bytes().decode('utf-8') # Fail closed: no silent ANSI replacement.
        rows.append({'file':path.name,'sha256':sha(path),'bytes':path.stat().st_size,
                     'evidence_path':path.relative_to(evidence).as_posix()})
    result={'schema':'run06-outputlog-selection-1','status':'capture_incomplete','files':rows,'count':len(files),
            'selection_rule':'journal generation order + every content digest + exact final Console history digest/length',
            'intermediate_logs_preserved':True,'files_concatenated':False,'selected':None}
    session=evidence/'py-session.json'
    if not files:result['reason']='no_OUTPUTLOG_files';return result
    if not session.exists():result['reason']='missing_final_session_report';return result
    report=read_json(session);summary=report.get('logical_output_capture')
    if not summary:result['reason']='missing_final_history_digest';return result
    records=summary.get('records',[])
    result.update(records=records,final_history_sha256=summary.get('final_history_sha256'),final_history_bytes=summary.get('final_history_bytes'),outcome=report.get('outcome'),error=report.get('error'),final_state=report.get('final_state'))
    if [r.get('generation') for r in records]!=list(range(1,len(records)+1)):
        result['reason']='invalid_generation_order';return result
    if len({r.get('file') for r in records})!=len(records) or {r.get('file') for r in records}!={r['file'] for r in rows}:
        result['reason']='missing_extra_or_duplicate_OUTPUTLOG_file';return result
    by_name={r['file']:r for r in rows}
    for record in records:
        actual=by_name[record['file']]
        if actual['sha256']!=record.get('sha256') or actual['bytes']!=record.get('bytes'):
            result['reason']='OUTPUTLOG_content_changed';return result
    manifest=folder/'outputlog-manifest.json'
    if not manifest.exists() or read_json(manifest).get('records')!=records:
        result['reason']='generation_manifest_missing_or_changed';return result
    candidates=[r for r in records if r['sha256']==summary['final_history_sha256'] and r['bytes']==summary['final_history_bytes']]
    if not candidates:result['reason']='no_snapshot_represents_final_history';return result
    selected=candidates[-1] # Last declared generation, only among exact matches.
    result.update(status='capture_complete',reason='exact_final_history_snapshot',selected=by_name[selected['file']],selected_generation=selected['generation'])
    return result

def main():
    evidence=Path(sys.argv[1]);result=select_capture(evidence)
    if result['selected']:
        raw=(evidence/result['selected']['evidence_path']).read_bytes()
        with (evidence/'py-logical-output.txt').open('xb') as stream:stream.write(raw)
    write_json(evidence/'py-capture.json',result)
    print(json.dumps({'status':result['status'],'count':result['count'],'reason':result['reason']},ensure_ascii=True))
    return 0 if result['status']=='capture_complete' else 3

if __name__=='__main__':raise SystemExit(main())
