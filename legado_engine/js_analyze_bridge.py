from __future__ import annotations

import json
import sys
from dataclasses import fields, is_dataclass
from typing import Any, Dict

from bs4 import Tag

from .analyze.analyze_rule import AnalyzeRule
from .models.book import Book, BookChapter, RuleData
from .models.book_source import BaseSource, BookSource
from .models.rss_source import RssSource


def _build_dataclass(cls, data: Dict[str, Any]) -> Any:
    allowed = {field.name for field in fields(cls)}
    kwargs = {key: value for key, value in (data or {}).items() if key in allowed}
    obj = cls(**kwargs)
    if hasattr(obj, "load_variable") and data.get("variable") is not None:
        obj.load_variable(data.get("variable"))
    return obj


def _build_source(data: Dict[str, Any]) -> BaseSource | None:
    if not isinstance(data, dict) or not data:
        return None
    if "bookSourceUrl" in data:
        return BookSource.from_dict(data)
    if "sourceUrl" in data:
        return RssSource.from_dict(data)
    return _build_dataclass(BaseSource, data)


def _build_rule_data(data: Dict[str, Any]) -> RuleData | None:
    if not isinstance(data, dict) or not data:
        return None
    if "bookUrl" in data or "name" in data or "author" in data:
        return _build_dataclass(Book, data)
    return _build_dataclass(RuleData, data)


def _build_chapter(data: Dict[str, Any]) -> BookChapter | None:
    if not isinstance(data, dict) or not data:
        return None
    return _build_dataclass(BookChapter, data)


def _serialize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Tag):
        return str(value)
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, tuple):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize(item) for key, item in value.items()}
    if is_dataclass(value):
        return {field.name: _serialize(getattr(value, field.name)) for field in fields(value)}
    return str(value)


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    operation = payload.get("operation")
    source = _build_source(payload.get("source") or {})
    rule_data = _build_rule_data(payload.get("book") or {})
    chapter = _build_chapter(payload.get("chapter") or {})
    base_url = str(payload.get("baseUrl") or "")
    redirect_url = str(payload.get("redirectUrl") or base_url)
    content = payload.get("content")

    analyze_rule = AnalyzeRule(rule_data or RuleData(), source)
    if content is None:
        content = ""
    analyze_rule.set_content(content, base_url=base_url)
    analyze_rule.set_redirect_url(redirect_url)
    analyze_rule.set_chapter(chapter)

    if operation == "set_content":
        result: Any = {
            "content": payload.get("newContent"),
            "baseUrl": payload.get("newBaseUrl") or base_url,
        }
    elif operation == "get_string":
        result = analyze_rule.get_string(
            payload.get("rule"),
            payload.get("mContent"),
            bool(payload.get("isUrl", False)),
        )
    elif operation == "get_string_list":
        result = analyze_rule.get_string_list(
            payload.get("rule"),
            payload.get("mContent"),
            bool(payload.get("isUrl", False)),
        )
    elif operation == "get_element":
        result = analyze_rule.get_element(payload.get("rule") or "")
        if isinstance(result, list):
            result = result[0] if result else None
    elif operation == "get_elements":
        result = analyze_rule.get_elements(payload.get("rule") or "")
    elif operation == "t2s":
        from .utils.content_help import chinese_convert
        result = chinese_convert(payload.get("text") or "", 2)  # traditional → simplified (T2S = mode 2)
    elif operation == "s2t":
        from .utils.content_help import chinese_convert
        result = chinese_convert(payload.get("text") or "", 1)  # simplified → traditional (S2T = mode 1)
    elif operation == "toNumChapter":
        from .utils.content_help import to_num_chapter
        result = to_num_chapter(payload.get("text") or "")
    elif operation == "getZipStringContent":
        import io
        import zipfile
        import urllib.request
        url = payload.get("url") or ""
        inner_path = payload.get("path") or ""
        charset = payload.get("charsetName") or None
        try:
            if url.startswith("http://") or url.startswith("https://"):
                with urllib.request.urlopen(url, timeout=15) as resp:
                    zip_bytes = resp.read()
            else:
                # treat as hex string
                zip_bytes = bytes.fromhex(url)
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                entry_bytes = zf.read(inner_path)
            if charset:
                result = entry_bytes.decode(charset, errors="replace")
            else:
                # auto-detect encoding (try utf-8 then gbk)
                try:
                    result = entry_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    result = entry_bytes.decode("gbk", errors="replace")
        except Exception as e:
            result = ""
    elif operation == "getCookie":
        java = getattr(rule, "_java", None)
        tag = payload.get("tag") or ""
        key = payload.get("key")
        result = java.getCookie(tag, key) if java else ""
    elif operation == "setCookie":
        java = getattr(rule, "_java", None)
        if java:
            java.setCookie(payload.get("tag") or "", payload.get("cookie") or "")
        result = None
    elif operation == "downloadFile":
        java = getattr(rule, "_java", None)
        if java:
            url_val = payload.get("url") or ""
            legacy = payload.get("legacyUrl")
            if legacy is not None:
                result = java.downloadFile(url_val, legacy)
            else:
                result = java.downloadFile(url_val)
        else:
            result = ""
    elif operation == "readFile":
        java = getattr(rule, "_java", None)
        result = java.readFile(payload.get("path") or "") if java else None
    elif operation == "readTxtFile":
        java = getattr(rule, "_java", None)
        charset = payload.get("charsetName") or ""
        result = java.readTxtFile(payload.get("path") or "", charset) if java else ""
    elif operation == "deleteFile":
        java = getattr(rule, "_java", None)
        result = java.deleteFile(payload.get("path") or "") if java else False
    elif operation in ("unzipFile", "unArchiveFile"):
        java = getattr(rule, "_java", None)
        result = java.unArchiveFile(payload.get("path") or "") if java else ""
    elif operation == "getTxtInFolder":
        java = getattr(rule, "_java", None)
        result = java.getTxtInFolder(payload.get("path") or "") if java else ""
    elif operation == "reGetBook":
        java = getattr(rule, "_java", None)
        if java:
            java.reGetBook()
        result = None
    elif operation == "refreshTocUrl":
        java = getattr(rule, "_java", None)
        if java:
            java.refreshTocUrl()
        result = None
    else:
        raise ValueError(f"Unsupported operation: {operation}")

    sys.stdout.write(json.dumps({"result": _serialize(result)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
