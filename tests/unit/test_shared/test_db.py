import os
from unittest.mock import MagicMock, patch

import pytest


def test_query_returns_rows():
    with patch("shared.db.psycopg2.connect") as mock_connect:
        conn = MagicMock()
        cursor = MagicMock()
        mock_connect.return_value = conn
        conn.cursor.return_value = cursor
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = [("user1",), ("user2",)]
        from shared.db import query

        result = query("SELECT developer_github FROM featured_developers")
    assert result == [("user1",), ("user2",)]


def test_query_passes_params():
    with patch("shared.db.psycopg2.connect") as mock_connect:
        conn = MagicMock()
        cursor = MagicMock()
        mock_connect.return_value = conn
        conn.cursor.return_value = cursor
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = []
        from shared.db import query

        query("SELECT * FROM episodes WHERE episode_id = %s", (1,))
    cursor.execute.assert_called_with("SELECT * FROM episodes WHERE episode_id = %s", (1,))


def test_query_empty_results():
    with patch("shared.db.psycopg2.connect") as mock_connect:
        conn = MagicMock()
        cursor = MagicMock()
        mock_connect.return_value = conn
        conn.cursor.return_value = cursor
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.fetchall.return_value = []
        from shared.db import query

        result = query("SELECT * FROM episodes WHERE 1=0")
    assert result == []


def test_execute_returns_rowcount():
    with patch("shared.db.psycopg2.connect") as mock_connect:
        conn = MagicMock()
        cursor = MagicMock()
        mock_connect.return_value = conn
        conn.cursor.return_value = cursor
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.rowcount = 3
        from shared.db import execute

        result = execute("UPDATE episodes SET language = 'Go' WHERE language = 'Golang'")
    assert result == 3


def test_execute_commits():
    with patch("shared.db.psycopg2.connect") as mock_connect:
        conn = MagicMock()
        cursor = MagicMock()
        mock_connect.return_value = conn
        conn.cursor.return_value = cursor
        cursor.__enter__ = lambda s: s
        cursor.__exit__ = MagicMock(return_value=False)
        cursor.rowcount = 1
        from shared.db import execute

        execute("INSERT INTO episodes (repo_name) VALUES ('test')")
    conn.commit.assert_called_once()


def test_connection_uses_env_var():
    with (
        patch("shared.db.psycopg2.connect") as mock_connect,
        patch.dict(os.environ, {"DB_CONNECTION_STRING": "postgresql://test:pw@host:5432/db"}),
    ):
        conn = MagicMock()
        mock_connect.return_value = conn
        conn.cursor.return_value = MagicMock()
        from shared.db import get_connection

        get_connection()
    assert "postgresql://test:pw@host:5432/db" in str(mock_connect.call_args)


def test_connection_uses_sslmode_require():
    with (
        patch("shared.db.psycopg2.connect") as mock_connect,
        patch.dict(os.environ, {"DB_CONNECTION_STRING": "postgresql://test@host/db"}),
    ):
        conn = MagicMock()
        mock_connect.return_value = conn
        from shared.db import get_connection

        get_connection()
    assert "sslmode" in str(mock_connect.call_args) or "require" in str(mock_connect.call_args)


def test_query_error_propagates():
    with patch("shared.db.psycopg2.connect") as mock_connect:
        mock_connect.side_effect = Exception("connection refused")
        from shared.db import query

        with pytest.raises(Exception, match="connection refused"):
            query("SELECT 1")
