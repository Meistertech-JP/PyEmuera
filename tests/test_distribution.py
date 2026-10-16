from __future__ import annotations
import io,json,shutil,subprocess,sys,tempfile,unittest,zipapp
from pathlib import Path
from test_core import Harness,CHARA,ROOT
from pyemuera.errors import EraError
from pyemuera.program import Program
from pyemuera.data import GameData
from pyemuera.runtime import VM
from pyemuera.console import Console
from pyemuera.audit import audit
from pyemuera.cli import write_report

class EdgeCases(Harness):
    def test_varset_relation_defaults_zero(self):
        vm=self.script('ADDCHARA 0\nTARGET=0\nVARSET RELATION',csv=CHARA);self.assertEqual(vm.get('RELATION:1'),0)
    def test_excess_builtin_arguments_rejected(self):
        vm=self.make()
        with self.assertRaises(EraError) as c:vm.eval('ABS(1,999)')
        self.assertEqual(c.exception.code,'E_ARGUMENT')
    def test_supplementary_unicode_utf16_length(self):
        vm=self.make();self.assertEqual(vm.eval('STRLENSU("😀")'),2)

    def test_expression_assignment_audit(self):
        vm=self.make('@MAIN\nA=UNSUPPORTED_FUNC(7)\nRETURN');r=audit(vm.program,vm.data);self.assertTrue(any('UNSUPPORTED_FUNC' in x['message'] for x in r['issues']))
    def test_nested_preprocessor(self):
        vm=self.script('[IF MISSING]\n[IF_NDEBUG]\nA=99\n[ELSE]\nA=88\n[ENDIF]\n[ELSEIF PRESENT]\nA=7\n[ELSE]\nA=8\n[ENDIF]',headers='#DEFINE PRESENT 1');self.assertEqual(vm.get('A'),7)
    def test_source_decode_error(self):
        vm=self.make();p=vm.root/'ERB/Main.ERB';p.write_bytes(b'\x81')
        # r37 Windows evidence: the non-flushed decoder drops this EOF lead.
        program=Program(vm.root);self.assertFalse(program.load_errors)
        self.assertFalse(program.functions)
    def test_invalid_for_step(self):
        vm=self.make('@MAIN\nFOR A,0,4,0\nNEXT')
        with self.assertRaises(EraError):vm.call('MAIN')
    def test_tail_call_chain(self):
        vm=self.make('@MAIN\nJUMP F\n@F\nA++\nSIF A<1500\nJUMP F\nRETURN A',max_frames=4);self.assertEqual(vm.call('MAIN'),1500)
    def test_ref_wrong_rank(self):
        vm=self.make('@MAIN\nCALL F,A\nRETURN\n@F(DEST)\n#DIM REF DEST,0,0\nRETURN')
        with self.assertRaises(EraError):vm.call('MAIN')
    def test_call_try_success_skips_catch(self):
        vm=self.make('@MAIN\nTRYCCALL F\nA=2\nCATCH\nA=9\nENDCATCH\nRETURN\n@F\nRETURN');vm.call('MAIN');self.assertEqual(vm.get('A'),2)
    def test_method_recursive_dynamic_parameter(self):
        vm=self.make('@MAIN\nA=FACT(7)\nRETURN\n@FACT(NN)\n#FUNCTION\n#DIM DYNAMIC NN\nSIF NN<=1\nRETURNF 1\nRETURNF NN*FACT(NN-1)');vm.call('MAIN');self.assertEqual(vm.get('A'),5040)
    def test_loadgame_flow_roundtrip(self):
        vm=self.make('@SYSTEM_TITLE\nMONEY=9\nSAVEDATA 0,"test"\nMONEY=1\nLOADDATA 0\nMONEY=8\nQUIT\n@EVENTLOAD\nA=MONEY\nQUIT');vm.run();self.assertEqual(vm.get('A'),9)
    def test_global_unsaved_not_serialized(self):
        vm=self.make(headers='#DIM GLOBAL PERSISTENT_ONLY\n#DIM SAVEDATA GLOBAL SHARED_SAVE');vm.set('PERSISTENT_ONLY',2);vm.set('SHARED_SAVE',5);vm.saves.write('global');vm.set('PERSISTENT_ONLY',3);vm.set('SHARED_SAVE',6);vm.saves.load('global');self.assertEqual((vm.get('PERSISTENT_ONLY'),vm.get('SHARED_SAVE')),(3,5))
    def test_save_wrong_game_atomic(self):
        vm=self.make();vm.saves.write(0);p=vm.saves.path(0);data=json.loads(p.read_text());data['identity']['title']='another';p.write_text(json.dumps(data));vm.set('A',42)
        with self.assertRaises(EraError):vm.saves.load(0)
        self.assertEqual(vm.get('A'),42)
    def test_save_metadata_atomic(self):
        vm=self.make();vm.saves.write(0);p=vm.saves.path(0);data=json.loads(p.read_text());data['description']=[];p.write_text(json.dumps(data));vm.set('A',42)
        with self.assertRaises(EraError):vm.saves.load(0)
        self.assertEqual(vm.get('A'),42)
    def test_save_symlink_escape(self):
        vm=self.make()
        with tempfile.TemporaryDirectory() as t:
            try:(vm.root/'.pyemuera').symlink_to(t,target_is_directory=True)
            except (OSError,NotImplementedError):self.skipTest('symlinks unavailable')
            with self.assertRaises(EraError):vm.saves.write(0)
    def test_report_cannot_overwrite_source(self):
        vm=self.make()
        with self.assertRaises(EraError):write_report(vm.root/'ERB/report.json',{},vm.root)
    def test_report_requires_json(self):
        vm=self.make()
        with self.assertRaises(EraError):write_report(vm.root/'save00.sav',{},vm.root)

