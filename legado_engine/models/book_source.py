"""
BookSource and rule data models – 1:1 port of Legado's Kotlin data classes.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


# ---------------------------------------------------------------------------
# Rule sub-classes (mirrors data/entities/rule/*.kt)
# ---------------------------------------------------------------------------

@dataclass
class SearchRule:
    """ruleSearch – maps to SearchRule.kt"""
    checkKeyWord: str | None = None
    bookList: str | None = None
    name: str | None = None
    author: str | None = None
    intro: str | None = None
    kind: str | None = None
    lastChapter: str | None = None
    updateTime: str | None = None
    bookUrl: str | None = None
    coverUrl: str | None = None
    wordCount: str | None = None


@dataclass
class ExploreRule:
    """ruleExplore – maps to ExploreRule.kt"""
    bookList: str | None = None
    name: str | None = None
    author: str | None = None
    intro: str | None = None
    kind: str | None = None
    lastChapter: str | None = None
    updateTime: str | None = None
    bookUrl: str | None = None
    coverUrl: str | None = None
    wordCount: str | None = None


@dataclass
class ExploreKind:
    """Mirrors Legado's ExploreKind for discover/category buttons."""
    title: str = ""
    url: str | None = None
    style: Optional[dict[str, Any]] = None


@dataclass
class BookInfoRule:
    """ruleBookInfo – maps to BookInfoRule.kt"""
    init: str | None = None
    name: str | None = None
    author: str | None = None
    intro: str | None = None
    kind: str | None = None
    lastChapter: str | None = None
    updateTime: str | None = None
    coverUrl: str | None = None
    tocUrl: str | None = None
    wordCount: str | None = None
    canReName: str | None = None
    downloadUrls: str | None = None


@dataclass
class TocRule:
    """ruleToc – maps to TocRule.kt"""
    preUpdateJs: str | None = None
    chapterList: str | None = None
    chapterName: str | None = None
    chapterUrl: str | None = None
    formatJs: str | None = None
    isVolume: str | None = None
    isVip: str | None = None
    isPay: str | None = None
    updateTime: str | None = None
    nextTocUrl: str | None = None


@dataclass
class ContentRule:
    """ruleContent – maps to ContentRule.kt"""
    content: str | None = None
    title: str | None = None
    nextContentUrl: str | None = None
    webJs: str | None = None
    sourceRegex: str | None = None
    replaceRegex: str | None = None
    imageStyle: str | None = None
    imageDecode: str | None = None
    payAction: str | None = None


@dataclass
class ReviewRule:
    """ruleReview – maps to ReviewRule.kt."""
    reviewUrl: str | None = None
    avatarRule: str | None = None
    contentRule: str | None = None
    postTimeRule: str | None = None
    reviewQuoteUrl: str | None = None
    voteUpUrl: str | None = None
    voteDownUrl: str | None = None
    postReviewUrl: str | None = None
    postQuoteUrl: str | None = None
    deleteUrl: str | None = None


# ---------------------------------------------------------------------------
# BaseSource (interface in Kotlin – dataclass mixin here)
# ---------------------------------------------------------------------------

