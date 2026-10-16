# Third-party notices

PyEmuera is an independently written Python program. It is not Emuera, not an official Emuera build, and not endorsed by the authors of Emuera or of any game. PyEmuera itself is released under the MIT License (`LICENSE`). The material below keeps its own terms; PyEmuera's MIT License does not replace them. The references that were consulted are listed in `SOURCES.md`.

## 1. Emuera

Copyright (C) 2008- MinorShift, 妊）|дﾟ)の中の人

PyEmuera reproduces the behavior of Emuera1824+v24 (archive SHA-256 `fd0dd5b83ab3f929e69de0b9af739fa9bf785b6f510b30d11aaf44db35af182a`). Parts of PyEmuera, such as the save-file codecs, the SFMT-based random number generator, the command tables, diagnostics and sorting behavior, were written in Python by studying the Emuera source code. They are source-informed work, not a clean-room implementation.

The Emuera license text is reproduced unchanged in `licenses/Emuera1824.txt` (SHA-256 `ce1134568e4a9fd56d4831c37dceb82050009e90349394f3f05a03a668500a06`). The same text is the `src1824+v24/src1824/license.txt` of the Emuera1824+v24 archive. The README of that modified version applies Emuera's license to it and permits derived versions under that license. The license permits use, modification and redistribution, provided that the origin is not misrepresented, altered source is marked as such, and the notice is kept.

### Emuera source files used as test fixtures

The source distribution contains five unmodified files from the Emuera1824+v24 archive. Tests read them to check diagnostic texts and source lines against the original. They are not part of the Python engine or of `PyEmuera.pyz`, and they remain under the Emuera license above, not under PyEmuera's MIT License. A copy of the original license is kept beside them as `tests/fixtures/r44_native_diagnostics/sources/Emuera1824_LICENSE.txt`. `Resources.resx` contains text resources only.

| File | SHA-256 |
| --- | --- |
| `tests/fixtures/r44_native_diagnostics/sources/ArgumentBuilder.cs` | `3df8f94f041dcee9e703f3f170cc48ad82d1d3016ce96b7f87a06ec5bba3ace9` |
| `tests/fixtures/r44_native_diagnostics/sources/Creator.Method.cs` | `e4efac8f8a81734e9cc75f893008dd8d5120e44e3391c44c075a582c0661cf08` |
| `tests/fixtures/r44_native_diagnostics/sources/Resources.resx` | `f58aa58913e97e4f9a6324a623aacdea686c19b8bd5b1bc989afde1c553f55e0` |
| `tests/fixtures/r44_native_diagnostics/numeric_sources/Instraction.Child.cs` | `c5f2284eb16409e4b6319b14eb009ceaa6520367e9f5aa5cba533828a732fce4` |
| `tests/fixtures/r44_native_diagnostics/numeric_sources/Process.cs` | `ef8ecc12e0321091127f600e581932986a50d2bd94b22fc4acae82921507e362` |

No Emuera executable, no other Emuera source file, no game and no save data is included.

### SFMT

Emuera's `_Library/SFMT.cs` credits Copyright (C) Rei HOBARA 2007, the SFMT algorithm by Mutsuo Saito and Makoto Matsumoto, and modifications by MinorShift (2009-07-02). `pyemuera/random1824.py` was written by inspecting that file. No SFMT library source or binary is included.

## 2. Microsoft Reference Source (.NET Framework)

Copyright (c) Microsoft Corporation. Licensed under the MIT License; the notice and permission text are in `licenses/MICROSOFT_REFERENCE_SOURCE_MIT.txt`.

`pyemuera/sort1824.py` and `pyemuera/arraysort1824.py` are Python adaptations of the sorting control flow in `mscorlib/system/collections/generic/arraysorthelper.cs` and `list.cs` from https://github.com/microsoft/referencesource . They do not require or include .NET. This permission does not cover Emuera files or Windows binaries.

## 3. Microsoft Windows Sorting Weight Table

`pyemuera/resources/nls_ja_windows10.bin.zlib` contains the portions of Microsoft's published Windows 10 Sorting Weight Table that are needed for Japanese string comparison on platforms other than Windows. It is used under the copyright permission of the Microsoft Open Specifications documentation ([MS-UCODEREF]); that permission does not grant patent or trademark rights. Details are in `THIRD_PARTY_MS_NLS_NOTICE_ja.md` and `pyemuera/resources/MS_OPEN_SPECIFICATIONS_NOTICE.txt`. No Wine or ReactOS code or data is included.

## 4. Unicode / Microsoft CP932 best-fit table

`pyemuera/specs/cp932_bestfit.json` is derived from https://www.unicode.org/Public/MAPPINGS/VENDORS/MICSFT/WindowsBestFit/bestfit932.txt (Microsoft vendor data published by Unicode, Inc.) under the Unicode License V3 (`licenses/UNICODE_LICENSE_V3.txt`). Table SHA-256 `2614cfea35c3c86c41d33198793a84ca44edee3cf0ee0013a61a43fba4ece331`.

## 5. Test and measurement data

Test fixtures and verification data were created for PyEmuera: neutral ERB probes, their output logs from the original Emuera executable, and .NET Framework / Windows measurement results. They contain no game text. Measurement programs written for PyEmuera call public .NET Framework and Windows APIs; they are not Emuera source code.
