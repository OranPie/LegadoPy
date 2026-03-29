from __future__ import annotations
"""
AnalyzeRule – 1:1 port of AnalyzeRule.kt.
"""


import re
import html as _html_module
from enum import Enum, auto
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..models.book_source import BaseSource
    from ..models.book import Book, BookChapter, RuleData

from .rule_analyzer import RuleAnalyzer
from .analyze_by_jsonpath import AnalyzeByJSonPath
from .analyze_by_jsoup import AnalyzeByJSoup
from .analyze_by_xpath import AnalyzeByXPath
from .analyze_by_regex import AnalyzeByRegex
from ..js_engine import eval_js, JsExtensions
from ..utils.network_utils import get_absolute_url, get_base_url, is_json


# ---------------------------------------------------------------------------
# Patterns (mirror AppPattern / AnalyzeRule companion)
# ---------------------------------------------------------------------------

# Matches @js:...  or  <js>...</js>
JS_PATTERN = re.compile(
    r"@js:([\s\S]*?)(?=@@|@CSS:|@XPath:|@Json:|$)"
    r"|<js>([\s\S]*?)</js>",
    re.IGNORECASE,
)

# Matches @put:{...}
_PUT_PATTERN = re.compile(r"@put:(\{[^}]+?\})", re.IGNORECASE)

# Matches @get:{key}  or  {{...}}
_EVAL_PATTERN = re.compile(
    r"@get:\{[^}]+?\}|\{\{[\w\W]*?\}\}",
    re.IGNORECASE,
)

# Matches $1  $2  etc. (regex group back-references in rule strings)
_REGEX_REF_PATTERN = re.compile(r"\$\d{1,2}")


# ---------------------------------------------------------------------------
# Mode
# ---------------------------------------------------------------------------

class Mode(Enum):
    XPath = auto()
    Json = auto()
    Default = auto()   # CSS/JSoup
    Js = auto()
    Regex = auto()


# ---------------------------------------------------------------------------
# SourceRule – inner class (mirrors AnalyzeRule.SourceRule)
# ---------------------------------------------------------------------------

