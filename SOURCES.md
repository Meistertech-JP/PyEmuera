# Sources and implementation basis

PyEmuera is a new Python implementation. This file lists the references that were consulted and what each one was used for. It distinguishes public documentation, inspected Emuera source code, and measurements of the original program. A reference listed here does not certify that PyEmuera is correct for every variant. Licensing and attribution are described in `THIRD_PARTY_NOTICES.md`.

No variant, variant text, save file, Emuera executable or complete Emuera source tree is distributed with PyEmuera. The only Emuera source files in the source distribution are five unmodified test fixtures; see `THIRD_PARTY_NOTICES.md`.

## 1. Primary reference: Emuera1824+v24

- Archive: `Emuera1824+v24.zip`, SHA-256 `fd0dd5b83ab3f929e69de0b9af739fa9bf785b6f510b30d11aaf44db35af182a`.
- This is the behavioral target of the current version. Its C# source was read for evaluation order, argument validation, diagnostics and registration tables. Per-registration evidence is recorded in `SOURCE_AUDIT_1824_v24.json`.
- Measurements of the executable from this archive (neutral ERB probes and their output logs) are stored as test fixtures and verification data. The identity between that executable and the bundled source is not proven.

## 2. Historical reference: Emuera 1.8.2.4 source (`src1824.zip`)

- Archive SHA-256 `ade8812a96390991c1d5662fa13f6cf508c87c8027d76856ccde96e700481794`, inspected from 2026-10-06. The archive name is not an independent certificate of authenticity.
- Used before Emuera1824+v24 became the primary reference, and now for historical comparison. Per-registration evidence is recorded in `SOURCE_AUDIT_1824.json`.
- Files consulted:
  - Save formats: `Sub/EraDataStream.cs` (positional text arrays, FINISHED and extension/SEP markers, CRLF, typed extension groups), `Sub/EraBinaryDataReader.cs` and `Sub/EraBinaryDataWriter.cs` (magic, wire version 1808, UTF-16LE .NET strings, packed integers, sparse 1D/2D/3D markers, character separators).
  - Variables: `GameData/Variable/VariableCode.cs`, `VariableData.cs`, `CharacterData.cs` (the 60 legacy global numeric slots including unused positions, 17 character numeric arrays, extension arrays, user-variable groups, clipping, clear-versus-copy), `VariableEvaluator.cs` (identity and version handling, LASTLOAD fields, SaveChara/LoadChara/GetDatFiles, DumpRanddata/InitRanddata), `VariableLocal.cs`, `IdentifierDictionary.cs` (forbidden LOCAL/ARG).
  - Game data: `GameData/GameBase.cs` (initial values, tryatoi, undefined VERSION), `GameData/ConstantData.cs` (setDefaultArrayLength, _decideActualArraySize_sub, loadDataTo, setCharacterData).
  - Process: `GameProc/LabelDictionary.cs` (first definition of duplicate non-event functions), `GameProc/Process.ScriptProc.cs`, `Process.State.cs`, `GameProc/LogicalLineParser.cs` (prefix increment lines), `GameProc/ErbLoader.cs`, `GameData/Function/UserDefinedMethodTerm.cs` (end of function and default return values).
  - Commands and functions: `GameProc/Function/FunctionIdentifier.cs` (PRINT registrations), `Function/Instraction.Child.cs` (PRINT handling flags, RETURN METHOD_SAFE check, RANDOMIZE/INITRAND/DUMPRAND, input), `GameData/Function/Creator.Method.cs` (UTF-16, arithmetic, COLOR, string, array, regex, grouping, joining, key state, client size), `ArgumentBuilder.cs` (SP_INPUTS, timed input, array builders), `ExpressionMediator.CheckEscape`, `ConvertStringType`.
  - Text: `Sub/LexicalAnalyzer.cs` (ReadSingleIdentifier, AnalyseFormattedString, AnalyseYenAt, full-width symbols), `GameView/EmueraConsole.Print.cs` (two-stage FORM, PRINTK/D, fixed-column padding, line rules), `GameView/HtmlManager.cs`.
  - Random numbers: `_Library/SFMT.cs`.
- Findings that shaped the implementation:
  - REF/REFBYNAME and SAVEVAR/LOADVAR throw `NotImplCodeEE` unconditionally in this source. PyEmuera reports them as unimplemented instead of inventing a successful behavior.
  - Normal save and load do not call DumpRanddata/InitRanddata automatically; only the corresponding instructions do. `--native-rng source` follows this; `--native-rng restore` is an opt-in extension.
  - The supported expression-function arities in `pyemuera/specs/functions.json` describe the implemented subset, not every original overload.

## 3. Public language documentation

The Emuera.EM+EE documentation project, consulted on 2026-10-06. Modern pages omit some legacy overloads; PyEmuera keeps legacy forms rather than treating the modern manual as exhaustive.

- Operators: https://evilmask.gitlab.io/emuera.em.doc/Emuera/operand.html
- Variables and numeric literals: https://evilmask.gitlab.io/emuera.em.doc/Emuera/variables.html
- User-defined variables: https://evilmask.gitlab.io/emuera.em.doc/Emuera/user_defined_variables.html
- Functions and preprocessors: https://evilmask.gitlab.io/emuera.em.doc/Emuera/function.html
- ERH headers and macros: https://evilmask.gitlab.io/emuera.em.doc/Emuera/ERH.html
- Expressions and FORM notation: https://evilmask.gitlab.io/emuera.em.doc/Emuera/expression.html
- User-defined in-expression functions: https://evilmask.gitlab.io/emuera.em.doc/Emuera/user_defined_in_expression_function.html
- Replacement: https://evilmask.gitlab.io/emuera.em.doc/Emuera/replace.html
- CSV format: https://evilmask.gitlab.io/emuera.em.doc/eramaker/CSV_format.html
- Engine flow: https://evilmask.gitlab.io/emuera.em.doc/Emuera/system_flow.html
- Commands: https://evilmask.gitlab.io/emuera.em.doc/Reference/PRINT.html, CALLF.html, RETURN.html, VARSET.html, REPEAT.html, FOR.html, CONTINUE.html, UNICODE.html, CALLTRAIN.html, STOPCALLTRAIN.html, DOTRAIN.html, SKIP_RELATE.html, EXISTCSV.html, GETCHARA.html, PRINTC.html, PRINTSINGLE.html, SORTCHARA.html, TWAIT.html, TINPUT.html (all under https://evilmask.gitlab.io/emuera.em.doc/Reference/)

