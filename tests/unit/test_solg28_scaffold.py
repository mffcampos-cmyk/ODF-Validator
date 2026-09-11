from pathlib import Path
from odf_validator.ingestion.builder import build_ruleset_pack

RULES_DIR = Path("Rules/SOLG28")


def test_solg28_scaffold_is_a_clean_empty_pack():
    # Files must exist before build_ruleset_pack is even worth calling —
    # an absent directory would "load" just as cleanly (rglob on a missing
    # path silently yields nothing), so asserting file presence directly
    # is what actually gates this test on the scaffold existing.
    assert (RULES_DIR / "pack.yaml").exists()
    readme = (RULES_DIR / "_reference" / "README.md").read_text(encoding="utf-8")
    assert "docs/adding-a-ruleset.md" in readme
    assert "docs/adding-a-discipline.md" in readme
    assert "Disciplines/" in readme

    pack = build_ruleset_pack(RULES_DIR)
    assert pack.name == "SOLG28"
    assert pack.version == ""
    assert pack.disciplines == []
    assert pack.rules == []
    assert pack.schema is None
    assert pack.report.errors == []
    assert pack.report.conflicts == []