class SourceRule:
    """
    Represents a single parsed rule segment.
    Mirrors AnalyzeRule.SourceRule (inner class).
    """

    _GET_RULE_TYPE = -2
    _JS_RULE_TYPE = -1
    _DEFAULT_TYPE = 0

    def __init__(
        self,
        rule_str: str,
        mode: Mode = Mode.Default,
        is_json_ctx: bool = False,
        is_regex_ctx: bool = False,
    ) -> None:
        self.mode: Mode = mode
        self.rule: str = ""
        self.replace_regex: str = ""
        self.replacement: str = ""
        self.replace_first: bool = False
        self.put_map: Dict[str, str] = {}

        self._rule_param: List[str] = []
        self._rule_type: List[int] = []

        # ---- detect mode from prefix ----
        if mode in (Mode.Js, Mode.Regex):
            self.rule = rule_str
        elif rule_str.upper().startswith("@CSS:"):
            self.mode = Mode.Default
            self.rule = rule_str          # pass through incl. @CSS: prefix
        elif rule_str.startswith("@@"):
            self.mode = Mode.Default
            self.rule = rule_str[2:]
        elif rule_str.upper().startswith("@XPATH:"):
            self.mode = Mode.XPath
            self.rule = rule_str[7:]
        elif rule_str.upper().startswith("@JSON:"):
            self.mode = Mode.Json
            self.rule = rule_str[6:]
        elif is_json_ctx or rule_str.startswith("$.") or rule_str.startswith("$["):
            self.mode = Mode.Json
            self.rule = rule_str
        elif rule_str.startswith("/"):
            self.mode = Mode.XPath
            self.rule = rule_str
        else:
            self.rule = rule_str

        # ---- strip @put:{...} ----
        self.rule = self._split_put_rule(self.rule, self.put_map)

        # ---- parse @get:{} / {{}} interpolation params ----
        if self.mode not in (Mode.Js, Mode.Regex):
            self._parse_eval_params()

    # ------------------------------------------------------------------

    def _split_put_rule(self, rule_str: str, put_map: Dict[str, str]) -> str:
        import json
        def _repl(m: re.Match) -> str:
            try:
                obj = json.loads(m.group(1))
                if isinstance(obj, dict):
                    put_map.update({str(k): str(v) for k, v in obj.items()})
            except Exception:
                pass
            return ""
        return _PUT_PATTERN.sub(_repl, rule_str)

    def _parse_eval_params(self) -> None:
        """
        Parse @get:{key} and {{js}} placeholders out of self.rule.
        Mirrors the init block of AnalyzeRule.SourceRule.
        """
        start = 0
        rule = self.rule
        m = _EVAL_PATTERN.search(rule, start)
        if m is None:
            # No interpolation – just split off ##regex
            self._split_regex(rule)
            return

        # There's at least one interpolation → promote to Regex mode unless
        # already explicit JS/Regex, and the ## separator hasn't appeared yet
        tmp_before = rule[start: m.start()]
        if self.mode not in (Mode.Js, Mode.Regex) and "##" not in tmp_before:
            self.mode = Mode.Regex

        pos = start
        for m in _EVAL_PATTERN.finditer(rule):
            if m.start() > pos:
                self._split_regex(rule[pos: m.start()])
            token = m.group()
            if token.upper().startswith("@GET:"):
                self._rule_type.append(self._GET_RULE_TYPE)
                self._rule_param.append(token[6: -1])   # @get:{KEY} → KEY
            elif token.startswith("{{"):
                self._rule_type.append(self._JS_RULE_TYPE)
                self._rule_param.append(token[2: -2])
            else:
                self._split_regex(token)
            pos = m.end()

        if pos < len(rule):
            self._split_regex(rule[pos:])

    def _split_regex(self, s: str) -> None:
        """
        Split 's' on $N back-refs and ## regex separators.
        Mirrors AnalyzeRule.SourceRule.splitRegex().
        """
        parts = s.split("##")
        base = parts[0]

        start = 0
        for m in _REGEX_REF_PATTERN.finditer(base):
            if m.start() > start:
                self._rule_type.append(self._DEFAULT_TYPE)
                self._rule_param.append(base[start: m.start()])
            self._rule_type.append(int(m.group()[1:]))   # group index
            self._rule_param.append(m.group())
            if self.mode not in (Mode.Js, Mode.Regex):
                self.mode = Mode.Regex
            start = m.end()
        if start < len(base):
            self._rule_type.append(self._DEFAULT_TYPE)
            self._rule_param.append(base[start:])

        # Store ## parts for later use in make_up_rule
        if len(parts) > 1:
            # Append a special sentinel so make_up_rule can extract them
            self._rule_type.append(self._DEFAULT_TYPE)
            self._rule_param.append("##" + "##".join(parts[1:]))

    # ------------------------------------------------------------------
    # make_up_rule – expand @get / {{ }} at runtime
    # ------------------------------------------------------------------

    def make_up_rule(
        self,
        result: Any,
        get_fn: "GetFn",
        eval_js_fn: "EvalJsFn",
        get_string_fn: "GetStringFn",
    ) -> None:
        """
        Mirrors AnalyzeRule.SourceRule.makeUpRule().
        Resolves _rule_param / _rule_type into self.rule, self.replace_regex,
        self.replacement, self.replace_first.
        """
        if not self._rule_param:
            # No interpolation – extract ## from raw rule
            self._extract_hash_parts(self.rule)
            return

        parts: List[str] = []
        for i, (rtype, rparam) in enumerate(zip(self._rule_type, self._rule_param)):
            if rparam.startswith("##"):
                # ## suffix carrying regex/replace info – don't append to rule
                self._extract_hash_parts("x" + rparam)  # dummy prefix
                continue
            if rtype > self._DEFAULT_TYPE:
                # $N back-ref into regex result list
                if isinstance(result, list) and rtype < len(result):
                    parts.append(str(result[rtype]) if result[rtype] is not None else rparam)
                else:
                    parts.append(rparam)
            elif rtype == self._JS_RULE_TYPE:
                if self._is_rule(rparam):
                    parts.append(get_string_fn(rparam) or "")
                else:
                    val = eval_js_fn(rparam, result)
                    if val is None:
                        pass
                    elif isinstance(val, float) and val % 1.0 == 0:
                        parts.append(f"{int(val)}")
                    else:
                        parts.append(str(val))
            elif rtype == self._GET_RULE_TYPE:
                parts.append(get_fn(rparam))
            else:
                parts.append(rparam)

        assembled = "".join(parts)
        self._extract_hash_parts(assembled)

    def _extract_hash_parts(self, s: str) -> None:
        parts = s.split("##")
        self.rule = parts[0].strip()
        self.replace_regex = parts[1] if len(parts) > 1 else ""
        self.replacement   = parts[2] if len(parts) > 2 else ""
        self.replace_first = len(parts) > 3

    @staticmethod
    def _is_rule(s: str) -> bool:
        return (s.startswith("@") or s.startswith("$.") or
                s.startswith("$[") or s.startswith("//"))

    def get_param_size(self) -> int:
        return len(self._rule_param)