class Distribution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.base=Path(cls.tmp.name);cls.staging=cls.base/'staging';cls.staging.mkdir()
        shutil.copytree(ROOT/'pyemuera',cls.staging/'pyemuera',ignore=shutil.ignore_patterns('__pycache__'))
        cls.archive=cls.base/'PyEmuera.pyz';zipapp.create_archive(cls.staging,cls.archive,main='pyemuera.cli:entrypoint',compressed=True)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_zipapp_version(self):
        p=subprocess.run([sys.executable,str(self.archive),'--version'],cwd=self.base,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr);self.assertIn(__import__('pyemuera').__version__,p.stdout)
    def test_zipapp_demo(self):
        p=subprocess.run([sys.executable,str(self.archive),str(ROOT/'examples/smoke'),'--inputs',str(ROOT/'examples/smoke/replay.txt'),'--no-wait'],cwd=self.base,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stderr);self.assertIn('散歩 1回',p.stdout);self.assertIn('残金 50',p.stdout)
    def test_zipapp_check_exit_status(self):
        with tempfile.TemporaryDirectory() as t:
            p=Path(t);(p/'ERB').mkdir();(p/'CSV').mkdir();(p/'ERB/main.erb').write_text('@MAIN\nBOGUS\nRETURN')
            r=subprocess.run([sys.executable,str(self.archive),t,'--check'],cwd=self.base,text=True,capture_output=True)
            self.assertEqual(r.returncode,2,r.stderr)
    def test_zipapp_no_argument_discovery(self):
        with tempfile.TemporaryDirectory() as t:
            dest=Path(t)/'日本語のゲーム';shutil.copytree(ROOT/'examples/smoke',dest);shutil.copy(self.archive,dest/'PyEmuera.pyz')
            p=subprocess.run([sys.executable,str(dest/'PyEmuera.pyz'),'--inputs',str(dest/'replay.txt'),'--no-wait'],cwd=self.base,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stderr);self.assertIn('散歩 1回',p.stdout)
    def test_zipapp_save_load_menu(self):
        with tempfile.TemporaryDirectory() as t:
            dest=Path(t);shutil.copytree(ROOT/'examples/smoke',dest,dirs_exist_ok=True)
            replay=dest/'save_test.txt';replay.write_text('0\n0\n101\n2\n0\n102\n2\n999\n')
            p=subprocess.run([sys.executable,str(self.archive),str(dest),'--inputs',str(replay),'--no-wait'],cwd=self.base,text=True,capture_output=True)
            self.assertEqual(p.returncode,0,p.stderr);self.assertIn('JSONセーブを読み込みました',p.stdout);self.assertTrue((dest/'.pyemuera/saves/2.json').exists())
            self.assertIn('所持金 50 / 地図 1枚',p.stdout[p.stdout.index('JSONセーブを読み込みました'):])