@dataclass
class BaseSource:
    jsLib: str | None = None
    enabledCookieJar: bool | None = True
    concurrentRate: str | None = None
    header: str | None = None
    loginUrl: str | None = None
    loginUi: str | None = None
    _variables: dict[str, str] = field(default_factory=dict, repr=False)

    def get_key(self) -> str:
        return ""

    def get_tag(self) -> str:
        return ""

    def getKey(self) -> str:  # noqa: N802
        return self.get_key()

    def getTag(self) -> str:  # noqa: N802
        return self.get_tag()

    def get_header_map(self, has_login_header: bool = True, engine=None) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.header:
            try:
                header_text = self.header
                if isinstance(header_text, str):
                    if header_text.startswith("@js:"):
                        from ..js import eval_js, JsExtensions
                        header_text = str(eval_js(
                            header_text[4:],
                            bindings={"source": self, "engine": engine},
                            java_obj=JsExtensions(engine=engine),
                        ) or "")
                    elif header_text.lower().startswith("<js>") and "</js>" in header_text.lower():
                        from ..js import eval_js, JsExtensions
                        end = header_text.lower().rfind("</js>")
                        header_text = str(eval_js(
                            header_text[4:end],
                            bindings={"source": self, "engine": engine},
                            java_obj=JsExtensions(engine=engine),
                        ) or "")
                h = json.loads(header_text)
                if isinstance(h, dict):
                    headers.update({str(k): str(v) for k, v in h.items()})
            except Exception:
                pass
        if has_login_header:
            headers.update(self.get_login_header_map())
        return headers

    def put(self, key: str, value: str) -> None:
        self._variables[key] = value

    def get(self, key: str) -> str:
        return self._variables.get(key, "")

    def login_ui_rows(self):
        from ..auth.login import parse_source_ui
        return parse_source_ui(self)

    def get_login_js(self) -> str | None:
        login_js = self.loginUrl
        if login_js is None:
            return None
        if login_js.startswith("@js:"):
            return login_js[4:]
        if login_js.startswith("<js>") and "</js>" in login_js:
            return login_js[4:login_js.rfind("</js>")]
        return login_js

    def login(self, engine=None) -> Any:
        login_js = self.get_login_js()
        if not login_js:
            return None
        from ..js import eval_js, JsExtensions
        js = (
            f"{login_js}\n"
            "if (typeof login === 'function') {\n"
            "  login.apply(this);\n"
            "} else {\n"
            "  throw('Function login not implements!!!');\n"
            "}\n"
        )
        return eval_js(js, bindings={"source": self, "engine": engine}, java_obj=JsExtensions(engine=engine))

    def getLoginJs(self) -> str | None:  # noqa: N802
        return self.get_login_js()

    def getLoginHeader(self) -> str:  # noqa: N802
        return self._variables.get("_login_header", "")

    def get_login_header_map(self) -> dict[str, str]:
        try:
            raw = self.getLoginHeader()
            return {
                str(k): str(v)
                for k, v in (json.loads(raw) or {}).items()
            } if raw else {}
        except Exception:
            return {}

    def getLoginHeaderMap(self) -> dict[str, str]:  # noqa: N802
        return self.get_login_header_map()

    def putLoginHeader(self, header: str) -> None:  # noqa: N802
        self._variables["_login_header"] = header

    def removeLoginHeader(self) -> None:  # noqa: N802
        self._variables.pop("_login_header", None)

    def removeLoginInfo(self) -> None:  # noqa: N802
        self._variables.pop("_login_info", None)

    def setVariable(self, value: str | None) -> None:  # noqa: N802
        if value is None:
            self._variables.pop("custom_variable_blob", None)
        else:
            self._variables["custom_variable_blob"] = value

    def getVariable(self) -> str:  # noqa: N802
        return self._variables.get("custom_variable_blob", "")

    def getLoginInfo(self) -> str:  # noqa: N802
        return self._variables.get("_login_info", "")

    def putLoginInfo(self, info: str) -> None:  # noqa: N802
        self._variables["_login_info"] = info

    def getLoginInfoMap(self) -> dict[str, str]:  # noqa: N802
        try:
            raw = self.getLoginInfo()
            return {
                str(k): str(v)
                for k, v in (json.loads(raw) or {}).items()
            } if raw else {}
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# BookSource (primary entity)
# ---------------------------------------------------------------------------

