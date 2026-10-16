"""Bounded, opt-in execution evidence; never asserts whole-game compatibility."""

from __future__ import annotations
from collections import Counter, deque
from datetime import datetime, timezone
import hashlib
import json
import platform
import re
from pathlib import Path
import sys
from . import __version__
from .registry import fingerprint
from .errors import EraError


class RunJournal:
    def __init__(self, seed=None, no_wait=False, record_inputs=False, trace_limit=128):
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.seed = seed
        self.no_wait = no_wait
        self.record_inputs = record_inputs
        self.records = []
        self.history = deque(maxlen=trace_limit)
        self.functions = Counter()
        self._command_names = []
        self._command_ids = {}
        self._command_counts = []
        self._coverage = bytearray()
        self._covered_count = 0
        self._tokens = []
        self.current = None
        self.phase = None
        self.inputs = 0
        self.total_events = 0
        self.sources = []
        self.source_digest = None
        self.vm = None

    def bind(self, vm):
        self.vm = vm
        count = 0
        for fs in vm.program.functions.values():
            for function in fs:
                for instruction in function.code:
                    instruction.evidence_id = count
                    count += 1
        self._coverage = bytearray(count)
        self._tokens = [None] * count
        root = vm.root
        files = {item['file']: item for item in vm.program.files + vm.data.files}
        digest = hashlib.sha256()
        for name, meta in sorted(files.items()):
            path = root / name
            if not path.resolve().is_relative_to(root):
                raise EraError(
                    'Source leaves game root while recording inventory.', code='E_PATH'
                )
            hasher = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    hasher.update(block)
            sha = hasher.hexdigest()
            self.sources.append(
                {
                    'file': name,
                    'sha256': sha,
                    'bytes': path.stat().st_size,
                    'encoding': meta.get('encoding'),
                }
            )
            digest.update(
                name.replace('\\', '/').encode('utf-8')
                + b'\0'
                + sha.encode('ascii')
                + b'\n'
            )
        self.source_digest = digest.hexdigest()

    def note(self, event, **fields):
        self.total_events += 1
        self.history.append(
            {
                'event': event,
                'step': self.vm.steps if self.vm else 0,
                'location': self.current,
                'phase': self.phase,
                **fields,
            }
        )

    @property
    def commands(self):
        return Counter(
            {n: self._command_counts[i] for i, n in enumerate(self._command_names)}
        )

    @property
    def covered(self):
        # Compatibility for embedders; materialize only on explicit inspection.
        return {
            (f.uid, pc)
            for fs in self.vm.program.functions.values()
            for f in fs
            for pc, ins in enumerate(f.code)
            if self._coverage[ins.evidence_id]
        }

    def instruction(self, frame, instruction):
        index = instruction.evidence_id
        token = self._tokens[index]
        if token is None:
            op = instruction.op
            command_id = self._command_ids.get(op)
            if command_id is None:
                command_id = len(self._command_names)
                self._command_ids[op] = command_id
                self._command_names.append(op)
                self._command_counts.append(0)
            location = {
                'file': instruction.location.path,
                'line': instruction.location.line,
                'function': frame.function.name,
            }
            token = (command_id, location, op)
            self._tokens[index] = token
        command_id, location, op = token
        self.current = location
        self._command_counts[command_id] += 1
        if not self._coverage[index]:
            self._coverage[index] = 1
            self._covered_count += 1
        self.total_events += 1
        self.history.append((self.vm.steps, self.phase, location, op))

    def expanded_history(self):
        return [
            (
                dict(
                    event='instruction',
                    step=row[0],
                    phase=row[1],
                    location=dict(row[2]),
                    command=row[3],
                )
                if isinstance(row, tuple)
                else dict(row)
            )
            for row in self.history
        ]

    def enter(self, frame):
        self.functions[frame.function.name] += 1

    def input(self, kind, text, timed_out=False):
        self.inputs += 1
        if self.record_inputs:
            if len(self.records) >= 1_000_000:
                raise EraError(
                    'Input recording limit reached (1000000).', code='E_LIMIT'
                )
            record = {'kind': kind, 'text': text}
            if timed_out:
                record['timeout'] = True
            self.records.append(record)
        self.note(
            'input_received', kind=kind
        )  # Never include text in the ordinary report.

    def report(self, outcome, error=None):
        vm = self.vm
        from .outputlog import capture_summary, final_state_summary

        return {
            'format': 'PyEmueraSession1',
            'engine_version': __version__,
            'language_specs_sha256': fingerprint(),
            'started_at': self.started_at,
            'finished_at': datetime.now(timezone.utc).isoformat(),
            'environment': {
                'python': platform.python_version(),
                'os': platform.system(),
                'machine': platform.machine(),
            },
            'outcome': outcome,
            'gameplay_verified': False,
            'scope_notice': 'Execution evidence for this one path only. A clean run, source hash '
            'or instruction coverage is not proof of full-game compatibility.',
            'seed': self.seed,
            'no_wait': self.no_wait,
            'sources_sha256': self.source_digest,
            'rng_algorithm': vm.rng.algorithm if vm else None,
            'native_rng_policy': vm.saves.native_rng if vm else None,
            'terminal_projection': (
                dict(vm.console._frame.stats)
                if vm and getattr(vm.console, '_frame', None) is not None
                else None
            ),
            'backend_diagnostics': (
                list(getattr(vm.console, 'diagnostic_events', [])) if vm else []
            ),
            'backend_diagnostics_scope': 'Physical terminal events only; not ERB history, OUTPUTLOG, or Windows rendering certification.',
            'sources': self.sources,
            'steps': vm.steps if vm else 0,
            'input_responses': self.inputs,
            'wait_instructions': vm.console.wait_count if vm else 0,
            'source_instructions_visited': self._covered_count,
            'compiled_instructions_total': (
                sum(len(f.code) for fs in vm.program.functions.values() for f in fs)
                if vm
                else 0
            ),
            'function_entries': dict(sorted(self.functions.items())),
            'executed_commands': dict(sorted(self.commands.items())),
            'history_limit': self.history.maxlen,
            'history_truncated': self.total_events > len(self.history),
            'recent_execution': self.expanded_history(),
            'error': error.as_dict() if error else None,
            'diagnostics': getattr(vm, 'emitted_diagnostics', []) if vm else [],
            'logical_output_capture': capture_summary(vm) if vm else None,
            'final_state': final_state_summary(vm) if vm else None,
            'privacy_notice': 'Normal PRINT output, variable snapshots, and input text are not collected here. '
            'Error messages may quote game prose. File/function names can also be sensitive. '
            'Review before sharing. --record-inputs separately includes typed text.',
        }

    def replay(self):
        return {
            'format': 'PyEmueraInput1',
            'engine_version': __version__,
            'language_specs_sha256': fingerprint(),
            'seed': self.seed,
            'no_wait': self.no_wait,
            'sources_sha256': self.source_digest,
            'inputs': self.records,
            'notice': 'Contains user-entered text. GETTIME and external saved state are not captured.',
        }


