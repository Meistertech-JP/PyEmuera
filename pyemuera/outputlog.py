"""Retained logical snapshots with explicit generation order and no overwrite.

Files remain a CLI adaptation of OUTPUTLOG. Oracle capture must verify their
content against final Console history; timestamp or filename order is no proof.
"""

from datetime import datetime
import hashlib
import json
from .errors import EraError
from .native_store import safe_overlay
from .unicode_boundary import loss_records


def logical_bytes(console):
    from .unicode_boundary import utf8_log

    # Completed empty display lines have a space; open current stays empty.
    lines = getattr(console, 'log_lines', console.lines)
    return utf8_log(
        '\n'.join([*lines, getattr(console, 'log_current', console.current)]) + '\n'
    )


def capture_summary(vm):
    content = logical_bytes(vm.console)
    return {
        'schema': 'pyemuera-outputlog-capture-1',
        'final_history_sha256': hashlib.sha256(content).hexdigest(),
        'final_history_bytes': len(content),
        'records': list(getattr(vm, 'outputlog_records', [])),
        'bounded_history': True,
        'selection_requires_final_history_digest': True,
        'encoding': 'UTF-8; lone UTF-16 units -> U+FFFD at log boundary',
        'lossy_code_units': loss_records(
            [
                *getattr(vm.console, 'log_lines', vm.console.lines),
                getattr(vm.console, 'log_current', vm.console.current),
            ]
        ),
    }


def final_state_summary(vm):
    """Opt-in journal digests; no raw game values are exported."""

    def variables(items):
        return {
            name: {
                'dims': var.dims,
                'character': var.character,
                'default': var.default,
                'values': sorted(var.values.items()),
            }
            for name, var in items.items()
            if not var.readonly
        }

    state = {
        'variables': variables(vm.data.variables),
        'characters': vm.data.character_count,
        'static': {str(k): variables(v) for k, v in vm.static.items()},
        'legacy': {str(k): variables(v) for k, v in vm.legacy.items()},
    }
    digest = lambda value: hashlib.sha256(
        json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(',', ':')
        ).encode('ascii')
    ).hexdigest()
    return {
        'mutable_state_sha256': digest(state),
        'rng_state_sha256': digest(vm.rng.getstate()),
        'steps': vm.steps,
        'frames_after_run': len(vm.frames),
        'method_depth': vm.method_depth,
        'scope': 'global/static/legacy mutable variables and character count; no unobserved reference-state claim',
    }


def write(vm):
    # Native file contains completed display lines only, with BOM and CRLF.
    # Keep indexed UTF-8 captures separately for the CLI replay manifest.
    native_lines = getattr(vm.console, 'log_lines', vm.console.lines)
    native_content = (
        (''.join(line + '\r\n' for line in native_lines))
        .encode('utf-16-le', errors='surrogatepass')
        .decode('utf-16-le', errors='replace')
        .encode('utf-16')
    )
    try:
        vm.saves.atomic_write(
            safe_overlay(vm.data.root, 'logs', 'emuera.log'), native_content
        )
    except (OSError, EraError) as exc:
        # Saves translates host I/O failures to E_SAVE_IO. Keep path policy,
        # script errors, interrupts and unexpected implementation faults fatal.
        if isinstance(exc, EraError) and exc.code != 'E_SAVE_IO':
            raise
        vm.console.warning('outputlog-failed', 'ログの出力に失敗しました')
        return
    vm.console.system_line('※※※ログファイルをemuera.logに出力しました※※※')
    try:
        _write_capture(vm)
    except (OSError, EraError) as exc:
        if isinstance(exc, EraError) and exc.code != 'E_SAVE_IO':
            raise
        vm.console.warning(
            'outputlog-capture-failed',
            'emuera.logは保存しましたが、追加ログまたはマニフェストの保存に失敗しました',
        )
        return
    vm.console.warning(
        'outputlog',
        'OUTPUTLOG writes the bounded text history under .pyemuera/logs; review it before sharing.',
    )


def _write_capture(vm):
    """Publish a capture record only after the complete manifest is committed.

    A partial capture or an unregistered complete file can remain after host
    I/O failure; retain it without claiming it in the committed record set.
    """
    content = logical_bytes(vm.console)
    records = getattr(vm, 'outputlog_records', None)
    if records is None:
        records = []
        vm.outputlog_records = records
    stem = 'output-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    suffix = 0
    while True:
        name = stem + ('' if suffix == 0 else '-' + str(suffix)) + '.txt'
        path = safe_overlay(vm.data.root, 'logs', name)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            stream = path.open('xb')
            break
        except FileExistsError:
            suffix += 1
    with stream:
        stream.write(content)
    location = vm.location
    record = {
        'generation': len(records) + 1,
        'file': name,
        'sha256': hashlib.sha256(content).hexdigest(),
        'bytes': len(content),
        'step': vm.steps,
        'location': (
            {'file': location.path, 'line': location.line} if location else None
        ),
    }
    manifest = safe_overlay(vm.data.root, 'logs', 'outputlog-manifest.json')
    vm.saves.atomic_write(
        manifest,
        (
            json.dumps(
                {'schema': 'pyemuera-outputlog-order-1', 'records': [*records, record]},
                ensure_ascii=False,
                indent=2,
            )
            + '\n'
        ).encode('utf-8'),
    )
    records.append(record)
