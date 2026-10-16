"""Execution outcome is independent of OUTPUTLOG availability and exit code.

Raw markers alone do not certify success. The caller verifies run/executable/
fixture/execution identity before trusting session or GUI records. No stdout
synthesis fills a missing logical log. Wrapper/timeout/platform are distinct.
"""
import re
try:
    from .oracle_status_r11 import assess as diagnostic_assess
except ImportError:
    from oracle_status_r11 import assess as diagnostic_assess
SCHEMA='run11-comparison-1'
INFRASTRUCTURE=frozenset(('timeout','forced_termination','launch_failure','wrapper_exception','invalid_evidence'))
def outcome_comparison(reference_outcome, py_outcome, **axes):
    result=diagnostic_assess(**axes)
    for key in ['error_stack_status','reference_error_stack','py_error_stack']:
        if key in axes:result[key]=axes[key]
    if axes.get('error_stack_status')=='mismatch_open':result['mismatch_detected']=True
    if reference_outcome in INFRASTRUCTURE or py_outcome in INFRASTRUCTURE:execution='infrastructure_pending'
    elif 'platform_unsupported' in (reference_outcome,py_outcome):execution='platform_unsupported'
    elif {reference_outcome,py_outcome}=={'normal_complete','script_error'}:execution='mismatch_open'
    elif reference_outcome==py_outcome and reference_outcome in ('normal_complete','script_error'):execution='verified_equal'
    else:execution='not_observed'
    result.update(schema=SCHEMA,reference_outcome=reference_outcome,py_outcome=py_outcome,execution_status=execution)
    result['mismatch_detected']=result['mismatch_detected'] or execution in ('mismatch_open','platform_unsupported')
    if execution=='platform_unsupported':status='platform_unsupported'
    elif result['mismatch_detected']:status='mismatch_open'
    elif execution=='infrastructure_pending':status='infrastructure_pending'
    elif execution=='not_observed' and result['status']=='verified_equal':status='execution_observation_pending'
    else:status=result['status']
    result['status']=result['overall_status']=status
    result['reference_error_phase']='unobserved'
    result['reference_final_state']='unobserved'
    return result

def reference_outcome(text, gui, *, identity_verified=False, expected_ids=()):
    if not identity_verified:return 'not_observed'
    if re.search(r'[^\r\n]+の\d+行目でエラーが発生しました',text or '') or gui.get('primary_error'):return 'script_error'
    ids=[s.split('|',2)[1] for s in (text or '').splitlines() if s.startswith('ORACLE|')]
    reviewed=gui.get('warnings_and_errors_reviewed') is True and gui.get('observer') not in (None,'','FILL') and gui.get('error_dialogs_observed')==0
    # Expected observations and GUI corroboration together; a lone forged end
    # line without identity/review/expected observations remains unobserved.
    if reviewed and 'end' in ids and all(i in ids for i in expected_ids):return 'normal_complete'
    return 'not_observed'

def py_outcome(session, *, identity_verified=False, infrastructure=None):
    if infrastructure in INFRASTRUCTURE:return infrastructure
    if not identity_verified or not isinstance(session,dict):return 'not_observed'
    error=session.get('error')
    if isinstance(error,dict) and error.get('code'):
        if error['code']=='E_UNSUPPORTED':return 'platform_unsupported'
        if error['code']=='E_INTERNAL':return 'wrapper_exception'
        return 'script_error'
    if session.get('outcome') in ('quit','completed','normal','success','system_exit') and not error:return 'normal_complete'
    return 'not_observed'

def validated_error(session, envelope, *, engine_version):
    if not isinstance(session,dict) or not isinstance(envelope,dict):return None
    if envelope.get('engine_version')!=engine_version or envelope.get('error')!=session.get('error'):raise ValueError('Stale or foreign structured error evidence')
    return envelope.get('error')
