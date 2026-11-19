from pathlib import Path

import pytest

from data_layer_path import resolve_data_layer_dir


def make_data_layer(root: Path) -> Path:
    data_layer = root / "finbuddy.ui" / "finbuddy"
    db_dir = data_layer / "db"
    db_dir.mkdir(parents=True)
    (db_dir / "__init__.py").write_text("", encoding="utf-8")
    (db_dir / "database.py").write_text("", encoding="utf-8")
    return data_layer


def test_resolves_sibling_ui_layout(tmp_path: Path) -> None:
    backend_dir = tmp_path / "beckend 3"
    backend_dir.mkdir()
    expected = make_data_layer(tmp_path)

    assert resolve_data_layer_dir(backend_dir / "main.py", {}) == expected.resolve()


def test_resolves_nested_ui_layout(tmp_path: Path) -> None:
    backend_dir = tmp_path / "beckend 3"
    backend_dir.mkdir()
    expected = make_data_layer(tmp_path / "fin-buddy-main")

    assert resolve_data_layer_dir(backend_dir / "main.py", {}) == expected.resolve()


def test_explicit_override_is_used_and_validated(tmp_path: Path) -> None:
    backend_dir = tmp_path / "beckend 3"
    backend_dir.mkdir()
    override = tmp_path / "custom-data-layer"
    override.mkdir()
    (override / "db").mkdir()
    (override / "db" / "__init__.py").write_text("", encoding="utf-8")
    (override / "db" / "database.py").write_text("", encoding="utf-8")

    assert resolve_data_layer_dir(
        backend_dir / "main.py", {"FINBUDDY_DATA_LAYER_DIR": str(override)}
    ) == override.resolve()

    with pytest.raises(FileNotFoundError, match="FINBUDDY_DATA_LAYER_DIR"):
        resolve_data_layer_dir(
            backend_dir / "main.py",
            {"FINBUDDY_DATA_LAYER_DIR": str(tmp_path / "missing")},
        )


def test_missing_data_layer_has_actionable_error(tmp_path: Path) -> None:
    backend_dir = tmp_path / "beckend 3"
    backend_dir.mkdir()

    with pytest.raises(FileNotFoundError, match="Set FINBUDDY_DATA_LAYER_DIR"):
        resolve_data_layer_dir(backend_dir / "main.py", {})


def test_health_reports_missing_database_without_creating_it(
    tmp_path: Path, monkeypatch
) -> None:
    from fastapi.testclient import TestClient

    import main

    missing_db = tmp_path / "disposable" / "missing.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", missing_db)

    response = TestClient(main.app).get("/health")

    assert response.status_code == 503
    assert response.json()["code"] == "database_unavailable"
    assert "FINBUDDY_DB" in response.json()["error"]
    assert not missing_db.exists()
