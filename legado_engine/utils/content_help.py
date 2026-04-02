"""
ContentHelp – Python port of ContentHelp.kt paragraph re-segmentation logic.

The Android original uses a dictionary-based Chinese NLP segmenter.  We
implement a practical approximation that handles the most common real-world
cases for web-scraped Chinese novels:

* Merges lines that were split mid-sentence (no trailing sentence-end mark).
* Splits walls-of-text at sentence-boundary punctuation.
* Normalises quotation marks.

Also provides Chinese script conversion (simplified ↔ traditional) via OpenCC
when the ``opencc`` package is available.
"""
from __future__ import annotations

import re
from typing import Optional

# Sentence-ending punctuation (Chinese + ASCII)
_SENT_END = frozenset('。！？!?～~')
# Right quotation marks
_QUOTE_RIGHT = frozenset('"』」')

# Patterns ported directly from the Kotlin source
_RE_QUOT_HTML   = re.compile(r'&quot;')
_RE_COLON_OPEN  = re.compile(r"[:：]['\"\u2018\u201c\u300c]+")
_RE_DBLQUOTE    = re.compile(r'[\u201c\u201d\u300c\u300d]+\s*[\u201c\u201d\u300c\u300d][\s\u201c\u201d\u300c\u300d]*')
_RE_DBLQUOTE2   = re.compile(r'[\u201c\u201d\u300c\u300d]+\s*[\u201c\u201d\u300c\u300d]+')
_RE_SPACE_IDEOG = re.compile(r'[\u3000\s]+')

# Sentence boundary for re-split
_RE_SPLIT_SENT  = re.compile(r'(?<=[。！？!?])')

# ── Chinese script conversion ────────────────────────────────────────────────
# Conversion modes (mirrors Legado's chineseConverterType PreferKey):
#   0 = no conversion, 1 = simplified → traditional, 2 = traditional → simplified
CHINESE_CONVERT_NONE = 0
CHINESE_CONVERT_S2T  = 1   # simplified → traditional
CHINESE_CONVERT_T2S  = 2   # traditional → simplified

_opencc_cache: dict[str, object] = {}


def _get_opencc(config: str) -> Optional[object]:
    """Return a cached OpenCC converter, or None if opencc is unavailable."""
    if config in _opencc_cache:
        return _opencc_cache[config]
    try:
        import opencc  # type: ignore[import]
        converter = opencc.OpenCC(config)
        _opencc_cache[config] = converter
        return converter
    except Exception:
        _opencc_cache[config] = None
        return None


def chinese_convert(text: str, mode: int) -> str:
    """
    Convert Chinese script between simplified and traditional.

    Args:
        text: Input text.
        mode: One of CHINESE_CONVERT_NONE (0), CHINESE_CONVERT_S2T (1),
              CHINESE_CONVERT_T2S (2).

    Returns:
        Converted text, or original text if conversion is unavailable.
    """
    if mode == CHINESE_CONVERT_NONE or not text:
        return text
    config = "s2t.json" if mode == CHINESE_CONVERT_S2T else "t2s.json"
    converter = _get_opencc(config)
    if converter is None:
        return text
    try:
        return converter.convert(text)  # type: ignore[union-attr]
    except Exception:
        return text


def re_segment(content: str, chapter_name: str = "") -> str:
    """
    Re-segment poorly formatted web-novel content.

    Mirrors ContentHelp.reSegment(): joins continuation lines, then
    re-splits at natural sentence/paragraph boundaries.

    Args:
        content: Raw chapter text (may be wall-of-text or mis-split).
        chapter_name: Chapter title used to skip title-only first line.

    Returns:
        Re-segmented text with one logical paragraph per line.
    """
    if not content:
        return content

    # --- normalise quotation entities & sequences ---
    text = _RE_QUOT_HTML.sub('\u201c', content)
    text = _RE_COLON_OPEN.sub('：\u201c', text)
    text = _RE_DBLQUOTE.sub('\u201c\n\u201d', text)

    paragraphs = re.split(r'\n(\s*)', text)

    buf: list[str] = []

    # Skip leading title line (matches Kotlin's "略过第一行文本")
    first_stripped = paragraphs[0].strip() if paragraphs else ''
    if chapter_name.strip() and first_stripped == chapter_name.strip():
        buf.append('  ')          # placeholder so buf is not empty
    elif paragraphs:
        buf.append(_RE_SPACE_IDEOG.sub('', paragraphs[0]))

    # Merge continuation lines: if the *last* char of buffer is NOT a
    # sentence-end mark, append without a newline.
    for i in range(1, len(paragraphs)):
        seg = _RE_SPACE_IDEOG.sub('', paragraphs[i])
        if not seg:
            continue
        last = _last_significant_char(buf)
        if last and (last in _SENT_END or (last in _QUOTE_RIGHT and _second_last(buf) in _SENT_END)):
            buf.append('\n')
        buf.append(seg)

    joined = ''.join(buf)

    # --- second pass: pre-split at obvious sentence ends ----------------
    joined = _RE_DBLQUOTE2.sub('\u201c\n\u201d', joined)

    lines = joined.split('\n')
    result_lines: list[str] = []
    for line in lines:
        result_lines.append(_find_new_lines(line))

    final = '\n'.join(result_lines)
    # Clean up leading whitespace / blank lines
    final = re.sub(r'^\s+', '', final)
    final = re.sub(r'\n(\s*)\n', '\n', final)
    return final


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _last_significant_char(buf: list[str]) -> str:
    """Return the last non-whitespace character in the buffer."""
    for chunk in reversed(buf):
        for ch in reversed(chunk):
            if not ch.isspace():
                return ch
    return ''


def _second_last(buf: list[str]) -> str:
    """Return the second-to-last non-whitespace character."""
    count = 0
    for chunk in reversed(buf):
        for ch in reversed(chunk):
            if not ch.isspace():
                count += 1
                if count == 2:
                    return ch
    return ''


def _find_new_lines(s: str) -> str:
    """
    Insert newlines within a paragraph at natural sentence boundaries,
    to avoid excessively long paragraphs (simplified version of
    ContentHelp.findNewLines / forceSplit).
    """
    if len(s) < 80:
        return s
    # Split after every sentence-ending punctuation followed by a quote
    result = re.sub(r'([。！？!?][""」』]?)(?=[^\n])', r'\1\n', s)
    return result
