"""
AnalyzeByJSoup – 1:1 port of AnalyzeByJSoup.kt.

Uses BeautifulSoup + lxml as CSS-selector engine.  Implements the full Legado
selector syntax:
  - @CSS:  prefix  → direct bs4 .select() call, last segment after '@' is
           the attribute accessor
  - tag.div.0       → ElementsSingle (Legado tag/class/id/text selector + index)
  - rule@attr       → attribute accessor on the final element set
  - &&  ||  %%      → combine rules (union / first-match / interleave)
  - @               → chain selectors (each sub-rule applied to prior result)
  - lastRule tokens: text, textNodes, ownText, html, all, or any attribute name
"""
from __future__ import annotations
import re
from typing import Any, List, Optional, Tuple

from bs4 import BeautifulSoup, Tag, NavigableString

from .rule_analyzer import RuleAnalyzer


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_html(doc: Any) -> Tag:
    if isinstance(doc, Tag):
        return doc
    html_str = doc if isinstance(doc, str) else str(doc)
    return BeautifulSoup(html_str, "lxml")


# ---------------------------------------------------------------------------
# IndexSpec – mirrors ElementsSingle index parsing
# ---------------------------------------------------------------------------

class _IndexSpec:
    """Parses and applies Legado's index syntax (.N, !N, [N:M:S, ...])."""

    def __init__(self) -> None:
        self.split: str = " "       # '.' = select, '!' = exclude, ' ' = all
        self.before_rule: str = ""
        self.index_default: List[int] = []
        self.indexes: List[Any] = []  # int or (start, end, step) triple

    def parse(self, rule: str) -> None:
        """Parse a single rule string, extracting prefix and index spec."""
        rus = rule.strip()
        length = len(rus)

        if length == 0:
            self.split = " "
            self.before_rule = ""
            return

        # ----------------------------------------------------------------
        # New-style [index] syntax
        # ----------------------------------------------------------------
        if rus[-1] == "]":
            length -= 1  # skip trailing ']'
            pos = length - 1
            l_buf = ""
            cur_minus = False
            cur_list: List[Optional[int]] = []

            while pos >= 0:
                rl = rus[pos]
                if rl == " ":
                    pos -= 1
                    continue
                if rl.isdigit():
                    l_buf = rl + l_buf
                    pos -= 1
                    continue
                if rl == "-":
                    cur_minus = True
                    pos -= 1
                    continue

                cur_int = None if not l_buf else ((-1 if cur_minus else 1) * int(l_buf))

                if rl == ":":
                    cur_list.append(cur_int)
                    l_buf = ""
                    cur_minus = False
                    pos -= 1
                    continue

                # Separator found
                if not cur_list:
                    if cur_int is None:
                        break
                    self.indexes.insert(0, cur_int)
                else:
                    step = cur_list[0] if len(cur_list) == 2 else 1
                    self.indexes.insert(0, (cur_int, cur_list[-1], step))
                    cur_list.clear()

                l_buf = ""
                cur_minus = False

                if rl == "!":
                    self.split = "!"
                    pos -= 1
                    while pos >= 0 and rus[pos] == " ":
                        pos -= 1

                if pos >= 0 and rus[pos] == "[":
                    self.before_rule = rus[:pos]
                    return

                if rl != ",":
                    break
                pos -= 1

        # ----------------------------------------------------------------
        # Old-style .N or !N  suffix
        # ----------------------------------------------------------------
        pos = len(rus) - 1
        l_buf = ""
        cur_minus = False

        while pos >= 0:
            rl = rus[pos]
            if rl == " ":
                pos -= 1
                continue
            if rl.isdigit():
                l_buf = rl + l_buf
                pos -= 1
                continue
            if rl == "-":
                cur_minus = True
                pos -= 1
                continue

            if rl in ("!", ".", ":"):
                self.index_default.insert(0, (-1 if cur_minus else 1) * int(l_buf))
                if rl != ":":
                    self.split = rl
                    self.before_rule = rus[:pos]
                    return
            else:
                break

            l_buf = ""
            cur_minus = False
            pos -= 1

        # No index found
        self.split = " "
        self.before_rule = rus

    def apply(self, elements: List[Tag]) -> List[Tag]:
        """Filter elements by the parsed index spec."""
        length = len(elements)
        if length == 0:
            return elements

        # Collect absolute indices
        idx_set: List[int] = []

        if not self.indexes:
            for ix in self.index_default:
                real = ix if ix >= 0 else ix + length
                if 0 <= real < length and real not in idx_set:
                    idx_set.append(real)
        else:
            for ix in self.indexes:
                if isinstance(ix, tuple):
                    start_r, end_r, step = ix
                    start = (start_r or 0)
                    if start < 0:
                        start += length
                    end = (end_r if end_r is not None else length - 1)
                    if end < 0:
                        end += length
                    start = max(0, min(start, length - 1))
                    end = max(0, min(end, length - 1))
                    step = max(1, step) if step > 0 else max(1, step + length)
                    if end >= start:
                        rng = range(start, end + 1, step)
                    else:
                        rng = range(start, end - 1, -step)
                    for i in rng:
                        if 0 <= i < length and i not in idx_set:
                            idx_set.append(i)
                else:
                    real = ix if ix >= 0 else ix + length
                    if 0 <= real < length and real not in idx_set:
                        idx_set.append(real)

        if not idx_set and not self.index_default and not self.indexes:
            return elements

        if self.split == "!":
            excl = set(idx_set)
            return [e for i, e in enumerate(elements) if i not in excl]
        elif self.split == ".":
            return [elements[i] for i in idx_set]
        else:
            return elements


