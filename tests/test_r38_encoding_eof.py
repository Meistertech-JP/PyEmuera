"""EOF buffering differs from malformed complete input and literal markers."""
import codecs
import tempfile
import unittest
from pathlib import Path
from pyemuera.source_encoding import decode_source
from pyemuera.native_save import TextReader
from pyemuera.text import read_text
from pyemuera.errors import EraError

CASES = [
    ('cp932_one_lead', b'\x81', ''),
    ('cp932_two_leads_form_character', b'\x81\x81', '＝'),
    ('cp932_invalid_then_pending', b'\x81 \x81', '・'),
    ('cp932_lead_then_lf', b'A\x81\nB', 'A・B'),
    ('cp932_lead_then_crlf', b'A\x81\r\nB', 'A・\nB'),
    ('cp932_literal_middle_dot', b'A\x81\x45', 'A・'),
    ('cp932_complete_invalid_at_end', b'A\x81\xad', 'A・'),
    ('utf8_literal_replacement', codecs.BOM_UTF8 + b'A\xef\xbf\xbd', 'A�'),
    ('utf8_complete_invalid_at_end', codecs.BOM_UTF8 + b'A\xff', 'A�'),
    ('utf8_pending_then_lf', codecs.BOM_UTF8 + b'A\xe3\x81\nB', 'A�\nB'),
    ('utf8_pending_then_ascii', codecs.BOM_UTF8 + b'A\xe3\x81B', 'A�B'),
    ('utf8_complete_invalid_then_pending', codecs.BOM_UTF8 + b'A\xff\xe3\x81', 'A�'),
    ('utf16le_pending_high_surrogate', codecs.BOM_UTF16_LE + b'A\x00\x00\xd8', 'A'),
    ('utf16be_odd_byte', codecs.BOM_UTF16_BE + b'\x00AB', 'A'),
    ('utf16be_pending_high_surrogate', codecs.BOM_UTF16_BE + b'\x00A\xd8\x00', 'A'),
    ('utf16le_invalid_then_pending', codecs.BOM_UTF16_LE + b'\x00\xdcA', '�'),
    ('utf16be_literal_replacement', codecs.BOM_UTF16_BE + b'\xff\xfd', '�'),
    ('utf32le_one_trailing_byte', codecs.BOM_UTF32_LE + b'A\x00\x00\x00B', 'A'),
    ('utf32le_two_trailing_bytes', codecs.BOM_UTF32_LE + b'A\x00\x00\x00B\x00', 'A'),
    ('utf32le_three_trailing_bytes', codecs.BOM_UTF32_LE + b'A\x00\x00\x00B\x00\x00', 'A'),
    ('utf32be_three_trailing_bytes', codecs.BOM_UTF32_BE + b'\x00\x00\x00A\x00\x00\x00', 'A'),
    ('utf32be_complete_invalid', codecs.BOM_UTF32_BE + b'\x00\x11\x00\x00', '�'),
    ('utf32le_literal_middle_dot', codecs.BOM_UTF32_LE + b'\xfb\x30\x00\x00', '・'),
    ('cp932_stream_boundary_eof', b'A' * 1023 + b'\x81', 'A' * 1023),
    ('cp932_stream_boundary_lf', b'A' * 1023 + b'\x81\nB', 'A' * 1023 + '・B'),
]
for label, bom in [('utf8', codecs.BOM_UTF8), ('utf16le', codecs.BOM_UTF16_LE),
                   ('utf16be', codecs.BOM_UTF16_BE), ('utf32le', codecs.BOM_UTF32_LE),
                   ('utf32be', codecs.BOM_UTF32_BE)]:
    CASES.append(('only_bom_' + label, bom, ''))


class EofDecoder(unittest.TestCase):
    def test_native_text_reader_shares_pending_eof_contract(self):
        self.assertEqual(TextReader(b'A\x81').lines, ['A'])
        self.assertEqual(TextReader(codecs.BOM_UTF8 + b'A\xe3\x81').lines, ['A'])
        self.assertEqual(TextReader(codecs.BOM_UTF16_LE + b'A\x00B').lines, ['A'])

    def test_explicit_cp932_remains_strict_on_incomplete_eof(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.csv'
            path.write_bytes(b'A\x81')
            with self.assertRaises(EraError) as caught:
                read_text(path, 'cp932')
            self.assertEqual(caught.exception.code, 'E_ENCODING')


for name, raw, expected in CASES:
    def check(self, raw=raw, expected=expected):
        self.assertEqual(decode_source(raw)[0], expected)
    setattr(EofDecoder, 'test_' + name, check)
