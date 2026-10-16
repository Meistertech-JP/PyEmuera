"""Evidence sidecar: never edits the official comparison or joins executions."""
from .oracle_outcome_r12 import outcome_comparison

def evidence_assessment(reference_outcome, py_outcome, *, execution_ids, gui_coverage, **axes):
    result=outcome_comparison(reference_outcome,py_outcome,**axes)
    result['gui_coverage']=gui_coverage
    result['execution_identity_status']='verified_equal' if len(set(execution_ids))==1 and all(execution_ids) else 'invalid_evidence'
    result['raw_log_status']=result['status']
    if result['execution_identity_status']=='invalid_evidence':
        result['status']=result['overall_status']='infrastructure_pending'
    result['new_windows_execution']=False
    result['gui_confirmation_unverified']=gui_coverage=='gui_coverage_unverified'
    return result
