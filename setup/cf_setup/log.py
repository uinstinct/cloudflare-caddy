"""Tiny, dependency-free verbose logger.

Everything goes to stderr so it shows up in `docker compose logs` and never
mixes with data a caller might capture on stdout. Colours are used only when
stderr is an interactive terminal (so CI logs stay clean plain text).
"""

from __future__ import annotations

import sys

_USE_COLOR = sys.stderr.isatty()


def _c(code: str, text: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def _emit(code: str, prefix: str, msg: str) -> None:
    print(_c(code, f"{prefix} {msg}"), file=sys.stderr, flush=True)


def banner(msg: str) -> None:
    _emit("1;36", "\n===", f"{msg} ===")


def step(msg: str) -> None:
    _emit("36", "[*]", msg)


def ok(msg: str) -> None:
    _emit("32", "[ok]", msg)


def action(msg: str) -> None:
    _emit("33", "[>>]", msg)


def skip(msg: str) -> None:
    _emit("90", "[skip]", msg)


def warn(msg: str) -> None:
    _emit("33", "[warn]", msg)


def error(msg: str) -> None:
    _emit("31", "[error]", msg)
