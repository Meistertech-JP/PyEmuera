from test_core import Harness
from pyemuera.errors import EraError

class EventAttributeA9(Harness):
    def test_single_skips_current_group_only(self):
        vm=self.make('''@EVENTX\n#PRI\n#SINGLE\nA+=1\nRETURN 1\n@EVENTX\n#PRI\nA+=100\nRETURN 0\n@EVENTX\nA+=10\nRETURN 0\n@EVENTX\n#LATER\nA+=1000\nRETURN 0''')
        vm.event('EVENTX');self.assertEqual(vm.get('A'),1011)
    def test_pri_later_runs_twice(self):
        vm=self.make('''@EVENTX\n#PRI\n#LATER\nA+=1\nRETURN 0''')
        vm.event('EVENTX');self.assertEqual(vm.get('A'),2)
    def test_only_runs_first_only(self):
        vm=self.make('''@EVENTX\n#ONLY\nA+=1\nRETURN 0\n@EVENTX\n#ONLY\nA+=100\nRETURN 0\n@EVENTX\nA+=1000\nRETURN 0''')
        vm.event('EVENTX');self.assertEqual(vm.get('A'),1)

class UserFunctionArgsA9(Harness):
    def test_omitted_arg_gets_implicit_zero_default(self):
        vm=self.make('@F(ARG:0)\nRETURN ARG:0')
        self.assertEqual(vm.call('F'),0)
    def test_default_argument_is_used(self):
        vm=self.make('@F(ARG:0=7)\nRETURN ARG:0')
        self.assertEqual(vm.call('F'),7)
    def test_optional_compatibility_switch(self):
        vm=self.make('@F(ARG:0)\nRETURN ARG:0',csv={'_fixed.config':'ユーザー関数の全ての引数の省略を許可する:YES\n'})
        self.assertEqual(vm.call('F'),0)
    def test_int_to_string_requires_compatibility_switch(self):
        vm=self.make('@F(ARGS:0)\nRETURN\n')
        with self.assertRaises(EraError): vm.call('F',[12])
        vm=self.make('@F(ARGS:0)\n#FUNCTIONS\nRETURNF ARGS:0',csv={'_fixed.config':'ユーザー関数の引数に自動的にTOSTRを補完する:YES\n'})
        self.assertEqual(vm.eval('F(12)'),'12')
