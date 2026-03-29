"""
RuleAnalyzer – 1:1 port of RuleAnalyzer.kt.

Handles:
- splitRule("&&", "||", "%%")  – rule-aware split avoiding brackets/quotes
- innerRule("{$.", ...)         – inline rule substitution
"""
from __future__ import annotations
from typing import Callable, List, Optional


class RuleAnalyzer:
    """
    Mirrors RuleAnalyzer.kt.  Parses rule strings without standard regex so
    that bracket-balanced sub-expressions (XPath/JSONPath selectors, JS code)
    containing the split tokens are not mis-split.
    """

    ESC = "\\"

    def __init__(self, data: str, code: bool = False) -> None:
        self.queue: str = data
        self.pos: int = 0
        self.start: int = 0
        self.startX: int = 0
        self.rule: List[str] = []
        self.step: int = 0
        self.elements_type: str = ""
        # choose balanced-group strategy: code (JS/JSON) vs rule (XPath/CSS)
        self._chomp_balanced = self._chomp_code_balanced if code else self._chomp_rule_balanced

    @property
    def elementsType(self) -> str:  # noqa: N802  (Kotlin name compat)
        return self.elements_type

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def trim(self) -> None:
        """Strip leading '@' or whitespace (control chars ≤ '!') from current pos."""
        q = self.queue
        if self.pos < len(q) and (q[self.pos] == "@" or q[self.pos] < "!"):
            self.pos += 1
            while self.pos < len(q) and (q[self.pos] == "@" or q[self.pos] < "!"):
                self.pos += 1
            self.start = self.pos
            self.startX = self.pos

    def reset_pos(self) -> None:
        self.pos = 0
        self.startX = 0

    # ------------------------------------------------------------------
    # Internal finders
    # ------------------------------------------------------------------

    def _consume_to(self, seq: str) -> bool:
        self.start = self.pos
        idx = self.queue.find(seq, self.pos)
        if idx != -1:
            self.pos = idx
            return True
        return False

    def _consume_to_any(self, *seqs: str) -> bool:
        pos = self.pos
        q = self.queue
        qlen = len(q)
        while pos < qlen:
            for s in seqs:
                if q[pos: pos + len(s)] == s:
                    self.step = len(s)
                    self.pos = pos
                    return True
            pos += 1
        return False

    def _find_to_any(self, *chars: str) -> int:
        pos = self.pos
        q = self.queue
        qlen = len(q)
        while pos < qlen:
            if q[pos] in chars:
                return pos
            pos += 1
        return -1

    # ------------------------------------------------------------------
    # Balanced-group consumers
    # ------------------------------------------------------------------

    def _chomp_code_balanced(self, open_c: str, close_c: str) -> bool:
        """
        Pull a balanced group where the open/close chars are '['/']' at outer
        level, with JS-style string escaping (\\).  Used for JSON/JS content.
        """
        pos = self.pos
        q = self.queue
        depth = 0
        other_depth = 0
        in_single = False
        in_double = False

        while pos < len(q):
            c = q[pos]
            pos += 1
            if c != self.ESC:
                if c == "'" and not in_double:
                    in_single = not in_single
                elif c == '"' and not in_single:
                    in_double = not in_double

                if in_single or in_double:
                    continue

                if c == "[":
                    depth += 1
                elif c == "]":
                    depth -= 1
                elif depth == 0:
                    if c == open_c:
                        other_depth += 1
                    elif c == close_c:
                        other_depth -= 1
            else:
                pos += 1  # skip escaped char

            if depth == 0 and other_depth == 0:
                break

        if depth > 0 or other_depth > 0:
            return False
        self.pos = pos
        return True

    def _chomp_rule_balanced(self, open_c: str, close_c: str) -> bool:
        """
        Pull a balanced group for XPath/CSS rules (no JS escaping inside
        brackets, but '' and "" strings are respected).
        """
        pos = self.pos
        q = self.queue
        depth = 0
        in_single = False
        in_double = False

        while pos < len(q):
            c = q[pos]
            pos += 1
            if c == "'" and not in_double:
                in_single = not in_single
            elif c == '"' and not in_single:
                in_double = not in_double

            if in_single or in_double:
                continue
            elif c == "\\":
                pos += 1
                continue

            if c == open_c:
                depth += 1
            elif c == close_c:
                depth -= 1

            if depth == 0:
                break

        if depth > 0:
            return False
        self.pos = pos
        return True

    # ------------------------------------------------------------------
    # splitRule – main public API
    # ------------------------------------------------------------------

    def split_rule(self, *split: str) -> List[str]:
        """
        Split the queue by any of the given separator strings while respecting
        balanced brackets/parentheses.  Returns list of rule segments and sets
        self.elements_type to the separator found.

        Mirrors the Kotlin tailrec splitRule(vararg split: String).
        """
        if len(split) == 1:
            self.elements_type = split[0]
            if not self._consume_to(self.elements_type):
                self.rule.append(self.queue[self.startX:])
                return self.rule
            self.step = len(self.elements_type)
            return self._split_rule_continue()
        else:
            if not self._consume_to_any(*split):
                self.rule.append(self.queue[self.startX:])
                return self.rule

        end = self.pos
        self.pos = self.start

        while True:
            st = self._find_to_any("[", "(")

            if st == -1:
                # No brackets at all – simple split
                self.rule = [self.queue[self.startX: end]]
                self.elements_type = self.queue[end: end + self.step]
                self.pos = end + self.step

                while self._consume_to(self.elements_type):
                    self.rule.append(self.queue[self.start: self.pos])
                    self.pos += self.step

                self.rule.append(self.queue[self.pos:])
                return self.rule

            if st > end:
                # separator precedes first bracket
                self.rule = [self.queue[self.startX: end]]
                self.elements_type = self.queue[end: end + self.step]
                self.pos = end + self.step

                while self._consume_to(self.elements_type) and self.pos < st:
                    self.rule.append(self.queue[self.start: self.pos])
                    self.pos += self.step

                if self.pos > st:
                    self.startX = self.start
                    return self._split_rule_continue()
                else:
                    self.rule.append(self.queue[self.pos:])
                    return self.rule

            # bracket precedes separator – jump over the balanced group
            self.pos = st
            close_c = "]" if self.queue[self.pos] == "[" else ")"
            if not self._chomp_balanced(self.queue[self.pos], close_c):
                raise ValueError(f"Unbalanced brackets after: {self.queue[:self.start]!r}")

            if end <= self.pos:
                # recalculate end position
                self.start = self.pos
                return self.split_rule(*split)

        # unreachable

    # alias matching Kotlin camelCase usage
    def splitRule(self, *split: str) -> List[str]:  # noqa: N802
        return self.split_rule(*split)

    def _split_rule_continue(self) -> List[str]:
        """Second-phase split once elements_type is known (Kotlin @JvmName("splitRuleNext"))."""
        end = self.pos
        self.pos = self.start

        while True:
            st = self._find_to_any("[", "(")

            if st == -1:
                self.rule.append(self.queue[self.startX: end])
                self.pos = end + self.step
                while self._consume_to(self.elements_type):
                    self.rule.append(self.queue[self.start: self.pos])
                    self.pos += self.step
                self.rule.append(self.queue[self.pos:])
                return self.rule

            if st > end:
                self.rule.append(self.queue[self.startX: end])
                self.pos = end + self.step
                while self._consume_to(self.elements_type) and self.pos < st:
                    self.rule.append(self.queue[self.start: self.pos])
                    self.pos += self.step
                if self.pos > st:
                    self.startX = self.start
                    return self._split_rule_continue()
                else:
                    self.rule.append(self.queue[self.pos:])
                    return self.rule

            self.pos = st
            close_c = "]" if self.queue[self.pos] == "[" else ")"
            if not self._chomp_balanced(self.queue[self.pos], close_c):
                raise ValueError(f"Unbalanced brackets after: {self.queue[:self.start]!r}")

            if end <= self.pos:
                self.start = self.pos
                if not self._consume_to(self.elements_type):
                    self.rule.append(self.queue[self.startX:])
                    return self.rule
                return self._split_rule_continue()

    # ------------------------------------------------------------------
    # innerRule – inline rule / template substitution
    # ------------------------------------------------------------------

    def inner_rule(
        self,
        inner: str,
        start_step: int = 1,
        end_step: int = 1,
        fr: Optional[Callable[[str], Optional[str]]] = None,
    ) -> str:
        """
        Mirrors innerRule(inner, startStep, endStep, fr) in Kotlin.
        Finds all occurrences of {inner...} balanced groups and calls fr() on
        the content between the delimiters.  Returns assembled string.
        """
        if fr is None:
            return ""
        st = []
        while self._consume_to(inner):
            pos_pre = self.pos
            if self._chomp_code_balanced("{", "}"):
                frv = fr(self.queue[pos_pre + start_step: self.pos - end_step])
                if frv:
                    st.append(self.queue[self.startX: pos_pre])
                    st.append(frv)
                    self.startX = self.pos
                    continue
            self.pos += len(inner)

        if self.startX == 0:
            return ""
        st.append(self.queue[self.startX:])
        return "".join(st)

    def inner_rule_str(
        self,
        start_str: str,
        end_str: str,
        fr: Callable[[str], Optional[str]],
    ) -> str:
        """
        Mirrors innerRule(startStr, endStr, fr) – replaces all startStr…endStr
        regions using fr().
        """
        st = []
        while self._consume_to(start_str):
            self.pos += len(start_str)
            pos_pre = self.pos
            if self._consume_to(end_str):
                frv = fr(self.queue[pos_pre: self.pos])
                st.append(self.queue[self.startX: pos_pre - len(start_str)])
                st.append(frv or "")
                self.pos += len(end_str)
                self.startX = self.pos

        if self.startX == 0:
            return self.queue
        st.append(self.queue[self.startX:])
        return "".join(st)

    # Kotlin camelCase aliases
    def innerRule(self, inner: str, start_step: int = 1, end_step: int = 1,  # noqa: N802
                  fr: Optional[Callable[[str], Optional[str]]] = None) -> str:
        return self.inner_rule(inner, start_step, end_step, fr)
