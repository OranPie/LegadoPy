from __future__ import annotations
"""
source_rule – SourceRule, Mode, and pattern constants extracted from AnalyzeRule.

These are the building blocks used by AnalyzeRule to parse rule strings.
"""

import re
from enum import Enum, auto
from typing import Any, Dict, List


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
        self.put_map: dict[str, str] = {}

        self._rule_param: list[str] = []
        self._rule_type: list[int] = []

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

    def _split_put_rule(self, rule_str: str, put_map: dict[str, str]) -> str:
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
        get_fn: Any,
        eval_js_fn: Any,
        get_string_fn: Any,
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

        parts: list[str] = []
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
