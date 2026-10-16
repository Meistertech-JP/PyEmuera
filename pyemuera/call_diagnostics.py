"""Project warning settings without removing raw records or normal line errors.

Missing CALL, missing CALLF, and uncalled labels have distinct native paths.
ONCE is per uppercase source file, with separate sets for each warning family.
Analysis mode aggregates ordinary missing CALL names instead of flushing lines.
The native missing summary deliberately consults FunctionNotCalledWarning.
"""

from collections import Counter


def project_missing_calls(program, threshold):
    mode = program.config.get('関数が見つからない警告の扱い', 'IGNORE').upper()
    other = program.config.get('関数が呼び出されなかった警告の扱い', 'IGNORE').upper()
    if mode not in {'IGNORE', 'DISPLAY', 'ONCE', 'LATER'}:
        mode = 'IGNORE'
    if other not in {'IGNORE', 'DISPLAY', 'ONCE', 'LATER'}:
        other = 'IGNORE'
    shown = []
    seen_missing, seen_uncalled = set(), set()
    suppressed = uncalled_suppressed = raw = 0
    analysis_names = Counter()
    events = getattr(program, 'load_diagnostic_events', None)
    if events is None:
        # Older direct API clients may construct only the category collections.
        events = [
            *program.argument_diagnostics,
            *getattr(program, 'uncalled_diagnostics', []),
        ]
    else:
        # Preserve the historical mutable category API: externally appended
        # records have no loader event and are projected after known events.
        registered = {id(diagnostic) for diagnostic in events}
        events = [
            *events,
            *[
                diagnostic
                for diagnostic in [
                    *program.argument_diagnostics,
                    *getattr(program, 'uncalled_diagnostics', []),
                ]
                if id(diagnostic) not in registered
            ],
        ]
    for diagnostic in events:
        phase = diagnostic.phase
        if phase == 'call-resolution' and program.analysis_mode:
            # Native printFunctionNotFoundWarning returns before setting IsError,
            # before DisplayWarningLevel, and before the IGNORE/ONCE policy.
            message = diagnostic.internal_message or diagnostic.reference_message
            name = message.removeprefix('Unknown function @')
            analysis_names[name] += 1
            continue
        if phase == 'uncalled-function':
            filename = diagnostic.location.path.upper()
            hide = other in {'IGNORE', 'LATER'}
            if other == 'ONCE' and filename:
                hide = filename in seen_uncalled
                seen_uncalled.add(filename)
            # Native counts uncalled suppression before the level filter.
            if hide:
                uncalled_suppressed += 1
            elif diagnostic.severity >= threshold or program.analysis_mode:
                shown.append(diagnostic)
            continue
        if diagnostic.severity < threshold and not program.analysis_mode:
            continue
        if phase != 'call-resolution':
            shown.append(diagnostic)
            continue
        raw += 1
        filename = diagnostic.location.path.upper()
        hide = mode == 'IGNORE'
        if mode == 'ONCE' and filename:
            hide = filename in seen_missing
            seen_missing.add(filename)
        if hide:
            suppressed += 1
        else:
            shown.append(diagnostic)
    summaries = []
    if analysis_names:
        summaries += [
            '・定義が見つからなかった関数: 他のファイルで定義されている場合はこの警告は無視できます',
            '　○一般関数:',
        ]
        summaries += [
            '　　' + name + ': ' + str(count) + '回'
            for name, count in analysis_names.items()
        ]
    else:
        if uncalled_suppressed and threshold <= 1 and other != 'IGNORE':
            summaries.append(
                '警告Lv1:定義された関数が一度も呼び出されていない事に関する警告を'
                + str(uncalled_suppressed)
                + '件無視しました'
            )
        if suppressed and threshold <= 2 and other != 'IGNORE':
            summaries.append(
                '警告Lv2:定義されていない関数を呼び出した事に関する警告を'
                + str(suppressed)
                + '件無視しました'
            )
    return (
        shown,
        summaries,
        {
            'mode': mode,
            'minimum_level': threshold,
            'missing_diagnostics_at_visible_level': raw,
            'suppressed_individual_warnings': suppressed,
            'summary_count': len(summaries),
            'summary_source_condition_FunctionNotCalledWarning': other,
            'uncalled_suppressed': uncalled_suppressed,
            'analysis_missing_names': dict(analysis_names),
            'native_binary_cross_setting_acceptance': 'pending',
        },
    )
