"""Source-contract tests observe writes, input boundaries, and callback state."""
from test_core import Harness
from pyemuera.errors import EraError, QuitSignal
from pyemuera.flow import shop


class ShopPurchase(Harness):
    SOURCE = ('@SHOW_SHOP\nA++\nPRINT_SHOPITEM\nRETURN 77\n'
              '@EVENTBUY\nB=RESULT\nC++\nPRINTL BOUGHT\nRETURN 81\n'
              '@USERSHOP\nD=RESULT\nQUIT\n')

    def prepare(self, choice=1, *, money=100, sale=1, owned=0, source=None):
        vm = self.make(source or self.SOURCE, inputs=[str(choice), '9999'], csv={
            'Item.csv': '1,Named,10\n3,Free,0\n4,,0\n5,Rebate,-5\n',
            '_fixed.config': 'AutoSave:NO\n',
        })
        vm.set('MONEY', money)
        vm.set('BOUGHT', 88)
        if choice >= 0 and choice < 1000:
            vm.set('ITEMSALES:' + str(choice), sale)
            vm.set('ITEM:' + str(choice), owned)
        self.waits = []
        original = vm.console.input

        def observe(*args, **kwargs):
            self.waits.append({name: vm.get(name) for name in ('MONEY', 'BOUGHT', 'RESULT', 'A', 'C')})
            return original(*args, **kwargs)

        vm.console.input = observe
        return vm

    def finish(self, vm):
        rng = vm.rng.getstate()
        with self.assertRaises(QuitSignal):
            shop(vm, loaded=True)
        self.assertEqual(vm.rng.getstate(), rng)

    def test_undefined_item_cannot_mutate_inventory_or_bought(self):
        vm = self.prepare(2)
        self.finish(vm)
        self.assertEqual((vm.get('MONEY'), vm.get('ITEM:2'), vm.get('BOUGHT'), vm.get('C')), (100, 0, 88, 0))
        self.assertEqual(self.waits[1]['RESULT'], 77)
        self.assertEqual(vm.get('A'), 1)
        self.assertIn('売っていません。', self.output.getvalue())

    def test_unsold_defined_item_retries_without_show_or_buy(self):
        vm = self.prepare(sale=0)
        self.finish(vm)
        self.assertEqual((vm.get('MONEY'), vm.get('ITEM:1'), vm.get('BOUGHT'), vm.get('C'), vm.get('A')), (100, 0, 88, 0, 1))
        self.assertEqual(self.waits[1]['RESULT'], 77)

    def test_owned_disabled_item_is_not_on_sale(self):
        vm = self.prepare(sale=0, owned=1)
        self.finish(vm)
        self.assertEqual(vm.get('ITEM:1'), 1)
        self.assertIn('売っていません。', self.output.getvalue())

    def test_owned_enabled_item_is_purchasable_again(self):
        vm = self.prepare(owned=1)
        self.finish(vm)
        self.assertEqual((vm.get('ITEM:1'), vm.get('MONEY')), (2, 90))

    def test_purchase_preserves_result_for_eventbuy(self):
        vm = self.prepare()
        self.finish(vm)
        self.assertEqual((vm.get('BOUGHT'), vm.get('B'), vm.get('C'), vm.get('A')), (1, 77, 1, 2))

    def test_purchase_write_order_is_money_item_bought(self):
        vm = self.prepare()
        writes = []
        for name in ('MONEY', 'ITEM', 'BOUGHT'):
            vm.data.variables[name].write_observer = lambda var, key, old, value: writes.append((var.name, old, value))
        self.finish(vm)
        self.assertEqual(writes, [('MONEY', 100, 90), ('ITEM', 0, 1), ('BOUGHT', 88, 1)])

    def test_insufficient_money_preserves_state_and_result(self):
        vm = self.prepare(money=9)
        self.finish(vm)
        self.assertEqual(self.waits[1], {'MONEY': 9, 'BOUGHT': 88, 'RESULT': 77, 'A': 1, 'C': 0})
        self.assertEqual(vm.get('ITEM:1'), 0)
        self.assertIn('お金が足りません。', self.output.getvalue())

    def test_zero_price_is_accepted(self):
        vm = self.prepare(3)
        self.finish(vm)
        self.assertEqual((vm.get('ITEM:3'), vm.get('MONEY'), vm.get('C')), (1, 100, 1))

    def test_explicit_empty_name_is_defined_and_displayed(self):
        vm = self.prepare(4)
        self.finish(vm)
        self.assertEqual((vm.get('ITEM:4'), vm.get('BOUGHT')), (1, 4))
        self.assertIn('[4] ($0)', self.output.getvalue())

    def test_negative_price_increases_money(self):
        vm = self.prepare(5)
        self.finish(vm)
        self.assertEqual((vm.get('MONEY'), vm.get('ITEM:5')), (105, 1))

    def test_negative_nonzero_sale_flag_is_enabled(self):
        vm = self.prepare(sale=-1)
        self.finish(vm)
        self.assertEqual(vm.get('ITEM:1'), 1)

    def test_negative_input_updates_result_and_calls_usershop(self):
        vm = self.prepare(-1)
        self.finish(vm)
        self.assertEqual((vm.get('D'), vm.get('RESULT'), vm.get('MONEY'), vm.get('C')), (-1, -1, 100, 0))

    def test_limit_input_uses_usershop_even_when_sale_flag_is_set(self):
        vm = self.prepare(100)
        self.finish(vm)
        self.assertEqual((vm.get('D'), vm.get('RESULT'), vm.get('ITEM:100')), (100, 100, 0))

    def test_missing_usershop_is_an_error_after_result_update(self):
        vm = self.prepare(100, source='@SHOW_SHOP\nRETURN 77\n')
        with self.assertRaises(EraError) as caught:
            shop(vm, loaded=True)
        self.assertEqual(caught.exception.code, 'E_FUNCTION')
        self.assertEqual(vm.get('RESULT'), 100)

    def test_sales_bounds_are_unsold(self):
        vm = self.prepare()
        vm.data.variables['ITEMSALES'].dims = (1,)
        self.finish(vm)
        self.assertEqual(vm.get('C'), 0)
        self.assertIn('売っていません。', self.output.getvalue())

    def test_name_bounds_are_unsold(self):
        vm = self.prepare()
        vm.data.variables['ITEMNAME'].dims = (1,)
        self.finish(vm)
        self.assertEqual(vm.get('C'), 0)
        self.assertIn('売っていません。', self.output.getvalue())

    def test_price_bounds_use_buy_failure_message(self):
        vm = self.prepare()
        vm.data.variables['ITEMPRICE'].dims = (1,)
        self.finish(vm)
        self.assertEqual((vm.get('MONEY'), vm.get('BOUGHT')), (100, 88))
        self.assertIn('お金が足りません。', self.output.getvalue())

    def test_inventory_bounds_preserve_native_partial_money_write(self):
        vm = self.prepare()
        vm.data.variables['ITEM'].dims = (1,)
        with self.assertRaises(EraError) as caught:
            shop(vm, loaded=True)
        self.assertEqual(caught.exception.code, 'E_INDEX')
        self.assertEqual((vm.get('MONEY'), vm.get('BOUGHT'), vm.get('RESULT'), vm.get('C')), (90, 88, 77, 0))

    def test_money_overflow_wraps_before_inventory_write(self):
        vm = self.prepare(5, money=9223372036854775807)
        self.finish(vm)
        self.assertEqual(vm.get('MONEY'), -9223372036854775804)

    def test_inventory_overflow_wraps(self):
        vm = self.prepare(owned=9223372036854775807)
        self.finish(vm)
        self.assertEqual(vm.get('ITEM:1'), -9223372036854775808)

    def test_usershop_temporary_line_retries_without_show(self):
        source = ('@SHOW_SHOP\nA++\nRETURN\n@USERSHOP\nD++\n'
                  'IF D==1\nREUSELASTLINE retry\nRETURN\nENDIF\nQUIT\n')
        vm = self.prepare(100, source=source)
        self.finish(vm)
        self.assertEqual((vm.get('A'), vm.get('D')), (1, 2))

    def test_eventbuy_temporary_line_retries_without_show(self):
        source = self.SOURCE.replace('PRINTL BOUGHT', 'REUSELASTLINE purchased')
        vm = self.prepare(source=source)
        self.finish(vm)
        self.assertEqual((vm.get('A'), vm.get('C')), (1, 1))

    def test_eventbuy_failure_does_not_roll_back_purchase(self):
        source = self.SOURCE.replace('PRINTL BOUGHT', 'X=1/0')
        vm = self.prepare(source=source)
        with self.assertRaises(EraError) as caught:
            shop(vm, loaded=True)
        self.assertEqual(caught.exception.code, 'E_ARITH')
        self.assertEqual((vm.get('MONEY'), vm.get('ITEM:1'), vm.get('BOUGHT'), vm.get('RESULT')), (90, 1, 1, 77))

    def test_definition_presence_survives_reset_and_save_load(self):
        vm = self.prepare(4)
        vm.saves.write(7, 'empty name')
        vm.reset()
        vm.saves.load(7)
        self.finish(vm)
        self.assertEqual(vm.get('ITEM:4'), 1)
