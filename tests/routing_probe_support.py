"""Independent state observations for the r38 -> r39 routing contract."""
import contextlib,datetime,hashlib,io,json
from pathlib import Path
from unittest.mock import patch
from test_core import Harness

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=True,default=str).encode()).hexdigest()

class FixedDatetime(datetime.datetime):
    @classmethod
    def now(cls, tz=None):return cls(2026,10,11,12,0,0)

def observe(name, case):
    from pyemuera import commands, outputlog
    h=Harness()
    raw=case['raw']
    body=name+(' '+raw if raw else '')
    # RESTART loops are intentionally bounded and expose frame/loop cleanup.
    source='@MAIN\n'+('NOSKIP\n' if name=='ENDNOSKIP' else '')+body+('\nENDNOSKIP' if name=='NOSKIP' else '')+'\nRETURN\n@EVENTTURNEND\nC+=1\nRETURN\n'
    if name=='RETURNF':source='@MAIN\n#FUNCTION\n'+body+'\n'
    if case['entry']=='direct':source='@MAIN\nRETURN\n'
    with patch.object(datetime,'datetime',FixedDatetime),patch.object(outputlog,'datetime',FixedDatetime),contextlib.redirect_stderr(io.StringIO()) as stderr:
        try:vm=h.make(source,inputs=['12','text'],max_steps=20,csv={'Chara7.csv':'番号,7\n名前,test\n呼び名,call\n基礎,0,100\n能力,0,2\n','Abl.csv':'0,test\n','Train.csv':'1,test\n'} if case.get('prepared') else None)
        except Exception as e:
            h.doCleanups()
            return {'phase':'load','error':{'type':type(e).__name__,'code':getattr(e,'code',None),'message':getattr(e,'message',str(e))},'stderr':stderr.getvalue()}
        if case.get('prepared'):
            vm.data.add_character(7)
            vm.data.config['KEY']='12'
            vm.train_context=True;vm.train_phase='SHOW_STATUS'
        vm.set('A',6);vm.set('RESULT',77);vm.set('RESULTS','unchanged')
        vm.console.write('first',True);vm.console.write('second',True)
        vm.console.skip_print=case['skip']
        trace=[];orig_eval=vm.eval;orig_set=vm.set
        def evaluate(raw):trace.append(['eval',raw]);return orig_eval(raw)
        def write(n,v):trace.append(['set',n,v]);return orig_set(n,v)
        vm.eval=evaluate;vm.set=write
        error=None;result=None
        try:
            if case['entry']=='direct':
                vm.frames.append(vm._new_frame(vm.program.functions['MAIN'][0]))
                result=commands.execute_command(vm,name,raw)
            elif name=='RETURNF':result=vm.call_expr('MAIN',[])
            else:result=vm.call('MAIN')
        except Exception as e:
            error={'type':type(e).__name__,'code':getattr(e,'code',None),'message':getattr(e,'message',str(e))}
        root=Path(vm.data.root)
        states={n:digest([list(v.dims),v.character,sorted((list(k),value) for k,value in v.values.items())]) for n,v in sorted(vm.data.variables.items())}
        frames=[{'function':f.function.name,'pc':f.pc,'loops':repr(f.loops),'selects':repr(f.selects),'skip_marks':f.skip_marks,'finished':f.finished} for f in vm.frames]
        saves={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and '.pyemuera' in p.parts}
        row={'result':result,'error':error,'trace':trace,'variables':states,'frames':frames,
             'rng':digest(vm.rng.getstate()),'steps':vm.steps,'output':h.output.getvalue(),
             'history':list(vm.console.log_lines),'skip':[vm.console.skip_print,vm.console.user_skip],
             'train':{'queue':list(vm.train_queue) if vm.train_queue is not None else None,'index':vm.train_queue_index,'total':vm.train_queue_total,'phase':vm.train_phase},'inputs':getattr(vm.console,'input_count',None),'wait':vm.console.wait_count,'files':saves,'stderr':stderr.getvalue()}
        text=json.dumps(row,ensure_ascii=True,default=str).replace(str(root),'<GAME>')
        h.doCleanups()
        return json.loads(text)
