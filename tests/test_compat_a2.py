"""Independent neutral ERB fixtures. These are NOT the requested real games."""
from __future__ import annotations
import io
import json
import subprocess
import sys
import unittest
from pathlib import Path
from test_core import Harness, ROOT, CHARA
from pyemuera.console import Console
from pyemuera.data import GameData
from pyemuera.errors import EraError
from pyemuera.journal import RunJournal, load_replay
from pyemuera.program import Program
from pyemuera.runtime import VM
from pyemuera.cli import write_report


class ReplacementTests(Harness):
    def test_documented_defaults(self):
        vm = self.make()
        self.assertEqual(vm.get('PBAND'), 4)
        self.assertEqual([vm.get('EXPLV:'+str(i)) for i in range(6)], [0,1,4,20,50,200])
        self.assertEqual(vm.get('PALAMLV:3'), 3000)
        self.assertEqual(vm.data.variables['SELECTCOM'].dims, (1000,))

    def test_default_relation(self):
        vm = self.script('ADDVOIDCHARA\nTARGET=0')
        self.assertEqual(vm.get('RELATION:55'), 0)

    def test_initial_values_and_reset(self):
        vm = self.make(csv={'_replace.csv':'EXPLVの初期値,0/2/9\nPALAMLVの初期値,0/7/55\nPBANDの初期値,8\nRELATIONの初期値,13'})
        vm.set('EXPLV:1', 90)
        vm.reset()
        self.assertEqual(vm.get('EXPLV:1'), 2)
        self.assertEqual(vm.get('EXPLV:3'), 0)
        self.assertEqual(vm.get('PBAND'), 8)
        vm.data.add_character(-1, void=True)
        self.assertEqual(vm.get('RELATION:0:7'), 13)

    def test_money_and_bar_and_drawline(self):
        vm = self.script('DRAWLINE\nPRINT_SHOPITEM\nPRINT_ITEM', csv={
            '_replace.csv':'お金の単位,円\n単位の位置,前\nDRAWLINE文字,=\nBAR文字1,#\nBAR文字2,_'})
        self.assertEqual(vm.eval('MONEYSTR(15)'), '円15')
        self.assertEqual(vm.eval('BARSTR(2,4,4)'), '[##__]')
        self.assertIn('='*60, self.output.getvalue())

    def test_unknown_setting_warns(self):
        vm = self.make(csv={'_replace.csv':'未知の設定,1'})
        self.assertFalse(any('未知の設定' in w for w in vm.data.warnings))

    def test_bad_setting_rejected(self):
        vm = self.make(csv={'_replace.csv':'販売アイテム数,-1'})
        self.assertEqual(vm.data.settings.shop_limit, -1)
        for text in ('汚れの初期値,0/nope/2', '単位の位置,下', 'PBANDの初期値,9223372036854775808'):
            with self.subTest(text=text):
                vm = self.make(csv={'_replace.csv':text})
                self.assertEqual(len(vm.data.warnings), 1)

    def test_stain_override_and_reset(self):
        vm = self.script('ADDVOIDCHARA\nTARGET=0\nSTAIN:5=88\nSTAIN:1=99\nRESET_STAIN 0', csv={'_replace.csv':'汚れの初期値,4/3/2'})
        self.assertEqual([vm.get('STAIN:'+str(i)) for i in range(6)], [4,3,2,0,0,0])

    def test_reset_stain_bad_character(self):
        vm = self.make('@MAIN\nRESET_STAIN 0')
        with self.assertRaises(EraError) as caught: vm.call('MAIN')
        self.assertEqual(caught.exception.code, 'E_CHARACTER')

    def test_shop_custom_range(self):
        vm = self.make('@SYSTEM_TITLE\nMONEY=50\nITEMSALES:150=1\nBEGIN SHOP\n@SHOW_SHOP\nPRINT_SHOPITEM\n@EVENTBUY\nA=BOUGHT\nQUIT',
            csv={'Item.csv':'150,地図,30','_replace.csv':'販売アイテム数,200'}, inputs=['150'])
        vm.run()
        self.assertEqual((vm.get('A'),vm.get('MONEY'),vm.get('ITEM:150')), (150,20,1))
        self.assertIn('[150] 地図($30)', self.output.getvalue())

    def test_shop_zero_disables_builtin_buy(self):
        vm = self.make('@SYSTEM_TITLE\nBEGIN SHOP\n@SHOW_SHOP\nRETURN\n@USERSHOP\nA=RESULT\nQUIT', csv={'_replace.csv':'販売アイテム数,0'}, inputs=['0'])
        vm.run(); self.assertEqual(vm.exit_reason, 'quit')

    def test_failed_purchase_repeats_input_without_show(self):
        vm = self.make('@SYSTEM_TITLE\nBEGIN SHOP\n@SHOW_SHOP\nA++\n@USERSHOP\nB=RESULT\nQUIT', inputs=['1','2','999'])
        vm.run(); self.assertEqual((vm.get('A'),vm.get('B')), (1,999))

    def test_title_menu_replacements(self):
        vm = self.make('@EVENTFIRST\nQUIT\n',csv={'_replace.csv':'システムメニュー0,開始する\nシステムメニュー1,読む'}, inputs=['9','0'])
        vm.run(); self.assertIn('[0] 開始する\n[1] 読む', self.output.getvalue())
        self.assertIn('無効な値です',self.output.getvalue());self.assertNotIn('[9]',self.output.getvalue())


