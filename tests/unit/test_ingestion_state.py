from pathlib import Path
from odf_validator.ingestion.state import IngestionState, hash_file


def test_hash_file_is_stable(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello")
    assert hash_file(p) == hash_file(p)
    assert len(hash_file(p)) == 64  # sha256 hex digest


def test_hash_changes_with_content(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("hello")
    h1 = hash_file(p)
    p.write_text("hello world")
    h2 = hash_file(p)
    assert h1 != h2


def test_fresh_state_reports_everything_changed(tmp_path):
    state = IngestionState.load(tmp_path / ".ingestion_state.json")
    assert state.is_changed("a.pdf", "deadbeef") is True


def test_update_then_unchanged_until_hash_differs(tmp_path):
    state_path = tmp_path / ".ingestion_state.json"
    state = IngestionState.load(state_path)
    state.update("a.pdf", "deadbeef")
    assert state.is_changed("a.pdf", "deadbeef") is False
    assert state.is_changed("a.pdf", "somethingelse") is True


def test_state_persists_across_load_save(tmp_path):
    state_path = tmp_path / ".ingestion_state.json"
    state = IngestionState.load(state_path)
    state.update("a.pdf", "deadbeef")
    state.save()

    reloaded = IngestionState.load(state_path)
    assert reloaded.is_changed("a.pdf", "deadbeef") is False


def test_corrupt_state_file_degrades_to_empty_state(tmp_path):
    state_path = tmp_path / ".ingestion_state.json"
    state_path.write_text("{not valid json", encoding="utf-8")
    state = IngestionState.load(state_path)
    assert state.is_changed("a.pdf", "deadbeef") is True


def test_save_creates_missing_parent_directories(tmp_path):
    state_path = tmp_path / "nested" / "dir" / ".ingestion_state.json"
    state = IngestionState.load(state_path)
    state.update("a.pdf", "deadbeef")
    state.save()
    assert state_path.exists()
