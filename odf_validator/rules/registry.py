from __future__ import annotations
from typing import Callable

PYTHON_RULES: dict[str, Callable] = {}


def python_rule(key: str):
    """Register a Python-coded rule under '<pack>:<fn>'. Python rules are an
    engine change and get core review; the pack prefix prevents cross-pack
    collisions. fn(root, rule, registry, ctx) -> list[Finding]."""
    if ":" not in key:
        raise ValueError(f"python_rule key must be '<pack>:<fn>', got '{key}'")
    def deco(fn: Callable) -> Callable:
        PYTHON_RULES[key] = fn
        return fn
    return deco
