# PyEmuera (ぱみゅーら / Pamyura)

**PyEmuera 3.0.0 Beta 2 candidate B2-RC1 (`3.0.0b2.dev1`)**

[日本語](README.md)

PyEmuera is an independent Python implementation that aims for high compatibility with Emuera variants: games written in ERB and CSV. It loads variant files without rewriting them and runs them in a text-only terminal. Images, audio, mouse interaction, and the original GUI's font rendering are outside its scope.

Think of it as an eramaker that can run Emuera-specific variants.

The reference target is **Emuera1824+v24**. ERH files are also supported. PyEmuera is an independent implementation, not an official Emuera build. This is a beta; complete compatibility with every feature or variant is not guaranteed.

## Download and run

B2-RC1 is a Beta 2 candidate. Use the runtime ZIP to play games; source code is provided separately in a source ZIP. Extract the entire runtime ZIP before use. GitHub's automatically generated `Source code (zip)` / `Source code (tar.gz)` archives are source snapshots for developers.

Install Python 3.10 or later separately, then run these commands from the extracted distribution directory:

```console
python PyEmuera.pyz --version
python PyEmuera.pyz "path/to/variant"
```

The variant directory must contain `ERB` and `CSV`. On Windows, you can also drag that directory onto `Start_PyEmuera.bat`. On Linux, use the commands above. Use `python3` instead of `python` if that is how your Python installation is named.

Run the distribution's sample with:

```console
python PyEmuera.pyz sample --inputs sample/replay.txt --no-wait
```

See `HOW_TO_USE_ja.txt` in the ZIP, or its [repository copy](packaging/public/HOW_TO_USE_ja.txt), for the detailed Japanese user guide.

## Requirements and platform coverage

| Purpose | Requirement |
| --- | --- |
| Running games from a pyz, source, or installed package | Python 3.10 or later and a terminal capable of text display and input |
| Development, the full unit suite, and verification work | Python 3.11 or later |

The engine and unit tests use only the Python standard library. No additional runtime libraries, .NET installation, or runtime downloads are needed. Building a wheel or sdist separately requires `build` and setuptools 77 or later.

However, having Python and a terminal does not guarantee operation in every environment or with every variant. Platform-specific input handling and terminal control may have limitations; unverified environments remain unverified.

Measurements have been made on Windows 10 and Linux. The r51 development history includes game execution on Windows 10 with Python 3.12 and 3.14, and Linux with Python 3.10–3.14. This history does not represent a full B2-RC1 rerun on every environment. Python 3.15 and later have not been verified.

### Other platforms

Windows 11 is a target platform, but extensive testing on actual Windows 11 systems has not yet been completed.
Because PyEmuera uses only the Python standard library, it may also run on macOS and Android environments such as Termux, provided Python 3.10 or later and a suitable terminal are available.
However, macOS and Android have not yet been tested. Successful startup, input/output handling, and compatibility on these platforms are not guaranteed.
Feedback and test reports from these environments are welcome.

Termux is an example of a runtime environment on Android. This does not mean that PyEmuera is distributed as a native Android app.

## Run from source

The repository contains the source code. Run these commands from the root of your clone:

```console
python run_pyemuera.py --version
python run_pyemuera.py "path/to/variant"
python run_pyemuera.py examples/smoke --inputs examples/smoke/replay.txt --no-wait
python run_pyemuera.py examples/smoke --check
```

`--check` performs static loading, registration, and declaration checks. Passing it does not prove that a game can be played to completion. Running the sample may create `examples/smoke/.pyemuera/`.

For tests, pyz builds, and Python package builds, see the [GitHub development supplement (Japanese)](DEVELOPING_ON_GITHUB_ja.md) and [developer guide (Japanese)](README_DEVELOPERS_ja.md). If you change the source, build the pyz being tested from that same source.

## Scope and known limitations

- PyEmuera handles logical text output and terminal display. The original GUI's images, backgrounds, audio, mouse interaction, font rendering, and pixel positioning are outside its scope. You can still configure your terminal's own font. Features exclusive to extensions such as EE or EM are also outside the target.
- Windows uses the OS's native NLS collation APIs. Other platforms use the bundled portable `ja-JP` implementation. For 36,864 Jamo comparison pairs on the fixed Windows 10, ja-JP, NLS 0x60305 reference, the portable implementation matched the saved .NET Framework measurements in 36,864/36,864 cases. This does not guarantee complete compatibility outside that set or on other Windows/NLS environments.
- Japanese IME input and input/interruption in Windows Terminal (ConPTY) have been checked on Windows, without covering every IME product, version, and configuration.
- Saves are written under the variant's `.pyemuera/` directory, without overwriting the original Emuera saves. Reading and writing native-format saves does not guarantee complete interoperability for every variable or variant.
- Time functions have fixed-clock and boundary tests. Exact comparison against synchronized live clocks in both engines at every boundary remains incomplete. Interruption tests have a documented intermittent failure.
- Unsupported commands or features stop with a load-time or runtime error.

