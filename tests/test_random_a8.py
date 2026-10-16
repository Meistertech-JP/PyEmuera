"""SFMT wire compatibility, stream boundaries, and old-Python migration."""
import copy,json,random,unittest
from test_core import Harness,CHARA
from pyemuera.random1824 import SFMT19937,EngineRandom,ALGORITHM
from pyemuera.errors import EraError
from pyemuera import native_save

# Official SFMT19937 seed-1234 vector, independently published by SFMT authors.
GOLDEN=[3440181298,1564997079,1510669302,2930277156,1452439940,3796268453,423124208,2143818589,3827219408,2987036003,2674978610,1536842514,2027035537,2534897563,1686527725,545368292,1489013321,1370534252,4231012796,3994803019]

class SFMTUnit(unittest.TestCase):
    def test_official_19937_1234_uint32(self):
        r=SFMT19937(1234);self.assertEqual([r.uint32() for _ in GOLDEN],GOLDEN)
    def test_reference_uint64_word_order(self):
        r=SFMT19937(1234);self.assertEqual(r.uint64(),GOLDEN[0]<<32|GOLDEN[1])
    def test_reference_modulo_not_rejection_sample(self):
        r=SFMT19937(1234);self.assertEqual(r.randrange(99),((GOLDEN[0]<<32)|GOLDEN[1])%99)
    def test_negative_seed_wraps_to_uint32(self):
        a,b=SFMT19937(-1),SFMT19937(0xffffffff);self.assertEqual(a.get_words(),b.get_words())
    def test_seed_high_word_ignored(self):
        a,b=SFMT19937((1<<32)+1234),SFMT19937(1234);self.assertEqual(a.get_words(),b.get_words())
    def test_all_zero_reference_state_is_not_silently_reseeded(self):
        r=SFMT19937(1234);r.set_words([0]*625);self.assertEqual([r.randrange(17) for _ in range(700)],[0]*700)
    def test_negative_index_atomic(self):
        r=SFMT19937(1234);before=r.get_words()
        with self.assertRaises(EraError):r.set_words([1]*624+[-1])
        self.assertEqual(r.get_words(),before)
    def test_signed_words_cast_uint32(self):
        r=SFMT19937(0);r.set_words([-1]*624+[0]);self.assertEqual(r.uint32(),0xffffffff)
    def test_index_above_block_regenerates(self):
        a=SFMT19937(1);b=SFMT19937(1);state=a.get_words();state[-1]=0x7fffffff;b.set_words(state);self.assertEqual(a.uint64(),b.uint64())
    def test_rng_roundtrip_versioned_json(self):
        a=EngineRandom(1234);[a.randrange(10000) for _ in range(343)];b=EngineRandom();b.setstate(json.loads(json.dumps(a.getstate())))
        self.assertEqual([a.randrange(1000) for _ in range(777)],[b.randrange(1000) for _ in range(777)])
    def test_legacy_python_future_stream_preserved(self):
        a=random.Random(18);a.randrange(999);b=EngineRandom(0);b.setstate(json.loads(json.dumps(a.getstate())))
        self.assertEqual(b.algorithm,'python-mt19937');self.assertEqual([a.randrange(999) for _ in range(777)],[b.randrange(999) for _ in range(777)])
    def test_legacy_native_conversion_refused(self):
        b=EngineRandom();b.setstate(random.Random(7).getstate())
        with self.assertRaises(EraError):b.get_native()
    def test_legacy_explicit_reseed_does_not_consume_stream(self):
        b=EngineRandom();b.setstate(random.Random(7).getstate());before=b.getstate();words=b.get_native(allow_reseed=True)
        self.assertEqual(len(words),625);self.assertEqual(b.getstate(),before);self.assertEqual(b.algorithm,'python-mt19937')
    def test_unknown_state_algorithm_rejected(self):
        r=EngineRandom(42);before=r.getstate()
        with self.assertRaises(EraError):r.setstate({'format':'PyEmueraRNG1','algorithm':'invented','state':[0]*625})
        self.assertEqual(r.getstate(),before)
    def test_invalid_max_range(self):
        for hi in [0,-1,1<<63]:
            with self.subTest(hi=hi),self.assertRaises(EraError):SFMT19937(1).randrange(hi)