class TrainTests(Harness):
    def train_vm(self, functions, event='', ids='3,歩く\n7,休む', inputs=None, replacements='', **kwargs):
        return self.make('@SYSTEM_TITLE\nADDVOIDCHARA\nTARGET=0\nBEGIN TRAIN\n@EVENTTRAIN\n'+event+'\nRETURN\n'+functions,
            csv={'Train.csv':ids,'_replace.csv':replacements}, inputs=inputs, **kwargs)

    def test_ordinal_menu_maps_to_csv_id(self):
        vm = self.train_vm('@COM7\nA=SELECTCOM\nQUIT', inputs=['1'])
        vm.run(); self.assertEqual(vm.get('A'), 7)
        self.assertIn('[0] 歩く',self.output.getvalue())
        self.assertIn('[1] 休む',self.output.getvalue())

    def test_unavailable_menu_slot_keeps_ordinal(self):
        vm = self.train_vm('@COM_ABLE3\nRETURN 0\n@COM7\nA=SELECTCOM\nQUIT', inputs=['1'])
        vm.run(); self.assertEqual(vm.get('A'),7)
        self.assertNotIn('[0] 歩く',self.output.getvalue())

    def test_com_able_default_zero(self):
        vm = self.train_vm('@COM_ABLE7\nRETURN 1\n@COM7\nA=SELECTCOM\nQUIT', inputs=['1'], replacements='COM_ABLE初期値,0')
        vm.run(); self.assertEqual(vm.get('A'),7)
        self.assertNotIn('[0]',self.output.getvalue())

    def test_availability_cached_not_recalled_on_selection(self):
        vm = self.train_vm('@COM_ABLE3\nA++\nRETURN 1\n@COM3\nQUIT', inputs=['0'])
        vm.run(); self.assertEqual(vm.get('A'),1)

    def test_calltrain_snapshot_order_and_continuation(self):
        vm = self.train_vm('@COM3\nB=B*10+3\nPRINTL run3\nRETURN 0\n@COM7\nB=B*10+7\nPRINTL run7\nRETURN 0\n@CALLTRAINEND\nC++\nQUIT',
            event='SELECTCOM:1=7,3\nCALLTRAIN 2\nSELECTCOM:2=7\nA=42')
        vm.run(); self.assertEqual((vm.get('A'),vm.get('B'),vm.get('C')), (42,73,1))
        self.assertIsNone(vm.train_queue)

    def test_calltrain_status_suppression_noskip_and_visible_commands(self):
        vm = self.train_vm('@SHOW_STATUS\nPRINTL hidden-status\nNOSKIP\nPRINTL visible-status\nENDNOSKIP\n@SHOW_USERCOM\nPRINTL hidden-menu\n@COM3\nPRINTL visible-command\nRETURN 0\n@CALLTRAINEND\nQUIT',
            event='SELECTCOM:1=3\nCALLTRAIN 1')
        vm.run(); output=self.output.getvalue()
        self.assertNotIn('hidden',output); self.assertIn('visible-status',output); self.assertIn('visible-command',output)

    def test_calltrain_invalid_choice_goes_to_usercom(self):
        vm = self.train_vm('@USERCOM\nA=RESULT\n@CALLTRAINEND\nB++\nQUIT', event='SELECTCOM:1=55\nCALLTRAIN 1')
        vm.run(); self.assertEqual((vm.get('A'),vm.get('B')), (55,1))

    def test_stopcalltrain_callback_inline_then_resume(self):
        vm = self.train_vm('@CALLTRAINEND\nA=A*10+2\nRETURN',
            event='SELECTCOM:1=3,7\nCALLTRAIN 2\nA=1\nSTOPCALLTRAIN\nA=A*10+3\nQUIT')
        vm.run(); self.assertEqual(vm.get('A'),123)

    def test_stopcalltrain_inactive_is_noop(self):
        vm = self.script('STOPCALLTRAIN\nA=7')
        self.assertEqual(vm.get('A'),7)

    def test_calltrain_bounds(self):
        for count in (-1,1000):
            vm = self.make('@MAIN\nCALLTRAIN '+str(count))
            with self.subTest(count=count), self.assertRaises(EraError) as caught: vm.call('MAIN')
            self.assertEqual(caught.exception.code,'E_ARGUMENT')

    def test_active_queue_replacement_is_explicitly_unsupported(self):
        vm = self.make('@MAIN\nSELECTCOM:1=0\nCALLTRAIN 1\nCALLTRAIN 1')
        # SetCommnds replaces the list without rejecting an active queue.
        vm.call('MAIN')
        self.assertEqual(list(vm.train_queue),[0])

    def test_dotrain_abandons_frames_without_reinitializing_train(self):
        vm = self.train_vm('@HELPER\nDOTRAIN 7\n@COM7\nA=TFLAG:1\nB=UP:0\nC=SELECTCOM\nQUIT\n@COM_ABLE7\nTHROW must not run',
            event='TFLAG:1=42\nUP:0=99\nCALL HELPER\nTHROW must not resume')
        vm.run(); self.assertEqual((vm.get('A'),vm.get('B'),vm.get('C')), (42,0,7))

    def test_dotrain_allows_unnamed_but_in_range_csv_id(self):
        vm = self.train_vm('@COM50\nA=SELECTCOM\nQUIT', event='DOTRAIN 50')
        vm.run(); self.assertEqual(vm.get('A'),50)

    def test_dotrain_cancels_queue_without_end_callback(self):
        vm = self.train_vm('@SHOW_STATUS\nDOTRAIN 9\n@COM9\nA=9\nPRINTL forced-command\nQUIT\n@CALLTRAINEND\nTHROW must not run',
            event='SELECTCOM:1=3,7\nCALLTRAIN 2')
        vm.run(); self.assertEqual(vm.get('A'),9);self.assertNotIn('forced-command',self.output.getvalue())

    def test_dotrain_rejected_from_eventcom(self):
        vm = self.train_vm('@EVENTCOM\nDOTRAIN 7\n@COM3\nQUIT', inputs=['0'])
        with self.assertRaises(EraError) as caught: vm.run()
        self.assertIn(caught.exception.code,('E_FLOW','E_METHOD_CONTEXT'))
        self.assertEqual(caught.exception.location.line,9)

    def test_dotrain_bounds(self):
        for target in (-1,1000):
            vm = self.train_vm('',event='DOTRAIN '+str(target))
            with self.subTest(target=target), self.assertRaises(EraError) as caught:vm.run()
            self.assertEqual(caught.exception.code,'E_INDEX')

    def test_eventcom_can_redirect_selected_command(self):
        vm = self.train_vm('@EVENTCOM\nSELECTCOM=7\n@COM7\nA=7\nQUIT', inputs=['0'])
        vm.run();self.assertEqual(vm.get('A'),7)

    def test_nextcom_resets_to_zero_before_eventcom(self):
        vm = self.train_vm('@EVENTCOM\nA=NEXTCOM\nNEXTCOM=-1\n@COM7\nB=SELECTCOM\nQUIT',event='NEXTCOM=7')
        vm.run();self.assertEqual((vm.get('A'),vm.get('B')),(0,7))

    def test_nextcom_legacy_loop_still_budgeted(self):
        vm = self.train_vm('@COM0\nRETURN 0',event='NEXTCOM=0',max_steps=50)
        with self.assertRaises(EraError) as caught:vm.run()
        self.assertEqual(caught.exception.code,'E_LIMIT')

    def test_prevcom_not_overwritten_by_engine(self):
        vm = self.train_vm('@COM3\nPREVCOM=88\nRETURN 0\n@CALLTRAINEND\nA=PREVCOM\nQUIT',event='SELECTCOM:1=3\nCALLTRAIN 1')
        vm.run();self.assertEqual(vm.get('A'),88)

    def test_source_cleared_before_eventcomend(self):
        vm = self.train_vm('@COM3\nSOURCE:0=7\nRETURN 1\n@SOURCE_CHECK\nA=SOURCE:0\n@EVENTCOMEND\nB=SOURCE:0\nQUIT',inputs=['0'])
        vm.run();self.assertEqual((vm.get('A'),vm.get('B')),(7,0))

    def test_entry_begin_enters_system_flow(self):
        vm = self.make('@MAIN\nBEGIN SHOP\n@SHOW_SHOP\nA=7\nQUIT')
        vm.run('MAIN');self.assertEqual(vm.get('A'),7)


