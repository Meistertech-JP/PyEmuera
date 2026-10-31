# Third-party notices

ZORKERB is a port of Zork I to eraBASIC (ERB/ERH/CSV). It is not an official release of, and is not endorsed by, Infocom, Microsoft, the authors of Emuera or the PyEmuera developers. Each component below keeps its own terms; one component's license does not replace another's.

## 1. ZORKERB

The ERB adaptation in `ERB/` and `CSV/` is Copyright (c) 2026 Meistertech-JP and is released under the MIT License (`LICENSE`).

## 2. Zork I

ZORK I: The Great Underground Empire — original game by Infocom.

ZORKERB is based on the historicalsource/zork1 source distribution at commit `97b7b3d68c075dd9af7da499c3e9690ada3471fd` (https://github.com/historicalsource/zork1). That distribution is provided under the MIT License, Copyright (c) 2025 Microsoft; the complete notice is in `licenses/ZORK1-MIT.txt`.

The game text printed by the ERB files is the original Zork I text from that source. The dictionary and syntax table in `ERB/38_ParserTables.ERB` were read from the compiled story `COMPILED/zork1.z3` of the same commit. Both remain under Microsoft's MIT License. The ZIL source and the story file themselves are not included.

## 3. PyEmuera

`PyEmuera-3.0.0b2.pyz` is PyEmuera 3.0.0b2 (https://github.com/Meistertech-JP/PyEmuera), SHA-256 `8473b250080ba678e05b4f484fcc6790f96614c2e9a7aaab077ab379e05f4bcb`, included unmodified.

- PyEmuera is released under the MIT License, Copyright (c) 2026 PyEmuera contributors.
- Parts of it were written by studying the Emuera source and remain subject to the Emuera license.
- It also contains Microsoft MIT-licensed reference source, Microsoft Open Specifications data and Unicode data under their own terms.

The license texts and notices are inside the `.pyz` file. Byte-for-byte copies are in `licenses/PyEmuera/`:

| File | Contents |
| --- | --- |
| `licenses/PyEmuera/LICENSE` | PyEmuera MIT License |
| `licenses/PyEmuera/THIRD_PARTY_NOTICES.md` | PyEmuera third-party notices |
| `licenses/PyEmuera/THIRD_PARTY_MS_NLS_NOTICE_ja.md` | Notice for the Microsoft sorting data |
| `licenses/PyEmuera/licenses/Emuera1824.txt` | Emuera license |
| `licenses/PyEmuera/licenses/MICROSOFT_REFERENCE_SOURCE_MIT.txt` | Microsoft Reference Source MIT License |
| `licenses/PyEmuera/licenses/UNICODE_LICENSE_V3.txt` | Unicode License V3 |

## 4. Names and trademarks

The MIT License of the Zork I source and of ZORKERB covers copyright only; it does not grant rights to use any trademark. Names such as "Zork" and "Infocom" may be trademarks of their respective owners. ZORKERB uses these names only to identify and describe the work. It contains no official logos, box art, packaging or marketing material.

## 5. Not included

No Emuera executable or source, Z-machine interpreter, original story file, ZIL source, save file or font is included.
