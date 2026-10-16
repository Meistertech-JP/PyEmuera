"""Opt-in measurements and watchpoints. No hooks are installed by default.

Times are instrumented wall time, not production-speed benchmarks. Function
self/inclusive totals attribute exclusive opcode time to the active ERB stack;
they exclude idle host/setup time outside opcodes. Categories are a second view
of the same work and must not be added to opcode/function totals.
"""

from __future__ import annotations
from collections import defaultdict
import time
from .errors import EraError


class VMProfiler:
    def __init__(self, vm):
        self.vm = vm
        self.originals = []
        self.stack = []
        self.opcodes = {}
        self.functions = {}
        self.categories = {}
        self.edges = defaultdict(int)
        self.started = None
        self.finished = None

    def _wrap(self, obj, name, fn):
        original = getattr(obj, name)
        self.originals.append((obj, name, original))
        setattr(obj, name, fn(original))

    def _time_category(self, name):
        def factory(original):
            def timed(*args, **kwargs):
                row = [time.perf_counter_ns(), 0]
                self.stack.append(row)
                try:
                    return original(*args, **kwargs)
                finally:
                    elapsed = time.perf_counter_ns() - row[0]
                    self.stack.pop()
                    if self.stack:
                        self.stack[-1][1] += elapsed
                    stat = self.categories.setdefault(name, [0, 0, 0])
                    stat[0] += 1
                    stat[1] += elapsed - row[1]
                    stat[2] += elapsed

            return timed

        return factory

    def install(self):
        self.started = time.perf_counter_ns()
        vm = self.vm

        def factory(original):
            def measured(frame, ins, pc):
                key = ins.op
                row = [time.perf_counter_ns(), 0]
                parents = tuple(vm.frames)
                opstack = getattr(self, '_opstack', None)
                if opstack is None:
                    opstack = []
                    self._opstack = opstack
                opstack.append(row)
                try:
                    return original(frame, ins, pc)
                finally:
                    elapsed = time.perf_counter_ns() - row[0]
                    opstack.pop()
                    if opstack:
                        opstack[-1][1] += elapsed
                    exclusive = elapsed - row[1]
                    stat = self.opcodes.setdefault(key, [0, 0, 0])
                    stat[0] += 1
                    stat[1] += exclusive
                    stat[2] += elapsed
                    for parent in parents:
                        f = self.functions.setdefault(parent.function.name, [0, 0, 0])
                        f[2] += exclusive
                    if parents:
                        self.functions[parents[-1].function.name][1] += exclusive
                    if any(f is frame for f in vm.frames) and frame.pc <= pc:
                        target = frame.pc
                        line = (
                            frame.function.code[target].location.line
                            if target < len(frame.function.code)
                            else None
                        )
                        self.edges[
                            (
                                frame.function.name,
                                ins.location.path,
                                ins.location.line,
                                target,
                                line,
                            )
                        ] += 1

            return measured

        self._wrap(vm, 'execute', factory)

        def enter_factory(original):
            def enter(f, *args, **kwargs):
                result = original(f, *args, **kwargs)
                self.functions.setdefault(f.name, [0, 0, 0])[0] += 1
                return result

            return enter

        self._wrap(vm, '_new_frame', enter_factory)
        for obj, name, label in [
            (vm, 'eval_node', 'expression'),
            (vm, '_resolve_ref', 'variable_reference'),
            (vm, 'format', 'formatting'),
            (vm.console, 'write', 'console_logical_output'),
            (vm.console, 'flush', 'terminal_flush'),
            (vm.console, '_sink', 'terminal_write'),
        ]:
            self._wrap(obj, name, self._time_category(label))
        if vm.journal:
            self._wrap(
                vm.journal, 'instruction', self._time_category('journal_instruction')
            )
        return self

    def stop(self):
        if self.finished is None:
            self.finished = time.perf_counter_ns()
        for obj, name, original in reversed(self.originals):
            setattr(obj, name, original)
        self.originals = []

    def report(self):
        def rows(stats):
            return [
                {
                    'name': n,
                    'count': v[0],
                    'self_seconds': v[1] / 1e9,
                    'inclusive_seconds': v[2] / 1e9,
                }
                for n, v in sorted(stats.items(), key=lambda x: x[1][1], reverse=True)
            ]

        return {
            'format': 'PyEmueraProfile1',
            'instrumented': True,
            'wall_seconds': (
                (self.finished or time.perf_counter_ns())
                - (self.started or time.perf_counter_ns())
            )
            / 1e9,
            'vm_steps': self.vm.steps,
            'opcodes': rows(self.opcodes),
            'functions': rows(self.functions),
            'categories': rows(self.categories),
            'back_edges': [
                dict(
                    function=k[0],
                    file=k[1],
                    line=k[2],
                    target_pc=k[3],
                    target_line=k[4],
                    count=v,
                )
                for k, v in sorted(self.edges.items(), key=lambda x: -x[1])
            ],
            'notice': 'Instrumented wall time includes blocking in opcodes. Function totals attribute opcode time; categories overlap that view. Do not use profiled time as normal speed/FPS. Real-time inputs can change when profiling is enabled.',
        }