# Type aliases for callbacks used in make_up_rule
GetFn = Any
EvalJsFn = Any
GetStringFn = Any



import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from .rule_analyzer import RuleAnalyzer
from .analyze_by_jsonpath import AnalyzeByJSonPath
from .analyze_by_jsoup import AnalyzeByJSoup
from .analyze_by_xpath import AnalyzeByXPath
from .analyze_by_regex import AnalyzeByRegex
from ..js_engine import eval_js, JsExtensions
from ..utils.network_utils import get_absolute_url, is_json, is_data_url

if TYPE_CHECKING:
    from ..models.book_source import BaseSource
    from ..models.book import Book, BookChapter, RuleData


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
        rule_data: "Optional[RuleData]" = None,
        source: "Optional[BaseSource]" = None,
        pre_update_js: bool = False,
    ) -> None:
        self._rule_data = rule_data
        self._source = source
        self._pre_update_js = pre_update_js

        self._content: Any = None
        self._base_url: Optional[str] = None
        self._redirect_url: Optional[str] = None
        self._is_json: bool = False
        self._is_regex: bool = False
        self._chapter: "Optional[BookChapter]" = None
        self._next_chapter_url: Optional[str] = None

        # lazy sub-parsers
        self._by_xpath: Optional[AnalyzeByXPath] = None
        self._by_jsoup: Optional[AnalyzeByJSoup] = None
        self._by_json: Optional[AnalyzeByJSonPath] = None

        # caches
        self._rule_cache: Dict[str, List[SourceRule]] = {}
        self._regex_cache: Dict[str, Optional[re.Pattern]] = {}

        # JS bindings
        self._java = JsExtensions(
            base_url=self._base_url or "",
            put_fn=lambda k, v: self.put(k, v),
            get_fn=lambda k: self.get(k),
        )

    # ------------------------------------------------------------------
    # Setters (mirror Kotlin extension functions)
    # ------------------------------------------------------------------

    def set_content(self, content: Any, base_url: Optional[str] = None) -> "AnalyzeRule":
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

    def set_base_url(self, base_url: Optional[str]) -> "AnalyzeRule":
        if base_url:
            self._base_url = base_url
            self._java._base_url = base_url
        return self

    def set_redirect_url(self, url: str) -> Optional[str]:
        if is_data_url(url):
            return self._redirect_url
        self._redirect_url = url
        return url

    def set_chapter(self, chapter: "Optional[BookChapter]") -> "AnalyzeRule":
        self._chapter = chapter
        return self

    def set_next_chapter_url(self, url: Optional[str]) -> "AnalyzeRule":
        self._next_chapter_url = url
        return self

    def set_rule_data(self, rule_data: "Optional[RuleData]") -> "AnalyzeRule":
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
        rule_str: Optional[str],
        all_in_one: bool = False,
    ) -> List[SourceRule]:
        """
        Mirrors splitSourceRule().
        Splits a rule string (possibly containing JS blocks) into ordered list
        of SourceRule objects.
        """
        if not rule_str:
            return []

        rule_list: List[SourceRule] = []
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

    def _split_source_rule_cached(self, rule_str: Optional[str]) -> List[SourceRule]:
        if not rule_str:
            return []
        if rule_str not in self._rule_cache:
            self._rule_cache[rule_str] = self.split_source_rule(rule_str)
        return self._rule_cache[rule_str]

    # Kotlin-style camelCase aliases
    def splitSourceRule(self, rule_str: Optional[str],  # noqa: N802
                        all_in_one: bool = False) -> List[SourceRule]:
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
        bindings = {
            "java":           self._java,
            "cookie":         {},
            "cache":          {},
            "source":         self._source,
            "book":           self._rule_data if isinstance(self._rule_data, Book) else None,
            "result":         result,
            "baseUrl":        self._base_url or "",
            "chapter":        self._chapter,
            "title":          self._chapter.title if self._chapter else None,
            "src":            self._content,
            "nextChapterUrl": self._next_chapter_url,
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
        rule_str: Optional[str],
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
        rule_list: List[SourceRule],
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

    def getString(self, rule_str: Optional[str], m_content: Any = None,  # noqa: N802
                  is_url: bool = False, unescape: bool = True) -> str:
        return self.get_string(rule_str, m_content, is_url, unescape)

    # ------------------------------------------------------------------
    # getStringList
    # ------------------------------------------------------------------

    def get_string_list(
        self,
        rule_str: Optional[str],
        m_content: Any = None,
        is_url: bool = False,
    ) -> Optional[List[str]]:
        """Mirrors getStringList()."""
        if not rule_str:
            return None
        rule_list = self._split_source_rule_cached(rule_str)
        return self._get_string_list(rule_list, m_content, is_url)

    def _get_string_list(
        self,
        rule_list: List[SourceRule],
        m_content: Any = None,
        is_url: bool = False,
    ) -> Optional[List[str]]:
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
            url_list: List[str] = []
            for item in (result or []):
                abs_url = get_absolute_url(self._redirect_url or self._base_url, str(item))
                if abs_url and abs_url not in url_list:
                    url_list.append(abs_url)
            return url_list
        return list(result) if result else None

    def getStringList(self, rule_str: Optional[str],  # noqa: N802
                      m_content: Any = None, is_url: bool = False):
        return self.get_string_list(rule_str, m_content, is_url)

    # ------------------------------------------------------------------
    # getElement / getElements
    # ------------------------------------------------------------------

    def get_element(self, rule_str: str) -> Any:
        """Mirrors getElement()."""
        if not rule_str:
            return None
        rule_list = self.split_source_rule(rule_str, all_in_one=True)
        result: Any = self._content
        for sr in rule_list:
            if result is None:
                break
            result = self._apply_rule_elements(sr, result)
            if sr.replace_regex:
                result = self._replace_regex(str(result), sr)
        return result

    def get_elements(self, rule_str: str) -> List[Any]:
        """Mirrors getElements()."""
        if not rule_str:
            return []
        rule_list = self.split_source_rule(rule_str, all_in_one=True)
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

    def getElements(self, rule_str: str) -> List[Any]:  # noqa: N802
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

    def _compile_regex(self, regex: str) -> Optional[re.Pattern]:
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
