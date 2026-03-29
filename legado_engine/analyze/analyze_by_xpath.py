"""
AnalyzeByXPath – 1:1 port of AnalyzeByXPath.kt.

Uses lxml as the XPath engine (mirrors JXDocument/JXNode from seimi-crawler).
"""
from __future__ import annotations
from typing import Any, List, Optional, Union

from lxml import etree
from lxml.etree import _Element  # type: ignore[attr-defined]

from .rule_analyzer import RuleAnalyzer


def _to_element(doc: Any) -> Optional[_Element]:
    """
    Convert string / lxml element to a single lxml _Element root.
    Mirrors AnalyzeByXPath.parse() / strToJXDocument().
    """
    if isinstance(doc, _Element):
        return doc

    html_str = doc if isinstance(doc, str) else str(doc)
    html_str = html_str.strip()

    # Handle XML fragments that Legado wraps automatically
    if html_str.endswith("</td>"):
        html_str = f"<tr>{html_str}</tr>"
    if html_str.endswith("</tr>") or html_str.endswith("</tbody>"):
        html_str = f"<table>{html_str}</table>"

    if html_str.startswith("<?xml"):
        try:
            return etree.fromstring(html_str.encode())
        except Exception:
            pass

    try:
        return etree.fromstring(
            html_str.encode(),
            parser=etree.HTMLParser(recover=True, encoding="utf-8"),
        )
    except Exception:
        return None


def _run_xpath(root: _Element, xpath: str) -> List[Any]:
    """Execute XPath; return list of results (elements or strings)."""
    try:
        result = root.xpath(xpath)
        if isinstance(result, list):
            return result
        return [result]
    except Exception:
        return []


def _node_to_str(node: Any) -> str:
    """Convert an lxml node or smart-string to a plain Python string."""
    if isinstance(node, _Element):
        parts = []
        if node.text:
            parts.append(node.text)
        for child in node:
            parts.append(_node_to_str(child))
            if child.tail:
                parts.append(child.tail)
        return "".join(parts).strip()
    return str(node).strip()


class AnalyzeByXPath:
    """Mirrors AnalyzeByXPath.kt."""

    def __init__(self, doc: Any) -> None:
        if isinstance(doc, AnalyzeByXPath):
            self._root = doc._root
        else:
            self._root = _to_element(doc)

    # ------------------------------------------------------------------
    # getElements
    # ------------------------------------------------------------------

    def get_elements(self, xpath: str) -> List[Any]:
        """Mirrors getElements() – returns list of lxml nodes."""
        if not xpath or self._root is None:
            return []

        ra = RuleAnalyzer(xpath)
        rules = ra.splitRule("&&", "||", "%%")

        if len(rules) == 1:
            return _run_xpath(self._root, xpath)

        results: List[List[Any]] = []
        for rl in rules:
            tmp = self.get_elements(rl)
            if tmp:
                results.append(tmp)
                if ra.elements_type == "||":
                    break

        nodes: List[Any] = []
        if results:
            if ra.elements_type == "%%":
                for i in range(len(results[0])):
                    for grp in results:
                        if i < len(grp):
                            nodes.append(grp[i])
            else:
                for grp in results:
                    nodes.extend(grp)
        return nodes

    # ------------------------------------------------------------------
    # getStringList
    # ------------------------------------------------------------------

    def get_string_list(self, xpath: str) -> List[str]:
        """Mirrors getStringList()."""
        result: List[str] = []
        if not xpath or self._root is None:
            return result

        ra = RuleAnalyzer(xpath)
        rules = ra.splitRule("&&", "||", "%%")

        if len(rules) == 1:
            for node in _run_xpath(self._root, xpath):
                result.append(_node_to_str(node))
            return result

        results: List[List[str]] = []
        for rl in rules:
            tmp = self.get_string_list(rl)
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

    # ------------------------------------------------------------------
    # getString
    # ------------------------------------------------------------------

    def get_string(self, rule: str) -> Optional[str]:
        """Mirrors getString() – joins results with newline."""
        if not rule or self._root is None:
            return None

        ra = RuleAnalyzer(rule)
        rules = ra.splitRule("&&", "||")

        if len(rules) == 1:
            nodes = _run_xpath(self._root, rule)
            if not nodes:
                return None
            return "\n".join(_node_to_str(n) for n in nodes)

        parts = []
        for rl in rules:
            tmp = self.get_string(rl)
            if tmp:
                parts.append(tmp)
                if ra.elements_type == "||":
                    break
        return "\n".join(parts) if parts else None
