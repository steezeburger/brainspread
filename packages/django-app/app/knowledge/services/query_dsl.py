"""Inline query DSL → query-engine JSON (issue #143).

Automations reference queries either as a named view (``view:<slug>``) or
as an inline boolean expression. This module compiles the inline surface
1:1 onto the JSON the query engine (issue #60) already runs — the engine
itself is untouched, so inline queries and SavedViews share exactly one
execution path.

Grammar (precedence: ``not`` > ``and`` > ``or``; parens group):

    expr    := or
    or      := and ("or" and)*
    and     := atom ("and" atom)*
    atom    := "not" atom | "(" expr ")" | predicate

Predicates (compact ``field:value`` or comparison ``field op value``):

    tag:sticky              → {"has_tag": "sticky"}
    type:doing              → {"block_type": "doing"}
    type:todo,doing         → {"block_type": {"in": [...]}}
    page_type:template      → {"page_type": "template"}
    has:project             → {"has_property": "project"}
    content:"foo bar"       → {"content_contains": "foo bar"}
    due < today             → {"due_at": {"lt": "today"}}
    due:today               → {"due_at": "today"}
    due is null             → {"due_at": {"is_null": true}}
    completed >= "7 days ago" → {"completed_at": {"gte": "7 days ago"}}
    prop:key=value          → {"property_eq": {"key": ..., "eq": ...}}

``scheduled`` is accepted as an alias for ``due`` (matching the engine's
own back-compat predicate alias). NOTE: use ``tag:x``, never ``#x`` — a
literal hashtag in block content would tag the automation block itself.

Values with spaces are double-quoted. Date values take the engine's own
tokens (today / tomorrow / N days ago / ISO) — resolution happens at
query compile time in the engine, not here.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class QueryDSLError(ValueError):
    """Raised when an inline query expression can't be parsed. The message
    is user-facing (recorded on the failed AutomationRun)."""


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(
    r"""
    \s*(
        \(              |   # lparen
        \)              |   # rparen
        <=|>=|=|<|>     |   # comparison ops (standalone; `=` needs spaces)
        "[^"]*"         |   # quoted value
        [A-Za-z0-9_:,=\-]+  # bare word (field:value, prop:key=value, dates)
    )
    """,
    re.VERBOSE,
)


def _tokenize(text: str) -> List[str]:
    tokens: List[str] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise QueryDSLError(f"unexpected character at: `{text[pos:pos + 20]}`")
        tokens.append(m.group(1))
        pos = m.end()
    return tokens


# ---------------------------------------------------------------------------
# Parser (recursive descent; not > and > or)
# ---------------------------------------------------------------------------


class _Parser:
    def __init__(self, tokens: List[str], raw: str) -> None:
        self.tokens = tokens
        self.raw = raw
        self.pos = 0

    def peek(self) -> Optional[str]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self) -> str:
        token = self.peek()
        if token is None:
            raise QueryDSLError(f"unexpected end of query: `{self.raw}`")
        self.pos += 1
        return token

    def parse(self) -> Dict[str, Any]:
        node = self._or()
        if self.peek() is not None:
            raise QueryDSLError(f"unexpected trailing input at `{self.peek()}`")
        return node

    def _or(self) -> Dict[str, Any]:
        children = [self._and()]
        while self.peek() is not None and self.peek().lower() == "or":
            self.next()
            children.append(self._and())
        return children[0] if len(children) == 1 else {"any": children}

    def _and(self) -> Dict[str, Any]:
        children = [self._atom()]
        while self.peek() is not None and self.peek().lower() == "and":
            self.next()
            children.append(self._atom())
        return children[0] if len(children) == 1 else {"all": children}

    def _atom(self) -> Dict[str, Any]:
        token = self.peek()
        if token is None:
            raise QueryDSLError(f"unexpected end of query: `{self.raw}`")
        if token.lower() == "not":
            self.next()
            return {"not": self._atom()}
        if token == "(":
            self.next()
            node = self._or()
            if self.peek() != ")":
                raise QueryDSLError("missing closing `)`")
            self.next()
            return node
        return self._predicate()

    # -- predicates ---------------------------------------------------------

    def _predicate(self) -> Dict[str, Any]:
        token = self.next()
        if ":" in token:
            field, _, value = token.partition(":")
            if not value and self.peek() is not None and _is_value(self.peek()):
                # `content:` followed by a quoted token ("foo bar").
                value = self.next()
            return _compile_colon_predicate(field.lower(), _unquote(value), token)

        field = token.lower()
        op_token = self.peek()
        if op_token in ("<", "<=", ">", ">=", "="):
            self.next()
            value = _unquote(self.next())
            return _compile_comparison(field, op_token, value)
        if op_token is not None and op_token.lower() == "is":
            self.next()
            tail = self.next().lower()
            negated = False
            if tail == "not":
                negated = True
                tail = self.next().lower()
            if tail != "null":
                raise QueryDSLError(f"expected `null` after `{field} is`")
            return _compile_is_null(field, not negated)

        raise QueryDSLError(
            f"can't parse `{token}` — expected `field:value`, a comparison, "
            "or `field is null`"
        )


def _is_value(token: str) -> bool:
    return token not in ("(", ")") and token.lower() not in ("and", "or", "not")


def _unquote(value: str) -> str:
    if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


# Fields usable in comparisons / is-null, mapped to engine predicates.
_DATE_FIELDS = {
    "due": "due_at",
    "due_at": "due_at",
    "scheduled": "due_at",
    "scheduled_for": "due_at",
    "completed": "completed_at",
    "completed_at": "completed_at",
}

_COMPARISON_OPS = {"<": "lt", "<=": "lte", ">": "gt", ">=": "gte", "=": "eq"}


def _date_field(field: str) -> str:
    mapped = _DATE_FIELDS.get(field)
    if mapped is None:
        raise QueryDSLError(
            f"unknown field `{field}` (expected one of: "
            f"{', '.join(sorted(set(_DATE_FIELDS)))})"
        )
    return mapped


def _compile_comparison(field: str, op: str, value: str) -> Dict[str, Any]:
    if not value:
        raise QueryDSLError(f"`{field} {op}` needs a value")
    return {_date_field(field): {_COMPARISON_OPS[op]: value}}


def _compile_is_null(field: str, is_null: bool) -> Dict[str, Any]:
    return {_date_field(field): {"is_null": is_null}}


def _compile_colon_predicate(field: str, value: str, raw: str) -> Dict[str, Any]:
    if not value:
        raise QueryDSLError(f"`{raw}` needs a value, e.g. `{field}:<value>`")

    if field == "tag":
        return {"has_tag": value}
    if field == "type":
        parts = [p for p in value.split(",") if p]
        return (
            {"block_type": parts[0]}
            if len(parts) == 1
            else {"block_type": {"in": parts}}
        )
    if field == "page_type":
        parts = [p for p in value.split(",") if p]
        return (
            {"page_type": parts[0]} if len(parts) == 1 else {"page_type": {"in": parts}}
        )
    if field == "has":
        return {"has_property": value}
    if field == "content":
        return {"content_contains": value}
    if field == "prop":
        key, sep, prop_value = value.partition("=")
        if not sep or not key or not prop_value:
            raise QueryDSLError("`prop:` expects `prop:key=value`")
        return {"property_eq": {"key": key, "eq": prop_value}}
    if field in _DATE_FIELDS:
        return {_date_field(field): value}

    raise QueryDSLError(
        f"unknown predicate `{field}:` (expected tag / type / page_type / "
        "has / content / prop / due / completed)"
    )


# Anything that marks a string as an actual DSL expression. A query with
# none of these is plain text and compiles to a content search — so
# `run_query("meeting with bob")` behaves like the old search_notes
# instead of failing to parse.
_DSL_SYNTAX_RE = re.compile(r"[:<>=()\"]|\b(?:and|or|not|is)\b", re.IGNORECASE)


def compile_inline_query(text: str) -> Dict[str, Any]:
    """Compile an inline query expression into a query-engine filter dict.
    Bare text with no DSL syntax compiles to ``content_contains``.
    Raises ``QueryDSLError`` on malformed input."""
    text = (text or "").strip()
    if not text:
        raise QueryDSLError("empty query expression")
    if "#" in text:
        raise QueryDSLError(
            "use `tag:<slug>` instead of `#<slug>` in queries — a literal "
            "hashtag would tag the automation block itself"
        )
    if not _DSL_SYNTAX_RE.search(text):
        return {"content_contains": text}
    return _Parser(_tokenize(text), text).parse()
