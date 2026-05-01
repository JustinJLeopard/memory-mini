from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from memory_mini import EntryStatus, Store
from memory_mini.cli import main
from memory_mini.embeddings import cosine_similarity, pack_vector, require_numpy, unpack_vector
from memory_mini.lifecycle import cleanup_cutoff, from_iso, to_iso
from memory_mini.namespace import (
    namespace_children,
    namespace_parent,
    namespace_parts,
    normalize_namespace,
)
from memory_mini.search import filter_prefix, filter_regex, visible_statuses


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "memory.db"


@pytest.fixture
def store(db_path: Path) -> Store:
    with Store(db_path) as memory:
        yield memory


def test_store_new_key(store: Store) -> None:
    entry = store.store("alpha", "one")
    assert entry.key == "alpha"
    assert entry.value == "one"
    assert entry.status is EntryStatus.ACTIVE


def test_upsert_overwrites(store: Store) -> None:
    store.store("alpha", "one")
    store.store("alpha", "two")
    assert store.get("alpha").value == "two"  # type: ignore[union-attr]


def test_no_upsert_duplicate_raises(store: Store) -> None:
    store.store("alpha", "one")
    with pytest.raises(sqlite3.IntegrityError):
        store.store("alpha", "two", upsert=False)


def test_get_missing_returns_none(store: Store) -> None:
    assert store.get("missing") is None


def test_list_with_namespace_filter(store: Store) -> None:
    store.store("a", "one", "project/a")
    store.store("b", "two", "project/b")
    assert [entry.key for entry in store.list("project/a")] == ["a"]


def test_namespace_isolation_get(store: Store) -> None:
    store.store("same", "one", "a")
    store.store("same", "two", "b")
    assert store.get("same", "a").value == "one"  # type: ignore[union-attr]
    assert store.get("same", "b").value == "two"  # type: ignore[union-attr]


def test_namespace_isolation_unique_key(store: Store) -> None:
    store.store("same", "one", "a")
    store.store("same", "two", "b")
    assert len(store.list()) == 2


def test_soft_delete_preserves_entry(store: Store) -> None:
    store.store("alpha", "one")
    assert store.soft_delete("alpha")
    assert store.get("alpha") is None
    assert store.get("alpha", include_deleted=True).status is EntryStatus.SOFT_DELETED  # type: ignore[union-attr]


def test_soft_delete_missing_false(store: Store) -> None:
    assert store.soft_delete("missing") is False


def test_upsert_reactivates_soft_deleted(store: Store) -> None:
    store.store("alpha", "one")
    store.soft_delete("alpha")
    store.store("alpha", "two")
    assert store.get("alpha").value == "two"  # type: ignore[union-attr]


def test_cleanup_removes_soft_deleted_past_threshold(store: Store) -> None:
    store.store("alpha", "one")
    store.soft_delete("alpha")
    store.conn.execute("UPDATE entries SET updated_at = '2000-01-01T00:00:00+00:00'")
    store.conn.commit()
    assert store.cleanup(retention=timedelta(days=1)) == 1
    assert store.get("alpha", include_deleted=True) is None


def test_cleanup_does_not_remove_recent_soft_deleted(store: Store) -> None:
    store.store("alpha", "one")
    store.soft_delete("alpha")
    assert store.cleanup(retention=timedelta(days=30)) == 0


def test_cleanup_all_deleted_removes_recent(store: Store) -> None:
    store.store("alpha", "one")
    store.soft_delete("alpha")
    assert store.cleanup(all_deleted=True) == 1


def test_cleanup_does_not_touch_active(store: Store) -> None:
    store.store("alpha", "one")
    assert store.cleanup(all_deleted=True) == 0
    assert store.get("alpha") is not None


def test_regex_search_key(store: Store) -> None:
    store.store("release-2026", "done")
    assert [entry.key for entry in store.search(r"release-\d+", mode="regex")] == ["release-2026"]


