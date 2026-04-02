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


# ── toNumChapter: mirrors StringUtils.chineseNumToInt + JsExtensions.toNumChapter ──

# Mapping from Chinese numeral chars to integer values (same as Kotlin ChnMap)
_CHN_MAP: dict[str, int] = {
    '〇': 0, '零': 0, '一': 1, '二': 2, '三': 3, '四': 4, '五': 5,
    '六': 6, '七': 7, '八': 8, '九': 9,
    '壹': 1, '贰': 2, '叁': 3, '肆': 4, '伍': 5,
    '陆': 6, '柒': 7, '捌': 8, '玖': 9,
    '十': 10, '拾': 10, '百': 100, '佰': 100,
    '千': 1000, '仟': 1000, '万': 10000, '亿': 100000000,
}

# Pattern: 第<num_part>章  (same as AppPattern.titleNumPattern)
_TITLE_NUM_PATTERN = re.compile(r'^(第)(.+?)(章.*)$')


def _full_to_half(s: str) -> str:
    """Convert fullwidth ASCII to halfwidth (mirrors StringUtils.fullToHalf)."""
    result = []
    for ch in s:
        code = ord(ch)
        if code == 12288:
            result.append(' ')
        elif 65281 <= code <= 65374:
            result.append(chr(code - 65248))
        else:
            result.append(ch)
    return ''.join(result)


def _chinese_num_to_int(ch_num: str) -> int:
    """
    Convert Chinese numeral string to integer.
    Mirrors StringUtils.chineseNumToInt().
    Returns -1 on failure.
    """
    ch_num = ch_num.strip()
    if not ch_num:
        return -1

    # Fast path: pure digit string
    try:
        return int(ch_num)
    except ValueError:
        pass

    # "一零二五" style — every char is a digit character
    digit_only = set('〇零一二三四五六七八九壹贰叁肆伍陆柒捌玖')
    if len(ch_num) > 1 and all(c in digit_only for c in ch_num):
        try:
            return int(''.join(str(_CHN_MAP[c]) for c in ch_num))
        except (KeyError, ValueError):
            pass

    # "一千零二十五" style
    result = 0
    tmp = 0
    billion = 0
    try:
        for i, ch in enumerate(ch_num):
            tmp_num = _CHN_MAP.get(ch)
            if tmp_num is None:
                return -1
            if tmp_num == 100000000:
                result += tmp
                result *= tmp_num
                billion = billion * 100000000 + result
                result = 0
                tmp = 0
            elif tmp_num == 10000:
                result += tmp
                result *= tmp_num
                tmp = 0
            elif tmp_num >= 10:
                if tmp == 0:
                    tmp = 1
                result += tmp_num * tmp
                tmp = 0
            else:
                prev_map = _CHN_MAP.get(ch_num[i - 1], 0) if i >= 1 else 0
                if i >= 2 and i == len(ch_num) - 1 and prev_map > 10:
                    tmp = tmp_num * prev_map // 10
                else:
                    tmp = tmp * 10 + tmp_num
        return result + tmp + billion
    except Exception:
        return -1


def _string_to_int(s: str) -> int:
    """
    Convert a string (possibly Chinese numerals or fullwidth digits) to int.
    Mirrors StringUtils.stringToInt().
    """
    s = _full_to_half(s).replace(' ', '').replace('\t', '')
    try:
        return int(s)
    except ValueError:
        return _chinese_num_to_int(s)


def to_num_chapter(s: str) -> str:
    """
    Convert a chapter title with Chinese numerals to Arabic numeral form.
    E.g. "第一千零二十五章 标题" → "第1025章 标题"
    Mirrors JsExtensions.toNumChapter().
    """
    if not s:
        return s
    m = _TITLE_NUM_PATTERN.match(s)
    if m:
        prefix, num_part, suffix = m.group(1), m.group(2), m.group(3)
        int_val = _string_to_int(num_part)
        if int_val >= 0:
            return f"{prefix}{int_val}{suffix}"
    return s
