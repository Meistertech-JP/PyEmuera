"""Sprite absence queries without inventing a graphics backend.

SpriteStateMethod returns zero when AppContents has no created sprite. This
CLI adapter establishes that contract for an empty/comment-only catalog. An
active resource declaration requires an unsupported image backend and fails
explicitly rather than reporting a false absence.
"""

from .errors import EraError, Location, Unsupported
from .expr import evaluate
from .text import read_text
from .source_lines import source_lines


def function(vm, name, nodes):
    value = evaluate(nodes[0], vm)
    if not isinstance(value, str):
        raise EraError(name + ' requires a string', code='E_TYPE')
    if not hasattr(vm, '_resource_catalog_checked'):
        root = vm.root
        folder = next(
            (p for p in root.iterdir() if p.is_dir() and p.name.upper() == 'RESOURCES'),
            None,
        )
        active = None
        if folder:
            for path in sorted(folder.rglob('*')):
                if not path.is_file() or path.suffix.lower() != '.csv':
                    continue
                if not path.resolve().is_relative_to(root):
                    raise EraError('Resource CSV leaves game root', code='E_PATH')
                for number, line in enumerate(
                    source_lines(read_text(path, vm.program.encoding)[0]), 1
                ):
                    line = line.lstrip(' \t\u3000')
                    if not line or line.startswith(';'):
                        continue
                    cells = line.split(',')
                    if len(cells) >= 2 and cells[0].strip() and cells[1]:
                        active = Location(str(path.relative_to(root)), number)
                        break
                if active:
                    break
        vm._resource_catalog_checked = active
    if vm._resource_catalog_checked is not None:
        raise Unsupported(
            'SPRITECREATED with active resource declarations requires an image resource backend',
            vm._resource_catalog_checked,
        )
    return 0
