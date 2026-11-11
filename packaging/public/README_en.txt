==============================================================
 PyEmuera 3.0.0 (Pamyura)
 Technical version: 3.0.0
==============================================================

PyEmuera is an independent Python implementation for running Emuera game
variants (ERB, ERH and CSV) in a text terminal, generally without
modifying the game files. Its compatibility reference is Emuera1824+v24.
It is not an official Emuera distribution.

Images, audio, mouse input and rendering by Emuera's original GUI are
outside its scope. Your terminal's own font settings remain available.

WHY A NEW RUNTIME?

  Emuera developed primarily around Windows, making other platforms
  harder to use. Investigating or changing subtle behavior required
  editing and rebuilding C# code; some behavior depends on the .NET
  runtime or the OS rather than being visible in the application source.

  PyEmuera makes it easier to inspect, modify and experiment with the
  runtime while retaining existing Emuera variants. Python source
  changes can be tried without a separate compilation step, and text
  interaction through standard input and output can be connected to
  external programs.

  This is useful for AI-assisted variant development and testing,
  automated play, tool integration and entirely new ways to play.
  PyEmuera is not just for playing Emuera games: it is a runtime for
  doing new things with them.

PERFORMANCE

  Across fixed input routes, execution time was reduced by 26.7-35.0%
  compared with Beta 3, with improved input response. The comparison
  covers the complete releases, including compatibility fixes; effects
  vary by variant and route. Windows 10 / CPython 3.12.10, alternating
  runs, warmups excluded, median elapsed time. See README_ja.md in
  the source distribution for the measurement conditions.

  Large variants may take time to start or initialize. Variants that
  need real-time updates may not reach the original engine's tempo.

DISTRIBUTIONS

  Runtime: PyEmuera-3.0.0-runtime.zip
  Source:  PyEmuera-3.0.0-source.zip

QUICK START (WINDOWS)

  1. Install Python 3.10 or later (not bundled).
  2. Extract the runtime ZIP.
  3. Drag a variant folder containing ERB and CSV directories onto
     Start_PyEmuera.bat.

  Alternatively, use a terminal:

      python PyEmuera.pyz "path/to/variant"

  On Linux, use python3 if python is not available. To try the bundled
  sample, drag the sample folder onto Start_PyEmuera.bat or run:

      python PyEmuera.pyz sample --inputs sample/replay.txt --no-wait

  HOW_TO_USE_ja.txt is the detailed usage guide (Japanese).

REQUIREMENTS AND COMPATIBILITY

  - Python 3.10 or later; text-capable terminal.
  - No .NET or third-party Python runtime packages are needed.
  - Running the engine requires no Internet connection.
  - Historical checks include Windows 10 and Linux. Windows 11
    coverage is limited; macOS and Android/Termux are not verified.
  - Reference implementation: Emuera1824+v24.
  - EE/EM extension-only features are not supported.
  - Graphical rendering, mouse input and audio are not supported.
  - Unsupported commands stop with an error rather than silently
    reporting success.
  - Save interoperability and all game routes are not fully verified.
    See KNOWN_ISSUES_ja.txt (Japanese).
  - Windows uses native NLS collation; other systems use a bundled
    Japanese profile. In a fixed Windows 10 / ja-JP / NLS 0x60305
    reference, 36,864 saved old-Hangul/Jamo comparison directions
    matched. This is not a universal compatibility guarantee.

CHANGES IN 3.0.0

  - Reduced repeated variable, reference and index checks.
  - Corrected raw-string ASCII boundary whitespace handling while
    preserving fullwidth spaces (U+3000) and expanded whitespace.
  - Fresh NEXTCOM / PREVCOM values are 0; BEGIN TRAIN sets -1.
  - Successful SAVEDATA does not overwrite RESULT after evaluating
    its arguments.
  - System-menu input is echoed once; invalid input prompts a retry.

VARIANTS CHECKED DURING DEVELOPMENT

  These checks cover specific versions and routes, not all branches
  or full-game completion. The games listed here are NOT bundled:

  - Touhou Shokushukyu Ver1.18.2 (corrected): escape ending on day 17
    reached in Windows development build r16
  - eratohoJ+ v1.05.5: early progress, saves, loads, shopping,
    Stage 1 combat and retreat
  - Touhou Shokushukyu Ver1.02.1: resumed saved games
  - eratohoYM Mk-3 kai 8proto6: reached a GAMEOVER screen
  - eratohoM3S: shooting stage
  - eratohoW: a fixed route through menus and events

FILES IN THE RUNTIME PACKAGE

  PyEmuera.pyz            Python engine
  Start_PyEmuera.bat      Start a variant
  Check_PyEmuera.bat      Check whether a variant can load
  Diagnose_PyEmuera.bat   Start with diagnostic logging
  sample/                 Pamyura Walkbook sample (original, all-ages)
  ZORKERB/                Unofficial ERB port of Zork I, r29
  README_en.txt           This English README
  README_ja.txt           Japanese README
  HOW_TO_USE_ja.txt       Detailed Japanese usage guide
  KNOWN_ISSUES_ja.txt     Known limitations (Japanese)
  CHANGELOG_ja.txt        Changelog (Japanese)
  LICENSE.txt             PyEmuera MIT License
  THIRD_PARTY_NOTICES.txt Third-party notices
  licenses/               Third-party license files
  SHA256SUMS.txt          Checksums for the packaged files

PLAYING ZORKERB

  The included ZORKERB r29 is an unofficial ERB port of Zork I.
  The independent project aims to port I, II and III; r29 covers I.
  Input is in English. No Z-machine or Frotz is required.

      python PyEmuera.pyz ZORKERB

  On Windows you can also drag ZORKERB onto Start_PyEmuera.bat.
  https://github.com/Meistertech-JP/ZORKERB/releases/tag/r29

VARIANT FILES AND SAVES

  PyEmuera does not overwrite a variant's ERB/CSV/configuration files
  or original Emuera saves. By default PyEmuera saves to
  .pyemuera/saves, or .pyemuera/native-saves for Emuera-format saves.
  It can read existing Emuera saves such as save00.sav.
  See HOW_TO_USE_ja.txt section 7 (Japanese) for created files.

DEVELOPERS

  The separate source ZIP contains source code, unit tests, fixtures
  and build scripts. README_DEVELOPERS_ja.md is the developer guide
  (Japanese). For CLI options run: python PyEmuera.pyz --help

LICENSES AND ATTRIBUTION

  PyEmuera is licensed under MIT (LICENSE.txt). Some data and
  reference material have separate terms; see THIRD_PARTY_NOTICES.txt
  and licenses/. Five unchanged Emuera test fixtures in the source
  archive are subject to Emuera's license.

  ZORKERB is separately MIT-licensed; Zork I source-derived material
  is under Microsoft's MIT license. See ZORKERB/LICENSE,
  ZORKERB/THIRD_PARTY_NOTICES.md and ZORKERB/licenses/.
  No Emuera.exe is included.