def test_regex_search_value(store: Store) -> None:
    store.store("alpha", "release complete")
    assert [entry.key for entry in store.search("complete", mode="regex")] == ["alpha"]


def test_regex_search_hides_deleted(store: Store) -> None:
    store.store("alpha", "release complete")
    store.soft_delete("alpha")
    assert store.search("complete", mode="regex") == []


def test_prefix_search(store: Store) -> None:
    store.store("session-a", "one")
    store.store("note-a", "two")
    assert [entry.key for entry in store.search("session", mode="prefix")] == ["session-a"]


def test_prefix_search_limit(store: Store) -> None:
    for idx in range(3):
        store.store(f"session-{idx}", "one")
    assert len(store.search("session", mode="prefix", limit=2)) == 2


def test_fts_search_content(store: Store) -> None:
    store.store("alpha", "durable memory release")
    assert [entry.key for entry in store.search("durable", mode="fts")] == ["alpha"]


def test_fts_search_namespace_filter(store: Store) -> None:
    store.store("alpha", "durable memory", "a")
    store.store("beta", "durable memory", "b")
    assert [entry.key for entry in store.search("durable", "b", mode="fts")] == ["beta"]


def test_fts_search_hides_deleted(store: Store) -> None:
    store.store("alpha", "durable memory")
    store.soft_delete("alpha")
    assert store.search("durable", mode="fts") == []


def test_unknown_search_mode_raises(store: Store) -> None:
    with pytest.raises(ValueError):
        store.search("x", mode="nope")


def test_expires_at_honored(store: Store) -> None:
    store.store("old", "value", expires_at=datetime(2000, 1, 1, tzinfo=UTC))
    assert store.get("old") is None
    assert store.get("old", include_deleted=True).status is EntryStatus.EXPIRED  # type: ignore[union-attr]


def test_future_expires_at_visible(store: Store) -> None:
    store.store("new", "value", expires_at=datetime.now(UTC) + timedelta(days=1))
    assert store.get("new") is not None


def test_metadata_round_trip(store: Store) -> None:
    entry = store.store("alpha", "one", metadata={"kind": "test"})
    assert entry.metadata == {"kind": "test"}


def test_last_accessed_updates(store: Store) -> None:
    store.store("alpha", "one")
    assert store.get("alpha").last_accessed_at is not None  # type: ignore[union-attr]


def test_stats_empty(store: Store) -> None:
    assert store.stats()["total"] == 0


def test_stats_counts_statuses(store: Store) -> None:
    store.store("a", "one")
    store.store("b", "two")
    store.soft_delete("b")
    stats = store.stats()
    assert stats["active"] == 1
    assert stats["soft-deleted"] == 1
    assert stats["total"] == 2


def test_namespaces(store: Store) -> None:
    store.store("a", "one", "project/a")
    store.store("b", "two", "project/b")
    assert store.namespaces() == ["project/a", "project/b"]


def test_context_manager_closes(db_path: Path) -> None:
    with Store(db_path) as memory:
        memory.store("a", "one")
    with pytest.raises(sqlite3.ProgrammingError):
        memory.conn.execute("SELECT 1")


def test_persistent_sqlite_file(db_path: Path) -> None:
    with Store(db_path) as memory:
        memory.store("a", "one")
    with Store(db_path) as memory:
        assert memory.get("a").value == "one"  # type: ignore[union-attr]


def test_default_namespace(db_path: Path) -> None:
    with Store(db_path, default_namespace="custom") as memory:
        memory.store("a", "one")
        assert memory.get("a", "custom") is not None


def test_normalize_namespace_default() -> None:
    assert normalize_namespace(None) == "default"
    assert normalize_namespace(" /project/topic/ ") == "project/topic"


def test_namespace_parts() -> None:
    assert namespace_parts("project/topic") == ("project", "topic")


def test_namespace_parent() -> None:
    assert namespace_parent("project/topic/deep") == "project/topic"
    assert namespace_parent("project") is None