class SkipTests(Harness):
    def test_skipped_print_does_not_evaluate_argument(self):
        vm = self.script('SKIPDISP 1\nPRINTV 1/0\nA=7\nSKIPDISP 0\nPRINTL visible')
        self.assertEqual(vm.get('A'),7);self.assertEqual(self.output.getvalue(),'visible\n')

    def test_skipped_printdata_does_not_evaluate_or_draw(self):
        vm = self.script('SKIPDISP 1\nPRINTDATAL\nDATAFORM {1/0}\nENDDATA\nSKIPDISP 0')
        self.assertEqual(self.output.getvalue(),'')

    def test_isskip_flag_and_skipdisp_result(self):
        vm = self.script('SKIPDISP 1\nA=RESULT\nB=ISSKIP()\nSKIPDISP 0\nC=ISSKIP()')
        self.assertEqual((vm.get('A'),vm.get('B'),vm.get('C')),(1,1,0))

    def test_noskip_input_and_restoration(self):
        vm = self.script('SKIPDISP 1\nNOSKIP\nPRINTL prompt\nINPUT\nA=RESULT\nB=ISSKIP()\nENDNOSKIP\nC=ISSKIP()',inputs=['42'])
        self.assertEqual((vm.get('A'),vm.get('B'),vm.get('C')),(42,0,1))
        self.assertEqual(self.output.getvalue(),'prompt\n42\n')

    def test_input_while_skipped_is_actionable_error(self):
        vm = self.make('@MAIN\nSKIPDISP 1\nINPUT',inputs=['1'])
        with self.assertRaises(EraError) as caught:vm.call('MAIN')
        self.assertEqual(caught.exception.code,'E_INPUT_SKIP')
        self.assertIn('NOSKIP',caught.exception.message)

    def test_skipped_wait_does_not_consume_input(self):
        output=io.StringIO();console=Console(['5'],output,no_wait=False)
        console.skip_print=True;console.wait();console.skip_print=False
        self.assertEqual(console.input(),5)

    def test_noskip_guard_restores_on_early_return(self):
        vm=self.make('@MAIN\nSKIPDISP 1\nCALL F\nA=ISSKIP()\nRETURN\n@F\nNOSKIP\nRETURN\nENDNOSKIP')
        vm.call('MAIN');self.assertEqual(vm.get('A'),1)

    def test_noskip_guard_survives_tail_jump(self):
        vm=self.make('@MAIN\nSKIPDISP 1\nCALL F\nA=ISSKIP()\nRETURN\n@F\nNOSKIP\nJUMP G\nENDNOSKIP\n@G\nRETURN')
        vm.call('MAIN');self.assertEqual(vm.get('A'),1)

    def test_unmatched_noskip_detected_during_load(self):
        for body in ('NOSKIP','ENDNOSKIP'):
            with self.subTest(body=body),self.assertRaises(EraError) as caught:self.make('@MAIN\n'+body)
            self.assertEqual(caught.exception.code,'E_SYNTAX')

    def test_nested_noskip_explicitly_rejected(self):
        with self.assertRaises(EraError) as caught:self.make('@MAIN\nNOSKIP\nNOSKIP\nENDNOSKIP\nENDNOSKIP')
        self.assertEqual(caught.exception.code,'E_UNSUPPORTED')


