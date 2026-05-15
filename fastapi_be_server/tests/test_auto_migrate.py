from pathlib import Path


def test_parse_statements_keeps_semicolon_inside_sql_string_literal():
    from app.utils.auto_migrate import _parse_statements

    statements = _parse_statements(
        """
        CREATE TABLE sample (
            id INT PRIMARY KEY,
            note VARCHAR(100) COMMENT 'queued/running; terminal state'
        );
        SELECT 'also; literal';
        """
    )

    assert len(statements) == 2
    assert "queued/running; terminal state" in statements[0]
    assert "also; literal" in statements[1]


def test_ai_reader_phase1_migration_parses_all_create_table_statements():
    from app.utils.auto_migrate import _parse_statements

    migration_path = (
        Path(__file__).resolve().parents[1]
        / "dist"
        / "init"
        / "87-create-ai-reader-agent-phase1-tables.sql"
    )

    statements = _parse_statements(migration_path.read_text(encoding="utf-8"))

    assert len(statements) == 6
    assert all(statement.startswith("CREATE TABLE IF NOT EXISTS") for statement in statements)