## 4. Public Emuera source repository (early versions)

Repository `0x00000FF/Emuera`, pinned commit `301ce4a4a4d0b0b20a14428a4680cf3dbd3559d8`, consulted on 2026-10-06 before the Emuera 1.8.2.4 source became the reference.

- https://github.com/0x00000FF/Emuera/blob/301ce4a4a4d0b0b20a14428a4680cf3dbd3559d8/Emuera/GameProc/Process.cs
- https://github.com/0x00000FF/Emuera/blob/301ce4a4a4d0b0b20a14428a4680cf3dbd3559d8/Emuera/GameProc/Process.ScriptProc.cs
- https://github.com/0x00000FF/Emuera/blob/301ce4a4a4d0b0b20a14428a4680cf3dbd3559d8/Emuera/GameProc/Process.SystemProc.cs
- https://github.com/0x00000FF/Emuera/blob/301ce4a4a4d0b0b20a14428a4680cf3dbd3559d8/Emuera/GameData/Variable/VariableEvaluator.cs (reset behavior, through code-search excerpts)
- https://raw.githubusercontent.com/0x00000FF/Emuera/301ce4a4a4d0b0b20a14428a4680cf3dbd3559d8/Emuera/GameData/ConstantData.cs

That revision is not authenticated as the official Emuera 1.824 build. Decisions recorded at that time, and still reflected in the code:

- SKIPDISP: the documentation says RESULT is always zero, while the inspected source assigns zero or one according to the skip flag. PyEmuera follows the source.
- CALLTRAIN installs a queue and the script continues with the following statements. Zero-count and replacement-of-active-queue cases are rejected instead of reproducing the legacy edge cases.
- NEXTCOM is set to zero after selection; the resulting loop can be stopped by the instruction budget.
- TRAIN menu positions and Train.csv ids are distinct. Disabled entries keep their positions; queues use CSV ids.
- MESSKIP/MOUSESKIP and display are adapted to a text terminal; mouse and GUI compatibility are not claimed.

## 5. Random numbers (SFMT19937)

- `_Library/SFMT.cs` of the Emuera source (credits in `THIRD_PARTY_NOTICES.md`).
- SFMT author resources (algorithm and test vectors only): https://www.math.sci.hiroshima-u.ac.jp/m-mat/MT/SFMT/ and https://raw.githubusercontent.com/MersenneTwister-Lab/SFMT/master/SFMT.19937.out.txt
- `pyemuera/random1824.py` implements the recurrence, the 625-word state layout, certification, Emuera's 32-bit combination and modulo range selection. The short seed-1234 prefix of the published test vectors is used as a test. During development a separately written scalar C++ recurrence was used for a 60,000-output differential comparison; it is not included in this distribution.

## 6. .NET Framework sorting

- Microsoft Reference Source, inspected on 2026-10-13:
  - https://github.com/microsoft/referencesource/blob/main/mscorlib/system/collections/generic/arraysorthelper.cs
  - https://github.com/microsoft/referencesource/blob/main/mscorlib/system/collections/generic/list.cs
  - https://github.com/microsoft/referencesource/blob/main/LICENSE.txt
- `pyemuera/sort1824.py` (List.Sort, used by ARRAYMSORT) and `pyemuera/arraysort1824.py` (Array.Sort, used by string ARRAYSORT) adapt the sorting control flow. Their behavior was checked against .NET Framework 4.8 measurements stored under `tests/fixtures/`.

## 7. String collation

- Windows: the operating system's `CompareStringEx` (NLS API), through `pyemuera/collation_windows.py`.
- Other platforms: `pyemuera/collation_portable.py` and `pyemuera/collation_jamo.py`, built from the published Windows 10 Sorting Weight Table and the [MS-UCODEREF] specification (see `THIRD_PARTY_MS_NLS_NOTICE_ja.md`). Expected comparison results come from .NET Framework 4.8 `CompareTo` measurements with ja-JP culture, stored under `tests/fixtures/`. The known differences are described in `COMPATIBILITY_ja.md`.

## 8. CP932 best-fit table

- https://www.unicode.org/Public/MAPPINGS/VENDORS/MICSFT/WindowsBestFit/bestfit932.txt (Microsoft vendor data published by Unicode), Unicode License V3. `pyemuera/specs/cp932_bestfit.json` is derived from it; table SHA-256 `2614cfea35c3c86c41d33198793a84ca44edee3cf0ee0013a61a43fba4ece331`.

## 9. Variants used for local checks

Several existing Emuera variants were run locally, unchanged, to find language features and to check play routes: 東方触手宮 Ver1.18.2修正版 and Ver1.02.1, eratohoJ+ v1.05.5, eratohoYM Mk-3改8proto6, eratohoM3S and eratohoW. The checked ranges are listed in `COMPATIBILITY_ja.md`. Their files, text, saves and output logs are not included. The unit tests use small independent scripts that reproduce language features, not variant content.
