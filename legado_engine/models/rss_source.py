from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List

from .book import RuleData
from .book_source import BaseSource


def _str_equal(a: str | None, b: str | None) -> bool:
    return a == b or ((a is None or a == "") and (b is None or b == ""))


def _split_groups(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in re.split(r"[\n,]+", value) if part.strip()]


@dataclass(eq=False)
class RssSource(BaseSource):
    sourceUrl: str = ""
    sourceName: str = ""
    sourceIcon: str = ""
    sourceGroup: str | None = None
    sourceComment: str | None = None
    enabled: bool = True
    variableComment: str | None = None
    loginCheckJs: str | None = None
    coverDecodeJs: str | None = None
    sortUrl: str | None = None
    singleUrl: bool = False
    articleStyle: int = 0
    ruleArticles: str | None = None
    ruleNextPage: str | None = None
    ruleTitle: str | None = None
    rulePubDate: str | None = None
    ruleDescription: str | None = None
    ruleImage: str | None = None
    ruleLink: str | None = None
    ruleContent: str | None = None
    contentWhitelist: str | None = None
    contentBlacklist: str | None = None
    shouldOverrideUrlLoading: str | None = None
    style: str | None = None
    enableJs: bool = True
    loadWithBaseUrl: bool = True
    injectJs: str | None = None
    lastUpdateTime: int = 0
    customOrder: int = 0

    def get_key(self) -> str:
        return self.sourceUrl

    def get_tag(self) -> str:
        return self.sourceName

    def getDisplayNameGroup(self) -> str:  # noqa: N802
        if not self.sourceGroup:
            return self.sourceName
        return f"{self.sourceName} ({self.sourceGroup})"

    def addGroup(self, groups: str) -> "RssSource":  # noqa: N802
        current = set(_split_groups(self.sourceGroup))
        current.update(_split_groups(groups))
        self.sourceGroup = ",".join(sorted(current)) if current else None
        return self

    def removeGroup(self, groups: str) -> "RssSource":  # noqa: N802
        current = set(_split_groups(self.sourceGroup))
        current.difference_update(_split_groups(groups))
        self.sourceGroup = ",".join(sorted(current)) if current else None
        return self

    def equal(self, source: "RssSource") -> bool:
        return (
            _str_equal(self.sourceUrl, source.sourceUrl)
            and _str_equal(self.sourceName, source.sourceName)
            and _str_equal(self.sourceIcon, source.sourceIcon)
            and self.enabled == source.enabled
            and _str_equal(self.sourceGroup, source.sourceGroup)
            and self.enabledCookieJar == source.enabledCookieJar
            and _str_equal(self.sourceComment, source.sourceComment)
            and _str_equal(self.concurrentRate, source.concurrentRate)
            and _str_equal(self.header, source.header)
            and _str_equal(self.loginUrl, source.loginUrl)
            and _str_equal(self.loginUi, source.loginUi)
            and _str_equal(self.loginCheckJs, source.loginCheckJs)
            and _str_equal(self.coverDecodeJs, source.coverDecodeJs)
            and _str_equal(self.sortUrl, source.sortUrl)
            and self.singleUrl == source.singleUrl
            and self.articleStyle == source.articleStyle
            and _str_equal(self.ruleArticles, source.ruleArticles)
            and _str_equal(self.ruleNextPage, source.ruleNextPage)
            and _str_equal(self.ruleTitle, source.ruleTitle)
            and _str_equal(self.rulePubDate, source.rulePubDate)
            and _str_equal(self.ruleDescription, source.ruleDescription)
            and _str_equal(self.ruleImage, source.ruleImage)
            and _str_equal(self.ruleLink, source.ruleLink)
            and _str_equal(self.ruleContent, source.ruleContent)
            and self.enableJs == source.enableJs
            and self.loadWithBaseUrl == source.loadWithBaseUrl
            and _str_equal(self.variableComment, source.variableComment)
            and _str_equal(self.style, source.style)
            and _str_equal(self.injectJs, source.injectJs)
        )

    def __eq__(self, other: object) -> bool:
        return isinstance(other, RssSource) and other.sourceUrl == self.sourceUrl

    def __hash__(self) -> int:
        return hash(self.sourceUrl)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RssSource":
        return cls(
            sourceUrl=str(data.get("sourceUrl", "") or ""),
            sourceName=str(data.get("sourceName", "") or ""),
            sourceIcon=str(data.get("sourceIcon", "") or ""),
            sourceGroup=data.get("sourceGroup"),
            sourceComment=data.get("sourceComment"),
            enabled=bool(data.get("enabled", True)),
            variableComment=data.get("variableComment"),
            jsLib=data.get("jsLib"),
            enabledCookieJar=bool(data.get("enabledCookieJar", True)),
            concurrentRate=data.get("concurrentRate"),
            header=data.get("header"),
            loginUrl=data.get("loginUrl"),
            loginUi=data.get("loginUi"),
            loginCheckJs=data.get("loginCheckJs"),
            coverDecodeJs=data.get("coverDecodeJs"),
            sortUrl=data.get("sortUrl"),
            singleUrl=bool(data.get("singleUrl", False)),
            articleStyle=int(data.get("articleStyle", 0) or 0),
            ruleArticles=data.get("ruleArticles"),
            ruleNextPage=data.get("ruleNextPage"),
            ruleTitle=data.get("ruleTitle"),
            rulePubDate=data.get("rulePubDate"),
            ruleDescription=data.get("ruleDescription"),
            ruleImage=data.get("ruleImage"),
            ruleLink=data.get("ruleLink"),
            ruleContent=data.get("ruleContent"),
            contentWhitelist=data.get("contentWhitelist"),
            contentBlacklist=data.get("contentBlacklist"),
            shouldOverrideUrlLoading=data.get("shouldOverrideUrlLoading"),
            style=data.get("style"),
            enableJs=bool(data.get("enableJs", True)),
            loadWithBaseUrl=bool(data.get("loadWithBaseUrl", True)),
            injectJs=data.get("injectJs"),
            lastUpdateTime=int(data.get("lastUpdateTime", 0) or 0),
            customOrder=int(data.get("customOrder", 0) or 0),
        )

    @classmethod
    def from_json(cls, text: str) -> "RssSource":
        return cls.from_dict(json.loads(text))

    @classmethod
    def from_json_array(cls, text: str) -> list["RssSource"]:
        data = json.loads(text)
        if isinstance(data, dict):
            return [cls.from_dict(data)]
        return [cls.from_dict(item) for item in data if isinstance(item, dict)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceUrl": self.sourceUrl,
            "sourceName": self.sourceName,
            "sourceIcon": self.sourceIcon,
            "sourceGroup": self.sourceGroup,
            "sourceComment": self.sourceComment,
            "enabled": self.enabled,
            "variableComment": self.variableComment,
            "jsLib": self.jsLib,
            "enabledCookieJar": self.enabledCookieJar,
            "concurrentRate": self.concurrentRate,
            "header": self.header,
            "loginUrl": self.loginUrl,
            "loginUi": self.loginUi,
            "loginCheckJs": self.loginCheckJs,
            "coverDecodeJs": self.coverDecodeJs,
            "sortUrl": self.sortUrl,
            "singleUrl": self.singleUrl,
            "articleStyle": self.articleStyle,
            "ruleArticles": self.ruleArticles,
            "ruleNextPage": self.ruleNextPage,
            "ruleTitle": self.ruleTitle,
            "rulePubDate": self.rulePubDate,
            "ruleDescription": self.ruleDescription,
            "ruleImage": self.ruleImage,
            "ruleLink": self.ruleLink,
            "ruleContent": self.ruleContent,
            "contentWhitelist": self.contentWhitelist,
            "contentBlacklist": self.contentBlacklist,
            "shouldOverrideUrlLoading": self.shouldOverrideUrlLoading,
            "style": self.style,
            "enableJs": self.enableJs,
            "loadWithBaseUrl": self.loadWithBaseUrl,
            "injectJs": self.injectJs,
            "lastUpdateTime": self.lastUpdateTime,
            "customOrder": self.customOrder,
        }


@dataclass
class RssArticle(RuleData):
    sourceUrl: str = ""
    sourceName: str = ""
    title: str = ""
    link: str = ""
    pubDate: str = ""
    description: str = ""
    image: str = ""
    content: str = ""
    baseUrl: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "sourceUrl": self.sourceUrl,
            "sourceName": self.sourceName,
            "title": self.title,
            "link": self.link,
            "pubDate": self.pubDate,
            "description": self.description,
            "image": self.image,
            "content": self.content,
            "baseUrl": self.baseUrl,
            "variable": self.variable,
        }
