"""Ordered, lossless warning observations. Raw logs do not prove diagnostic origin."""
import re
from collections import Counter
SCHEMA = 'run07-comparison-1'
HEADER = re.compile(r'警告Lv(\d+):(.*)')
POSITION = re.compile(r'(.+?):(\d+)行目:(.*)')
def warning_records(text, source_lines=None):
    raw = re.findall(r'[^\n]*\n|[^\n]+$',text)
    records=[]
    for index, full in enumerate(raw):
        # CR/LF are transport separators only; retain their exact bytes as text.
        content=full[:-2] if full.endswith('\r\n') else full[:-1] if full.endswith(('\r','\n')) else full
        m=HEADER.fullmatch(content)
        if not m: continue
        pos=POSITION.fullmatch(m[2]); filename=pos[1] if pos else None
        line=int(pos[2]) if pos else None
        source=None; source_known=False
        if pos and source_lines is not None:
            candidates=[v for (f,n),v in source_lines.items() if f==filename and n==line]
            if len(candidates)==1:
                source_known=True
                if index+1<len(raw):
                    next_raw=raw[index+1]; next_line=next_raw[:-2] if next_raw.endswith('\r\n') else next_raw[:-1] if next_raw.endswith(('\r','\n')) else next_raw
                    if next_line==candidates[0]: source=next_line
        records.append(dict(severity=int(m[1]),raw_line=full,raw_content=content,
            location_present=bool(pos),file=filename,line=line,
            message=pos[3] if pos else m[2],source_text=source,
            source_text_present=source is not None,source_context_known=source_known,
            log_line=index+1,warning_order=len(records),diagnostic_phase=None,
            diagnostic_origin='raw_log_unproven'))
    signatures=[signature(r) for r in records]; counts=Counter(signatures); seen=Counter()
    for r,s in zip(records,signatures):
        seen[s]+=1;r['occurrence_index']=seen[s];r['occurrence_count']=counts[s]
    return records

def signature(record):
    return tuple(record[k] for k in ('severity','raw_content','location_present','file','line','message','source_text_present','source_text'))

def compare_warnings(reference, py, source_lines=None, *, warning_like_user_text=False,
                     structured_py_diagnostics=None, origin_reviewed=False):
    left=warning_records(reference,source_lines);right=warning_records(py,source_lines)
    a,b=[signature(r) for r in left],[signature(r) for r in right]
    ambiguous=bool(warning_like_user_text)
    if structured_py_diagnostics is not None:
        expected=[(d['severity'],d['file'].replace('\\','/').split('/')[-1],d['line'],d['reference_message']) for d in structured_py_diagnostics if d.get('kind')=='warning']
        actual=[(r['severity'],r['file'],r['line'],r['message']) for r in right]
        ambiguous |= expected!=actual
    elif (left or right) and not origin_reviewed:
        ambiguous=True
    source_unresolved=any(r['location_present'] and not r['source_context_known'] for r in left+right)
    differences=[]
    if len(a)!=len(b): differences.append('warning_count')
    if Counter(a)!=Counter(b):differences.append('warning_record_multiset')
    elif a!=b:differences.append('warning_order')
    for x,y in zip(left,right):
        for key in ('severity','location_present','file','line','message','raw_content','source_text_present','source_text'):
            if x[key]!=y[key] and key not in differences: differences.append(key)
    equal=a==b
    return dict(schema=SCHEMA,reference_warnings=left,py_warnings=right,
        logical_warning_records_equal=equal,warning_differences=differences,
        warning_origin_ambiguous=ambiguous,warning_source_unresolved=source_unresolved,
        warning_comparison_complete=not ambiguous and not source_unresolved,
        warning_status='mismatch_open' if not equal else 'warning_observation_pending' if ambiguous or source_unresolved else 'verified_equal',
        policy='Exact code points, whitespace, count and order; CR/LF transport separately retained. Location/phase never inferred. Raw-log origin requires external provenance; PRINT-like ambiguity stays pending.')

def fixture_sources(game, read_text):
    result={}; warning_like=False
    for p in game.rglob('*'):
        if p.is_file() and p.suffix.lower() in ('.erb','.erh'):
            for i,line in enumerate(read_text(p).splitlines(),1):
                key=(p.name,i)
                if key in result and result[key]!=line: result.pop(key,None)
                else:result[key]=line
                if re.match(r'\s*PRINT',line,re.I) and '警告Lv' in line:warning_like=True
    return result,warning_like