See [Compatibility](COMPATIBILITY_ja.md), [Known Limitations](packaging/public/KNOWN_ISSUES_ja.txt), and the [development supplement](DEVELOPING_ON_GITHUB_ja.md) for details in Japanese.

## Variant verification history

These are **bounded observations from different development revisions**. They are not a rerun of every route on B2-RC1 and do not guarantee every branch or complete operation of each variant.

| Variant | Observed scope |
| --- | --- |
| 東方触手宮 Ver1.18.2修正版 | Development revision r16 on an actual Windows machine: new game through the day-17 escape ending and return to the title screen |
| 東方触手宮 Ver1.02.1 | Progressed from an existing day-6 save to day 9; loaded an existing day-224 save (not a continuous playthrough from day 1 to day 224) |
| eratohoJ+ v1.05.5 | New game through day 2, saving/loading, purchases, Stage 1 encounters, and retreat |
| eratohoYM Mk-3改8proto6 | Reached the GAMEOVER screen on day 4; this is not a normal game clear |
| eratohoM3S | Executed a shooting stage |
| eratohoW | Executed a fixed route covering normal game screens, menus, and events |

See [Compatibility](COMPATIBILITY_ja.md) for the evidence categories and scope. These variants, their saves, and their play logs are not bundled. The included sample is an independent demo.

## License and sources

PyEmuera itself uses the [MIT License](LICENSE). Third-party material retains its own terms; PyEmuera's MIT License does not replace them.

- [Third-Party Notices](THIRD_PARTY_NOTICES.md) cover five Emuera source files used as test fixtures, SFMT-related work, Microsoft Reference Source, and Unicode-related data.
- [Microsoft NLS data sources and terms (Japanese)](THIRD_PARTY_MS_NLS_NOTICE_ja.md) and [license texts](licenses/).
- [Sources](SOURCES.md), [Architecture (Japanese)](ARCHITECTURE_ja.md), and the [existing package README (Japanese)](README_ja.md).


### MIT permission for the SFMT reference material

For the HOBARA-origin material referenced by `pyemuera/random1824.py`, PyEmuera selects the MIT option offered on [Rei HOBARA's official distribution page](https://www.rei.to/random.html). Copyright (C) Rei HOBARA 2007. The permission, conditions, and disclaimer in the [official MIT notice](https://www.rei.to/MITL.txt) correspond to the identical text reproduced in the accompanying [LICENSE](LICENSE). This relies on HOBARA's own permission and does not replace any third-party terms with PyEmuera's license.

This clarification applies to these exact Beta 1 release artifacts, not to B2-RC1 hashes. The copyright notice and permission text are already included in the ZIP's `THIRD_PARTY_NOTICES.txt` and `LICENSE.txt`, their counterparts under `source/`, and the standalone pyz's `THIRD_PARTY_NOTICES.md` and `LICENSE`.

| Release artifact | SHA-256 |
| --- | --- |
| `PyEmuera-3.0.0b1.zip` | `df2f302490b638a6f7e74313bc40f98d36dfe7e0515e202f26deae7d5bc319a3` |
| `PyEmuera-3.0.0b1.pyz` | `305fcf27c723b9ca155ac087928f993eb32b141288fee689b0a621c0f337f1a7` |

## Report a bug

Use [GitHub Issues](https://github.com/Meistertech-JP/PyEmuera/issues). Include the PyEmuera version, OS, terminal and Python versions, variant name and version, reproduction steps, expected and actual behavior, and error messages. A minimal reproduction without game text is helpful.

Section 10 of the [user guide (Japanese)](packaging/public/HOW_TO_USE_ja.txt) explains diagnostic records and checks before sharing them. Do not post private logs, credentials, personal information, absolute paths containing usernames, entered names, or game text verbatim. Do not attach variant files or private saves without permission. If a record cannot be shared, describe the situation in words instead.