def test_namespace_children() -> None:
    assert namespace_children("project", ["project/a", "project/b", "other/a"]) == [
        "project/a",
        "project/b",
    ]


def test_filter_prefix_helper(store: Store) -> None:
    entries = [store.store("alpha", "one"), store.store("beta", "two")]
    assert [entry.key for entry in filter_prefix(entries, "a")] == ["alpha"]


def test_filter_regex_helper(store: Store) -> None:
    entries = [store.store("alpha", "one"), store.store("beta", "two")]
    assert [entry.key for entry in filter_regex(entries, "tw")] == ["beta"]


def test_iso_helpers() -> None:
    now = datetime(2026, 5, 1, tzinfo=UTC)
    assert from_iso(to_iso(now)) == now


def test_to_iso_accepts_string_and_none() -> None:
    assert to_iso("2026-05-01T00:00:00+00:00") == "2026-05-01T00:00:00+00:00"
    assert to_iso(None) is None


def test_cleanup_cutoff_none() -> None:
    assert cleanup_cutoff(None) is None


def test_visible_statuses() -> None:
    assert visible_statuses(False) == (EntryStatus.ACTIVE,)
    assert EntryStatus.SOFT_DELETED in visible_statuses(True)


def test_pack_unpack_vector() -> None:
    blob, dims = pack_vector([1.0, 2.0])
    assert dims == 2
    assert unpack_vector(blob, dims) == [1.0, 2.0]


def test_cosine_similarity() -> None:
    assert cosine_similarity([1, 0], [1, 0]) == pytest.approx(1.0)


def test_cosine_similarity_zero_vector() -> None:
    assert cosine_similarity([0, 0], [1, 0]) == 0.0


def test_cosine_similarity_dimension_mismatch() -> None:
    with pytest.raises(ValueError):
        cosine_similarity([1], [1, 2])


def test_embedding_round_trip(store: Store) -> None:
    entry = store.store("alpha", "one", embedding=[1.0, 0.0], embedding_model="unit")
    assert entry.embedding_model == "unit"
    assert entry.embedding_dims == 2


def test_embed_and_store(store: Store) -> None:
    entry = store.embed_and_store("alpha", "abc", lambda text: [float(len(text))])
    assert entry.embedding_dims == 1


def test_vector_search_returns_nearest_k(store: Store) -> None:
    try:
        require_numpy()
    except ImportError:
        pytest.skip("numpy not installed")
    store.store("near", "one", embedding=[1.0, 0.0])
    store.store("far", "two", embedding=[0.0, 1.0])
    results = store.vector_search([1.0, 0.0], k=1)
    assert results[0][0].key == "near"


def test_embed_and_search(store: Store) -> None:
    try:
        require_numpy()
    except ImportError:
        pytest.skip("numpy not installed")
    store.embed_and_store("short", "aa", lambda text: [float(len(text)), 0.0])
    store.embed_and_store("long", "aaaaaa", lambda text: [float(len(text)), 0.0])
    assert store.embed_and_search("a", lambda text: [float(len(text)), 0.0], k=1)[0][0].key


def test_vector_search_dimension_mismatch_skips(store: Store) -> None:
    try:
        require_numpy()
    except ImportError:
        pytest.skip("numpy not installed")
    store.store("alpha", "one", embedding=[1.0, 0.0])
    assert store.vector_search([1.0, 0.0, 0.0]) == []


def test_vector_search_requires_numpy_when_missing(store: Store) -> None:
    try:
        require_numpy()
    except ImportError:
        with pytest.raises(ImportError, match="memory-mini\\[embed\\]"):
            store.vector_search([1.0])
    else:
        pytest.skip("numpy installed")


def test_list_include_deleted(store: Store) -> None:
    store.store("alpha", "one")
    store.soft_delete("alpha")
    assert len(store.list(include_deleted=True)) == 1


def test_search_include_deleted(store: Store) -> None:
    store.store("alpha", "one")
    store.soft_delete("alpha")
    assert len(store.search("alpha", include_deleted=True)) == 1


