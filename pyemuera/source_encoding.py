"""EraStreamReader's StreamReader(stream, Config.Encode) byte contract.

Config.Encode is SHIFT-JIS (932), independent of the console code page.
StreamReader detects and consumes one Unicode BOM before decoding. Its DBCS
decoder consumes a lead and the following byte as one unit even when invalid;
932's default best-fit replacement is U+30FB, not Python's U+FFFD.
Explicit encodings remain a strict, opt-in host extension in text.read_text.
The .NET Framework StreamReader never flushes its Decoder at EOF: a pending
incomplete unit is discarded, but malformed complete units still fall back.
"""

from __future__ import annotations
import codecs


def _cp932_fallback(error):
    if not isinstance(error, UnicodeDecodeError):
        raise error
    first = error.object[error.start]
    lead = 0x81 <= first <= 0x9F or 0xE0 <= first <= 0xFC
    end = min(len(error.object), error.start + (2 if lead else 1))
    return '\u30fb', end


codecs.register_error('pyemuera_dotnet_cp932', _cp932_fallback)

# Long BOMs must precede UTF-16 LE, whose preamble is their prefix.
_BOMS = (
    (codecs.BOM_UTF32_LE, 'utf-32-le'),
    (codecs.BOM_UTF32_BE, 'utf-32-be'),
    (codecs.BOM_UTF8, 'utf-8-sig'),
    (codecs.BOM_UTF16_LE, 'utf-16-le'),
    (codecs.BOM_UTF16_BE, 'utf-16-be'),
)


def decode_source(data: bytes) -> tuple[str, str]:
    for preamble, encoding in _BOMS:
        if data.startswith(preamble):
            codec = 'utf-8' if encoding == 'utf-8-sig' else encoding
            decoder = codecs.getincrementaldecoder(codec)(errors='replace')
            return decoder.decode(data[len(preamble) :], final=False), encoding
    decoder = codecs.getincrementaldecoder('cp932')(errors='pyemuera_dotnet_cp932')
    return decoder.decode(data, final=False), 'cp932'
