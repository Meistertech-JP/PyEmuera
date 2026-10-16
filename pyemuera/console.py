from __future__ import annotations
import sys
import os
import time
import re
from collections import deque
from .errors import EraError


class BufferedOutput:
    """Coalesce host writes, preserving byte order, styles and explicit flushes."""

    def __init__(self, stream, limit=65536):
        self.stream = stream
        self.parts = []
        self.size = 0
        self.limit = limit

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def write(self, text):
        self.parts.append(text)
        self.size += len(text)
        if self.size >= self.limit:
            self.flush()
        return len(text)

    def flush(self):
        if self.parts:
            text = ''.join(self.parts)
            self.parts.clear()
            self.size = 0
            from .host_output import write_all

            try:
                write_all(self.stream, text)
            except UnicodeEncodeError as exc:
                if getattr(exc, '_pyemuera_written_chars', 0):
                    raise
                enc = getattr(self.stream, 'encoding', None) or 'utf-8'
                write_all(self.stream, text.encode(enc, errors='replace').decode(enc))
        self.stream.flush()


class Console:
    """Line terminal. JSON replay entries retain input kinds to detect drift.

    A transcript is not collected here: the optional journal records only source
    positions and input counts unless input recording was explicitly enabled.

    Lazy state declarations below intentionally have no initial values. The
    owning feature creates them at its historical boundary, so absence remains
    observable to embedders and lightweight test doubles. PRINT_SPACE owns the
    fractional projection; row commit/discard invalidates only an existing value.
    Startup owns its once-per-Console marker. Neither VM reset nor game load
    erases Console history, warning registration, or the sticky output failure.
    """

    shape_remainder: tuple[int | None, int]
    _startup_emitted: bool
    _writing_rule: bool
    _host_line_echo: bool
    last_timeout: bool
    output_mode_status: dict

    def __init__(
        self,
        inputs=None,
        output=None,
        no_wait=False,
        journal=None,
        *,
        layout="raw",
        ambiguous_width=1,
    ):
        self.inputs = iter(inputs) if inputs is not None else None
        self.output = output if output is not None else sys.stdout
        self.no_wait = no_wait
        self.journal = journal
        self.lines = deque(maxlen=10000)
        self._rule_lines = deque(maxlen=10000)
        self._native_print_buffer = (0, 0, None)
        self.current = ''
        self.log_lines = deque(maxlen=10000)
        self.log_current = ''
        self.temporary_line = False
        self.display_elements = []
        self.input_buffer = ''
        self.markup_current = []
        self.markup_lines = deque(maxlen=10000)
        self.button_context = None
        self.html_focus = 0xFFFF00
        self.line_count = 0
        self.wait_count = 0
        self.input_count = 0
        self.input_backend_status = {'backend': 'unselected', 'active': False}
        self.warning_keys = set()
        self.diagnostic_events = []
        self.skip_print = False
        self.user_skip = False
        if layout not in ('raw', 'terminal') or ambiguous_width not in (1, 2):
            raise ValueError('Invalid terminal layout options')
        self.layout = layout
        self.ambiguous_width = ambiguous_width
        self.emitted_columns = 0
        self.logical_columns = 0
        self.columns = 100
        self.ui = None
        self.style_override = None
        self.color_enabled = False
        self._last_style = None
        self.vt_enabled = False
        self._screen_rows = deque(maxlen=10000)
        self._pending = []
        self._row_has_output = False
        self.batch_output = False
        self._markup_signature = None
        self._markup_style = None
        self.renderer_mode = "stream"
        self._frame = None
        self._retained = None
        self._redraw = 1
        self._output_failure = None

    def enable_batching(self):
        if not self.batch_output:
            self.output = BufferedOutput(self.output)
            self.batch_output = True

    def _sync_output_failure(self):
        # Background/prompt methods may call the frame directly. Observe its
        # latched boundary failure before making any further Console mutation.
        failure = getattr(self._frame, '_output_failure', None)
        if self._output_failure is None and isinstance(failure, Exception):
            self._record_output_failure(failure)

    def _check_output(self):
        """Never retry an indeterminate partial host write as game output."""
        self._sync_output_failure()
        if self._output_failure is not None:
            raise self._output_failure

    def _record_output_failure(self, exc):
        self._output_failure = exc
        # _pending is a physical projection buffer, not ERB current/history.
        # The failed call may have emitted an unknown prefix. Retrying it from
        # flush()/close() would duplicate game text, so it cannot be replayed.
        self._pending.clear()
        self._row_has_output = False

    def _write_host(self, text):
        from .host_output import write_all

        self._check_output()
        try:
            write_all(self.output, text)
        except UnicodeEncodeError as exc:
            # Initial atomic encoding rejection retains _sink's fallback. A
            # known short-write prefix must never be replaced from the start.
            if getattr(exc, '_pyemuera_written_chars', 0):
                self._record_output_failure(exc)
            raise
        except (OSError, ValueError) as exc:
            self._record_output_failure(exc)
            raise

    def _flush_host(self):
        self._check_output()
        try:
            self.output.flush()
        except (OSError, ValueError) as exc:
            self._record_output_failure(exc)
            raise

    def _sink(self, text):
        """Keep UTF-16 code units in state; replace only unencodable glyphs.

        StringIO/testing streams retain the original text because they accept
        it. A host failure is propagated without replaying an unknown prefix.
        """
        try:
            self._write_host(text)
        except UnicodeEncodeError as exc:
            if getattr(exc, '_pyemuera_written_chars', 0):
                raise
            encoding = getattr(self.output, 'encoding', None) or 'utf-8'
            self._write_host(text.encode(encoding, errors='replace').decode(encoding))

    def write_rule(self, text):
        """Commit a complete logical rule with backend-only display provenance.

        Keep write() interception compatible with existing journals/observers.
        The scoped marker never enters strings, OUTPUTLOG, variables or saves.
        """
        old = getattr(self, '_writing_rule', False)
        self._writing_rule = True
        try:
            self.write(text, True)
        finally:
            self._writing_rule = old

    def _append_markup(self, text, style):
        """Record raw text/style before host emission, merging equal runs.

        The markup cache ignores historical background: the surface background
        is current state. Completed rows keep foreground/font/button metadata.
        """
        from .html1824 import MarkupStyle

        effective = style or (0xC0C0C0, 0, 0)
        signature = (
            effective[0],
            effective[2],
            self.ui.get('font', 'monospace') if self.ui else 'monospace',
            self.html_focus,
            self.button_context,
        )
        if signature != self._markup_signature:
            mark = MarkupStyle(*signature)
            # Publish the matching key/value only after construction succeeds.
            self._markup_signature = signature
            self._markup_style = mark
        mark = self._markup_style
        chunks = text.split('\n')
        for index, chunk in enumerate(chunks):
            if chunk:
                if self.markup_current and self.markup_current[-1][1] == mark:
                    previous = self.markup_current[-1][0]
                    self.markup_current[-1] = (previous + chunk, mark)
                else:
                    self.markup_current.append((chunk, mark))
            if index < len(chunks) - 1:
                self.markup_lines.append(
                    (
                        tuple(self.markup_current),
                        self.ui.get('alignment', 'LEFT') if self.ui else 'LEFT',
                    )
                )
                self.markup_current = []

    def _emit_text(self, text, rendered, style, rule):
        """Update retained projection or emit to the selected host backend.

        Rule provenance fits a terminal row; ordinary PRINT remains uncut.
        Terminal-layout rows buffer across calls. Every synchronous backend
        presents before history is committed. A failure may have emitted a
        prefix, but never commits the failed write as a logical line.
        """
        if self._retained is not None:
            if self.ui is not None:
                self._retained.set_background(self.ui['bgcolor'])
            feed = self._retained.feed_rule if rule else self._retained.feed
            feed(text, style, self.ui.get('alignment', 'LEFT') if self.ui else 'LEFT')
        if self._frame is not None:
            if self._redraw & 1 and '\n' in text:
                self._frame.present()
        elif rule and self.is_terminal():
            # Stream terminals also reserve their final column. Redirection
            # remains byte-for-byte logical output and never depends on size.
            import shutil
            from .layout import project_rule

            width = min(
                self.columns,
                max(1, shutil.get_terminal_size((self.columns, 24)).columns - 1),
            )
            alignment = self.ui.get('alignment', 'LEFT') if self.ui else 'LEFT'
            self.flush()
            self._set_style(style)
            chunks = text.split('\n')
            for i, chunk in enumerate(chunks):
                if i:
                    self._sink('\n')
                if chunk:
                    projected, _ = project_rule(
                        chunk,
                        width,
                        layout=self.layout,
                        ambiguous=self.ambiguous_width,
                        alignment=alignment,
                    )
                    self._sink(projected)
            self._flush_host()
            self._row_has_output = False
        elif self.layout == 'terminal':
            # Buffer a logical row across PRINT calls so corridor padding can
            # inspect the following glyph, even across function/style changes.
            for c in text:
                if c == '\n':
                    self.flush()
                    self._write_host('\n')
                    self._flush_host()
                    self._row_has_output = False
                else:
                    self._pending.append((c, style))
            if len(self._pending) > 1_000_000:
                raise EraError('Display line limit', code='E_LIMIT')
        else:
            self._set_style(style)
            self._sink(rendered)
            if not self.batch_output or '\n' in text:
                self._flush_host()

    def _reset_shape_projection(self):
        """Discard a row's fractional PRINT_SPACE projection, preserving laziness.

        Completed/deleted/reused rows may share the same logical line number.
        A stale fraction must not migrate to a new row after CLEARLINE. Actual
        shape geometry remains a separate, explicitly approximate CLI model.
        """
        if 'shape_remainder' in self.__dict__:
            self.shape_remainder = (None, 0)

    def _append_history(self, text, newline, log_text, rule, style):
        """Append logical history after emission; keep raw and log text distinct.

        OUTPUTLOG blank rows use a space; display history may hold an empty row.
        Measure host size separately for each completed line, as before. This is
        not an input echo, redraw, or physical suffix-erasure operation.
        """
        logged = text if log_text is None else log_text + ('\n' if newline else '')
        log_parts = (self.log_current + logged).split('\n')
        for item in log_parts[:-1]:
            self.log_lines.append(item if item else ' ')
        self.log_current = log_parts[-1]
        pieces = (self.current + text).split('\n')
        for part in pieces[:-1]:
            self.lines.append(part)
            self._rule_lines.append(
                (style, self.ui.get('alignment', 'LEFT') if self.ui else 'LEFT')
                if rule
                else None
            )
            from .layout import project, terminal_width

            measured = (
                project(part, self.ambiguous_width)
                if self.layout == 'terminal'
                else part
            )
            import shutil

            width = max(1, shutil.get_terminal_size((self.columns, 24)).columns)
            self._screen_rows.append(
                1
                if rule and self.is_terminal()
                else max(
                    1,
                    (terminal_width(measured, self.ambiguous_width) + width - 1)
                    // width,
                )
            )
            self.line_count += 1
        self.current = pieces[-1]
        if '\n' in text:
            self._reset_shape_projection()

    def system_line(self, text):
        """Native system notices are independent of script SKIPDISP."""
        skipped = self.skip_print
        self.skip_print = False
        try:
            if self.current and not self.temporary_line:
                self.write('', True)
            self.write(text, True)
        finally:
            self.skip_print = skipped

    def print_buffer_text(self, text):
        """PrintStringBuffer.Append's UTF-16 cap; expression strings stay intact.

        Style changes move the builder into the parts list before starting a new
        builder. Consequently the first append after a style change is not
        truncated; subsequent appends observe total buffer length.
        """
        style = self.style_override or tuple(
            (self.ui or {}).get(k) for k in ('color', 'bgcolor', 'style', 'font')
        )
        state = getattr(self, '_native_print_buffer', (0, 0, None))
        total, builder, previous = state
        out = []
        marker = '※※※バッファーの文字数が2000字(全角1000字)を超えています。これ以降は表示できません※※※'
        for index, part in enumerate(str(text).split('\n')):
            if index:
                out.append('\n')
                total = builder = 0
                previous = None
            raw = part.encode('utf-16-le', errors='surrogatepass')
            if total > 2000:
                continue
            if builder == 0 or previous == style:
                if builder > 2000:
                    continue
                if builder + len(raw) // 2 > 2000:
                    part = (
                        raw[: 2 * (2000 - builder)].decode(
                            'utf-16-le', errors='surrogatepass'
                        )
                        + marker
                    )
            else:
                builder = 0
            length = len(part.encode('utf-16-le', errors='surrogatepass')) // 2
            total += length
            builder += length
            previous = style
            out.append(part)
        self._native_print_buffer = (total, builder, previous)
        return ''.join(out)

    def write(self, text: str, newline=False, *, log_text=None):
        """Sanitize, prepare markup, emit/present, then commit logical history.

        skip_print exits before conversion. A temporary row is discarded before
        new text. Host failure preserves prior committed history and rejects
        later game-output retries; earlier markup/output effects remain visible.
        REDRAW-suppressed output commits normally without a physical present.
        """
        rule = getattr(self, '_writing_rule', False)
        if self.skip_print:
            return
        self._check_output()
        # Remove terminal escape / OSC / C0 / C1 sequences from game text.
        text = ''.join(
            c
            for c in str(text)
            if c in '\n\t' or (ord(c) >= 32 and not 127 <= ord(c) < 160)
        )
        if self.temporary_line:
            self.discard_current()
            self.temporary_line = False
        if newline:
            text += '\n'
        from .layout import project, terminal_width

        rendered = (
            project(text, self.ambiguous_width) if self.layout == 'terminal' else text
        )
        # Keep raw source text in history. A line read by ERB must not contain
        # the output adapter's spacing characters.
        style = self.style_override or (
            (self.ui['color'], self.ui['bgcolor'], self.ui['style'])
            if self.ui is not None
            else None
        )
        self._append_markup(text, style)
        try:
            self._emit_text(text, rendered, style, rule)
        except (OSError, ValueError) as exc:
            self._record_output_failure(exc)
            raise
        self.emitted_columns = terminal_width(
            rendered.rsplit('\n', 1)[-1], self.ambiguous_width
        ) + (self.emitted_columns if '\n' not in rendered else 0)
        self._append_history(text, newline, log_text, rule, style)
        if text.endswith('\n'):
            self._native_print_buffer = (0, 0, None)

    def _read_input_entry(self, deadline, one, any_key):
        """Acquire replay/key/timed/line input and translate only ordinary EOF.

        Reuse the caller's deadline on retries. A key/timed/prompt read releases
        the host cursor in finally, including KeyboardInterrupt; cancellation
        must not be converted to E_INPUT_EOF. This stage does not journal input.
        """
        timed_out = False
        try:
            if self.inputs is not None:
                self.input_backend_status = {'backend': 'replay', 'active': False}
                text = next(self.inputs)
            elif one:
                self.input_backend_status = {
                    'backend': 'existing_single_key',
                    'active': True,
                }
                try:
                    text = self._read_key(
                        (
                            None
                            if deadline is None
                            else max(0, deadline - time.monotonic())
                        ),
                        any_key=any_key,
                    )
                finally:
                    self.input_backend_status['active'] = False
                    if self._frame is not None:
                        self._frame.finish_prompt()
                timed_out = text is None
                if timed_out:
                    text = ''
            elif deadline is not None:
                self.input_backend_status = {
                    'backend': 'existing_timed_line',
                    'active': True,
                }
                try:
                    text = self._timed_read(max(0, deadline - time.monotonic()))
                finally:
                    self.input_backend_status['active'] = False
                    if self._frame is not None:
                        self._frame.finish_prompt()
                timed_out = text is None
                if timed_out:
                    text = ''
            else:
                self._host_line_echo = bool(sys.stdin.isatty())
                if self._frame is not None:
                    self._frame.present_prompt('> ')
                    try:
                        text = self._read_line('')
                    finally:
                        self._frame.finish_prompt()
                else:
                    text = self._read_line('> ')
        except (StopIteration, EOFError) as exc:
            raise EraError(
                'Input ended. Supply more --inputs or use an interactive terminal.',
                code='E_INPUT_EOF',
            ) from exc
        return text, timed_out

    def _read_line(self, prompt):
        status = self.input_backend_status = {'backend': 'Python input', 'active': True}
        if os.name == 'nt':
            from .windows_input import Win32ConsoleLine, read_console_line

            backend = Win32ConsoleLine.from_stream(sys.stdin, status)
            if backend is not None:
                self._host_line_echo = status['host_echo']
                self._sink(prompt)
                self._flush_host()
                return read_console_line(backend, status)
        try:
            return input(prompt)
        finally:
            status['active'] = False

    def _validate_input_entry(self, text, timed_out, kind, timeout_ms):
        """Validate typed replay records before counts/journal/timeout effects.

        Return a complete raw string and timeout flag. A malformed record has
        consumed the entry but leaves the accepted-input count and journal alone.
        Truncation to one UTF-16 unit happens later, after journal recording.
        """
        if isinstance(text, dict):
            if text.get('kind') != kind or not isinstance(text.get('text'), str):
                raise EraError(
                    f'Replay input kind mismatch: expected {kind}. '
                    'Check engine/game versions and --no-wait.',
                    code='E_REPLAY',
                )
            if type(text.get('timeout', False)) is not bool:
                raise EraError('Invalid replay timeout flag', code='E_REPLAY')
            timed_out = text.get('timeout', False)
            if timed_out and timeout_ms is None:
                raise EraError('Timeout record at untimed input', code='E_REPLAY')
            text = text['text']
        if not isinstance(text, str):
            raise EraError(
                'Replay entry must be a string or a typed input record.',
                code='E_REPLAY',
            )
        return text, timed_out

    def input(
        self,
        string=False,
        default=None,
        *,
        kind=None,
        force=False,
        timeout_ms=None,
        one=False,
        any_key=False,
    ):
        """Commit pending output, acquire/validate, record, then convert input.

        A single deadline governs interactive retries. Timeout/default return
        precedes integer conversion; replay invalid integers fail without retry.
        Recording sees the untruncated string. Echo remains the command layer's
        responsibility so input acquisition cannot invent game-output rows.
        """
        kind = kind or ('string' if string else 'integer')
        # Emuera returns from DoScript at a value/key wait and PrintFlush(false)
        # commits the pending PRINT buffer before an input value is echoed.
        # This is an input-boundary flush, not an ERB PRINTL after INPUT.
        if (self.current or self.log_current) and not self.temporary_line:
            self.write('', True)
        self.flush(force=True)
        self.reset_style()
        if self.skip_print and not force:
            raise EraError(
                'INPUT reached while display is skipped. Use NOSKIP/ENDNOSKIP '
                'or SKIPDISP 0 around the prompt.',
                code='E_INPUT_SKIP',
            )
        if self.journal:
            self.journal.note('input_request', kind=kind)
        self.last_timeout = False
        self._host_line_echo = False
        deadline = (
            time.monotonic() + timeout_ms / 1000 if timeout_ms is not None else None
        )
        while True:
            text, timed_out = self._read_input_entry(deadline, one, any_key)
            text, timed_out = self._validate_input_entry(
                text, timed_out, kind, timeout_ms
            )
            if self.temporary_line:
                self.discard_current()
                self.temporary_line = False
            self.input_count += 1
            if self.journal:
                self.journal.input(kind, text, timed_out)
            self.last_timeout = timed_out
            if timed_out:
                return default
            if one and text:
                from .input_commands import first_unit

                text = first_unit(text)
            if text == '' and default is not None:
                return default
            if string:
                return text
            try:
                stripped = text.strip()
                if re.fullmatch(r'[+-]?[0-9]+', stripped) is None:
                    raise ValueError('not an Int64')
                value = int(stripped, 10)
                if not -(1 << 63) <= value < 1 << 63:
                    raise ValueError('Int64 overflow')
                return value
            except ValueError:
                if self.inputs is not None:
                    raise EraError('Expected integer replay input.', code='E_INPUT')
                self.write('整数を入力してください。', True)

    def _input_echo(self, text):
        # Redirect/replay: engine emits echo. Host line-input terminal echo is
        # already physical; retain it logically without emitting a second copy.
        self.input_buffer = text
        if not text:
            return  # Print(empty)/PrintFlush does not invent a blank echo row.
        if not getattr(self, '_host_line_echo', False) or self._frame is not None:
            self.write(text, True)
        else:
            self.lines.append(text)
            self.log_lines.append(text)
            self._rule_lines.append(None)
            if self._retained is not None:
                style = (
                    (self.ui['color'], self.ui['bgcolor'], self.ui['style'])
                    if self.ui
                    else None
                )
                self._retained.feed(text + '\n', style)
            self.emitted_columns = 0
            self._row_has_output = False
            self._native_print_buffer = (0, 0, None)
            self.current = ''
            self.log_current = ''
            self.markup_current = []
            self.line_count += 1
            self._reset_shape_projection()

    def wait(self, force=False):
        self.flush(force=True)
        self.wait_count += 1
        if self.skip_print and not force:
            return
        if not self.no_wait:
            self.input(string=True, kind='wait', force=force)

    def _read_key(self, seconds=None, *, any_key=False):
        """Read one terminal key without an Enter requirement or reader thread.

        POSIX cbreak settings are always restored (also on timeout/cancellation).
        Redirected stdin uses a line fallback. --inputs has typed single-key
        records and never touches OS terminal modes.
        """
        self.flush(force=True)
        if self._frame is not None:
            self._frame.present_prompt('> ')
        else:
            self._sink('> ')
            self._flush_host()
        if not sys.stdin.isatty():
            if seconds is not None:
                raise EraError(
                    'Timed single-key input requires a terminal or replay',
                    code='E_CONSOLE',
                )
            line = sys.stdin.readline()
            if not line:
                raise EOFError
            return line.rstrip('\r\n')
        deadline = None if seconds is None else time.monotonic() + seconds
        if os.name == 'nt':
            import msvcrt

            while deadline is None or time.monotonic() < deadline:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ('\x00', '\xe0'):
                        extra = msvcrt.getwch()
                        if not any_key:
                            continue
                        ch = '\x1b' + extra
                    if ch == '\x03':
                        raise KeyboardInterrupt
                    if ch in ('\r', '\n'):
                        ch = ''
                    return ch
                time.sleep(0.005)
            return None
        import select, termios, tty, codecs

        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
        decoder = codecs.getincrementaldecoder(sys.stdin.encoding or 'utf-8')(
            errors='replace'
        )
        try:
            tty.setcbreak(fd)
            while True:
                remaining = (
                    None if deadline is None else max(0, deadline - time.monotonic())
                )
                ready, _, _ = select.select([fd], [], [], remaining)
                if not ready:
                    return None
                raw = os.read(fd, 1)
                if not raw:
                    raise EOFError
                ch = decoder.decode(raw)
                if not ch:
                    continue
                if ch == '\x03':
                    raise KeyboardInterrupt
                if ch == '\x1b':
                    # Consume an ANSI key sequence, never leak '[A' into the
                    # next game input. Escape alone is accepted as a key.
                    tail = b''
                    while select.select([fd], [], [], 0.005)[0]:
                        piece = os.read(fd, 1)
                        tail += piece
                        if len(tail) > 64 or (
                            len(tail) > 1 and 0x40 <= tail[-1] <= 0x7E
                        ):
                            break
                    if tail and not any_key:
                        continue
                if ch in ('\r', '\n'):
                    ch = ''
                return ch
        finally:
            termios.tcsetattr(fd, termios.TCSANOW, saved)

    def _timed_read(self, seconds):
        """Timed, Enter-terminated input; never leaves a blocked reader thread."""
        if seconds <= 0:
            return None
        if not sys.stdin.isatty():
            raise EraError(
                'Timed input requires a terminal or --inputs replay.', code='E_CONSOLE'
            )
        if self._frame is not None:
            self._frame.present_prompt('> ')
        else:
            self._sink('> ')
            self._flush_host()
        self._host_line_echo = True
        end = time.monotonic() + seconds
        if os.name == 'nt':
            import msvcrt

            chars = []
            while time.monotonic() < end:
                if msvcrt.kbhit():
                    c = msvcrt.getwch()
                    if c == '\x03':
                        raise KeyboardInterrupt
                    if c in ('\x00', '\xe0'):
                        msvcrt.getwch()
                        continue
                    if c in ('\r', '\n'):
                        if self._frame is None:
                            self._sink('\n')
                            self._flush_host()
                        return ''.join(chars)
                    if c == '\b':
                        if chars:
                            chars.pop()
                            self._write_host('\b \b')
                            self._flush_host()
                    else:
                        chars.append(c)
                        self._sink(c)
                        self._flush_host()
                else:
                    time.sleep(min(0.01, max(0, end - time.monotonic())))
        else:
            import select

            ready, _, _ = select.select(
                [sys.stdin], [], [], max(0, end - time.monotonic())
            )
            if ready:
                line = sys.stdin.readline()
                if not line:
                    raise EOFError
                return line.rstrip('\r\n')
            # Discard a partial line, rather than feeding it to the next prompt.
            try:
                import termios

                termios.tcflush(sys.stdin, termios.TCIFLUSH)
            except (ImportError, OSError):
                pass
        return None

    def timed_wait(self, milliseconds, force=False):
        self.flush(force=True)
        self.wait_count += 1
        if self.no_wait or self.skip_print:
            return
        if force:
            time.sleep(milliseconds / 1000)
        else:
            self.input(
                string=True, default='', kind='timed_wait', timeout_ms=milliseconds
            )

    def warning(self, key, message):
        if key not in self.warning_keys:
            self.warning_keys.add(key)
            text = f'[PyEmuera warning] {message}'
            # stderr can share the same physical terminal as the retained ANSI
            # projection. Its writes invalidate pixels unknown to the frame.
            shared = self._diagnostic_shares_terminal()
            cursor_before = self._frame.last_cursor if self._frame else None
            if shared:
                self.flush(force=True)
                if self._frame is not None:
                    self._sink('\x1b[0m')
                    self._flush_host()
                else:
                    self.reset_style()
                    if self.current:
                        self._sink('\n')
                        self._flush_host()
                        self.emitted_columns = 0
                        self._row_has_output = False
            print(text, file=sys.stderr)
            if shared and self._frame is not None:
                self._frame.external_diagnostic(text)
            elif shared and self._retained is not None:
                # A later global repaint must retain already visible warnings.
                self._retained.diagnostic_lines.append(text)
            self.diagnostic_events.append(
                {
                    'key': key,
                    'renderer': self.renderer_mode,
                    'shared_terminal': shared,
                    'layer': 'physical_diagnostic',
                    'logical_history_changed': False,
                    'frame_cursor_before': cursor_before,
                    'frame_cursor': self._frame.last_cursor if self._frame else None,
                    'columns_requested': self.columns,
                    'viewport': self._frame.previous_size if self._frame else None,
                }
            )

    def _diagnostic_shares_terminal(self):
        if not self.is_terminal() or not getattr(sys.stderr, 'isatty', lambda: False)():
            return False
        try:
            if os.name == 'nt':
                import msvcrt, ctypes

                mode = ctypes.c_ulong()
                return bool(
                    ctypes.windll.kernel32.GetConsoleMode(
                        msvcrt.get_osfhandle(self.output.fileno()), ctypes.byref(mode)
                    )
                    and ctypes.windll.kernel32.GetConsoleMode(
                        msvcrt.get_osfhandle(sys.stderr.fileno()), ctypes.byref(mode)
                    )
                )
            return os.ttyname(self.output.fileno()) == os.ttyname(sys.stderr.fileno())
        except (OSError, ValueError, AttributeError):
            return False

    def last_line(self, index=0):
        if index == 0 and self.current:
            return self.current
        values = list(self.lines)
        return values[-1 - index] if 0 <= index < len(values) else ''

    def is_terminal(self):
        return bool(getattr(self.output, 'isatty', lambda: False)())

    def enable_color(self, mode):
        requested = mode == 'always' or (mode == 'auto' and self.is_terminal())
        enabled = requested
        if requested and os.name == 'nt':
            from .windows_console_mode import WindowsOutputMode

            if '_output_mode' not in self.__dict__:
                self._output_mode = WindowsOutputMode.for_output(self.output)
                self.output_mode_status = self._output_mode.status
            # A real console emits color only after the VT lease succeeds.
            # Non-console sinks have no mode word; always/auto still records VT.
            if self._output_mode.api is not None:
                enabled = self._output_mode.enable()
            else:
                self._output_mode.enable()
        self.color_enabled = enabled
        self.vt_enabled = enabled or (os.name != 'nt' and self.is_terminal())

    def reset_style(self):
        if self._frame is not None:
            return
        if self.color_enabled and self._last_style is not None:
            self._write_host('\x1b[0m')
            self._flush_host()
            self._last_style = None

    def clear_lines(self, n):
        self._check_output()
        if self.batch_output:
            self._flush_host()
        if n <= 0:
            return
        count = min(n, len(self.lines))
        physical = 0
        if self._retained is not None:
            self._retained.clear(count)
        for _ in range(count):
            self.lines.pop()
            if self._rule_lines:
                self._rule_lines.pop()
            if self.log_lines:
                self.log_lines.pop()
            if self.markup_lines:
                self.markup_lines.pop()
            physical += self._screen_rows.pop() if self._screen_rows else 1
        self.line_count = max(0, self.line_count - count)
        self._native_print_buffer = (0, 0, None)
        self._reset_shape_projection()
        self.current = ''
        self.log_current = ''
        self.markup_current = []
        self.emitted_columns = 0
        self._pending.clear()
        self._row_has_output = False
        if self._frame is not None:
            return
        if self.is_terminal() and self.vt_enabled:
            self._write_host('\r\x1b[2K' + ('\x1b[1A\x1b[2K' * physical) + '\r')
            self._flush_host()
        elif count:
            self.warning(
                'rewrite',
                'Redirected output is append-only; CLEARLINE updates VM history without emitting fake game text.',
            )

    def reuse_line(self, text):
        self._check_output()
        if self.batch_output:
            self._flush_host()
        # Rewrite pending/current line, not the previous completed history line.
        self._native_print_buffer = (0, 0, None)
        self._reset_shape_projection()
        self.current = ''
        self.log_current = ''
        self.markup_current = []
        self.emitted_columns = 0
        self._pending.clear()
        self._row_has_output = False
        if self._retained is not None:
            self._retained.current = []
            self._retained.dirty = True
        if self._frame is not None:
            pass
        elif self.is_terminal() and self.vt_enabled:
            self._write_host('\r\x1b[2K')
        else:
            self.warning(
                'reuse',
                'Redirected output cannot erase earlier bytes; REUSELASTLINE replaces only pending VM text.',
            )
        self.write(text)
        self.temporary_line = True

    def discard_current(self):
        """Clear the uncommitted logical row and every projection of that row."""
        self._native_print_buffer = (0, 0, None)
        self._reset_shape_projection()
        self.current = ''
        self.log_current = ''
        self.markup_current = []
        self.emitted_columns = 0
        self._pending.clear()
        self._row_has_output = False
        if self._retained is not None:
            self._retained.current = []
            self._retained.dirty = True

    def _set_style(self, style):
        if style is not None and self.ui is not None:
            style = (style[0], self.ui['bgcolor'], style[2])
        if not self.color_enabled or style is None or style == self._last_style:
            return
        fg, bg, bits = style
        codes = (
            ['0']
            + (['1'] if bits & 1 else [])
            + (['3'] if bits & 2 else [])
            + (['4'] if bits & 4 else [])
            + (['9'] if bits & 8 else [])
        )
        codes += [
            f'38;2;{fg>>16&255};{fg>>8&255};{fg&255}',
            f'48;2;{bg>>16&255};{bg>>8&255};{bg&255}',
        ]
        self._write_host('\x1b[' + ';'.join(codes) + 'm')
        self._last_style = style

    def flush(self, force=False):
        self._check_output()
        if self._frame is not None:
            if self.ui is not None:
                self._frame.set_background(self.ui['bgcolor'])
            if force or self._redraw & 1:
                try:
                    self._frame.present()
                except (OSError, ValueError) as exc:
                    self._record_output_failure(exc)
                    raise
            return
        if not self._pending:
            if self.batch_output:
                self._flush_host()
            return
        from .layout import projected_cell

        # Group runs by style; write one large string per run, not per glyph.
        if not self._row_has_output and self.ui is not None:
            from .layout import project, terminal_width

            width = terminal_width(
                project(''.join(c for c, _ in self._pending), self.ambiguous_width),
                self.ambiguous_width,
            )
            gap = max(0, self.columns - width)
            alignment = self.ui.get('alignment', 'LEFT')
            if alignment in ('CENTER', 'RIGHT'):
                self._write_host(' ' * (gap // 2 if alignment == 'CENTER' else gap))
        self._row_has_output = True
        previous = None
        run = []
        for i, (c, style) in enumerate(self._pending):
            if previous != style and run:
                self._set_style(previous)
                self._sink(''.join(run))
                run = []
            following = self._pending[i + 1][0] if i + 1 < len(self._pending) else ''
            run.append(projected_cell(c, following, self.ambiguous_width))
            previous = style
        if run:
            self._set_style(previous)
            self._sink(''.join(run))
        self._pending.clear()
        self._flush_host()

    def configure_renderer(self, mode='auto'):
        if mode not in ('auto', 'diff', 'stream'):
            raise ValueError('Invalid renderer')
        self._check_output()
        self.renderer_mode = mode
        if self.is_terminal() and self.vt_enabled and self._retained is None:
            from .terminal_frame import RetainedFrame

            frame = RetainedFrame(
                self.output,
                layout=self.layout,
                ambiguous_width=self.ambiguous_width,
                columns=self.columns,
                color=self.color_enabled,
                alternate_screen=mode != 'stream',
            )
            frame.set_background(self.ui['bgcolor'] if self.ui else 0)
            # Configuration precedes game output in CLI. On a late API switch,
            # reconstruct old HTML runs (foreground/font style) when available.
            for i, text in enumerate(self.lines):
                rule = self._rule_lines[i] if i < len(self._rule_lines) else None
                if rule:
                    style, alignment = rule
                    frame.feed_rule(text + '\n', style, alignment)
                elif (
                    i < len(self.markup_lines)
                    and ''.join(t for t, _ in self.markup_lines[i][0]) == text
                ):
                    runs, alignment = self.markup_lines[i]
                    for t, mark in runs:
                        frame.feed(t, (mark.color, 0, mark.bits), alignment)
                    frame.feed('\n')
                else:
                    frame.feed(text + '\n')
            if self.current:
                frame.feed(self.current)
            self._retained = frame
        if mode == 'diff':
            self._activate_frame()

    def set_background(self, color):
        """Change the display surface, preserving text/foreground/font history.

        A VT stream needs a retained viewport once a global repaint is requested;
        it uses the main screen rather than the diff backend's alternate screen.
        Redirected/non-VT output remains append-only and cannot recolor old bytes.
        """
        old_color = self.ui['bgcolor'] if self.ui is not None else 0
        if self.ui is not None:
            self.ui['bgcolor'] = color
        if self._retained is not None:
            self._retained.set_background(color)
            if self.color_enabled and color != old_color:
                self._activate_frame(flush_pending=False)
                if self._redraw & 1:
                    self._frame.present()

    def _activate_frame(self, *, flush_pending=True):
        if self._frame is not None or self._retained is None:
            return
        # A global repaint already has this row in the retained model. Emitting
        # the stream buffer first would violate a REDRAW-suppressed transition.
        if flush_pending:
            self.flush()
        self._frame = self._retained
        self._pending.clear()

    def set_redraw(self, value):
        self._redraw = value
        if self.renderer_mode != 'stream' and not (value & 1):
            self._activate_frame()
        if value & 2:
            self.flush(force=True)

    def close(self):
        """Flush healthy output, then restore terminal modes without game replay.

        After an output failure, presentation is unsafe because the host may
        already hold a prefix. Cleanup may still emit style/cursor restoration;
        these backend sequences never enter ERB history or OUTPUTLOG.
        """
        try:
            self._sync_output_failure()
            try:
                if self._output_failure is None:
                    self.flush(force=True)
            finally:
                if self._frame is not None:
                    self._frame.close()
                elif self.color_enabled and self._last_style is not None:
                    from .host_output import write_all

                    try:
                        write_all(self.output, '\x1b[0m')
                        self.output.flush()
                    finally:
                        self._last_style = None
        finally:
            # VT must remain enabled for the ANSI cleanup above. Its Win32 mode
            # lease is separate from the frame/input cursor and runs even when
            # physical restoration writes fail or KeyboardInterrupt propagates.
            lease = self.__dict__.get('_output_mode')
            if lease is not None:
                lease.restore()
