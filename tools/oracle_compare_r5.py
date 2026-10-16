"""Lossless oracle comparison. Logical Console log and terminal stdout stay separate."""
from pathlib import Path
import hashlib,json,re

def read_text(path):
    data=Path(path).read_bytes()
    if data[:2] in (b'\xff\xfe',b'\xfe\xff'):
        return data.decode('utf-16')
    return data.decode('utf-8-sig')

def lines(text):
    # Remove record separators only. Never strip spaces or normalize Unicode.
    return [s[:-1] if s.endswith('\r') else s for s in text.split('\n')]

def markers(text):
    return [s for s in lines(text) if s.startswith('ORACLE|')]

def warning_records(text):
    src=lines(text);result=[]
    for i,line in enumerate(src):
        match=re.fullmatch(r'警告Lv(\d+):(.+):(\d+)行目:(.*)',line)
        if match:
            result.append({'severity':int(match[1]),'file':match[2],
                           'line':int(match[3]),'reference_message':match[4],
                           'source_text':src[i+1] if i+1<len(src) else None})
    return result

def observations(reference,logical,physical,expected_ids):
    r,p,s=markers(reference),markers(logical),markers(physical)
    ids=lambda values:[x.split('|',2)[1] for x in values]
    complete=ids(r)==expected_ids and ids(p)==expected_ids and len(set(expected_ids))==len(expected_ids)
    width_rows=[]
    for left,right in zip(r,p):
        if len(left.split('|',3))==4:
            width_rows.append({'case_id':left.split('|',3)[1],'reference':left,
                              'py_logical':right,'equal':left==right})
    return {'marker_observations_equal':r==p,'reference_capture_complete':ids(r)==expected_ids,
            'py_capture_complete':ids(p)==expected_ids,'unique_ids_complete':complete,
            'logical_warning_records_equal':warning_records(reference)==warning_records(logical),
            'reference_warnings':warning_records(reference),'py_warnings':warning_records(logical),
            'physical_marker_observations_equal':r==s,'reference_markers':r,
            'py_logical_markers':p,'py_physical_markers':s,'individual_observations':width_rows,
            'comparison_policy':'exact code points and spaces in logical records; only CR/LF separators removed'}

def write_json_exclusive(path,value):
    # Fully encode before opening; a serialization/encoding failure cannot
    # truncate an existing result or leave a zero-byte success file.
    payload=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    with Path(path).open('xb') as stream:
        stream.write(payload)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
