from __future__ import annotations
"""
AnalyzeRule – 1:1 port of AnalyzeRule.kt.
"""

import re
import html as _html_module
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models.book_source import BaseSource
    from ..models.book import Book, BookChapter, RuleData

from .rule_analyzer import RuleAnalyzer
from .analyze_by_jsonpath import AnalyzeByJSonPath
from .analyze_by_jsoup import AnalyzeByJSoup
from .analyze_by_xpath import AnalyzeByXPath
from .analyze_by_regex import AnalyzeByRegex
from ..engine import resolve_engine
from ..js import eval_js, JsExtensions
from ..utils.network_utils import get_absolute_url, is_json, is_data_url
from .source_rule import JS_PATTERN, Mode, SourceRule

class _AnalyzeRuleP2:
    """
    Central parsing engine – 1:1 port of AnalyzeRule.kt.

    Usage::

        rule = AnalyzeRule(book, source)
        rule.set_content(html_body, base_url)
        title = rule.get_string("h1.title@text")
        chapters = rule.get_elements("ul.chapter-list > li")
    """

    def __init__(
        self,
        rule_data: "RuleData | None" = None,
        source: "BaseSource | None" = None,
        pre_update_js: bool = False,
        engine=None,
    ) -> None:
        self._engine = resolve_engine(engine)
        self._rule_data = rule_data
        self._source = source
        self._pre_update_js = pre_update_js

        self._content: Any = None
        self._base_url: str | None = None
        self._redirect_url: str | None = None
        self._is_json: bool = False
        self._is_regex: bool = False
        self._chapter: "BookChapter | None" = None
        self._next_chapter_url: str | None = None

        # lazy sub-parsers
        self._by_xpath: AnalyzeByXPath | None = None
        self._by_jsoup: AnalyzeByJSoup | None = None
        self._by_json: AnalyzeByJSonPath | None = None

        # caches
        self._rule_cache: dict[tuple[str, bool], list[SourceRule]] = {}
        self._regex_cache: dict[str, re.Pattern | None] = {}

        # JS bindings
        self._java = JsExtensions(
            base_url=self._base_url or "",
            put_fn=lambda k, v: self.put(k, v),
            get_fn=lambda k: self.get(k),
            engine=self._engine,
        )

    # ------------------------------------------------------------------
    # Setters (mirror Kotlin extension functions)
    # ------------------------------------------------------------------

    def set_content(self, content: Any, base_url: str | None = None) -> "AnalyzeRule":
        if content is None:
            raise ValueError("Content cannot be null")
        self._content = content
        from bs4 import Tag
        if isinstance(content, Tag):
            self._is_json = False
        else:
            self._is_json = is_json(str(content))
        if base_url:
            self.set_base_url(base_url)
        # Invalidate sub-parsers
        self._by_xpath = None
        self._by_jsoup = None
        self._by_json = None
        return self

    def set_base_url(self, base_url: str | None) -> "AnalyzeRule":
        if base_url:
            self._base_url = base_url
            self._java._base_url = base_url
        return self

    def set_redirect_url(self, url: str) -> str | None:
        if is_data_url(url):
            return self._redirect_url
        self._redirect_url = url
        return url

    def set_chapter(self, chapter: "BookChapter | None") -> "AnalyzeRule":
        self._chapter = chapter
        return self

    def set_next_chapter_url(self, url: str | None) -> "AnalyzeRule":
        self._next_chapter_url = url
        return self

    def set_rule_data(self, rule_data: "RuleData | None") -> "AnalyzeRule":
        self._rule_data = rule_data
        return self

    # ------------------------------------------------------------------
    # Sub-parser accessors (lazy, cached against content object)
    # ------------------------------------------------------------------

    def _get_by_xpath(self, obj: Any) -> AnalyzeByXPath:
        if obj is not self._content:
            return AnalyzeByXPath(obj)
        if self._by_xpath is None:
            self._by_xpath = AnalyzeByXPath(self._content)
        return self._by_xpath

    def _get_by_jsoup(self, obj: Any) -> AnalyzeByJSoup:
        if obj is not self._content:
            return AnalyzeByJSoup(obj)
        if self._by_jsoup is None:
            self._by_jsoup = AnalyzeByJSoup(self._content)
        return self._by_jsoup

    def _get_by_json(self, obj: Any) -> AnalyzeByJSonPath:
        if obj is not self._content:
            return AnalyzeByJSonPath(obj)
        if self._by_json is None:
            self._by_json = AnalyzeByJSonPath(self._content)
        return self._by_json

    # ------------------------------------------------------------------
    # splitSourceRule – parse rule string into SourceRule list
    # ------------------------------------------------------------------

    def split_source_rule(
        self,
        rule_str: str | None,
        all_in_one: bool = False,
    ) -> list[SourceRule]:
        """
        Mirrors splitSourceRule().
        Splits a rule string (possibly containing JS blocks) into ordered list
        of SourceRule objects.
        """
        if not rule_str:
            return []

        rule_list: list[SourceRule] = []
        mode = Mode.Default
        start = 0

        # :prefix → AllInOne Regex mode
        if all_in_one and rule_str.startswith(":"):
            mode = Mode.Regex
            self._is_regex = True
            start = 1
        elif self._is_regex:
            mode = Mode.Regex

        for m in JS_PATTERN.finditer(rule_str):
            if m.start() > start:
                tmp = rule_str[start: m.start()].strip()
                if tmp:
                    rule_list.append(SourceRule(tmp, mode,
                                                is_json_ctx=self._is_json,
                                                is_regex_ctx=self._is_regex))
            js_code = m.group(2) or m.group(1)
            rule_list.append(SourceRule(js_code, Mode.Js))
            start = m.end()

        if len(rule_str) > start:
            tmp = rule_str[start:].strip()
            if tmp:
                rule_list.append(SourceRule(tmp, mode,
                                            is_json_ctx=self._is_json,
                                            is_regex_ctx=self._is_regex))
        return rule_list

    def _split_source_rule_cached(
        self,
        rule_str: str | None,
        all_in_one: bool = False,
    ) -> list[SourceRule]:
        if not rule_str:
            return []
        cache_key = (rule_str, bool(all_in_one))
        if cache_key not in self._rule_cache:
            self._rule_cache[cache_key] = self.split_source_rule(rule_str, all_in_one=all_in_one)
        return self._rule_cache[cache_key]

    # Kotlin-style camelCase aliases
    def splitSourceRule(self, rule_str: str | None,  # noqa: N802
                        all_in_one: bool = False) -> list[SourceRule]:
        return self.split_source_rule(rule_str, all_in_one)



