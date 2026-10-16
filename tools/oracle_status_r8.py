"""Multi-axis evidence assessment. Known mismatches take priority over pending.

An equal prior marker says nothing about post-error state. Capture and diagnostic
provenance are independent dimensions, never promoted by a status string.
"""
SCHEMA='run08-comparison-1'
AXES=('marker_status','warning_status','error_category_status','error_location_status','error_text_status','post_error_state_status','capture_status')
def assess(**axes):
    result={key:axes.get(key,'not_observed') for key in AXES}
    mismatch=any(value in ('mismatch_open','mismatch_confirmed','unequal') for value in result.values())
    result.update(schema=SCHEMA,mismatch_detected=mismatch)
    if mismatch:status='mismatch_open'
    elif result['capture_status']!='capture_complete':status='capture_incomplete'
    elif result['post_error_state_status']=='not_observed' and result['error_category_status']!='not_applicable':status='error_observation_pending'
    elif result['warning_status']!='verified_equal':status='warning_observation_pending'
    elif all(result[k] in ('verified_equal','not_applicable','capture_complete') for k in AXES):status='verified_equal'
    else:status='observation_pending'
    result['overall_status']=result['status']=status
    return result

def error_axes(reference,py_error):
    import re
    from pathlib import PurePosixPath
    header=re.search(r'([^\r\n]+)の(\d+)行目でエラーが発生しました',reference)
    text=re.search(r'エラー内容：([^\r\n]*)',reference)
    if not header and not py_error:return {k:'not_applicable' for k in ('error_category_status','error_location_status','error_text_status','post_error_state_status')}
    if not header or not py_error:return dict(error_category_status='mismatch_open',error_location_status='mismatch_open',error_text_status='not_observed',post_error_state_status='not_observed')
    message=text[1] if text else None
    families=[('0による除算','E_ARITH'),('累乗結果','E_ARITH'),('配列の範囲外','E_INDEX'),('要素数を超えて','E_INDEX'),('式が異常です','E_SYNTAX'),('引数が足りません','E_ARGUMENT'),('型が正しくありません','E_TYPE'),('式の結果が数値','E_TYPE'),('変数以外','E_REFERENCE')]
    expected=next((code for token,code in families if message and token in message),None)
    return dict(error_category_status='not_observed' if expected is None else 'verified_equal' if expected==py_error['code'] else 'mismatch_open',error_location_status='verified_equal' if int(header[2])==py_error.get('line') and PurePosixPath(py_error.get('file','').replace('\\','/')).name==header[1] else 'mismatch_open',error_text_status='not_observed' if message is None else 'verified_equal' if message==py_error.get('diagnostic_message',py_error.get('message')) else 'mismatch_open',post_error_state_status='not_observed')
