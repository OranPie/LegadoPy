"""
AnalyzeByRegex – 1:1 port of AnalyzeByRegex.kt.

Chains multiple regex patterns: each successive pattern is applied to the
concatenation of all matches from the previous step.
"""
from __future__ import annotations
import re
from functools import lru_cache
from typing import List, Optional


@lru_cache(maxsize=512)
def _compile(pattern: str) -> re.Pattern:
    """Compile and cache regex patterns to avoid repeated re.compile() calls."""
    return re.compile(pattern, re.DOTALL)


class AnalyzeByRegex:
    """Mirrors AnalyzeByRegex.kt (static object in Kotlin)."""

    @staticmethod
    def get_element(res: str, regs: List[str], index: int = 0) -> Optional[List[str]]:
        """
        Mirrors getElement() – chains regex patterns; returns capture groups
        of the first match of the last pattern.
        """
        try:
            pattern = _compile(regs[index])
        except re.error:
            return None

        m = pattern.search(res)
        if m is None:
            return None

        if index + 1 == len(regs):
            # Last regex – return all groups including group(0)
            info = [m.group(0)]
            for g in range(1, len(m.groups()) + 1):
                info.append(m.group(g) or "")
            return info

        # Intermediate regex – collect all matches, then recurse
        all_matches = "".join(mo.group(0) for mo in pattern.finditer(res))
        return AnalyzeByRegex.get_element(all_matches, regs, index + 1)

    @staticmethod
    def get_elements(res: str, regs: List[str], index: int = 0) -> List[List[str]]:
        """
        Mirrors getElements() – returns list-of-lists (rows × columns).
        Each inner list contains [full_match, group1, group2, ...].
        """
        try:
            pattern = _compile(regs[index])
        except re.error:
            return []

        matches = list(pattern.finditer(res))
        if not matches:
            return []

        if index + 1 == len(regs):
            books = []
            for m in matches:
                info = [m.group(0)]
                for g in range(1, len(m.groups()) + 1):
                    info.append(m.group(g) or "")
                books.append(info)
            return books

        all_matches = "".join(m.group(0) for m in matches)
        return AnalyzeByRegex.get_elements(all_matches, regs, index + 1)
