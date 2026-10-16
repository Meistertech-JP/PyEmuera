"""Capture subprocess streams as bytes; no PowerShell text redirection/guessing."""
import sys,subprocess,json,hashlib,os
from pathlib import Path

def decode_record(raw,encoding='utf-8'):
    result=dict(raw_sha256=hashlib.sha256(raw).hexdigest(),raw_byte_count=len(raw),encoding=encoding,decoded_text=None,decoding_error=None,capture_method='subprocess.PIPE bytes, strict explicit decoding')
    try:result['decoded_text']=raw.decode(encoding,errors='strict')
    except (UnicodeError,LookupError) as exc:result['decoding_error']=str(exc)
    return result

def capture(command,evidence):
    evidence=Path(evidence);env=dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1')
    forbidden=['py-stderr.raw','py-stderr.txt','py-stderr-capture.json','py-output.raw','py-output.txt']
    if any((evidence/n).exists() for n in forbidden):raise FileExistsError('Fresh evidence required; never replace streams')
    proc=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
    record=decode_record(proc.stderr);record['process_exit_code']=proc.returncode
    for prefix,raw in [('py-output',proc.stdout),('py-stderr',proc.stderr)]:
        (evidence/(prefix+'.raw')).write_bytes(raw)
        decoded=decode_record(raw)
        if decoded['decoding_error'] is None:(evidence/(prefix+'.txt')).write_bytes(raw)
    structured=evidence/'py-error.json'
    if structured.exists():
        error=json.loads(structured.read_text(encoding='utf-8-sig')).get('error',{});display=error.get('diagnostic_message',error.get('message'))
        record['structured_diagnostic_message']=display;record['structured_message_in_decoded_stderr']=display in record['decoded_text'] if display and record['decoded_text'] is not None else None
    (evidence/'py-stderr-capture.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return proc.returncode
if __name__=='__main__':
    # args: evidence, then full process argv (Python executable supplied by caller).
    raise SystemExit(capture(sys.argv[2:],sys.argv[1]))
