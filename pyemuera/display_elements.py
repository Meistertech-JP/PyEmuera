"""Retained non-text display elements; terminal is NOT a bitmap backend.

Shapes/images are validated and retained with geometry, resource provenance and
reference log tags. Cell reservations are explicitly approximate. Tooltip
configuration is retained; there is no pointer/hover surface on CLI.
"""

import csv, hashlib, struct
from pathlib import Path
from .errors import EraError
from .expr import integer
from .text import read_text
from .source_lines import source_lines


def image_resource(vm, name):
    root = vm.data.root.resolve()
    resources = root / 'resources'
    for p in sorted(resources.glob('*.csv')):
        for row in csv.reader(source_lines(read_text(p)[0])):
            if len(row) < 2 or row[0] != name:
                continue
            q = (resources / row[1]).resolve()
            if not q.is_relative_to(root):
                raise EraError('Resource leaves game root', code='E_PATH')
            if not q.is_file():
                return None
            raw = q.read_bytes()
            if raw[:8] != b'\x89PNG\r\n\x1a\n' or len(raw) < 24:
                return None
            w, h = struct.unpack('>II', raw[16:24])
            crop = [0, 0, w, h]
            if len(row) >= 6:
                crop = list(map(int, row[2:6]))
            return dict(
                path=q.relative_to(root).as_posix(),
                sha256=hashlib.sha256(raw).hexdigest(),
                width=w,
                height=h,
                crop=crop,
            )
    return None


def execute(vm, spec, arg):
    n = spec['name']
    con = vm.console
    if n.startswith('PRINT_') and con.skip_print:
        return True
    a = vm.args(arg)
    if n.startswith('TOOLTIP_'):
        expected = 2 if n == 'TOOLTIP_SETCOLOR' else 1
        if len(a) != expected:
            raise EraError(
                '引数が設定されていません' if len(a) < expected else '引数が多すぎます',
                code='E_ARGUMENT',
            )
        vals = [integer(v) for v in a]
        tip = vm.ui.setdefault('tooltip', {})
        if n == 'TOOLTIP_SETCOLOR':
            for i, v in enumerate(vals):
                if not 0 <= v <= 0xFFFFFF:
                    raise EraError(
                        ('第１' if i == 0 else '第２')
                        + '引数が色を表す整数の範囲外です',
                        code='E_ARGUMENT',
                    )
            tip['foreground'], tip['background'] = vals
        else:
            v = vals[0]
            if not 0 <= v <= 0x7FFFFFFF:
                raise EraError('引数の値が適切な範囲外です', code='E_ARGUMENT')
            tip['delay' if n.endswith('DELAY') else 'duration'] = (
                v if n.endswith('DELAY') else min(v, 32767)
            )
        con.warning(
            'tooltip-backend',
            'Tooltip settings are retained; terminal hover popup is unsupported.',
        )
        return True
    if n == 'PRINT_RECT':
        vals = [integer(v) for v in a]
        if any(not -0x80000000 <= v <= 0x7FFFFFFF for v in vals):
            raise EraError('PRINT_RECT引数が32bit範囲外です', code='E_ARGUMENT')
        valid = (len(vals) == 1 and vals[0] > 0) or (
            len(vals) == 4 and vals[0] >= 0 and vals[2] > 0 and vals[3] > 0
        )
        tag = "<shape type='rect' param='" + ', '.join(map(str, vals)) + "'>"
        extent = (
            vals[0] if len(vals) == 1 else vals[0] + vals[2] if len(vals) == 4 else 0
        )
        element = dict(
            kind='rect',
            param=vals,
            valid_geometry=valid,
            line=con.line_count,
            unit='font-em/100',
            color=vm.ui['color'],
            background=vm.ui['bgcolor'],
            pixel_rendered=False,
        )
        con.display_elements.append(element)
        con.warning(
            'graphics-backend',
            'Rectangle/image model is retained; terminal bitmap drawing is unsupported.',
        )
        con.write(
            ' ' * min(10000, max(0, extent) // 50) if valid else tag, log_text=tag
        )
        return True
    if n == 'PRINT_IMG':
        if len(a) != 1 or not isinstance(a[0], str):
            raise EraError('PRINT_IMG requires one string expression', code='E_TYPE')
        name = a[0]
        res = image_resource(vm, name)
        tag = "<img src='" + name + "'>"
        con.display_elements.append(
            dict(
                kind='image',
                resource_name=name,
                resource=res,
                line=con.line_count,
                pixel_rendered=False,
            )
        )
        con.warning(
            'graphics-backend',
            'Rectangle/image model is retained; terminal bitmap drawing is unsupported.',
        )
        # Missing resource is the reference's visible error element. A valid
        # bitmap reserves cells only; no invented ASCII image or fake pixels.
        con.write(
            ' ' * min(10000, max(0, res['crop'][2]) // 8) if res else tag, log_text=tag
        )
        return True
    return False