def _get_elements_single(root: Tag, rule: str) -> List[Tag]:
    """
    Mirrors ElementsSingle.getElementsSingle().
    Dispatches on 'children', 'class.X', 'tag.X', 'id.X', 'text.X', or CSS.
    """
    spec = _IndexSpec()
    spec.parse(rule)

    br = spec.before_rule
    if not br:
        children = list(root.children)
        elements = [c for c in children if isinstance(c, Tag)]
    else:
        parts = br.split(".", 1)
        first = parts[0]
        if first == "children":
            elements = [c for c in root.children if isinstance(c, Tag)]
        elif first == "class" and len(parts) > 1:
            elements = root.find_all(class_=parts[1])
        elif first == "tag" and len(parts) > 1:
            elements = root.find_all(parts[1])
        elif first == "id" and len(parts) > 1:
            elements = root.find_all(id=parts[1])
        elif first == "text" and len(parts) > 1:
            elements = root.find_all(string=re.compile(re.escape(parts[1])))
            # find_all with string returns NavigableString – get parents
            elements = [e.parent for e in elements if e.parent]
        else:
            try:
                elements = root.select(br)
            except Exception:
                elements = []

    return spec.apply(elements)


# ---------------------------------------------------------------------------
# SourceRule – thin wrapper mirroring AnalyzeByJSoup.SourceRule
# ---------------------------------------------------------------------------

class _SourceRule:
    def __init__(self, rule_str: str) -> None:
        self.is_css = False
        if rule_str.upper().startswith("@CSS:"):
            self.is_css = True
            self.elements_rule = rule_str[5:].strip()
        else:
            self.elements_rule = rule_str


# ---------------------------------------------------------------------------
# Result extractors (getResultLast)
# ---------------------------------------------------------------------------

def _get_result_last(elements: List[Tag], last_rule: str) -> List[str]:
    """
    Mirrors getResultLast() – extracts a string from each element using
    the attribute/keyword in last_rule.
    """
    texts: List[str] = []
    lr = last_rule.strip()

    for el in elements:
        if not isinstance(el, Tag):
            continue
        if lr == "text":
            t = el.get_text(" ", strip=True)
            if t:
                texts.append(t)
        elif lr == "textNodes":
            tn = [s.strip() for s in el.strings if isinstance(s, NavigableString) and s.strip()]
            if tn:
                texts.append("\n".join(tn))
        elif lr == "ownText":
            # Only direct text children
            t = "".join(s for s in el.children
                        if isinstance(s, NavigableString)).strip()
            if t:
                texts.append(t)
        elif lr == "html":
            for script in el.find_all("script"):
                script.decompose()
            for style in el.find_all("style"):
                style.decompose()
            h = str(el)
            if h:
                texts.append(h)
        elif lr == "all":
            texts.append(str(el))
        else:
            # attribute
            val = el.get(lr, "")
            if isinstance(val, list):
                val = " ".join(val)
            if val and val not in texts:
                texts.append(val)
    return texts


# ---------------------------------------------------------------------------
# AnalyzeByJSoup
# ---------------------------------------------------------------------------

