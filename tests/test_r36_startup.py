"""Native string-item parsing and startup are independent from game execution."""
import io
from unittest.mock import patch
from test_core import Harness
from pyemuera.settings import Settings
from pyemuera.startup import load_label_rows, read_startup, emit_startup
from pyemuera.load_arguments import display_diagnostics
from pyemuera.console import Console
from pyemuera.data import GameData
from pyemuera.errors import EraError
from pyemuera.cli import main

class Startup(Harness):
    def game(self, replace=None, config='', source='@SYSTEM_TITLE\nPRINTL BODY\nQUIT\n'):
        csv={'_fixed.config': config}
        if replace is not None:csv['_Replace.csv']=replace
        return self.make(source,csv=csv)

    def test_absent_file_defaults_and_query_aliases(self):
        vm=self.game()
        self.assertEqual(vm.data.settings.load_label,'Now Loading...')
        self.assertEqual(vm.eval('GETCONFIGS("LoadLabel")'),'Now Loading...')
        self.assertEqual(vm.eval('GETCONFIGS("起動時簡略表示")'),'Now Loading...')

    def test_string_query_wrong_type_remains_error(self):
        vm=self.game('LoadLabel,123')
        with self.assertRaises(EraError) as e:vm.eval('GETCONFIG("LoadLabel")')
        self.assertEqual(e.exception.code,'E_TYPE')
        self.assertIn('GETCONFIGS',e.exception.message)

    def test_native_alias_duplicate_order_is_shared(self):
        vm=self.game('LoadLabel,first\n起動時簡略表示,second\nLoadLabel,third\n')
        self.assertEqual(vm.data.settings.load_label,'third')
        self.assertFalse(any('unsupported setting' in w for w in vm.data.warnings))

    def test_empty_duplicate_cannot_clear_previous_value(self):
        vm=self.game('LoadLabel,first\n起動時簡略表示,   \nLoadLabel:\n')
        self.assertEqual(vm.data.settings.load_label,'first')

    def test_colon_separator_and_remainder_are_preserved(self):
        vm=self.game('起動時簡略表示:  準備, 読み込み:続行  \n')
        self.assertEqual(vm.data.settings.load_label,'準備, 読み込み:続行')

    def test_quoted_string_is_not_ERB_expression(self):
        vm=self.game('LoadLabel,"RAND(10)+A++"\n')
        rng=vm.rng.getstate();display_diagnostics(vm)
        self.assertIn('"RAND(10)+A++"',self.output.getvalue())
        self.assertEqual(vm.rng.getstate(),rng);self.assertEqual(vm.get('A'),0)

    def test_unknown_setting_warning_is_kept(self):
        vm=self.game('UnknownSetting,x\nLoadLabel,known\n')
        # r37: native ignores unknown replace entries; retain the test ID.
        self.assertFalse(any('UnknownSetting' in w for w in vm.data.warnings))
        self.assertEqual(vm.data.settings.load_label,'known')

    def test_startup_is_once_even_without_diagnostics(self):
        vm=self.game('LoadLabel,START\n');rng=vm.rng.getstate()
        display_diagnostics(vm);display_diagnostics(vm);vm.run()
        self.assertEqual(self.output.getvalue(),'START\nBODY\n')
        self.assertEqual(list(vm.console.log_lines),['START','BODY'])
        self.assertEqual(vm.rng.getstate(),rng)
        self.assertEqual(vm.console.input_count,0)
        self.assertEqual(len(vm.program.load_diagnostic_events),0)

    def test_startup_precedes_warnings_without_registering_warning(self):
        vm=self.game('LoadLabel,START\n','FunctionNotFoundWarning:DISPLAY\n','@SYSTEM_TITLE\nCALL ABSENT\nQUIT\n')
        rng=vm.rng.getstate();display_diagnostics(vm)
        text=self.output.getvalue();self.assertTrue(text.startswith('START\n警告Lv2:'))
        self.assertEqual(len(vm.emitted_diagnostics),1)
        self.assertEqual(len(vm.program.load_diagnostic_events),1)
        self.assertEqual((vm.steps,vm.get('A')),(0,0));self.assertEqual(vm.rng.getstate(),rng)

    def test_cli_prints_before_program_and_data_construction(self):
        vm=self.game('LoadLabel,EARLY\n');root=vm.program.root;output=io.StringIO();seen=[]
        from pyemuera import cli
        old_program=cli.Program;old_data=cli.GameData
        def program(*a,**kw):seen.append(('Program',output.getvalue()));return old_program(*a,**kw)
        def data(*a,**kw):seen.append(('GameData',output.getvalue()));return old_data(*a,**kw)
        with patch('sys.stdout',output),patch.object(cli,'Program',side_effect=program),patch.object(cli,'GameData',side_effect=data):
            result=main([str(root),'--no-wait'])
        self.assertEqual(result,0)
        self.assertEqual(seen,[('Program','EARLY\n'),('GameData','EARLY\n')])
        self.assertEqual(output.getvalue().count('EARLY\n'),1)

    def test_check_does_not_emit_game_startup(self):
        vm=self.game('LoadLabel,EARLY\n');output=io.StringIO()
        with patch('sys.stdout',output):code=main([str(vm.program.root),'--check'])
        self.assertEqual(code,0);self.assertNotIn('EARLY',output.getvalue())

    def test_empty_effective_label_skips_row(self):
        self.game();out=io.StringIO();console=Console(output=out)
        emit_startup(console,Settings(load_label=''),{})
        self.assertEqual(out.getvalue(),'');self.assertEqual(console.line_count,0)

    def test_analysis_data_ignores_replace_file(self):
        vm=self.game('LoadLabel,CUSTOM\nDRAWLINE文字,=\n')
        data=GameData(vm.program.root,analysis_mode=True)
        self.assertEqual(data.settings.load_label,'Now Loading...')
        self.assertEqual(data.settings.drawline,'-')
        self.assertNotIn('_REPLACE',data.csv_rows)

    def test_preflight_matches_effective_label(self):
        vm=self.game('LoadLabel,one\n起動時簡略表示:last, value\n')
        settings,config=read_startup(vm.program.root)
        self.assertEqual(settings.load_label,vm.data.settings.load_label)
        self.assertEqual(config,vm.data.config)

