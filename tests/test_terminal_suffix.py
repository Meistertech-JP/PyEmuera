"""Physical suffix erasure with the measured Mint Mono ambiguous-cell widths.

This small terminal model covers rows which do not physically wrap. It does
not claim to emulate Windows input, scroll, or wrap-at-last-column behavior.
"""
import io,re,unittest
from pyemuera.terminal_frame import RetainedFrame

class CellSurface:
    def __init__(self):self.cells=[[' ']*120 for _ in range(5)];self.row=self.col=0
    def apply(self,stream):
        for token in re.findall(r'\x1b\[[0-9;?]*[A-Za-z]|[^\x1b]',stream):
            if token.startswith('\x1b['):
                if token.endswith('H'):
                    y,x=map(int,token[2:-1].split(';'));self.row=y-1;self.col=x-1
                elif token.endswith('K'):self.cells[self.row][self.col:]=[' ']*(120-self.col)
                continue
            width=2 if token in '…あ　' else 1
            if self.col+width>119:raise AssertionError('Outside the non-wrapping model contract')
            self.cells[self.row][self.col]=token
            for i in range(1,width):self.cells[self.row][self.col+i]='~'
            self.col+=width

class PhysicalSuffix(unittest.TestCase):
    def make(self):
        self.output=io.StringIO();self.host=CellSurface()
        return RetainedFrame(self.output,layout='raw',columns=100,color=False,size_provider=lambda:(120,5),alternate_screen=False)
    def present(self,frame):
        self.output.seek(0);self.output.truncate();frame.present();s=self.output.getvalue();self.host.apply(s);return s
    def test_growing_logical_row_clears_physically_longer_old_row(self):
        f=self.make();f.feed('…'*55);self.present(f)
        f.reuse('-'*100);patch=self.present(f)
        self.assertEqual(''.join(self.host.cells[0]),'-'*100+' '*20)
        self.assertEqual(patch.count('\x1b[K'),1)
    def test_equal_logical_width_can_shrink_physical_width(self):
        f=self.make();f.feed('…'*10);self.present(f);f.reuse('a'*10);self.present(f)
        self.assertEqual(''.join(self.host.cells[0]),'a'*10+' '*110)
    def test_default_cp932_projection_can_shrink_physical_width(self):
        f=self.make();f.layout='terminal';f.feed('…'*37);self.present(f)
        # Projection adds one pad per ellipsis: logical74, host111 cells.
        self.assertEqual(f.previous[0].width,74)
        f.reuse('-'*100);self.present(f)
        self.assertEqual(''.join(self.host.cells[0]),'-'*100+' '*20)
    def test_shorter_row_and_fullwidth_text(self):
        f=self.make();f.feed('あ'*20);self.present(f);f.reuse('a');self.present(f)
        self.assertEqual(''.join(self.host.cells[0]),'a'+' '*119)
    def test_unchanged_frame_does_not_erase_or_write(self):
        f=self.make();f.feed('…'*10);self.present(f)
        self.assertEqual(self.present(f),'')
    def test_changed_row_does_not_redraw_other_rows_or_mutate_history(self):
        f=self.make();f.feed('stable\n'+'…'*10);self.present(f);before=tuple(f.rows)
        f.reuse('b'*10);patch=self.present(f)
        self.assertNotIn('stable',patch);self.assertEqual(tuple(f.rows),before)
        self.assertEqual(patch.count('\x1b[K'),1)
