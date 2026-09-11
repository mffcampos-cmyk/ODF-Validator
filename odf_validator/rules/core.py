from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from .loader import load_rule_defs
from .defs_model import RuleDef

CORE_RULES_DIR = Path(__file__).resolve().parent.parent / "core_rules"
CORE_PREFIX = "CORE_"


@lru_cache(maxsize=1)
def _load() -> tuple[RuleDef, ...]:
    paths = sorted(CORE_RULES_DIR.glob("*.yaml"))
    (rules, errors, conflicts, deduped,
     specialised) = load_rule_defs(paths, allow_core=True)
    # Core rules are hand-curated and few: a redundant duplicate among them
    # is a packaging mistake, so deduped counts as a problem here even though
    # it is routine for pack rules. Core rules are game- and discipline-
    # agnostic by definition, so a specialisation among them is equally a bug.
    problems = errors + conflicts + deduped + specialised
    if problems:
        raise RuntimeError("Bundled core rules failed to load: " + "; ".join(problems))
    bad = [r.id for r in rules if not r.id.startswith(CORE_PREFIX)]
    if bad:
        raise RuntimeError(f"Core rules without CORE_ prefix: {bad}")
    return tuple(rules)


def load_core_rules() -> list[RuleDef]:
    """Engine-bundled, game-agnostic rules. Applied to every pack, before
    pack rules. Cached; raises RuntimeError on any load problem because a
    broken core is a packaging bug, not a runtime condition."""
    return list(_load())