def test_get_include_deleted_after_soft_delete(store: Store) -> None:
    store.store("alpha", "one")
    store.soft_delete("alpha")
    entry = store.get("alpha", include_deleted=True)
    assert entry is not None and entry.value == "one"


def test_cli_store_get_smoke(db_path: Path) -> None:
    run_cli(db_path, "store", "alpha", "one")
    result = run_cli(db_path, "get", "alpha")
    assert result.stdout.strip() == "one"


def test_cli_list_smoke(db_path: Path) -> None:
    run_cli(db_path, "store", "alpha", "one", "--namespace", "project")
    result = run_cli(db_path, "list", "--namespace", "project")
    assert "project\talpha" in result.stdout


def test_cli_search_smoke(db_path: Path) -> None:
    run_cli(db_path, "store", "session-alpha", "one")
    result = run_cli(db_path, "search", "session")
    assert "session-alpha" in result.stdout


def test_cli_soft_delete_smoke(db_path: Path) -> None:
    run_cli(db_path, "store", "alpha", "one")
    result = run_cli(db_path, "soft-delete", "alpha")
    assert result.stdout.strip() == "deleted"


def test_cli_cleanup_smoke(db_path: Path) -> None:
    run_cli(db_path, "store", "alpha", "one")
    run_cli(db_path, "soft-delete", "alpha")
    result = run_cli(db_path, "cleanup", "--all-deleted")
    assert result.stdout.strip() == "1"


def test_cli_stats_smoke(db_path: Path) -> None:
    run_cli(db_path, "store", "alpha", "one")
    result = run_cli(db_path, "stats")
    assert json.loads(result.stdout)["total"] == 1


def test_cli_main_store_get(db_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--db", str(db_path), "store", "alpha", "one"]) == 0
    assert "alpha" in capsys.readouterr().out
    assert main(["--db", str(db_path), "get", "alpha"]) == 0
    assert capsys.readouterr().out.strip() == "one"


def test_cli_main_get_missing(db_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--db", str(db_path), "get", "missing"]) == 0
    assert capsys.readouterr().out == "\n"


def test_cli_main_list_search_stats(db_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--db", str(db_path), "store", "session-alpha", "release", "--namespace", "sessions"])
    capsys.readouterr()
    assert main(["--db", str(db_path), "list", "--namespace", "sessions"]) == 0
    assert "session-alpha" in capsys.readouterr().out
    assert main(["--db", str(db_path), "search", "release", "--mode", "fts"]) == 0
    assert "session-alpha" in capsys.readouterr().out
    assert main(["--db", str(db_path), "stats"]) == 0
    assert json.loads(capsys.readouterr().out)["total"] == 1


def test_cli_main_soft_delete_cleanup(db_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--db", str(db_path), "store", "alpha", "one"])
    capsys.readouterr()
    assert main(["--db", str(db_path), "soft-delete", "alpha"]) == 0
    assert capsys.readouterr().out.strip() == "deleted"
    assert main(["--db", str(db_path), "cleanup", "--all-deleted"]) == 0
    assert capsys.readouterr().out.strip() == "1"


def test_cli_no_upsert_fails(db_path: Path) -> None:
    run_cli(db_path, "store", "alpha", "one", "--no-upsert")
    result = run_cli(db_path, "store", "alpha", "two", "--no-upsert", check=False)
    assert result.returncode != 0


def test_store_metadata_json_is_sorted(store: Store) -> None:
    store.store("alpha", "one", metadata={"b": 1, "a": 2})
    row = store.conn.execute("SELECT metadata FROM entries").fetchone()
    assert row["metadata"] == '{"a": 2, "b": 1}'


def run_cli(db_path: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    src_path = str(Path(__file__).resolve().parents[1] / "src")
    env["PYTHONPATH"] = src_path + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "memory_mini.cli", "--db", str(db_path), *args],
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )
    if check and result.returncode != 0:
        raise AssertionError(result.stderr)
    return result
