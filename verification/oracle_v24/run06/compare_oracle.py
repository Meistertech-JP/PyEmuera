from pathlib import Path
import sys,json,re
sys.dont_write_bytecode=True
from oracle_common import read_text,observations,write_json_exclusive,sha
from capture_logs import select_capture

def compare(case,e):
    defs=json.loads(read_text(case/'oracle_definitions.json'))
    result={'schema':'run06-comparison-1','run_id':defs['run_id'],'case_id':defs['case_id'],
            'status':'capture_incomplete','automated_observation':True,
            'limitation':'Fixed markers and recorded warnings only. Error final state/phase and unseen conditions remain pending.'}
    required=['reference-meta.json','py-meta.json','reference-output.txt','py-output.txt','py-session.json']
    missing=[x for x in required if not (e/x).is_file()]
    result['missing_evidence_files']=missing
    if missing:result['reason']='evidence_file_missing';return result
    rm=json.loads(read_text(e/'reference-meta.json'));pm=json.loads(read_text(e/'py-meta.json'))
    for key in ['reference_id','source_tree_sha256','fixture_manifest','run_id']:
        if rm[key]!=pm[key] or rm[key]!=defs[key]:raise ValueError('Stale/foreign evidence: '+key)
    if not rm.get('execution_id') or rm['execution_id']!=pm.get('execution_id'):raise ValueError('Execution identity mismatch')
    if rm['exe_sha256']!=defs['exe_sha256'] or pm['pyz_sha256']!=defs['pyz_sha256']:raise ValueError('Executable identity mismatch')
    for run in ['reference-run','py-run']:
        for row in defs['fixture_manifest']:
            if sha(e/run/row['path'])!=row['sha256']:raise ValueError('Executed fixture/config modified: '+row['path'])
    if sha(e/'reference-run/Emuera1824+v24.exe')!=defs['exe_sha256']:raise ValueError('Executed exe mismatch')
    if (e/'reference-output.txt').read_bytes()!=(e/'reference-run/emuera.log').read_bytes():raise ValueError('Reference log copy modified')
    capture=select_capture(e);result['py_capture']=capture
    if capture['status']!='capture_complete':result['reason']=capture['reason'];return result
    if not (e/'py-logical-output.txt').exists():result['reason']='selected_log_copy_missing';return result
    if sha(e/'py-logical-output.txt')!=capture['selected']['sha256']:raise ValueError('Selected logical log changed')
    ref=read_text(e/'reference-output.txt');py=read_text(e/'py-logical-output.txt');stdout=read_text(e/'py-output.txt')
    result.update(observations(ref,py,stdout,defs['expected_ids']))
    result.update(execution_id=rm['execution_id'],reference_id=defs['reference_id'],fixture_manifest=defs['fixture_manifest'],exe_sha256=rm['exe_sha256'],pyz_sha256=pm['pyz_sha256'],source_tree_sha256=defs['source_tree_sha256'],source_reference=defs['source_reference'],capture_hashes={n:sha(e/n) for n in ['reference-output.txt','py-logical-output.txt','py-output.txt','py-session.json']},missing_expected_markers={'reference':[x for x in defs['expected_ids'] if x not in [s.split('|',2)[1] for s in result['reference_markers']]],'py':[x for x in defs['expected_ids'] if x not in [s.split('|',2)[1] for s in result['py_logical_markers']]]})
    gui=json.loads(read_text(e/'gui-observation.json')) if (e/'gui-observation.json').exists() else {}
    if gui.get('execution_id') is not None and gui['execution_id']!=rm['execution_id']:
        raise ValueError('GUI observation belongs to a different execution')
    result['gui_observation']={k:gui.get(k) for k in ['observer','observation_source','user_confirmed','warnings_and_errors_reviewed','primary_error','error_phase','final_state_observed']}
    reviewed=gui.get('warnings_and_errors_reviewed') is True and bool(gui.get('observer')) and gui.get('observer')!='FILL' and gui.get('execution_id')==rm['execution_id'] and gui.get('error_dialogs_observed')==0
    result['user_confirmed_gui_observation']=gui.get('execution_id')==rm['execution_id'] and gui.get('user_confirmed') is True and gui.get('observation_source')=='user_confirmed_gui_observation'
    header=re.search(r'([^\r\n]+)の(\d+)行目でエラーが発生しました',ref)
    result['reference_error_location_from_log']={'file':header[1],'line':int(header[2])} if header else None
    if defs['error_probe']:
        result.update(status='error_observation_pending',reason='error final state/phase requires separate evidence; prior marker equality insufficient')
    elif result['missing_expected_markers']['reference'] or result['missing_expected_markers']['py']:
        result.update(status='expected_markers_incomplete',reason='files present but expected observations not reached')
    else:
        equal=result['marker_observations_equal'] and result['unique_ids_complete'] and result['logical_warning_records_equal'] and rm.get('runtime_executed') is True and pm['exit_code']==0 and not header and not gui.get('primary_error') and gui.get('error_dialogs_observed',0) in (None,0)
        result.update(status='verified_equal' if equal and reviewed else 'warning_review_pending' if equal else 'mismatch_open',reason='fixed observation comparison')
    return result

def main():
    case=Path(sys.argv[1]);e=Path(sys.argv[2])
    if (e/'comparison.json').exists():raise FileExistsError('Never overwrite earlier comparison')
    result=compare(case,e);write_json_exclusive(e/'comparison.json',result)
    print(json.dumps({k:result.get(k) for k in ['schema','status','marker_observations_equal','reference_capture_complete','reason']},ensure_ascii=True))
    return 0 if result['status']=='verified_equal' else 2 if result['status'] in ('mismatch_open','expected_markers_incomplete') else 3

if __name__=='__main__':raise SystemExit(main())