@dataclass(eq=False)
class BookSource(BaseSource):
    """Maps to BookSource.kt data class."""
    # Core identity
    bookSourceUrl: str = ""
    bookSourceName: str = ""
    bookSourceGroup: str | None = None
    bookSourceType: int = 0          # 0=text, 1=audio, 2=image, 3=file
    bookUrlPattern: str | None = None
    customOrder: int = 0
    enabled: bool = True
    enabledExplore: bool = True

    # Source metadata
    loginCheckJs: str | None = None
    coverDecodeJs: str | None = None
    bookSourceComment: str | None = None
    variableComment: str | None = None
    lastUpdateTime: int = 0
    respondTime: int = 180000
    weight: int = 0

    # URL templates
    exploreUrl: str | None = None
    exploreScreen: str | None = None
    searchUrl: str | None = None

    # Rules (all optional – lazily created)
    ruleExplore: ExploreRule | None = None
    ruleSearch: SearchRule | None = None
    ruleBookInfo: BookInfoRule | None = None
    ruleToc: TocRule | None = None
    ruleContent: ContentRule | None = None
    ruleReview: ReviewRule | None = None

    def get_key(self) -> str:
        return self.bookSourceUrl

    def get_tag(self) -> str:
        return self.bookSourceName

    # Lazy rule accessors (mirror get*Rule() methods in Kotlin)
    def get_search_rule(self) -> SearchRule:
        if self.ruleSearch is None:
            self.ruleSearch = SearchRule()
        return self.ruleSearch

    def get_explore_rule(self) -> ExploreRule:
        if self.ruleExplore is None:
            self.ruleExplore = ExploreRule()
        return self.ruleExplore

    def get_book_info_rule(self) -> BookInfoRule:
        if self.ruleBookInfo is None:
            self.ruleBookInfo = BookInfoRule()
        return self.ruleBookInfo

    def get_toc_rule(self) -> TocRule:
        if self.ruleToc is None:
            self.ruleToc = TocRule()
        return self.ruleToc

    def get_content_rule(self) -> ContentRule:
        if self.ruleContent is None:
            self.ruleContent = ContentRule()
        return self.ruleContent

    def get_review_rule(self) -> ReviewRule:
        if self.ruleReview is None:
            self.ruleReview = ReviewRule()
        return self.ruleReview

    def getKey(self) -> str:  # noqa: N802
        return self.bookSourceUrl or ""

    def getSearchRule(self) -> SearchRule:  # noqa: N802
        return self.get_search_rule()

    def getExploreRule(self) -> ExploreRule:  # noqa: N802
        return self.get_explore_rule()

    def getBookInfoRule(self) -> BookInfoRule:  # noqa: N802
        return self.get_book_info_rule()

    def getTocRule(self) -> TocRule:  # noqa: N802
        return self.get_toc_rule()

    def getContentRule(self) -> ContentRule:  # noqa: N802
        return self.get_content_rule()

    def getReviewRule(self) -> ReviewRule:  # noqa: N802
        return self.get_review_rule()

    def getDisPlayNameGroup(self) -> str:  # noqa: N802
        if not self.bookSourceGroup:
            return self.bookSourceName
        return f"{self.bookSourceName} ({self.bookSourceGroup})"

    def addGroup(self, groups: str) -> "BookSource":  # noqa: N802
        if not groups:
            return self
        cur = {g.strip() for g in (self.bookSourceGroup or "").replace("\n", ",").split(",") if g.strip()}
        cur.update(g.strip() for g in groups.replace("\n", ",").split(",") if g.strip())
        self.bookSourceGroup = ",".join(sorted(cur)) if cur else None
        return self

    def removeGroup(self, groups: str) -> "BookSource":  # noqa: N802
        if not groups:
            return self
        cur = {g.strip() for g in (self.bookSourceGroup or "").replace("\n", ",").split(",") if g.strip()}
        cur.difference_update(g.strip() for g in groups.replace("\n", ",").split(",") if g.strip())
        self.bookSourceGroup = ",".join(sorted(cur)) if cur else None
        return self

    def hasGroup(self, group: str) -> bool:  # noqa: N802
        cur = {g.strip() for g in (self.bookSourceGroup or "").replace("\n", ",").split(",") if g.strip()}
        return group in cur

    def getCheckKeyword(self, default: str) -> str:  # noqa: N802
        rule = self.ruleSearch
        if rule and rule.checkKeyWord and rule.checkKeyWord.strip():
            return rule.checkKeyWord
        return default

    def getInvalidGroupNames(self) -> str:  # noqa: N802
        groups = [
            g.strip()
            for g in (self.bookSourceGroup or "").replace("\n", ",").split(",")
            if g.strip()
        ]
        return ",".join(g for g in groups if "失效" in g or g == "校验超时")

    def removeInvalidGroups(self) -> None:  # noqa: N802
        self.removeGroup(self.getInvalidGroupNames())

    def removeErrorComment(self) -> None:  # noqa: N802
        if not self.bookSourceComment:
            return
        self.bookSourceComment = "\n".join(
            part for part in self.bookSourceComment.split("\n\n")
            if not part.startswith("// Error: ")
        )

    def addErrorComment(self, exc: Exception) -> None:  # noqa: N802
        msg = f"// Error: {exc}"
        self.bookSourceComment = (
            msg if not self.bookSourceComment else f"{msg}\n\n{self.bookSourceComment}"
        )

    def getDisplayVariableComment(self, other_comment: str) -> str:  # noqa: N802
        if not self.variableComment:
            return other_comment
        return f"{self.variableComment}\n{other_comment}"

    def to_part(self) -> "BookSourcePart":
        return BookSourcePart.from_book_source(self)

    @staticmethod
    def _str_equal(a: str | None, b: str | None) -> bool:
        return a == b or ((a is None or a == "") and (b is None or b == ""))

    def equal(self, source: "BookSource") -> bool:
        return (
            self._str_equal(self.bookSourceName, source.bookSourceName)
            and self._str_equal(self.bookSourceUrl, source.bookSourceUrl)
            and self._str_equal(self.bookSourceGroup, source.bookSourceGroup)
            and self.bookSourceType == source.bookSourceType
            and self._str_equal(self.bookUrlPattern, source.bookUrlPattern)
            and self._str_equal(self.bookSourceComment, source.bookSourceComment)
            and self.customOrder == source.customOrder
            and self.enabled == source.enabled
            and self.enabledExplore == source.enabledExplore
            and self.enabledCookieJar == source.enabledCookieJar
            and self._str_equal(self.variableComment, source.variableComment)
            and self._str_equal(self.concurrentRate, source.concurrentRate)
            and self._str_equal(self.jsLib, source.jsLib)
            and self._str_equal(self.header, source.header)
            and self._str_equal(self.loginUrl, source.loginUrl)
            and self._str_equal(self.loginUi, source.loginUi)
            and self._str_equal(self.loginCheckJs, source.loginCheckJs)
            and self._str_equal(self.coverDecodeJs, source.coverDecodeJs)
            and self._str_equal(self.exploreUrl, source.exploreUrl)
            and self._str_equal(self.searchUrl, source.searchUrl)
            and self.getSearchRule() == source.getSearchRule()
            and self.getExploreRule() == source.getExploreRule()
            and self.getBookInfoRule() == source.getBookInfoRule()
            and self.getTocRule() == source.getTocRule()
            and self.getContentRule() == source.getContentRule()
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, BookSource) and other.bookSourceUrl == self.bookSourceUrl

    def __hash__(self) -> int:
        return hash(self.bookSourceUrl)



    # ------------------------------------------------------------------
    # JSON import/export (the format used by the Legado app community)
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BookSource":
        """Deserialize from the community JSON format."""
        def parse_rule(rule_cls, key: str):
            raw = d.get(key)
            if raw is None:
                return None
            if isinstance(raw, str):
                try:
                    raw = json.loads(raw)
                except Exception:
                    return None
            if isinstance(raw, dict):
                # Filter only known fields
                known = {f for f in rule_cls.__dataclass_fields__}
                return rule_cls(**{k: v for k, v in raw.items() if k in known})
            return None

        bs = cls(
            bookSourceUrl=d.get("bookSourceUrl", ""),
            bookSourceName=d.get("bookSourceName", ""),
            bookSourceGroup=d.get("bookSourceGroup"),
            bookSourceType=d.get("bookSourceType", 0),
            bookUrlPattern=d.get("bookUrlPattern"),
            customOrder=d.get("customOrder", 0),
            enabled=d.get("enabled", True),
            enabledExplore=d.get("enabledExplore", True),
            jsLib=d.get("jsLib"),
            enabledCookieJar=d.get("enabledCookieJar", True),
            concurrentRate=d.get("concurrentRate"),
            header=d.get("header"),
            loginUrl=d.get("loginUrl"),
            loginUi=d.get("loginUi"),
            loginCheckJs=d.get("loginCheckJs"),
            coverDecodeJs=d.get("coverDecodeJs"),
            bookSourceComment=d.get("bookSourceComment"),
            variableComment=d.get("variableComment"),
            lastUpdateTime=d.get("lastUpdateTime", 0),
            respondTime=d.get("respondTime", 180000),
            weight=d.get("weight", 0),
            exploreUrl=d.get("exploreUrl"),
            exploreScreen=d.get("exploreScreen"),
            searchUrl=d.get("searchUrl"),
            ruleExplore=parse_rule(ExploreRule, "ruleExplore"),
            ruleSearch=parse_rule(SearchRule, "ruleSearch"),
            ruleBookInfo=parse_rule(BookInfoRule, "ruleBookInfo"),
            ruleToc=parse_rule(TocRule, "ruleToc"),
            ruleContent=parse_rule(ContentRule, "ruleContent"),
            ruleReview=parse_rule(ReviewRule, "ruleReview"),
        )
        return bs

    @classmethod
    def from_json(cls, text: str) -> "BookSource":
        return cls.from_dict(json.loads(text))

    @classmethod
    def from_json_array(cls, text: str) -> list["BookSource"]:
        return [cls.from_dict(d) for d in json.loads(text)]

    def to_dict(self) -> dict[str, Any]:
        import dataclasses
        def _rule_to_dict(r):
            if r is None:
                return None
            return {k: v for k, v in dataclasses.asdict(r).items() if v is not None}

        d: dict[str, Any] = {
            "bookSourceUrl": self.bookSourceUrl,
            "bookSourceName": self.bookSourceName,
            "bookSourceGroup": self.bookSourceGroup,
            "bookSourceType": self.bookSourceType,
            "bookUrlPattern": self.bookUrlPattern,
            "customOrder": self.customOrder,
            "enabled": self.enabled,
            "enabledExplore": self.enabledExplore,
            "jsLib": self.jsLib,
            "enabledCookieJar": self.enabledCookieJar,
            "concurrentRate": self.concurrentRate,
            "header": self.header,
            "loginUrl": self.loginUrl,
            "loginUi": self.loginUi,
            "loginCheckJs": self.loginCheckJs,
            "coverDecodeJs": self.coverDecodeJs,
            "bookSourceComment": self.bookSourceComment,
            "variableComment": self.variableComment,
            "lastUpdateTime": self.lastUpdateTime,
            "respondTime": self.respondTime,
            "weight": self.weight,
            "searchUrl": self.searchUrl,
            "exploreUrl": self.exploreUrl,
            "exploreScreen": self.exploreScreen,
            "ruleSearch": _rule_to_dict(self.ruleSearch),
            "ruleExplore": _rule_to_dict(self.ruleExplore),
            "ruleBookInfo": _rule_to_dict(self.ruleBookInfo),
            "ruleToc": _rule_to_dict(self.ruleToc),
            "ruleContent": _rule_to_dict(self.ruleContent),
            "ruleReview": _rule_to_dict(self.ruleReview),
        }
        return {k: v for k, v in d.items() if v is not None}