for key in ['UseReplaceFile','_Replace.csvを利用する']:
 for value in ['YES','NO']:
    def run(self,key=key,value=value):
        vm=self.game('LoadLabel,CUSTOM\nDRAWLINE文字,=\n',key+':'+value+'\n')
        self.assertEqual(vm.data.settings.load_label,'CUSTOM' if value=='YES' else 'Now Loading...')
        self.assertEqual(vm.data.settings.drawline,'=' if value=='YES' else '-')
        settings,_=read_startup(vm.program.root);self.assertEqual(settings.load_label,vm.data.settings.load_label)
    setattr(Startup,'test_replace_gate_'+str(['UseReplaceFile','_Replace.csvを利用する'].index(key))+'_'+value,run)
for key in ['DisplayReport','ロード時にレポートを表示する']:
 for value in ['YES','NO']:
    def run(self,key=key,value=value):
        vm=self.game('LoadLabel,CUSTOM\n',key+':'+value+'\n')
        display_diagnostics(vm)
        self.assertEqual(self.output.getvalue(),'CUSTOM\n' if value=='NO' else '')
        self.assertEqual(vm.eval('GETCONFIGS("LoadLabel")'),'CUSTOM')
    setattr(Startup,'test_display_gate_'+str(['DisplayReport','ロード時にレポートを表示する'].index(key))+'_'+value,run)
for i,text in enumerate(['LoadLabel,','LoadLabel:  ','LoadLabel',';LoadLabel,ignored','LoadLabel,,,','LoadLabel,123','LoadLabel,  日本語  ']):
    def run(self,text=text):
        vm=self.game(text+'\n')
        expected=text.split(',',1)[-1].strip() if ',' in text and not text.startswith(';') else 'Now Loading...'
        if not expected:expected='Now Loading...'
        self.assertEqual(vm.data.settings.load_label,expected)
    setattr(Startup,'test_string_row_'+str(i),run)

for value,expected in [('2',True),('-1',True),('0',False),('前',True),('後',False),('TRUE',True),('FALSE',False)]:
    def run(self,value=value,expected=expected):
        vm=self.game('LoadLabel,CUSTOM\n','UseReplaceFile:'+value+'\nDisplayReport:'+value+'\n')
        self.assertEqual(vm.data.settings.load_label,'CUSTOM' if expected else 'Now Loading...')
        display_diagnostics(vm)
        self.assertEqual(self.output.getvalue(),'' if expected else 'Now Loading...\n')
    setattr(Startup,'test_native_flag_'+str(['2','-1','0','前','後','TRUE','FALSE'].index(value)),run)