class VariableTrace:
    def __init__(self, vm, names, functions=(), limit=50000):
        self.vm = vm
        self.names = tuple(dict.fromkeys(n.upper() for n in names))
        self.functions = set(n.upper() for n in functions)
        self.limit = limit
        self.events = []
        self.dropped = 0
        self.active = None
        self.hooks = []
        self.known = {}
        self.originals = []
        for n in self.names:
            if n not in vm.data.variables:
                raise EraError('Unknown watched variable ' + n, code='E_VARIABLE')

    def _record(self, row):
        if len(self.events) < self.limit:
            self.events.append(row)
        else:
            self.dropped += 1

    def _context(self):
        vm = self.vm
        active = self.active
        if active:
            frame, ins = active
            loc = ins.location
            function = frame.function.name
            op = ins.op
        else:
            loc = vm.location
            function = vm.frames[-1].function.name if vm.frames else None
            op = None
        roles = {
            n: vm.data.variables[n].values.get((0,), vm.data.variables[n].default)
            for n in ('TARGET', 'MASTER', 'ASSI', 'PLAYER')
            if n in vm.data.variables
        }
        target = roles.get('TARGET', -1)
        character = None
        if isinstance(target, int) and 0 <= target < vm.data.character_count:
            character = {
                n: vm.data.variables[n].values.get(
                    (target,), vm.data.variables[n].default
                )
                for n in ('NO', 'CALLNAME')
                if n in vm.data.variables
            }
        return {
            'step': vm.steps,
            'file': loc.path if loc else None,
            'line': loc.line if loc else None,
            'function': function,
            'command': op,
            'character_count': vm.data.character_count,
            'roles': roles,
            'target_character': character,
        }

    def _on_write(self, var, key, old, new):
        known = self.known.setdefault(var.name, {})
        if new == var.default:
            known.pop(key, None)
        else:
            known[key] = new
        self._record(
            {
                'event': 'write',
                'variable': var.name,
                'key': list(key),
                'old': old,
                'new': new,
                **self._context(),
            }
        )

    def scan(self):
        for n in self.names:
            var = self.vm.data.variables[n]
            old = self.known[n]
            if old == var.values:
                continue
            for key in sorted(set(old) | set(var.values)):
                before = old.get(key, var.default)
                after = var.values.get(key, var.default)
                if before != after:
                    self._record(
                        {
                            'event': 'bulk_change_detected',
                            'variable': n,
                            'key': list(key),
                            'old': before,
                            'new': after,
                            **self._context(),
                        }
                    )
            self.known[n] = dict(var.values)

    def install(self):
        for n in self.names:
            var = self.vm.data.variables[n]
            self.known[n] = dict(var.values)
            self.hooks.append((var, var.write_observer))
            var.write_observer = self._on_write
        self._record(
            {
                'event': 'initial_state',
                'variables': {
                    n: {
                        'default': self.vm.data.variables[n].default,
                        'values': [
                            [list(k), v] for k, v in sorted(self.known[n].items())
                        ],
                    }
                    for n in self.names
                },
                **self._context(),
            }
        )
        original = self.vm.execute
        self.originals.append(('execute', original))

        def execute(frame, ins, pc):
            old = self.active
            self.active = (frame, ins)
            try:
                return original(frame, ins, pc)
            finally:
                self.scan()
                self.active = old

        self.vm.execute = execute
        original_enter = self.vm._new_frame
        self.originals.append(('_new_frame', original_enter))

        def enter(f, *args, **kwargs):
            result = original_enter(f, *args, **kwargs)
            if f.name in self.functions:
                self._record(
                    {'event': 'function_enter', 'entered': f.name, **self._context()}
                )
            return result

        self.vm._new_frame = enter
        return self

    def stop(self):
        self.scan()
        for var, observer in self.hooks:
            var.write_observer = observer
        self.hooks = []
        for name, original in reversed(self.originals):
            setattr(self.vm, name, original)
        self.originals = []

    def report(self):
        return {
            'format': 'PyEmueraVariableTrace1',
            'variables': self.names,
            'functions': sorted(self.functions),
            'events': self.events,
            'limit': self.limit,
            'dropped': self.dropped,
            'privacy_notice': 'Explicit opt-in: contains variable values and character names. Review before sharing. Bulk updates are detected at instruction boundaries, not claimed as individual setter calls.',
        }