import re
from typing import Any, List, Optional, TYPE_CHECKING

from ..utils.network_utils import get_absolute_url

if TYPE_CHECKING:
    from ..models.book import Book, BookChapter


class AnalyzeRule(_AnalyzeRuleP2):

    # ------------------------------------------------------------------
    # put / get variables
    # ------------------------------------------------------------------

    def put(self, key: str, value: str) -> str:
        if self._chapter is not None:
            self._chapter.put_variable(key, value)
        elif self._rule_data is not None:
            self._rule_data.put_variable(key, value)
        elif self._source is not None:
            self._source.put(key, value)
        return value

    def get(self, key: str) -> str:
        from ..models.book import Book, BookChapter
        if key == "bookName":
            book = self._rule_data
            if isinstance(book, Book):
                return book.name
        if key == "title":
            if self._chapter is not None:
                return self._chapter.title
        val = (
            (self._chapter.get_variable(key) if self._chapter else None)
            or (self._rule_data.get_variable(key) if self._rule_data else None)
            or (self._source.get(key) if self._source else None)
            or ""
        )
        return val or ""

    # ------------------------------------------------------------------
    # evalJS
    # ------------------------------------------------------------------

    def eval_js(self, js_str: str, result: Any = None) -> Any:
        """Mirrors AnalyzeRule.evalJS()."""
        from ..models.book import Book, BookChapter
        from .analyze_url import JsCookie
        bindings = {
            "java":           self._java,
            "cookie":         JsCookie(self._engine.cookie_store),
            "cache":          self._engine.cache,
            "source":         self._source,
            "book":           self._rule_data if isinstance(self._rule_data, Book) else None,
            "result":         result,
            "baseUrl":        self._base_url or "",
            "chapter":        self._chapter,
            "title":          self._chapter.title if self._chapter else None,
            "src":            self._content,
            "nextChapterUrl": self._next_chapter_url,
            "engine":         self._engine,
        }
        return eval_js(js_str, result=result, bindings=bindings, java_obj=self._java)

    def evalJS(self, js_str: str, result: Any = None) -> Any:  # noqa: N802
        return self.eval_js(js_str, result)

    # ------------------------------------------------------------------
    # Helper: apply one SourceRule step to current result
    # ------------------------------------------------------------------

    def _apply_rule(
        self,
        source_rule: SourceRule,
        result: Any,
        is_url: bool = False,
    ) -> Any:
        """Dispatch a single SourceRule onto result."""
        self._put_rule(source_rule.put_map)
        source_rule.make_up_rule(
            result,
            get_fn=self.get,
            eval_js_fn=self.eval_js,
            get_string_fn=lambda r: self.get_string(r),
        )
        rule = source_rule.rule
        if not rule and not source_rule.replace_regex:
            return result

        if source_rule.mode == Mode.Js:
            return self.eval_js(rule, result)
        elif source_rule.mode == Mode.Json:
            by_json = self._get_by_json(result)
            return by_json.get_string(rule)
        elif source_rule.mode == Mode.XPath:
            by_xpath = self._get_by_xpath(result)
            return by_xpath.get_string(rule)
        elif source_rule.mode == Mode.Default:
            if is_url:
                return self._get_by_jsoup(result).get_string0(rule)
            return self._get_by_jsoup(result).get_string(rule)
        else:
            return rule   # Mode.Regex: raw rule (result already via make_up_rule)

    def _apply_rule_list(
        self,
        source_rule: SourceRule,
        result: Any,
        is_url: bool = False,
    ) -> Any:
        """Like _apply_rule but returns list."""
        self._put_rule(source_rule.put_map)
        source_rule.make_up_rule(
            result,
            get_fn=self.get,
            eval_js_fn=self.eval_js,
            get_string_fn=lambda r: self.get_string(r),
        )
        rule = source_rule.rule
        if not rule and not source_rule.replace_regex:
            return result

        if source_rule.mode == Mode.Js:
            return self.eval_js(rule, result)
        elif source_rule.mode == Mode.Json:
            return self._get_by_json(result).get_string_list(rule)
        elif source_rule.mode == Mode.XPath:
            return self._get_by_xpath(result).get_string_list(rule)
        elif source_rule.mode == Mode.Default:
            return self._get_by_jsoup(result).get_string_list(rule)
        else:
            return rule

    def _apply_rule_elements(self, source_rule: SourceRule, result: Any) -> Any:
        """Like _apply_rule but returns elements (for getElements)."""
        self._put_rule(source_rule.put_map)
        source_rule.make_up_rule(
            result,
            get_fn=self.get,
            eval_js_fn=self.eval_js,
            get_string_fn=lambda r: self.get_string(r),
        )
        rule = source_rule.rule
        if not rule:
            return result

        if source_rule.mode == Mode.Regex:
            return AnalyzeByRegex.get_elements(
                str(result), rule.split("&&"))
        elif source_rule.mode == Mode.Js:
            return self.eval_js(rule, result)
        elif source_rule.mode == Mode.Json:
            return self._get_by_json(result).get_list(rule)
        elif source_rule.mode == Mode.XPath:
            return self._get_by_xpath(result).get_elements(rule)
        else:
            return self._get_by_jsoup(result).get_elements(rule)

    # ------------------------------------------------------------------
    # getString
    # ------------------------------------------------------------------

    def get_string(
        self,
        rule_str: str | None,
        m_content: Any = None,
        is_url: bool = False,
        unescape: bool = True,
    ) -> str:
        """Mirrors getString(). Returns single string."""
        if not rule_str:
            return ""
        rule_list = self._split_source_rule_cached(rule_str)
        return self._get_string(rule_list, m_content, is_url, unescape)

    def _get_string(
        self,
        rule_list: list[SourceRule],
        m_content: Any = None,
        is_url: bool = False,
        unescape: bool = True,
    ) -> str:
        result: Any = m_content or self._content
        if result is None or not rule_list:
            return ""
        for sr in rule_list:
            if result is None:
                break
            result = self._apply_rule(sr, result, is_url=is_url)
            if result is not None and sr.replace_regex:
                result = self._replace_regex(str(result), sr)
        if result is None:
            result = ""
        result_str = str(result)
        if unescape and "&" in result_str:
            import html as _html
            result_str = _html.unescape(result_str)
        if is_url:
            if not result_str.strip():
                return self._base_url or ""
            return get_absolute_url(self._redirect_url or self._base_url, result_str)
        return result_str

    def getString(self, rule_str: str | None, m_content: Any = None,  # noqa: N802
                  is_url: bool = False, unescape: bool = True) -> str:
        return self.get_string(rule_str, m_content, is_url, unescape)

    # ------------------------------------------------------------------
    # getStringList
    # ------------------------------------------------------------------

    def get_string_list(
        self,
        rule_str: str | None,
        m_content: Any = None,
        is_url: bool = False,
    ) -> Optional[list[str]]:
        """Mirrors getStringList()."""
        if not rule_str:
            return None
        rule_list = self._split_source_rule_cached(rule_str)
        return self._get_string_list(rule_list, m_content, is_url)

    def _get_string_list(
        self,
        rule_list: list[SourceRule],
        m_content: Any = None,
        is_url: bool = False,
    ) -> Optional[list[str]]:
        result: Any = m_content or self._content
        if result is None or not rule_list:
            return None
        for sr in rule_list:
            if result is None:
                break
            result = self._apply_rule_list(sr, result, is_url=is_url)
            if sr.replace_regex:
                if isinstance(result, list):
                    result = [self._replace_regex(str(x), sr) for x in result]
                elif result is not None:
                    result = self._replace_regex(str(result), sr)
        if result is None:
            return None
        if isinstance(result, str):
            result = result.split("\n")
        if is_url:
            url_list: list[str] = []
            for item in (result or []):
                abs_url = get_absolute_url(self._redirect_url or self._base_url, str(item))
                if abs_url and abs_url not in url_list:
                    url_list.append(abs_url)
            return url_list
        return list(result) if result else None

    def getStringList(self, rule_str: str | None,  # noqa: N802
                      m_content: Any = None, is_url: bool = False):
        return self.get_string_list(rule_str, m_content, is_url)

    # ------------------------------------------------------------------
    # getElement / getElements
    # ------------------------------------------------------------------

    def get_element(self, rule_str: str) -> Any:
        """Mirrors getElement()."""
        if not rule_str:
            return None
        rule_list = self._split_source_rule_cached(rule_str, all_in_one=True)
        result: Any = self._content
        for sr in rule_list:
            if result is None:
                break
            result = self._apply_rule_elements(sr, result)
            if sr.replace_regex:
                result = self._replace_regex(str(result), sr)
        return result

    def get_elements(self, rule_str: str) -> list[Any]:
        """Mirrors getElements()."""
        if not rule_str:
            return []
        rule_list = self._split_source_rule_cached(rule_str, all_in_one=True)
        result: Any = self._content
        for sr in rule_list:
            if result is None:
                break
            result = self._apply_rule_elements(sr, result)
        if result is None:
            return []
        if isinstance(result, list):
            return result
        return [result]

    def getElement(self, rule_str: str) -> Any:  # noqa: N802
        return self.get_element(rule_str)

    def getElements(self, rule_str: str) -> list[Any]:  # noqa: N802
        return self.get_elements(rule_str)

    # ------------------------------------------------------------------
    # Regex replace
    # ------------------------------------------------------------------

    def _replace_regex(self, result: str, rule: SourceRule) -> str:
        if not rule.replace_regex:
            return result
        pattern = self._compile_regex(rule.replace_regex)
        try:
            if rule.replace_first:
                if pattern:
                    m = pattern.search(result)
                    if m:
                        return m.group(0)
                return rule.replacement
            else:
                if pattern:
                    return pattern.sub(rule.replacement, result)
                return result.replace(rule.replace_regex, rule.replacement)
        except Exception:
            return result

    def _compile_regex(self, regex: str) -> re.Pattern | None:
        if regex not in self._regex_cache:
            try:
                self._regex_cache[regex] = re.compile(regex, re.DOTALL)
            except re.error:
                self._regex_cache[regex] = None
        return self._regex_cache[regex]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _put_rule(self, put_map: dict) -> None:
        for key, val_rule in put_map.items():
            self.put(key, self.get_string(val_rule))

    def get_source(self):
        return self._source
