"""Deterministic multilingual lexical similarity for the v1 baseline."""

from __future__ import annotations

import re

_LATIN = re.compile(r"[a-zA-Z0-9_./+-]{2,}")
_CJK = re.compile(r"[\u3400-\u9fff]+")


def tokens(text: str) -> set[str]:
    lowered = text.lower()
    result = {match.group(0) for match in _LATIN.finditer(lowered)}
    for match in _CJK.finditer(lowered):
        value = match.group(0)
        result.update(value)
        result.update(value[index:index + 2] for index in range(len(value) - 1))
    return result


def similarity(left: str, right: str) -> float:
    a, b = tokens(left), tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def choices_agree(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    if left.strip().casefold() == right.strip().casefold():
        return True
    return similarity(left, right) >= 0.6
