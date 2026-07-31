"""Shared command redaction and secret-exposure detection.

One implementation used by every producer/wrapper, builder, publisher, and
verifier that touches a subprocess command line or a stored
``sanitised_command`` receipt field, so credential handling can't drift
between call sites (WP5).

Two functions:

- ``sanitise_command()``: redact a raw argv sequence into a safe string
  suitable for storage in an ``ExecutionReceipt.sanitised_command`` field.
- ``contains_exposed_secret()``: detect whether an already-stored command
  string still contains an exposed credential value (used as a defensive
  second check in schema validation, independent of whether the value was
  supposed to have been redacted upstream).

Supported forms: ``--name=value``, ``--name value``, ``NAME=value``
environment assignments, and ``Authorization: Bearer <value>`` headers
(as one token or split across multiple argv tokens).
"""

from __future__ import annotations

import re
from typing import Sequence

REDACTED_MARKER = "***REDACTED***"

# A flag/env-var *name* is treated as holding a secret value if it ends in
# one of these words (after stripping leading dashes) — e.g. "--token",
# "--hf-token", "HF_TOKEN", "--api-key", "--secret", "--password",
# "--authorization". Compound names like "--token-state" or
# "--token-present-run" do NOT end in one of these words, so their
# (non-secret) values are left untouched.
_SENSITIVE_NAME_RE = re.compile(
    r"(?:^|[_-])(token|password|secret|api[_-]?key|apikey|authorization)$",
    re.IGNORECASE,
)

_INLINE_ASSIGNMENT_RE = re.compile(r"^(--?[A-Za-z0-9][A-Za-z0-9_-]*|[A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_BEARER_INLINE_RE = re.compile(r"^(authorization:\s*bearer\s+)(\S+)$", re.IGNORECASE)


def _name_is_sensitive(name: str) -> bool:
    return bool(_SENSITIVE_NAME_RE.search(name.lstrip("-")))


def sanitise_command(command: Sequence[str]) -> str:
    """Redact credential-bearing values out of a raw argv sequence.

    Returns a single space-joined string safe to store as
    ``ExecutionReceipt.sanitised_command``. Never leaves an ``HF_TOKEN``,
    password, secret, API key, or Authorization-header value in the output.
    """
    tokens = list(command)
    out: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]

        # "Authorization: Bearer <value>" as a single token.
        m = _BEARER_INLINE_RE.match(tok)
        if m:
            out.append(m.group(1) + REDACTED_MARKER)
            i += 1
            continue

        # "--name=value" or "NAME=value".
        m = _INLINE_ASSIGNMENT_RE.match(tok)
        if m and _name_is_sensitive(m.group(1)):
            out.append(f"{m.group(1)}={REDACTED_MARKER}")
            i += 1
            continue

        # "--name value" (two tokens).
        if tok.startswith("-") and _name_is_sensitive(tok) and i + 1 < n:
            out.append(tok)
            out.append(REDACTED_MARKER)
            i += 2
            continue

        # "Authorization:" "Bearer" "<value>" split across three tokens.
        if (
            tok.rstrip(":").lower() == "authorization"
            and i + 2 < n
            and tokens[i + 1].lower() == "bearer"
        ):
            out.append(tok)
            out.append(tokens[i + 1])
            out.append(REDACTED_MARKER)
            i += 3
            continue

        out.append(tok)
        i += 1

    return " ".join(out)


# Values that prove a specific match was already redacted — checked against
# the exact matched value/argument only, never against surrounding text, so
# a safe marker on one assignment can never exempt a *different* exposed
# value elsewhere in the same command (PR #26 review finding P1-1).
_SAFE_VALUE_RE = re.compile(r"^(\*\*\*redacted\*\*\*|\[redacted\]|<redacted>)$", re.IGNORECASE)

# A raw Hugging Face token literal is self-evidently a secret regardless of
# what flag (if any) precedes it in the command string.
_RAW_HF_TOKEN_RE = re.compile(r"\bhf_[A-Za-z0-9]{16,}\b")

_BEARER_RE = re.compile(r"authorization:\s*bearer\s+(\S+)", re.IGNORECASE)

# "--name=value" or "NAME=value" (contiguous, no surrounding whitespace).
_INLINE_NAME_VALUE_RE = re.compile(
    r"(?<![\w-])(--?[A-Za-z][A-Za-z0-9_-]*|[A-Za-z_][A-Za-z0-9_]*)=(\S*)"
)

# "--name value" (space-separated, not "--name=value"). Reuses
# _name_is_sensitive so compound flags like "--token-state" or
# "--token-present-run" are correctly left unflagged — the same rule
# sanitise_command() uses to decide what to redact.
_SPACE_SEPARATED_RE = re.compile(r"(--?[A-Za-z0-9][A-Za-z0-9_-]*)\s+(\S+)")


def _strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _is_safe_value(value: str) -> bool:
    return bool(_SAFE_VALUE_RE.match(_strip_matching_quotes(value)))


def contains_exposed_secret(text: str) -> str | None:
    """Return a description of the first exposed secret found, else ``None``.

    Exempts only the matched value or compound flag itself — never a
    surrounding window of text — so a safe marker elsewhere in the command
    (e.g. ``--token-state present`` appearing near an unredacted
    ``HF_TOKEN=...``) can never suppress a real, separate exposure.
    """
    if not text:
        return None

    if _RAW_HF_TOKEN_RE.search(text):
        return "raw Hugging Face token literal"

    for match in _BEARER_RE.finditer(text):
        if not _is_safe_value(match.group(1)):
            return "exposed Authorization header"

    for match in _INLINE_NAME_VALUE_RE.finditer(text):
        name, value = match.group(1), match.group(2)
        if not _name_is_sensitive(name):
            continue
        if not value or _is_safe_value(value):
            continue
        return f"exposed {name.lstrip('-')} value"

    for match in _SPACE_SEPARATED_RE.finditer(text):
        name, value = match.group(1), match.group(2)
        if not _name_is_sensitive(name):
            continue
        if _is_safe_value(value):
            continue
        return f"exposed {name.lstrip('-')} value"

    return None