def load_replay(path: Path):
    if path.stat().st_size > 64 * 1024 * 1024:
        raise EraError('Replay file exceeds 64 MiB.', code='E_LIMIT')
    text = path.read_text(encoding='utf-8-sig')
    if path.suffix.lower() != '.json':
        return text.splitlines(), None
    try:
        obj = json.loads(text)
    except (ValueError, RecursionError) as exc:
        raise EraError('Invalid JSON replay.', code='E_REPLAY') from exc
    if not isinstance(obj, dict) or obj.get('format') != 'PyEmueraInput1':
        raise EraError('Not a PyEmueraInput1 replay.', code='E_REPLAY')
    records = obj.get('inputs')
    if not isinstance(records, list) or len(records) > 1000000:
        raise EraError('Invalid replay input list.', code='E_REPLAY')
    for row in records:
        if (
            not isinstance(row, dict)
            or row.get('kind')
            not in {
                'integer',
                'string',
                'wait',
                'timed_integer',
                'timed_string',
                'timed_wait',
                'one_integer',
                'one_string',
                'timed_one_integer',
                'timed_one_string',
                'key_wait',
            }
            or not isinstance(row.get('text'), str)
        ):
            raise EraError('Invalid typed replay entry.', code='E_REPLAY')
        if type(row.get('timeout', False)) is not bool or (
            row.get('timeout') and not row['kind'].startswith('timed_')
        ):
            raise EraError('Invalid timed replay entry.', code='E_REPLAY')
    if type(obj.get('no_wait')) is not bool or (
        obj.get('seed') is not None and type(obj.get('seed')) is not int
    ):
        raise EraError('Invalid replay settings.', code='E_REPLAY')
    if obj.get('entry') is not None and not isinstance(obj['entry'], str):
        raise EraError('Invalid replay entry point.', code='E_REPLAY')
    if 'debug' in obj and type(obj['debug']) is not bool:
        raise EraError('Invalid replay debug setting.', code='E_REPLAY')
    if not isinstance(obj.get('engine_version'), str) or not obj['engine_version']:
        raise EraError('Missing replay engine version.', code='E_REPLAY')
    if not isinstance(obj.get('sources_sha256'), str) or not re.fullmatch(
        r'[0-9a-fA-F]{64}', obj['sources_sha256']
    ):
        raise EraError('Missing replay source fingerprint.', code='E_REPLAY')
    return records, obj
