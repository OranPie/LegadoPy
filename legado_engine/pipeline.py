from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .analyze_url import StrResponse


class JsHeaders:
    def __init__(self, headers: Optional[Dict[str, str]] = None) -> None:
        self._headers = {str(k): str(v) for k, v in (headers or {}).items()}

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        key_lower = str(key).lower()
        for header_key, value in self._headers.items():
            if header_key.lower() == key_lower:
                return value
        return default

    def to_dict(self) -> Dict[str, str]:
        return dict(self._headers)


class JsBody:
    def __init__(self, text: Optional[str]) -> None:
        self._text = "" if text is None else str(text)

    def string(self) -> str:
        return self._text

    def __str__(self) -> str:
        return self._text


@dataclass
class JsStrResponse:
    response: StrResponse

    def body(self) -> JsBody:
        return JsBody(self.response.body)

    def code(self) -> int:
        return int(self.response.status_code)

    def headers(self) -> JsHeaders:
        return JsHeaders(self.response.headers)

    def header(self, name: str) -> Optional[str]:
        return self.headers().get(name)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "_legado_type": "StrResponse",
            "url": self.response.url,
            "bodyText": "" if self.response.body is None else str(self.response.body),
            "statusCode": int(self.response.status_code),
            "headersMap": {str(k): str(v) for k, v in (self.response.headers or {}).items()},
        }


def normalize_response_result(value: Any, fallback: StrResponse) -> StrResponse:
    if value is None:
        return fallback
    if isinstance(value, StrResponse):
        return value
    if isinstance(value, JsStrResponse):
        return value.response
    if isinstance(value, dict):
        if value.get("_legado_type") == "StrResponse":
            return StrResponse(
                url=str(value.get("url", fallback.url) or fallback.url),
                body=str(value.get("bodyText", fallback.body or "") or ""),
                status_code=int(value.get("statusCode", fallback.status_code) or fallback.status_code),
                headers={
                    str(k): str(v)
                    for k, v in (value.get("headersMap") or fallback.headers or {}).items()
                },
            )
        if {"url", "body"}.issubset(value.keys()):
            return StrResponse(
                url=str(value.get("url", fallback.url) or fallback.url),
                body="" if value.get("body") is None else str(value.get("body")),
                status_code=int(value.get("statusCode", value.get("status_code", fallback.status_code)) or fallback.status_code),
                headers={
                    str(k): str(v)
                    for k, v in (value.get("headers") or fallback.headers or {}).items()
                },
            )
    if hasattr(value, "body") and hasattr(value, "url"):
        return StrResponse(
            url=str(getattr(value, "url", fallback.url) or fallback.url),
            body="" if getattr(value, "body", None) is None else str(getattr(value, "body")),
            status_code=int(getattr(value, "status_code", getattr(value, "statusCode", fallback.status_code)) or fallback.status_code),
            headers={
                str(k): str(v)
                for k, v in (getattr(value, "headers", None) or fallback.headers or {}).items()
            },
        )
    return StrResponse(
        url=fallback.url,
        body=str(value),
        status_code=fallback.status_code,
        headers=dict(fallback.headers or {}),
    )


def run_login_check(analyze_url: Any, source: Any, response: StrResponse) -> StrResponse:
    check_js = getattr(source, "loginCheckJs", None)
    if not check_js or not str(check_js).strip():
        return response
    result = analyze_url.eval_js(str(check_js), result=JsStrResponse(response))
    return normalize_response_result(result, response)