for index in [0,1,2,621,622,623,624,625,1247,1248,4999]:
    def case(self,index=index):
        a=SFMT19937(99)
        for _ in range(index):a.uint32()
        b=SFMT19937(0);b.set_words(a.get_words())
        self.assertEqual([a.uint64() for _ in range(701)],[b.uint64() for _ in range(701)])
    setattr(SFMTUnit,'test_block_boundary_'+str(index),case)

class RandomVM(Harness):
    def test_dump_init_reproduces_next_draw(self):
        vm=self.script('RANDOMIZE 1234\nDUMPRAND\nA=RAND:10000\nINITRAND\nB=RAND:10000');self.assertEqual(vm.get('A'),vm.get('B'))
    def test_dump_records_index(self):
        vm=self.script('RANDOMIZE 1234\nA=RAND:999\nDUMPRAND');self.assertEqual(vm.get('RANDDATA:624'),2)
    def test_randomize_omitted_is_seed_zero(self):
        vm=self.script('RANDOMIZE\nA=RAND:99');self.assertEqual(vm.get('A'),SFMT19937(0).randrange(99))
    def test_state_randomize_transitions_from_legacy(self):
        vm=self.make();vm.rng.setstate(random.Random(7).getstate());vm.call('MAIN');self.assertEqual(vm.rng.algorithm,'python-mt19937');vm.rng.seed(0);self.assertEqual(vm.rng.algorithm,ALGORITHM)
    def test_json_saves_randdata_and_active_state_separately(self):
        vm=self.script('RANDOMIZE 1234\nDUMPRAND\nA=RAND:99');words=copy.deepcopy(vm.data.variables['RANDDATA'].values);vm.saves.write(0);expected=vm.rng.randrange(333);vm.saves.load(0)
        self.assertEqual(vm.rng.randrange(333),expected);self.assertEqual(vm.data.variables['RANDDATA'].values,words)
    def test_native_source_mode_does_not_autodump(self):
        vm=self.script('RANDOMIZE 1234');vm.saves.format='emuera-binary';vm.saves.write(0)
        state=native_save.decode(vm.saves.native_path(0).read_bytes());self.assertFalse(state.variables['RANDDATA'].values)
    def test_native_source_load_preserves_active_rng(self):
        vm=self.script('RANDOMIZE 1234\nDUMPRAND');vm.saves.format='emuera-binary';vm.saves.write(0);vm.rng.randrange(99);before=vm.rng.getstate();vm.saves.load(0);self.assertEqual(vm.rng.getstate(),before)
    def test_native_restore_policy_reproduces_next_draw(self):
        for fmt in ['emuera-text','emuera-binary']:
            with self.subTest(fmt=fmt):
                vm=self.script('RANDOMIZE 1234\nA=RAND:99');vm.saves.format=fmt;vm.saves.native_rng='restore';vm.saves.write(0);expected=[vm.rng.randrange(876) for _ in range(667)];vm.saves.load(0)
                self.assertEqual([vm.rng.randrange(876) for _ in range(667)],expected)
    def test_legacy_json_missing_randdata_keeps_python_rng(self):
        vm=self.make();r=random.Random(5);vm.rng.setstate(r.getstate());vm.saves.write(0);p=vm.saves.path(0);d=json.loads(p.read_text());d['variables'].pop('RANDDATA');p.write_text(json.dumps(d));vm.rng.seed(99);vm.saves.load(0)
        self.assertEqual(vm.rng.algorithm,'python-mt19937');self.assertEqual(vm.rng.randrange(1000000),r.randrange(1000000))
    def test_restore_from_legacy_needs_opt_in_reseed(self):
        vm=self.make();vm.rng.setstate(random.Random(4).getstate());vm.saves.format='emuera-binary';vm.saves.native_rng='restore'
        with self.assertRaises(EraError):vm.saves.write(0)
        self.assertFalse(vm.saves.native_path(0).exists());vm.saves.allow_rng_reseed=True;self.assertEqual(vm.saves.write(0),1)
