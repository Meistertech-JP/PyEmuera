# Portable direct Jamo comparison

The portable implementation targets the pinned Windows 10 Japanese NLS
profile already shipped with PyEmuera. It does not establish compatibility
with every Unicode string or with other versions of NLS. The Windows native
backend, Framework sorting algorithm, and unary sort-key API remain separate.

## Entry and fallback

`direct_jamo_sign` runs only for exact `str` inputs containing a Jamo code unit or a BMP
category-1 unit from the fixed NLS table. The 500-unit category-1 entry set is
generated from that table and tested exhaustively over the BMP.
Other strings and string subclasses keep the existing path. Non-Jamo
nonspacing/separator boundaries use the same state rules. The implementation uses the
existing fixed weight and Jamo tables and Python's standard library only.
There are no native calls, expected-answer dictionaries, or normalization.

The state machine returns `None` for a category whose reached transition has
not been implemented. The caller then compares the complete original inputs
using the established portable path. It does not compare only the remaining
suffix. An unsupported character in an unvisited suffix does not invalidate an
already decisive comparison.

## State and order

Each side retains its original UTF-16 tuple, cursor, cached weight, Jamo extra
weight, and provenance of an internally generated invalid-kana cache. All state
is local to one comparison. The pair retains the first pending diacritic and
case differences, four kana levels, and word-punctuation state.

1. Scan equal raw prefixes. If the immediately preceding common unit is Jamo,
   restart both cursors from the original buffers. Removing the prefix or
   restarting only the previous cluster is not equivalent.
2. Sample the cached categories before dispatch. Mapping may change the cached
   primary and cursor, while the sampled categories still control this pass.
3. Build an old-Hangul cluster from the pinned five-field records. Supply the
   native fillers for missing slots, accumulate nearest modern indices and
   slot extras, and retain the native last-consumed cursor convention.
4. When one side skips an ignored unit or punctuation, preserve the other
   side's mapped cache. The next sample can therefore have a synthesized
   Hangul category rather than the original Jamo category.
5. Compare primary weights. Compare the Jamo extra weights only when both
   pre-mapper samples were category 4. Comparing extras whenever primary
   weights match would impose a different ordering.
6. Preserve secondary differences while primary comparison continues.
   A current diacritic mismatch may consume immediately adjacent nonspacing
   units before establishing the pending difference. An already pending
   difference changes the later nonspacing and termination behavior.
7. Kana repetition/prolongation examines preceding original input units.
   It must not reuse a Jamo's synthesized primary as the preceding raw weight.
   An invalid contextual kana produces an internal `0xffff` cache; this is
   distinguished from an unsupported input weight with category `0xff`.
8. At one-sided termination, inspect remaining original units. Significant
   trailing input can take precedence over a pending secondary difference.
   Only after both sides finish are remaining pending levels returned.

These rules deliberately preserve nontransitive results of the observed direct
comparison. They do not turn direct comparison into unary sort-key ordering.

## Native evidence anchors

Addresses are relative to the fixed `kernel32.dll` whose SHA-256 is
`3701c8bb5a0e8dc6ce06b2ef878a73747df5d3570e4b1293ca71bb5764566d49`.
They are evidence references, not addresses used by the implementation.

| Behavior | Observed native path |
| --- | --- |
| Long comparison and cached samples | `3c80`, `3e52` |
| Prefix scan and Jamo restart | `4070`, `412b–418c` |
| Jamo mapping and state update | `5a460–5a743`, `5a74c` |
| Sampled category gate for extra weights | `5daa`, `2f4a3` |
| One-sided end and remaining input scan | `4278`, `47ca`, `4a03` |
| Kana mapping and raw backward search | `5338`, `2eed0–2f0b3` |
| Standalone nonspacing dispatch | `2f0db`, `2f45b` |
| Diacritic lookahead | `5614`, `5691`, `2f577`, `2f631` |
| Pending diacritic at termination | `2f69c`, `2f71d` |

## Regression evidence in the source tree

`tests/test_direct_jamo_state.py` checks the 36,864-direction fixture
and its hash, checks intermediate mapper/sample observations, and replays
independent structural, kana, and nonspacing controls. The compact fixtures
under `tests/fixtures/post_b1_direct` retain all three saved comparison signs
and their raw Oracle hashes. They are test data, never runtime input.

Build a pyz from the current source before testing changes. Validation results are scoped to the archived Windows/NLS profile and the
recorded test populations; passing them does not imply complete equivalence
for all Windows versions or Unicode strings.
