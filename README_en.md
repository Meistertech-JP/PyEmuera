# PyEmuera (Pamyura)

**PyEmuera 3.0.0 Beta 2 (`3.0.0b2`)** · [日本語](README.md)

PyEmuera is an independent Python implementation for running Emuera game variants (ERB, ERH, and CSV files) in a text-only terminal, generally without changing the game's files. Its compatibility reference is **Emuera1824+v24**; it is not an official Emuera distribution.

Images, audio, mouse input, and rendering by Emuera's original GUI are out of scope. As beta software, it does not guarantee compatibility with every game or feature.

## Download and run

Download **`PyEmuera-3.0.0b2-runtime.zip`** from [Releases](https://github.com/Meistertech-JP/PyEmuera/releases) and extract it. The separate **`PyEmuera-3.0.0b2-source.zip`** contains source code and tests. GitHub's automatically generated `Source code` archives are not the runtime distribution.

Install Python 3.10 or later separately. On Windows, drag a game variant folder onto `Start_PyEmuera.bat`. You can also use the terminal:

```console
python PyEmuera.pyz --help
python PyEmuera.pyz "path/to/variant"
python PyEmuera.pyz sample --inputs sample/replay.txt --no-wait
```

Use `python3` when appropriate. A variant folder normally contains `ERB` and `CSV` directories. The runtime ZIP includes `HOW_TO_USE_ja.txt` (Japanese usage guide); the [detailed reference](README_ja.md) is also in Japanese.

## Requirements and compatibility

| Area | Scope |
| --- | --- |
| Runtime | Python 3.10+, text-capable terminal |
| Development and full unit suite | Python 3.11+ |
| Windows | Tested on Windows 10; Windows 11 testing remains limited |
| Linux | Tested on x86_64 Linux; terminal behavior may depend on the environment |
| Other systems | macOS and Android/Termux have not been verified |

Running the engine requires only Python's standard library, not .NET or third-party Python packages.

For string collation, Windows uses its native NLS API; other systems use a bundled fixed Japanese (`ja-JP`) profile. The portable comparator matched all 36,864 saved .NET Framework old-Hangul/Jamo comparison directions for a Windows 10 NLS `0x60305` reference. This does not establish complete compatibility with all Unicode strings or Windows releases.

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
