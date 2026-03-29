"""
AnalyzeByJSonPath – 1:1 port of AnalyzeByJSonPath.kt.

Uses jsonpath-ng as the JSONPath engine.
"""
from __future__ import annotations
import json
from typing import Any, List, Optional

from jsonpath_ng import parse as _jparse
from jsonpath_ng.exceptions import JsonPathParserError

from .rule_analyzer import RuleAnalyzer


def _jp_read(ctx: Any, rule: str) -> Any:
    """Execute a JSONPath expression on an already-parsed object."""
    try:
        expr = _jparse(rule)
        matches = expr.find(ctx)
        if not matches:
            return None
        if len(matches) == 1:
            return matches[0].value
        return [m.value for m in matches]
    except (JsonPathParserError, Exception):
        return None


def _parse_ctx(json_input: Any) -> Any:
    """Convert string/dict/list to a Python object suitable for jsonpath-ng."""
    if isinstance(json_input, str):
        try:
            return json.loads(json_input)
        except Exception:
            return {}
    return json_input


class AnalyzeByJSonPath:
    """Mirrors AnalyzeByJSonPath.kt – JSONPath-based content analysis."""

    def __init__(self, json_input: Any) -> None:
        if isinstance(json_input, AnalyzeByJSonPath):
            self._ctx = json_input._ctx
        else:
            self._ctx = _parse_ctx(json_input)

    # ------------------------------------------------------------------
    # getString
    # ------------------------------------------------------------------

    def get_string(self, rule: str) -> Optional[str]:
        """Mirrors getString() – returns a single string."""
        if not rule:
            return None

        ra = RuleAnalyzer(rule, code=True)
        rules = ra.splitRule("&&", "||")

        if len(rules) == 1:
            # Handle inline {$.xxx} sub-rules
            ra.reset_pos()
            resolved = ra.inner_rule("{$.", fr=lambda r: self.get_string(r))
            if resolved:
                return resolved
            # Normal JSONPath
            val = _jp_read(self._ctx, rule)
            if val is None:
                return None
            if isinstance(val, list):
                return "\n".join(str(v) for v in val)
            return str(val)
        else:
            parts = []
            for rl in rules:
                tmp = self.get_string(rl)
                if tmp:
                    parts.append(tmp)
                    if ra.elements_type == "||":
                        break
            return "\n".join(parts) if parts else None

    # ------------------------------------------------------------------
    # getStringList
    # ------------------------------------------------------------------

    def get_string_list(self, rule: str) -> List[str]:
        """Mirrors getStringList()."""
        result: List[str] = []
        if not rule:
            return result

        ra = RuleAnalyzer(rule, code=True)
        rules = ra.splitRule("&&", "||", "%%")

        if len(rules) == 1:
            ra.reset_pos()
            st = ra.inner_rule("{$.", fr=lambda r: self.get_string(r))
            if st:
                result.append(st)
                return result
            val = _jp_read(self._ctx, rule)
            if val is None:
                return result
            if isinstance(val, list):
                result.extend(str(v) for v in val)
            else:
                result.append(str(val))
            return result
        else:
            results: List[List[str]] = []
            for rl in rules:
                tmp = self.get_string_list(rl)
                if tmp:
                    results.append(tmp)
                    if ra.elements_type == "||":
                        break
            if results:
                if ra.elements_type == "%%":
                    # interleave
                    for i in range(len(results[0])):
                        for grp in results:
                            if i < len(grp):
                                result.append(grp[i])
                else:
                    for grp in results:
                        result.extend(grp)
        return result

    # ------------------------------------------------------------------
    # getObject / getList
    # ------------------------------------------------------------------

    def get_object(self, rule: str) -> Any:
        """Mirrors getObject() – raw JSONPath result."""
        return _jp_read(self._ctx, rule)

    def get_list(self, rule: str) -> Optional[List[Any]]:
        """Mirrors getList() – returns list or None."""
        result: List[Any] = []
        if not rule:
            return result

        ra = RuleAnalyzer(rule, code=True)
        rules = ra.splitRule("&&", "||", "%%")

        if len(rules) == 1:
            val = _jp_read(self._ctx, rules[0])
            if val is None:
                return result
            if isinstance(val, list):
                return val
            return [val]
        else:
            results = []
            for rl in rules:
                tmp = self.get_list(rl)
                if tmp:
                    results.append(tmp)
                    if ra.elements_type == "||":
                        break
            if results:
                if ra.elements_type == "%%":
                    for i in range(len(results[0])):
                        for grp in results:
                            if i < len(grp):
                                result.append(grp[i])
                else:
                    for grp in results:
                        result.extend(grp)
        return result