@dataclass(eq=False)
class BookSourcePart:
    """Lightweight source entity mirroring Legado's BookSourcePart."""

    bookSourceUrl: str = ""
    bookSourceName: str = ""
    bookSourceGroup: str | None = None
    customOrder: int = 0
    enabled: bool = True
    enabledExplore: bool = True
    hasLoginUrl: bool = False
    lastUpdateTime: int = 0
    respondTime: int = 180000
    weight: int = 0
    hasExploreUrl: bool = False

    @classmethod
    def from_book_source(cls, source: BookSource) -> "BookSourcePart":
        return cls(
            bookSourceUrl=source.bookSourceUrl,
            bookSourceName=source.bookSourceName,
            bookSourceGroup=source.bookSourceGroup,
            customOrder=source.customOrder,
            enabled=source.enabled,
            enabledExplore=source.enabledExplore,
            hasLoginUrl=bool((source.loginUrl or "").strip()),
            lastUpdateTime=source.lastUpdateTime,
            respondTime=source.respondTime,
            weight=source.weight,
            hasExploreUrl=bool((source.exploreUrl or "").strip()),
        )

    def getDisPlayNameGroup(self) -> str:  # noqa: N802
        if not self.bookSourceGroup:
            return self.bookSourceName
        return f"{self.bookSourceName} ({self.bookSourceGroup})"

    def addGroup(self, groups: str) -> None:  # noqa: N802
        if not groups:
            return
        cur = {g.strip() for g in (self.bookSourceGroup or "").replace("\n", ",").split(",") if g.strip()}
        cur.update(g.strip() for g in groups.replace("\n", ",").split(",") if g.strip())
        self.bookSourceGroup = ",".join(sorted(cur)) if cur else None

    def removeGroup(self, groups: str) -> None:  # noqa: N802
        if not groups:
            return
        cur = {g.strip() for g in (self.bookSourceGroup or "").replace("\n", ",").split(",") if g.strip()}
        cur.difference_update(g.strip() for g in groups.replace("\n", ",").split(",") if g.strip())
        self.bookSourceGroup = ",".join(sorted(cur)) if cur else None

    def __eq__(self, other: object) -> bool:
        return isinstance(other, BookSourcePart) and other.bookSourceUrl == self.bookSourceUrl

    def __hash__(self) -> int:
        return hash(self.bookSourceUrl)


def to_book_source_parts(sources: list[BookSource]) -> list[BookSourcePart]:
    return [BookSourcePart.from_book_source(source) for source in sources]
