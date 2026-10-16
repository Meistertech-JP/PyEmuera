"""Retained terminal projection, independent of ERB history and save state.

Only a terminal backend uses this module. A REDRAW-suppressed logical edit does
not erase physical rows. present() builds a complete snapshot and patches changed
rows in one host write. This is not a promise of atomic repaint by every terminal.
"""

from __future__ import annotations
from collections import deque
from dataclasses import dataclass
import shutil
from itertools import islice
from .layout import project, projected_cell, terminal_width, project_rule

DEFAULT_STYLE = (0xC0C0C0, 0, 0)


@dataclass(frozen=True)
class ScreenRow:
    runs: tuple
    width: int


@dataclass(frozen=True)
class RuleRow:
    """Command provenance; the text remains the complete logical rule."""

    text: str
    style: tuple
    alignment: str


def sgr(style):
    fg, bg, bits = style or DEFAULT_STYLE
    codes = ['0'] + [
        str(code) for bit, code in ((1, 1), (2, 3), (4, 4), (8, 9)) if bits & bit
    ]
    codes.extend(
        (
            f'38;2;{fg>>16&255};{fg>>8&255};{fg&255}',
            f'48;2;{bg>>16&255};{bg>>8&255};{bg&255}',
        )
    )
    return '\x1b[' + ';'.join(codes) + 'm'


