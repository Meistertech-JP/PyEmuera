"""Native source contracts, independent from pixel/font rendering."""
import codecs
import io
from pathlib import Path
from test_core import Harness
from pyemuera.settings import Settings
from pyemuera.text import load_config
from pyemuera.console import Console
from pyemuera.errors import EraError
from pyemuera import outputlog


class StringsSettings(Harness):
    def config(self, files):
        vm=self.make()
        for name,text in files.items():
            (vm.data.root/name).write_text(text,encoding='utf-8-sig')
        warnings=[]
        return load_config(vm.data.root,warnings=warnings),warnings

    def test_money_default_prefix_signed_boundaries(self):
        vm=self.make()
        for n in (0,-1,10,-9223372036854775808,9223372036854775807):
            literal='(-9223372036854775807-1)' if n==-(1<<63) else str(n)
            self.assertEqual(vm.eval(f'MONEYSTR({literal})'),'$'+str(n))

    def test_money_config_position_bool_aliases(self):
        for raw,expected in [('後','-10円'),('0','-10円'),('YES','円-10'),('-2','円-10')]:
            vm=self.make(csv={'_replace.csv':f'MoneyLabel,円\nMoneyFirst,{raw}\n'})
            self.assertEqual(vm.eval('MONEYSTR(-10)'),expected)

    def test_money_format_keeps_prefix_and_sign_outside_width(self):
        vm=self.make()
        self.assertEqual(vm.eval('MONEYSTR(-10,"D4")'),'$-0010')

    def test_shop_literal_spacing_and_grouping(self):
        vm=self.make('@MAIN\nPRINT_SHOPITEM 1/0\nRETURN\n',csv={'Item.csv':'1,Named,10\n2,Free,0\n'})
        vm.set('ITEMSALES:1',1);vm.set('ITEMSALES:2',1)
        vm.call('MAIN')
        self.assertEqual(list(vm.console.lines), ['[1] Named($10)            [2] Free($0)              '])

    def test_join_result_is_not_limited_by_display_buffer(self):
        vm=self.make()
        vm.set('STR:0','a'*1999);vm.set('STR:1','bc')
        self.assertEqual(vm.eval('STRLENSU(STRJOIN(STR,"",0,2))'),2001)
        self.assertEqual(vm.eval('STRJOIN(STR,"",0,2)')[-2:],'bc')

    def test_print_2000_utf16_limit_does_not_modify_variable(self):
        vm=self.make('@MAIN\nPRINTS STR\nPRINTSL "z"\nRETURN\n')
        vm.set('STR','a'*2001);vm.call('MAIN')
        self.assertEqual(vm.get('STR'),'a'*2001)
        self.assertTrue(vm.console.lines[0].startswith('a'*2000+'※※※'))
        self.assertNotIn('z',vm.console.lines[0])

    def test_print_exact_2000_then_new_line_resets_buffer(self):
        vm=self.make('@MAIN\nPRINTSL STR\nPRINTL next\nRETURN\n')
        vm.set('STR','a'*2000);vm.call('MAIN')
        self.assertEqual(list(vm.console.lines),['a'*2000,'next'])

    def test_print_cap_counts_surrogate_units(self):
        vm=self.make('@MAIN\nPRINTSL STR\nRETURN\n');vm.set('STR','😀'*1001);vm.call('MAIN')
        self.assertTrue(vm.console.lines[0].startswith('😀'*1000+'※※※'))

    def test_temporary_message_visible_during_wait_then_removed(self):
        con=Console(['9'],io.StringIO(),no_wait=True)
        con.reuse_line('売っていません。')
        original=con._read_input_entry
        observed=[]
        def read(*args):
            observed.append((con.current,con.temporary_line,list(con.lines)))
            return original(*args)
        con._read_input_entry=read
        self.assertEqual(con.input(),9)
        self.assertEqual(observed,[('売っていません。',True,[])])
        self.assertEqual((con.current,con.temporary_line,list(con.lines)),('',False,[]))

    def test_config_native_order_and_fixed_alias_lock(self):
        config,warnings=self.config({'_default.config':'FontSize:99\n',
            'CSV/default.config':'FontSize:11\n','emuera.config':'フォントサイズ:12\n',
            '_fixed.config':'FontSize:98\n','CSV/fixed.config':'FontSize:13\nフォントサイズ:14\n'})
        self.assertEqual(config['FontSize'],'13');self.assertEqual(config['フォントサイズ'],'13')
        self.assertFalse(warnings)

    def test_config_underscore_preferred_over_fallback(self):
        config,_=self.config({'CSV/default.config':'FontSize:11\n','CSV/_default.config':'FontSize:12\n'})
        self.assertEqual(config['FontSize'],'12')

    def test_config_invalid_stops_file_but_later_file_loads(self):
        config,warnings=self.config({'CSV/_default.config':'FontSize:12\nPrintCLength:oops\nFontSize:13\n',
            'emuera.config':'PrintCLength:28\n'})
        self.assertEqual((config['FontSize'],config['PrintCLength']),('12','28'))
        self.assertIn('CSV/_default.config:2',warnings[0])

    def test_config_unknown_ignored_and_int32_overflow_stops(self):
        config,warnings=self.config({'emuera.config':'Unknown:hello\nFontSize:2147483648\nPrintCLength:33\n'})
        self.assertNotIn('Unknown',config);self.assertNotIn('PrintCLength',config)
        self.assertIn('数字でない文字が含まれています',warnings[0])

    def test_config_empty_skips_but_whitespace_bool_stops(self):
        config,warnings=self.config({'emuera.config':'AutoSave:\nAutoSave: \nFontSize:33\n'})
        self.assertNotIn('AutoSave',config);self.assertNotIn('FontSize',config)
        self.assertEqual(len(warnings),1)

    def test_replace_duplicate_invalid_preserves_prefix_and_stops(self):
        vm=self.make(csv={'_replace.csv':'お金の単位,円\nお金の単位, \n販売アイテム数,bad\nお金の単位,X\n'})
        self.assertEqual(vm.data.settings.money_label,'円')
        self.assertEqual(vm.data.settings.shop_limit,100)
        self.assertTrue(any('数字でない' in w for w in vm.data.warnings))

    def test_replace_partial_array_on_error(self):
        vm=self.make(csv={'_replace.csv':'汚れの初期値,9/8/oops/7\nMoneyLabel,X\n'})
        self.assertEqual(vm.data.settings.stain,(9,8));self.assertEqual(vm.data.settings.money_label,'$')

    def test_replace_char_failure_does_not_stop_file(self):
        vm=self.make(csv={'_replace.csv':'BAR文字1,ab\nMoneyLabel,円\n'})
        self.assertEqual(vm.data.settings.bar_full,'*');self.assertEqual(vm.data.settings.money_label,'円')

    def test_replace_colon_alias_and_trimming(self):
        vm=self.make(csv={'_replace.csv':'MoneyLabel: 円:銭,金 \n'})
        self.assertEqual(vm.data.settings.money_label,'円:銭,金')

    def test_getconfig_native_defaults_types_and_allowed_subset(self):
        vm=self.make()
        self.assertEqual(vm.eval('GETCONFIG("MoneyFirst")'),1)
        self.assertEqual(vm.eval('GETCONFIGS("FontName")'),'ＭＳ ゴシック')
        self.assertEqual(vm.eval('GETCONFIG("ForeColor")'),0xc0c0c0)
        with self.assertRaises(EraError) as caught:vm.eval('GETCONFIGS("FontSize")')
        self.assertIn('型が違います',caught.exception.message)
        with self.assertRaises(EraError) as caught:vm.eval('GETCONFIG("UseMouse")')
        self.assertIn('取得は許可されていません',caught.exception.message)

    def test_outputlog_native_utf16_committed_rows_then_notification(self):
        vm=self.make();vm.console.write('first',True);vm.console.write('pending')
        outputlog.write(vm)
        path=vm.data.root/'.pyemuera/logs/emuera.log'
        raw=path.read_bytes()
        self.assertTrue(raw.startswith(codecs.BOM_UTF16_LE))
        self.assertEqual(raw.decode('utf-16'),'first\r\n')
        self.assertEqual(vm.console.lines[-1],'※※※ログファイルをemuera.logに出力しました※※※')
        outputlog.write(vm)
        self.assertIn('※※※ログファイルをemuera.logに出力しました※※※',path.read_text(encoding='utf-16'))

    def test_getfont_reports_config_name_without_host_font_substitution(self):
        vm=self.make(csv={'_fixed.config':'FontName:Native Test Font\n'})
        self.assertEqual(vm.eval('GETFONT()'),'Native Test Font')

    def test_unicode_controls_return_empty_and_warn_each_time(self):
        vm=self.make('@MAIN\nA=1\nSTR \'= UNICODE(A)\nSTR:1 \'= UNICODE(A)\nRETURN\n')
        vm.call('MAIN')
        self.assertEqual((vm.get('STR'),vm.get('STR:1')),('',''))
        self.assertEqual(list(vm.console.lines),[
            '注意:Main.ERBの3行目でUNICODE関数に制御文字に対応する値(0x1)が渡されました',
            '注意:Main.ERBの4行目でUNICODE関数に制御文字に対応する値(0x1)が渡されました'])
        self.assertEqual(vm.eval('UNICODE(31)'),chr(31))
        self.assertEqual(vm.eval('UNICODE(10)'),chr(10))

    def test_outputlog_failure_has_no_success_notice_or_record(self):
        from unittest.mock import patch
        vm=self.make()
        with patch.object(vm.saves,'atomic_write',side_effect=OSError('disk full')):
            outputlog.write(vm)
        self.assertEqual(list(vm.console.lines),[])
        self.assertFalse(getattr(vm,'outputlog_records',[]))

    def test_print_item_void_never_parses_or_evaluates_raw_argument(self):
        from pyemuera.status_display import execute
        vm=self.make()
        before=vm.rng.getstate()
        for raw in ('1/0','A++,RAND(10)','"unterminated','((('):
            self.assertTrue(execute(vm,'PRINT_ITEM',raw))
        self.assertEqual(vm.get('A'),0);self.assertEqual(vm.rng.getstate(),before)
        self.assertEqual(list(vm.console.lines),['所持アイテム：なし']*4)

    def test_system_notices_are_not_suppressed_by_skipdisp(self):
        vm=self.make('@MAIN\nSKIPDISP 1\nSTR \'= UNICODE(1)\nOUTPUTLOG\nRETURN\n')
        vm.call('MAIN')
        self.assertEqual(len(vm.console.lines),2)
        self.assertTrue(vm.console.lines[0].startswith('注意:Main.ERBの3行目'))
        self.assertEqual(vm.console.lines[1],'※※※ログファイルをemuera.logに出力しました※※※')
        self.assertTrue(vm.console.skip_print)

    def test_analysis_maxlog_override_precedes_even_invalid_or_empty_parse(self):
        vm=self.make()
        path=vm.data.root/'CSV/_fixed.config'
        for raw in ('bad','', ' ', '-1','100'):
            path.write_text('MaxLog:'+raw+'\nFontSize:24\n',encoding='utf-8-sig')
            warnings=[]
            result=load_config(vm.data.root,warnings=warnings,analysis_mode=True)
            self.assertEqual(result['MaxLog'],'10000')
            self.assertEqual(result['履歴ログの行数'],'10000')
            self.assertEqual(result['FontSize'],'24')
            self.assertEqual(warnings,[])

    def test_analysis_absent_maxlog_retains_native_default5000(self):
        from pyemuera.config1824 import BY_NAME
        vm=self.make()
        config=load_config(vm.data.root,analysis_mode=True)
        self.assertNotIn('MaxLog',config)
        self.assertEqual(BY_NAME['MaxLog'][3],'5000')

    def test_normal_maxlog_invalid_still_stops_file(self):
        config,warnings=self.config({'CSV/_fixed.config':'MaxLog:bad\nFontSize:24\n'})
        self.assertNotIn('FontSize',config)
        self.assertIn('数字でない文字が含まれています',warnings[0])
