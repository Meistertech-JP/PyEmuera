"""Japanese StrConv width policy, separate from normalization and cell layout.

Emuera calls Strings.StrConv(Narrow/Wide, Config.Language).  The portable
Japanese backend models the ANSI-932 boundary observed in run04, then applies
only width mappings.  It does not normalize compatibility ideographs, circled
numbers or units.  Other language policies and Windows best-fit edge cases
are not certified by the Japanese oracle.
"""

from dataclasses import dataclass
import unicodedata
import json
from importlib.resources import files
from .errors import Unsupported

BESTFIT = json.loads(
    files('pyemuera').joinpath('specs/cp932_bestfit.json').read_text(encoding='utf-8')
)['wc_to_mb']


@dataclass(frozen=True)
class LanguagePolicy:
    name: str
    lcid: int
    codepage: str

    @classmethod
    def from_config(cls, config):
        language = config.get('内部で使用する東アジア言語', 'JAPANESE').upper()
        if language != 'JAPANESE':
            raise Unsupported(
                'StrConv width policy for '
                + language
                + ' requires a separate Windows locale oracle'
            )
        return cls(language, 0x0411, 'cp932')


# Unicode <narrow> data is used as character mapping data, not as a request to
# apply NFKC to the string.  Restrict it to the Japanese half-width block.
HALF_TO_FULL = {}
for _value in range(0xFF61, 0xFFA0):
    _parts = unicodedata.decomposition(chr(_value)).split()
    if _parts and _parts[0] == '<narrow>':
        HALF_TO_FULL[chr(_value)] = ''.join(chr(int(p, 16)) for p in _parts[1:])
HALF_TO_FULL['ﾞ'] = '゛'
HALF_TO_FULL['ﾟ'] = '゜'
FULL_TO_HALF = {value: key for key, value in HALF_TO_FULL.items()}

# Canonically voiced katakana expand to two narrow characters.  Combining
# marks supplied by the caller are handled at the ANSI boundary, not folded
# into a preceding character by global normalization.
for _value in range(0x30A0, 0x3100):
    _parts = unicodedata.decomposition(chr(_value)).split()
    if len(_parts) == 2 and not _parts[0].startswith('<'):
        _base, _mark = (chr(int(p, 16)) for p in _parts)
        if _base in FULL_TO_HALF and _mark in ('\u3099', '\u309a'):
            FULL_TO_HALF[chr(_value)] = FULL_TO_HALF[_base] + (
                'ﾞ' if _mark == '\u3099' else 'ﾟ'
            )


def _ansi_input(text, policy):
    """Represent the observed Japanese ANSI boundary without normalizing text.

    Unencodable combining marks become '?' in run04.  This replacement belongs
    to the language function only: oracle/log/JSON handling never uses it.
    Supplementary/surrogate behavior has no reference oracle and is explicit.
    """
    if any(ord(ch) > 0xFFFF or 0xD800 <= ord(ch) <= 0xDFFF for ch in text):
        raise Unsupported('StrConv width with supplementary/surrogate characters')
    result = []
    for ch in text:
        try:
            result.append(ch.encode(policy.codepage).decode(policy.codepage))
        except UnicodeEncodeError:
            code = BESTFIT.get(f'{ord(ch):04X}')
            if code is None:
                result.append('?')
            else:
                value = int(code, 16)
                raw = value.to_bytes(2 if value > 255 else 1, 'big')
                result.append(raw.decode(policy.codepage))
    return ''.join(result)


def narrow(text, policy):
    out = []
    for ch in _ansi_input(text, policy):
        if '\uff01' <= ch <= '\uff5e':
            out.append(chr(ord(ch) - 0xFEE0))
        elif ch == '\u3000':
            out.append(' ')
        else:
            out.append(FULL_TO_HALF.get(ch, ch))
    return ''.join(out)


def wide(text, policy):
    out = []
    for ch in _ansi_input(text, policy):
        mapped = HALF_TO_FULL.get(ch, ch)
        if '!' <= mapped <= '~':
            mapped = chr(ord(mapped) + 0xFEE0)
        elif mapped == ' ':
            mapped = '\u3000'
        # LCMap full-width can compose kana plus spacing dakuten.  NFC is
        # applied only to this pair; unrelated characters are never normalized.
        if mapped in ('゛', '゜') and out and '\u3040' <= out[-1] <= '\u30ff':
            pair = unicodedata.normalize(
                'NFC', out[-1] + ('\u3099' if mapped == '゛' else '\u309a')
            )
            if len(pair) == 1:
                out[-1] = pair
                continue
        out.append(mapped)
    return ''.join(out)


def convert(text, full, config):
    # Creator.Method returns early before checking the locale for empty text.
    if not text:
        return ''
    policy = LanguagePolicy.from_config(config)
    return wide(text, policy) if full else narrow(text, policy)