class RetainedFrame:
    def __init__(
        self,
        output,
        *,
        layout='terminal',
        ambiguous_width=1,
        columns=100,
        color=True,
        size_provider=None,
        alternate_screen=True,
    ):
        self.output = output
        self.layout = layout
        self.ambiguous_width = ambiguous_width
        self.columns = columns
        self.color = color
        self.size_provider = size_provider or (
            lambda: shutil.get_terminal_size((columns, 24))
        )
        self.rows = deque(maxlen=10000)
        self.current = []
        self.alignment = 'LEFT'
        self.previous = None
        self.previous_size = None
        self.active = False
        self.closed = False
        self.last_cursor = None
        self.dirty = True
        self._wrap_cache = {}
        self.background = 0
        self.previous_background = None
        self.alternate_screen = alternate_screen
        self.diagnostic_lines = deque(maxlen=3)
        self.external_dirty = False
        self._output_failure = None
        self.stats = {
            'presents': 0,
            'unchanged': 0,
            'full': 0,
            'differential': 0,
            'changed_rows': 0,
            'host_writes': 0,
            'bytes': 0,
            'resizes': 0,
        }

    def _check_output(self):
        if self._output_failure is not None:
            raise self._output_failure

    def _write_host(self, text):
        from .host_output import write_all

        self._check_output()
        try:
            write_all(self.output, text)
        except (OSError, ValueError) as exc:
            self._output_failure = exc
            raise

    def _flush_host(self):
        self._check_output()
        try:
            self.output.flush()
        except (OSError, ValueError) as exc:
            self._output_failure = exc
            raise

    def feed(self, text, style=None, alignment='LEFT'):
        self.dirty = True
        style = style or DEFAULT_STYLE
        # Background is not part of the lifetime of a printed string.
        style = (style[0], 0, style[2])
        for index, chunk in enumerate(text.split('\n')):
            if index:
                self.rows.append((tuple(self.current), self.alignment))
                self.current = []
            if not self.current:
                self.alignment = alignment
            if chunk:
                if self.current and self.current[-1][1] == style:
                    self.current[-1] = (self.current[-1][0] + chunk, style)
                else:
                    self.current.append((chunk, style))

    def feed_rule(self, text, style=None, alignment='LEFT'):
        # Console commits the preceding logical row before a rule command.
        if self.current:
            self.feed('\n')
        style = style or DEFAULT_STYLE
        style = (style[0], 0, style[2])
        chunks = text.split('\n')
        for chunk in chunks[:-1]:
            self.rows.append(RuleRow(chunk, style, alignment))
        if chunks[-1]:
            self.feed(chunks[-1], style, alignment)
        self.dirty = True

    def clear(self, n):
        for _ in range(min(n, len(self.rows))):
            self.rows.pop()
        self.current = []
        self.dirty = True

    def reuse(self, text, style=None, alignment='LEFT'):
        self.current = []
        self.feed(text, style, alignment)

    def invalidate(self):
        # A normal host input echo is outside this projection. Do not trust the
        # previous pixels for the next present, but never erase before writing.
        self.previous = None
        self.dirty = True

    def set_background(self, color):
        if color != self.background:
            self.background = color
            self.dirty = True

    def _paint_style(self, style):
        fg, _, bits = style or DEFAULT_STYLE
        return fg, self.background, bits

    def _wrap(self, runs, alignment, width):
        key = (runs, alignment, width, self.columns, self.layout, self.ambiguous_width)
        cached = self._wrap_cache.get(key)
        if cached is not None:
            return cached
        chars = [(c, style) for text, style in runs for c in text]
        units = []
        for i, (c, style) in enumerate(chars):
            following = chars[i + 1][0] if i + 1 < len(chars) else ''
            text = (
                projected_cell(c, following, self.ambiguous_width)
                if self.layout == 'terminal'
                else c
            )
            if c == '\t':
                text = ' ' * (8 - sum(u[2] for u in units) % 8)
            units.extend(
                (g, style, terminal_width(g, self.ambiguous_width)) for g in text
            )
        total = sum(x[2] for x in units)
        gap = max(0, self.columns - total)
        if alignment in ('CENTER', 'RIGHT'):
            pad = gap // 2 if alignment == 'CENTER' else gap
            units = [(' ', DEFAULT_STYLE, 1)] * pad + units
        out = []
        row = []
        used = 0

        def emit():
            nonlocal row, used
            out.append(ScreenRow(tuple(row), used))
            row = []
            used = 0

        for glyph, style, size in units:
            if size > width:
                glyph = '?'
                size = 1
            if used + size > width and used:
                emit()
            if row and row[-1][1] == style:
                row[-1] = (row[-1][0] + glyph, style)
            else:
                row.append((glyph, style))
            used += size
        emit()
        result = tuple(out)
        if len(self._wrap_cache) >= 256:
            self._wrap_cache.pop(next(iter(self._wrap_cache)))
        self._wrap_cache[key] = result
        return result

    def _project_game_rows(self, height, width):
        """Project logical rows; rules fit one row, ordinary text may wrap.

        This stage preserves history and styles. Diagnostics, viewport clipping,
        prompt cursor and current global background are applied by snapshot.
        """
        logical = list(islice(reversed(self.rows), height))
        logical.reverse()
        logical.append((tuple(self.current), self.alignment))
        physical = []
        for entry in logical:
            if isinstance(entry, RuleRow):
                text, used = project_rule(
                    entry.text,
                    min(self.columns, width),
                    layout=self.layout,
                    ambiguous=self.ambiguous_width,
                    alignment=entry.alignment,
                )
                physical.append(ScreenRow(((text, entry.style),), used))
            else:
                runs, alignment = entry
                physical.extend(self._wrap(runs, alignment, width))
        return physical

    def _diagnostic_rows(self, width, height):
        """Keep warning heads while reserving most of the viewport for the game.

        Full messages remain in diagnostic_lines and the original stderr write.
        Only an overflowing retained projection is summarized. At least two
        game rows survive; newest warnings take precedence in tiny viewports.
        Short warnings retain the exact prior projection. No warning is newly
        registered here, and no ERB/OUTPUTLOG history is changed.
        """
        if height <= 2:
            return []
        budget = min(height - 2, max(1, height // 3))
        blocks = [
            self._wrap(((text, DEFAULT_STYLE),), 'LEFT', width)
            for text in self.diagnostic_lines
        ]
        if sum(map(len, blocks)) <= budget:
            return [row for block in blocks for row in block]
        # The repeated product label must not displace the warning's meaning
        # in a narrow summary. This is a physical label, not a new diagnostic.
        summaries = [
            (
                '[!] ' + text[len('[PyEmuera warning] ') :]
                if text.startswith('[PyEmuera warning] ')
                else text
            )
            for text in self.diagnostic_lines
        ]
        blocks = [
            self._wrap(((text, DEFAULT_STYLE),), 'LEFT', width)
            for text in summaries[-min(len(summaries), budget) :]
        ]
        each, extra = divmod(budget, len(blocks))
        projected = []
        for index, block in enumerate(blocks):
            allowance = each + (index >= len(blocks) - extra)
            shown = list(block[:allowance])
            if len(block) > allowance:
                # Input text is already projected. Measure/truncate cells, never
                # codepoints alone or a second CP932 projection of that text.
                marker = '.' * min(3, width)
                available = width - len(marker)
                prefix = []
                used = 0
                for text, _ in shown[-1].runs:
                    for glyph in text:
                        cells = terminal_width(glyph, self.ambiguous_width)
                        if used + cells > available:
                            break
                        prefix.append(glyph)
                        used += cells
                    else:
                        continue
                    break
                shown[-1] = ScreenRow(
                    ((''.join(prefix) + marker, DEFAULT_STYLE),), used + len(marker)
                )
            projected.extend(shown)
        return projected

    def snapshot(self):
        cols, height = self.size_provider()
        cols = max(2, int(cols))
        height = max(2, int(height))
        # Reserve the last terminal column: avoid automatic wrapping/scrolling
        # in the bottom-right cell, including a double-width final glyph.
        width = cols - 1
        physical = self._project_game_rows(height, width)
        # Backend diagnostics occupy a separate projection region; they never
        # enter ERB history, HTML_GETPRINTEDSTR, or OUTPUTLOG.
        diagnostic = self._diagnostic_rows(width, height)
        physical = physical[-max(1, height - len(diagnostic)) :]
        cursor = (len(physical), min(cols, physical[-1].width + 1))
        physical.extend(diagnostic)
        # Resolve the current console-wide background for every old/new run,
        # alignment pad and diagnostic. Cached wrapping contains text only.
        physical = [
            ScreenRow(
                tuple((text, self._paint_style(style)) for text, style in row.runs),
                row.width,
            )
            for row in physical
        ]
        return tuple(physical), cursor, (cols, height)

    def present(self):
        """Patch changed physical rows, then place the game/input cursor.

        Each changed row erases its suffix even when logical width grows: host
        glyph widths can differ. Unchanged rows receive no host write. A resize,
        external diagnostic or global background change invalidates pixels.
        """
        self._check_output()
        frame, cursor, size = self.snapshot()
        self.stats['presents'] += 1
        old = self.previous
        background_changed = self.previous_background != self.background
        obsolete_rows = len(old or ())
        if self.previous_size is not None and self.previous_size != size:
            self.stats['resizes'] += 1
            old = None
        if old == frame and self.last_cursor == cursor and not background_changed:
            self.stats['unchanged'] += 1
            self.dirty = False
            return
        patch = []
        if not self.active:
            patch.append(('\x1b[?1049h' if self.alternate_screen else '') + '\x1b[?25l')
            self.active = True
        self.stats['full' if old is None else 'differential'] += 1
        count = (
            size[1]
            if self.external_dirty or background_changed or old is None
            else max(len(frame), len(old), obsolete_rows)
        )
        empty = ScreenRow((), 0)
        for index in range(min(count, size[1])):
            row = frame[index] if index < len(frame) else empty
            before = old[index] if old is not None and index < len(old) else None
            if before == row and not background_changed:
                continue
            patch.append(f'\x1b[{index+1};1H')
            for text, style in row.runs:
                if self.color:
                    patch.append(sgr(style))
                patch.append(text)
            # Clear the physical suffix after every changed row. Logical widths
            # cannot predict host glyph widths (e.g. conhost U+2026 uses two
            # cells). Equal or growing logical rows can still leave old cells.
            # Unchanged rows remain untouched; history and wrapping are separate.
            if self.color:
                patch.append(sgr(self._paint_style(DEFAULT_STYLE)))
            patch.append('\x1b[K')
            self.stats['changed_rows'] += 1
        patch.append(f'\x1b[{cursor[0]};{cursor[1]}H')
        text = ''.join(patch)
        self._write_host(text)
        self._flush_host()
        self.stats['host_writes'] += 1
        self.stats['bytes'] += len(text.encode('utf-8', 'replace'))
        self.previous = frame
        self.previous_size = size
        self.last_cursor = cursor
        self.dirty = False
        self.external_dirty = False
        self.previous_background = self.background

    def external_diagnostic(self, text):
        self.diagnostic_lines.append(text)
        self.external_dirty = True
        self.invalidate()
        self.present()

    def present_prompt(self, text='> '):
        """A host input prompt is a projection overlay, never game history."""
        saved, alignment = list(self.current), self.alignment
        try:
            self.feed(text)
            self.present()
            self._write_host('\x1b[?25h')
            self._flush_host()
        finally:
            self.current = saved
            self.alignment = alignment
            self.dirty = True

    def finish_prompt(self):
        """Host input owns the visible cursor until it returns or is cancelled."""
        self._write_host('\x1b[?25l')
        self._flush_host()
        self.invalidate()

    def close(self):
        if self.closed:
            return
        try:
            if self.active:
                from .host_output import write_all

                write_all(
                    self.output,
                    '\x1b[0m\x1b[?25h'
                    + ('\x1b[?1049l' if self.alternate_screen else ''),
                )
                self.output.flush()
        finally:
            self.active = False
            self.closed = True