class EvidenceTests(Harness):
    def command(self,vm,*args):
        return subprocess.run([sys.executable,'-m','pyemuera',str(vm.root),*map(str,args)],cwd=ROOT,capture_output=True,text=True,timeout=15)

    def test_journal_is_bounded_and_has_no_game_text(self):
        base=self.make('@MAIN\nREPEAT 100\nPRINTL confidential-game-text\nREND\nRETURN')
        journal=RunJournal(seed=1,trace_limit=8)
        vm=VM(base.program,GameData(base.root),Console(output=io.StringIO(),no_wait=True,journal=journal),journal=journal)
        vm.run('MAIN');report=journal.report(vm.exit_reason)
        self.assertEqual(len(report['recent_execution']),8)
        self.assertTrue(report['history_truncated'])
        self.assertNotIn('confidential-game-text',json.dumps(report))
        self.assertEqual(report['function_entries']['MAIN'],1)
        self.assertFalse(report['gameplay_verified'])

    def test_json_record_and_replay_roundtrip(self):
        vm=self.make('@MAIN\nINPUTS\nPRINTSL RESULTS\nINPUT\nPRINTVL RESULT\nQUIT')
        inputs=vm.root/'inputs.txt';inputs.write_text('秘密の入力\n42\n',encoding='utf-8')
        recording=vm.root/'record.json';session=vm.root/'session.json'
        result=self.command(vm,'--entry','MAIN','--inputs',inputs,'--no-wait','--record-inputs',recording,'--session-report',session)
        self.assertEqual(result.returncode,0,result.stderr)
        metadata=json.loads(recording.read_text());report=json.loads(session.read_text())
        self.assertEqual(metadata['inputs'][0],{'kind':'string','text':'秘密の入力'})
        self.assertEqual(report['outcome'],'quit')
        self.assertNotIn('秘密の入力',session.read_text())
        replay=self.command(vm,'--inputs',recording)
        self.assertEqual(replay.returncode,0,replay.stderr)
        self.assertEqual(result.stdout,replay.stdout)

    def test_json_replay_source_mismatch_and_explicit_override(self):
        vm=self.make('@MAIN\nINPUT\nQUIT');inputs=vm.root/'inputs.txt';inputs.write_text('1\n');record=vm.root/'r.json'
        result=self.command(vm,'--entry','MAIN','--inputs',inputs,'--record-inputs',record)
        self.assertEqual(result.returncode,0,result.stderr)
        (vm.root/'ERB/Main.ERB').write_text('@MAIN\nINPUT\nA=7\nQUIT')
        failed=self.command(vm,'--inputs',record)
        self.assertNotEqual(failed.returncode,0);self.assertIn('E_REPLAY',failed.stderr)
        allowed=self.command(vm,'--inputs',record,'--allow-replay-mismatch')
        self.assertEqual(allowed.returncode,0,allowed.stderr)

    def test_typed_input_kind_mismatch(self):
        console=Console([{'kind':'wait','text':''}],io.StringIO())
        with self.assertRaises(EraError) as caught:console.input()
        self.assertEqual(caught.exception.code,'E_REPLAY')

    def test_eof_is_not_reported_as_success(self):
        vm=self.make('@MAIN\nINPUT\nINPUT\nQUIT');inputs=vm.root/'inputs.txt';inputs.write_text('1\n');session=vm.root/'s.json'
        result=self.command(vm,'--entry','MAIN','--inputs',inputs,'--session-report',session)
        self.assertEqual(result.returncode,1)
        report=json.loads(session.read_text());self.assertEqual(report['outcome'],'input_exhausted')
        self.assertEqual(report['error']['code'],'E_INPUT_EOF')
        self.assertEqual(report['error']['line'],3)

    def test_check_catches_global_declaration_error(self):
        vm=self.make();(vm.root/'ERB/Bad.ERH').write_text('#DIM BROKEN,UNKNOWN_SIZE')
        report=vm.root/'check.json';result=self.command(vm,'--check','--report',report)
        self.assertEqual(result.returncode,2,result.stderr)
        data=json.loads(report.read_text());self.assertFalse(data['initialization_checked'])
        self.assertTrue(any(i['code']=='E_VARIABLE' for i in data['issues']))

    def test_existing_report_protected(self):
        vm=self.make();path=vm.root/'r.json';path.write_text('keep me')
        with self.assertRaises(EraError):write_report(path,{},vm.root)
        self.assertEqual(path.read_text(),'keep me')
        write_report(path,{'ok':True},vm.root,overwrite=True)
        self.assertEqual(json.loads(path.read_text()),{'ok':True})

    def test_report_cannot_overwrite_own_save(self):
        vm=self.make();path=vm.root/'.pyemuera/saves/0.json'
        with self.assertRaises(EraError):write_report(path,{},vm.root,overwrite=True)

    def test_record_cannot_overwrite_replay_even_with_flag(self):
        vm=self.make();inputs=vm.root/'r.json';inputs.write_text('original')
        result=self.command(vm,'--inputs',inputs,'--record-inputs',inputs,'--overwrite-reports')
        self.assertEqual(result.returncode,1);self.assertEqual(inputs.read_text(),'original')

    def test_bad_replay_format_rejected(self):
        vm=self.make();path=vm.root/'r.json';path.write_text('{"inputs":[]}')
        with self.assertRaises(EraError) as caught:load_replay(path)
        self.assertEqual(caught.exception.code,'E_REPLAY')

    def test_error_reporting_preserves_game_sources(self):
        vm=self.make('@MAIN\nNOT_IMPLEMENTED\nQUIT');source=(vm.root/'ERB/Main.ERB').read_bytes()
        result=self.command(vm,'--entry','MAIN','--report',vm.root/'check.json','--error-report',vm.root/'error.json','--session-report',vm.root/'session.json')
        self.assertEqual(result.returncode,1)
        self.assertEqual((vm.root/'ERB/Main.ERB').read_bytes(),source)
        self.assertEqual(json.loads((vm.root/'error.json').read_text())['error']['code'],'E_LOAD')
        self.assertEqual(json.loads((vm.root/'session.json').read_text())['recent_execution'],[])


