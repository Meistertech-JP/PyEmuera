# PyEmuera (Pamyura)

**PyEmuera 3.0.0 (`3.0.0`)** · [日本語](README.md)

PyEmuera is an independent Python implementation for running Emuera game variants (ERB, ERH, and CSV files) in a text-only terminal, generally without changing the game's files. Its compatibility reference is **Emuera1824+v24**; it is not an official Emuera distribution.

Images, audio, mouse input, and rendering by Emuera's original GUI are out of scope.

Across three fixed game-variant routes, **median execution time was reduced by 26.7–35.0% compared with Beta 3, with improved input response times**. This compares the complete releases, including corrections toward original Emuera behavior. Results depend on the variant and route. See the [measurement conditions](README_ja.md#性能の確認範囲).

## Download and run

Download **`PyEmuera-3.0.0-runtime.zip`** from [Releases](https://github.com/Meistertech-JP/PyEmuera/releases) and extract it. The separate **`PyEmuera-3.0.0-source.zip`** contains source code and tests. GitHub's automatically generated `Source code` archives are not the runtime distribution.

Install Python 3.10 or later separately. On Windows, drag a game variant folder onto `Start_PyEmuera.bat`. You can also use the terminal:

```console
python PyEmuera.pyz "path/to/variant"
```

Examples using the bundled games:

```console
python PyEmuera.pyz ZORKERB
python PyEmuera.pyz sample --inputs sample/replay.txt --no-wait
```

The runtime ZIP includes Pamyura Walkbook (`sample/`) and [ZORKERB r29](https://github.com/Meistertech-JP/ZORKERB/releases/tag/r29) (`ZORKERB/`). ZORKERB is an unofficial ERB port of Zork I, descended from the text adventure Zork created on mainframes in the 1970s. The independent [ZORKERB project](https://github.com/Meistertech-JP/ZORKERB) aims to port Zork I, II, and III; r29 covers I. Input is in English; neither a Z-machine nor Frotz is needed. On Windows, drag the `ZORKERB` folder onto `Start_PyEmuera.bat`. For rights and license terms, see `ZORKERB/LICENSE`, `ZORKERB/THIRD_PARTY_NOTICES.md`, and `ZORKERB/licenses/`.

Use `python3` when appropriate. A variant folder normally contains `ERB` and `CSV` directories. The runtime ZIP includes `HOW_TO_USE_ja.txt` (Japanese usage guide); the [detailed reference](README_ja.md) is also in Japanese.

## Changes in 3.0.0

- Reduced repeated variable, reference and index checks. Runtime effects depend on the game and route.
- Raw string assignment follows the original boundary-literal handling for ASCII whitespace, preserving fullwidth spaces (U+3000) and whitespace in substituted values.
- Fresh `NEXTCOM` and `PREVCOM` values are 0; `BEGIN TRAIN` still sets them to -1.
- On successful `SAVEDATA`, `RESULT` is not overwritten after argument evaluation.
- System menus echo the original input once and request another entry for invalid input.

## Requirements and compatibility

| Area | Scope |
| --- | --- |
| Runtime | Python 3.10+, text-capable terminal |
| Development and full unit suite | Python 3.11+ |
| Windows | Historical checks, including earlier releases, used Windows 10; Windows 11 coverage remains limited |
| Linux | Historical checks, including earlier releases, used x86_64 Linux; terminal behavior depends on the environment |
| Other systems | macOS and Android/Termux have not been verified |

These historical environment examples do not establish a current 3.0.0 pass on every platform.

Running the engine requires only Python's standard library, not .NET or third-party Python packages.

For string collation, Windows uses its native NLS API; other systems use a bundled fixed Japanese (`ja-JP`) profile. The portable comparator matched all 36,864 saved .NET Framework old-Hangul/Jamo comparison directions for a Windows 10 NLS `0x60305` reference. This does not establish complete compatibility with all Unicode strings or Windows releases.

Japanese IME input and input/interruption in Windows Terminal (ConPTY) have been checked in representative Windows configurations, without covering every IME or setting. Time acquisition has tests for fixed clocks, date/second boundaries and write order; exhaustive comparisons of unsynchronized live clocks remain limited. A known timing-sensitive interruption test remains documented in the developer guide.

See [Compatibility](COMPATIBILITY_ja.md) for limitations, including the graphical interface and save-file interoperability.

## Source, licenses, and support

From an extracted source distribution:

```console
python run_pyemuera.py --help
python run_pyemuera.py examples/smoke --inputs examples/smoke/replay.txt --no-wait
```

The [developer guide](README_DEVELOPERS_ja.md) (Japanese) covers testing, rebuilding, and packaging. See [Architecture](ARCHITECTURE_ja.md), [Direct Jamo comparison](docs/portable-jamo-state-machine.md), and [Sources](SOURCES.md) for technical information.

PyEmuera is licensed under the [MIT License](LICENSE). Third-party components retain their respective terms; see [Third-party notices](THIRD_PARTY_NOTICES.md) and [NLS data notice](THIRD_PARTY_MS_NLS_NOTICE_ja.md).

Report reproducible issues at [GitHub Issues](https://github.com/Meistertech-JP/PyEmuera/issues), including the version, OS, Python, game variant, steps, and observed results. Remove private details and game content from diagnostic records before sharing.