class AnalyzeByJSoup:
    """Mirrors AnalyzeByJSoup.kt – CSS/HTML-based content analysis."""

    def __init__(self, doc: Any) -> None:
        if isinstance(doc, AnalyzeByJSoup):
            self._root = doc._root
        else:
            self._root = _parse_html(doc)

    # ------------------------------------------------------------------
    # getElements
    # ------------------------------------------------------------------

    def get_elements(self, rule: str) -> List[Tag]:
        """Mirrors getElements(rule) – entry point."""
        return self._get_elements(self._root, rule)

    def _get_elements(self, root: Tag, rule: str) -> List[Tag]:
        if not root or not rule:
            return []

        elements: List[Tag] = []
        source_rule = _SourceRule(rule)
        ra = RuleAnalyzer(source_rule.elements_rule)
        rule_strs = ra.splitRule("&&", "||", "%%")

        elements_list: List[List[Tag]] = []

        if source_rule.is_css:
            for rs in rule_strs:
                try:
                    tmp = root.select(rs)
                except Exception:
                    tmp = []
                elements_list.append(tmp)
                if tmp and ra.elements_type == "||":
                    break
        else:
            for rs in rule_strs:
                rs_ra = RuleAnalyzer(rs)
                rs_ra.trim()
                sub_rules = rs_ra.splitRule("@")

                if len(sub_rules) > 1:
                    el: List[Tag] = [root] if isinstance(root, Tag) else list(root)
                    for sub_rl in sub_rules:
                        es: List[Tag] = []
                        for et in el:
                            es.extend(_get_elements_single(et, sub_rl))
                        el = es
                    tmp = el
                else:
                    tmp = _get_elements_single(root, rs)

                elements_list.append(tmp)
                if tmp and ra.elements_type == "||":
                    break

        if elements_list:
            if ra.elements_type == "%%":
                for i in range(len(elements_list[0])):
                    for grp in elements_list:
                        if i < len(grp):
                            elements.append(grp[i])
            else:
                for grp in elements_list:
                    elements.extend(grp)

        return elements

    # ------------------------------------------------------------------
    # getString / getString0
    # ------------------------------------------------------------------

    def get_string(self, rule_str: str) -> Optional[str]:
        """Mirrors getString() – joins all results with newline."""
        lst = self.get_string_list(rule_str)
        if not lst:
            return None
        if len(lst) == 1:
            return lst[0]
        return "\n".join(lst)

    def get_string0(self, rule_str: str) -> str:
        """Mirrors getString0() – returns first result or empty string."""
        lst = self.get_string_list(rule_str)
        return lst[0] if lst else ""

    # ------------------------------------------------------------------
    # getStringList
    # ------------------------------------------------------------------

    def get_string_list(self, rule_str: str) -> List[str]:
        """Mirrors getStringList()."""
        texts: List[str] = []
        if not rule_str:
            return texts

        source_rule = _SourceRule(rule_str)

        if not source_rule.elements_rule:
            texts.append(self._root.get_text() if self._root else "")
            return texts

        ra = RuleAnalyzer(source_rule.elements_rule)
        rule_strs = ra.splitRule("&&", "||", "%%")

        results: List[List[str]] = []

        for rs in rule_strs:
            if source_rule.is_css:
                last_at = rs.rfind("@")
                if last_at == -1:
                    continue
                selector = rs[:last_at]
                attr = rs[last_at + 1:]
                try:
                    els = self._root.select(selector)
                except Exception:
                    els = []
                tmp = _get_result_last(els, attr)
            else:
                tmp = self._get_result_list(rs) or []

            if tmp:
                results.append(tmp)
                if ra.elements_type == "||":
                    break

        if results:
            if ra.elements_type == "%%":
                for i in range(len(results[0])):
                    for grp in results:
                        if i < len(grp):
                            texts.append(grp[i])
            else:
                for grp in results:
                    texts.extend(grp)

        return texts

    def _get_result_list(self, rule_str: str) -> Optional[List[str]]:
        """Mirrors getResultList() – traverse @-chained rules."""
        if not rule_str:
            return None

        elements: List[Tag] = [self._root]

        ra = RuleAnalyzer(rule_str)
        ra.trim()
        rules = ra.splitRule("@")

        last_idx = len(rules) - 1
        for i in range(last_idx):
            es: List[Tag] = []
            for el in elements:
                es.extend(_get_elements_single(el, rules[i]))
            elements = es

        if not elements:
            return None

        return _get_result_last(elements, rules[last_idx]) or None