class FinalGuardTests(Harness):
    def test_train_command_cannot_escape_expression(self):
        vm=self.make('@MAIN\nA=SIDE()\nRETURN\n@SIDE\n#FUNCTION\nCALLTRAIN 1\nRETURNF 0')
        with self.assertRaises(EraError) as caught:vm.call('MAIN')
        self.assertIn(caught.exception.code,('E_FLOW','E_METHOD_CONTEXT'))
        self.assertIsNone(vm.train_queue)

    def test_declaration_cannot_execute_game_function(self):
        base=self.make('@SIDE\n#FUNCTION\nSAVEDATA 8,"must-not-write"\nRETURNF 1')
        (base.root/'ERB/Unsafe.ERH').write_text('#DIM VALUE = SIDE()')
        with self.assertRaises(EraError) as caught:
            VM(Program(base.root),GameData(base.root))
        self.assertEqual(caught.exception.code,'E_UNSUPPORTED')
        self.assertFalse((base.root/'.pyemuera').exists())

    def test_builtin_initializers_still_work(self):
        vm=self.make(headers='#DIM CONST VALUE = MAX(2,8)')
        self.assertEqual(vm.get('VALUE'),8)

    def test_bad_replay_metadata(self):
        vm=self.make();path=vm.root/'r.json'
        valid={'format':'PyEmueraInput1','engine_version':'3.0.0a2','seed':1,'no_wait':True,
               'sources_sha256':'a'*64,'inputs':[],'entry':None,'debug':False}
        for key,value in [('entry',12),('debug','false'),('engine_version',9),('sources_sha256','z'*64)]:
            with self.subTest(key=key):
                path.write_text(json.dumps({**valid,key:value}))
                with self.assertRaises(EraError) as caught:load_replay(path)
                self.assertEqual(caught.exception.code,'E_REPLAY')

    def test_calltrainend_can_force_next_command(self):
        vm=self.make('@SYSTEM_TITLE\nADDVOIDCHARA\nTARGET=0\nBEGIN TRAIN\n@EVENTTRAIN\nSELECTCOM:1=3\nCALLTRAIN 1\nRETURN\n@COM3\nRETURN 0\n@CALLTRAINEND\nDOTRAIN 7\n@COM7\nA=7\nQUIT',csv={'Train.csv':'3,歩く\n7,休む'})
        vm.run();self.assertEqual(vm.get('A'),7)
