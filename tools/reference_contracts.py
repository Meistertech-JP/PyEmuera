"""Source registration / argument-contract extraction, not a C# compiler.

Reads the exact supplied archive. Every record carries registration, class and
CheckArgumentType line ranges and hashes; custom validation remains a source
contract, never guessed from a function name or runtime handler presence.
"""
import hashlib,re
from pathlib import Path


def clean(text,mask_strings=False):
    out=list(text);i=0
    while i<len(text):
        start=i
        if text.startswith('//',i):
            i=text.find('\n',i)
            if i<0:i=len(text)
            for k in range(start,i):out[k]=' '
        elif text.startswith('/*',i):
            end=text.find('*/',i+2);i=len(text) if end<0 else end+2
            for k in range(start,i):
                if text[k]!='\n':out[k]=' '
        elif text.startswith('@"',i) or text[i] in ('"',"'"):
            verbatim=text.startswith('@"',i);quote='"' if verbatim else text[i];i+=2 if verbatim else 1
            while i<len(text):
                if text[i]==quote:
                    if verbatim and i+1<len(text) and text[i+1]==quote:i+=2;continue
                    i+=1;break
                if not verbatim and text[i]=='\\':i+=2
                else:i+=1
            if mask_strings:
                for k in range(start,min(i,len(text))):
                    if text[k]!='\n':out[k]=' '
        else:i+=1
    return ''.join(out)


def balanced(mask,start,opening='{',closing='}'):
    if mask[start]!=opening:raise ValueError('Expected balanced opener')
    level=0
    for i in range(start,len(mask)):
        if mask[i]==opening:level+=1
        elif mask[i]==closing:
            level-=1
            if not level:return i+1
    raise ValueError('Unclosed C# source block')


def location(path,text,start,end,root):
    return {'file':path.relative_to(root).as_posix(),'start_line':text.count('\n',0,start)+1,'end_line':text.count('\n',0,end)+1,'sha256':hashlib.sha256(text[start:end].encode('utf-8')).hexdigest()}


def read_source(path):
    raw=path.read_bytes()
    if raw.startswith((b'\xff\xfe',b'\xfe\xff')):return raw.decode('utf-16')
    try:return raw.decode('utf-8-sig')
    except UnicodeError:return raw.decode('cp932')

def extract(root):
    root=Path(root);classes={};files={}
    for path in sorted(root.rglob('*.cs')):
        text=read_source(path);stripped=clean(text);mask=clean(text,True);files[path.relative_to(root).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
        for m in re.finditer(r'\b(?:sealed\s+)?class\s+(\w+)\s*:\s*(FunctionMethod|AbstractInstruction|ArgumentBuilder)\b',mask):
            start=mask.find('{',m.end());end=balanced(mask,start);body=stripped[start:end];mb=mask[start:end]
            source=location(path,text,m.start(),end,root);item={'class':m[1],'base':m[2],'source':source,'body':body}
            arrays=re.findall(r'argumentTypeArray\s*=\s*new\s+Type\[\]\s*\{([^}]*)\}',body)
            item['type_arrays']=[re.findall(r'typeof\((\w+)\)|\b(null)\b',a) for a in arrays]
            item['type_arrays']=[[a or b for a,b in arr] for arr in item['type_arrays']]
            cm=re.search(r'public\s+override\s+string\s+CheckArgumentType\s*\([^)]*\)\s*\{',mb)
            if cm:
                cstart=start+cm.end()-1;cend=balanced(mask,cstart)
                item['validation']=location(path,text,cstart,cend,root)
                checks=clean(text[cstart:cend])
                item['arity_tests']=re.findall(r'arguments\.Length\s*(<=|>=|==|!=|<|>)\s*(\d+)',checks)
                item['validation_text']=checks
            else:item['arity_tests']=[]
            item['builders']=sorted(set(re.findall(r'(?:GetArgumentBuilder\(FunctionArgType\.|argb\[FunctionArgType\.)([A-Z_0-9]+)',body)))
            classes[m[1]]=item
    registrations={'commands':[],'functions':[]}
    for kind,rel,pattern in [
      ('commands','GameProc/Function/FunctionIdentifier.cs',r'\b(add(?:Print|PrintData)?Function)\(FunctionCode\.([A-Z_0-9]+)'),
      ('functions','GameData/Function/Creator.cs',r'(?:methodList)?\["([A-Z_0-9]+)"\]\s*=\s*new\s+(\w+)\(')]:
        path=root/rel;text=read_source(path);stripped=clean(text);mask=clean(text,True)
        for m in re.finditer(pattern,stripped):
            end=stripped.find(';',m.end())+1
            if kind=='functions' and not m.group().startswith('methodList'):
                end=stripped.find('\n',m.end())
            raw=stripped[m.start():end]
            if kind=='commands':
                name=m[2];family=m[1]
                cls='PRINT_Instruction' if family=='addPrintFunction' else 'PRINT_DATA_Instruction' if family=='addPrintDataFunction' else None
                cm=re.search(r'new\s+(\w+)\(',raw)
                if cm:cls=cm[1]
            else:name=m[1];cls=m[2]
            definition=classes.get(cls,{})
            builders=re.findall(r'argb\[FunctionArgType\.([A-Z_0-9]+)\]',raw) or definition.get('builders',[])
            row={'name':name,'registration':location(path,text,m.start(),end,root),'registration_text':raw,'implementation_class':cls,'argument_builders':builders,'definition':definition.get('source'),'declared_argument_type_arrays':definition.get('type_arrays',[]),'custom_validator':definition.get('validation'),'source_argument_count_tests':definition.get('arity_tests',[])}
            arrays=row['declared_argument_type_arrays']
            if kind=='functions' and not row['custom_validator'] and arrays and all(a==arrays[0] for a in arrays):row['fixed_parameter_types']=arrays[0]
            if kind=='commands':
                if cls=='PRINT_Instruction':row['method_safe']='W'!=name[-1]
                elif cls=='PRINT_DATA_Instruction':row['method_safe']='W'!=name[-1]
                elif not cls:row['method_safe']='METHOD_SAFE' in raw
                else:
                    # Source constructors in these instruction classes use flag
                    # OR composition. Conditional PRINT modes above are split.
                    body=definition.get('body','')
                    row['method_safe']='METHOD_SAFE' in body[:body.find('public override') if 'public override' in body else len(body)] or 'METHOD_SAFE' in raw
            registrations[kind].append(row)
    return {'commands':registrations['commands'],'functions':registrations['functions'],'classes':classes,'source_file_hashes':files}
