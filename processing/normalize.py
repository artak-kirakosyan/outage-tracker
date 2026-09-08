"""
Text normalization shared by every parser.

Real fetched content (both ENA and Veolia) contains source quirks that
silently break naive regex/tokenizing if left alone: non-breaking spaces
(U+00A0) throughout Veolia's Telegram posts, and a mix of hyphen/en-dash/
em-dash characters used interchangeably as the range delimiter. This
module normalizes those away without touching wording or case, so parsers
downstream can assume plain ASCII '-' and single ASCII spaces.
"""
import re
import unicodedata

# En dash, em dash, horizontal bar, figure dash — all seen or plausible
# as range delimiters; ordinary hyphen-minus is left as-is.
_DASH_VARIANTS_RE = re.compile("[\u2010\u2011\u2012\u2013\u2014\u2015]")
_WHITESPACE_RUN_RE = re.compile(r"[ \t\u00a0]+")


def normalize_text(text: str) -> str:
    """
    Collapse non-breaking spaces and dash variants, and squash runs of
    whitespace into single ASCII spaces. Leaves line breaks, wording,
    and case untouched — callers that need to split on lines should do
    so before calling this, or normalize per-line.
    """
    text = unicodedata.normalize("NFC", text)
    text = _DASH_VARIANTS_RE.sub("-", text)
    text = _WHITESPACE_RUN_RE.sub(" ", text)
    return text.strip()


def normalize_multiline(text: str) -> str:
    """Same as normalize_text, but preserves newlines (normalizes within
    each line only). Used for block-structured content like ENA's
    planned-outage prose, where line breaks carry heading structure."""
    lines = text.replace("\r\n", "\n").split("\n")
    return "\n".join(normalize_text(line) for line in lines)
