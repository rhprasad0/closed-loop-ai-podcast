from __future__ import annotations

import asyncio
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# query_episodes
# ---------------------------------------------------------------------------


def test_query_episodes_excludes_large_fields():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.side_effect = [
            [(3,)],  # COUNT query
            [
                (
                    1,
                    date(2025, 7, 6),
                    "https://github.com/user/repo",
                    "repo",
                    "user",
                    "Test User",
                    5,
                    1,
                    "episodes/1/episode.mp3",
                    "episodes/1/episode.mp4",
                    "episodes/1/cover.png",
                    datetime(2025, 7, 6, 12, 0, 0),
                ),
            ],
        ]

        from lambdas.mcp.tools.data import query_episodes

        result = asyncio.run(query_episodes())

    # The SELECT query (second call) should not include large text fields
    select_sql = mock_query.call_args_list[1][0][0]
    assert "script_text" not in select_sql
    assert "research_json" not in select_sql
    assert "cover_art_prompt" not in select_sql
    assert len(result["episodes"]) == 1


def test_query_episodes_applies_filters():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.side_effect = [
            [(0,)],  # COUNT query
            [],      # SELECT query
        ]

        from lambdas.mcp.tools.data import query_episodes

        asyncio.run(
            query_episodes(
                developer_github="testuser",
                limit=5,
                offset=10,
                order_by="air_date",
                order="asc",
            )
        )

    # Check the SELECT query
    select_sql = mock_query.call_args_list[1][0][0]
    select_params = mock_query.call_args_list[1][0][1]
    assert "developer_github" in select_sql
    assert "testuser" in select_params
    assert "ORDER BY" in select_sql
    assert "air_date" in select_sql
    assert "asc" in select_sql
    assert "LIMIT" in select_sql
    assert "OFFSET" in select_sql


def test_query_episodes_filters_by_episode_id():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.side_effect = [
            [(1,)],  # COUNT
            [(1, date(2025, 7, 6), "url", "repo", "user", "Name", 5, 1, None, None, None, datetime(2025, 7, 6))],
        ]

        from lambdas.mcp.tools.data import query_episodes

        result = asyncio.run(query_episodes(episode_id=1))

    count_sql = mock_query.call_args_list[0][0][0]
    assert "episode_id = %s" in count_sql
    assert result["total_count"] == 1


def test_query_episodes_filters_by_language():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.side_effect = [
            [(2,)],  # COUNT
            [],
        ]

        from lambdas.mcp.tools.data import query_episodes

        asyncio.run(query_episodes(language="Python"))

    count_sql = mock_query.call_args_list[0][0][0]
    assert "language = %s" in count_sql


def test_query_episodes_invalid_order_by_defaults_to_created_at():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.side_effect = [[(0,)], []]

        from lambdas.mcp.tools.data import query_episodes

        asyncio.run(query_episodes(order_by="DROP TABLE episodes; --"))

    # Should fall back to created_at, not use the injected value
    select_sql = mock_query.call_args_list[1][0][0]
    assert "created_at" in select_sql
    assert "DROP" not in select_sql


def test_query_episodes_invalid_order_defaults_to_desc():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.side_effect = [[(0,)], []]

        from lambdas.mcp.tools.data import query_episodes

        asyncio.run(query_episodes(order="invalid"))

    select_sql = mock_query.call_args_list[1][0][0]
    assert "desc" in select_sql.lower()


def test_query_episodes_clamps_limit():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.side_effect = [[(0,)], []]

        from lambdas.mcp.tools.data import query_episodes

        asyncio.run(query_episodes(limit=999))

    # limit should be clamped to 50
    select_params = mock_query.call_args_list[1][0][1]
    # limit is the second-to-last param, offset is last
    assert 50 in select_params


def test_query_episodes_returns_total_count():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.side_effect = [
            [(42,)],  # COUNT
            [],        # SELECT (no rows)
        ]

        from lambdas.mcp.tools.data import query_episodes

        result = asyncio.run(query_episodes())

    assert result["total_count"] == 42
    assert result["episodes"] == []


def test_query_episodes_serializes_dates():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.side_effect = [
            [(1,)],
            [
                (
                    1,
                    date(2025, 7, 6),
                    "url",
                    "repo",
                    "user",
                    "Name",
                    5,
                    1,
                    None,
                    None,
                    None,
                    datetime(2025, 7, 6, 12, 0, 0),
                ),
            ],
        ]

        from lambdas.mcp.tools.data import query_episodes

        result = asyncio.run(query_episodes())

    ep = result["episodes"][0]
    assert ep["air_date"] == "2025-07-06"
    assert ep["created_at"] == "2025-07-06T12:00:00"


# ---------------------------------------------------------------------------
# get_episode_detail
# ---------------------------------------------------------------------------


def test_get_episode_detail_returns_full_row():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.return_value = [
            (
                1,
                date(2025, 7, 6),
                "https://github.com/user/repo",
                "repo",
                "user",
                "Test User",
                5,
                "Python",
                "**Hype:** Hello!",
                '{"key": "val"}',
                "art prompt",
                "episodes/1/episode.mp3",
                "episodes/1/episode.mp4",
                "episodes/1/cover.png",
                1,
                "exec-123",
                datetime(2025, 7, 6, 12, 0, 0),
            ),
        ]

        from lambdas.mcp.tools.data import get_episode_detail

        result = asyncio.run(get_episode_detail(episode_id=1))

    assert result["episode_id"] == 1
    assert result["script_text"] == "**Hype:** Hello!"
    assert result["research_json"] == '{"key": "val"}'
    assert result["cover_art_prompt"] == "art prompt"
    assert result["language"] == "Python"


def test_get_episode_detail_not_found_raises():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.return_value = []

        from lambdas.mcp.tools.data import get_episode_detail

        with pytest.raises(ValueError, match="Episode 999 not found"):
            asyncio.run(get_episode_detail(episode_id=999))


def test_get_episode_detail_queries_by_episode_id():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.return_value = [
            tuple(range(17)),  # 17 columns in the SELECT
        ]

        from lambdas.mcp.tools.data import get_episode_detail

        asyncio.run(get_episode_detail(episode_id=42))

    sql = mock_query.call_args[0][0]
    params = mock_query.call_args[0][1]
    assert "episode_id = %s" in sql
    assert params == (42,)


# ---------------------------------------------------------------------------
# query_metrics
# ---------------------------------------------------------------------------


def test_query_metrics_joins_episodes():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.return_value = [
            (1, "repo", "user", "https://linkedin.com/post/1", 1200, 45, 12, 8, date(2025, 7, 10)),
        ]

        from lambdas.mcp.tools.data import query_metrics

        result = asyncio.run(query_metrics())

    sql = mock_query.call_args[0][0]
    assert "JOIN" in sql or "join" in sql.lower()
    assert result["metrics"][0]["repo_name"] == "repo"
    assert result["metrics"][0]["views"] == 1200


def test_query_metrics_filters_by_episode_id():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.return_value = []

        from lambdas.mcp.tools.data import query_metrics

        asyncio.run(query_metrics(episode_id=5))

    sql = mock_query.call_args[0][0]
    params = mock_query.call_args[0][1]
    assert "m.episode_id = %s" in sql
    assert 5 in params


def test_query_metrics_invalid_order_by_defaults_to_views():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.return_value = []

        from lambdas.mcp.tools.data import query_metrics

        asyncio.run(query_metrics(order_by="DROP TABLE; --"))

    sql = mock_query.call_args[0][0]
    assert "views" in sql.lower()
    assert "DROP" not in sql


def test_query_metrics_serializes_snapshot_date():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.return_value = [
            (1, "repo", "user", None, 100, 10, 5, 2, date(2025, 7, 10)),
        ]

        from lambdas.mcp.tools.data import query_metrics

        result = asyncio.run(query_metrics())

    assert result["metrics"][0]["snapshot_date"] == "2025-07-10"


# ---------------------------------------------------------------------------
# query_featured_developers
# ---------------------------------------------------------------------------


def test_query_featured_developers_joins_episodes():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.return_value = [
            ("user", 1, date(2025, 7, 6), "repo"),
        ]

        from lambdas.mcp.tools.data import query_featured_developers

        result = asyncio.run(query_featured_developers())

    sql = mock_query.call_args[0][0]
    assert "JOIN" in sql or "join" in sql.lower()
    assert result["developers"][0]["repo_name"] == "repo"
    assert result["developers"][0]["developer_github"] == "user"


def test_query_featured_developers_respects_limit():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.return_value = []

        from lambdas.mcp.tools.data import query_featured_developers

        asyncio.run(query_featured_developers(limit=25))

    params = mock_query.call_args[0][1]
    assert params == (25,)


def test_query_featured_developers_serializes_featured_date():
    with patch("lambdas.mcp.tools.data.db.query") as mock_query:
        mock_query.return_value = [
            ("dev1", 1, date(2025, 7, 6), "repo"),
        ]

        from lambdas.mcp.tools.data import query_featured_developers

        result = asyncio.run(query_featured_developers())

    assert result["developers"][0]["featured_date"] == "2025-07-06"


# ---------------------------------------------------------------------------
# run_sql
# ---------------------------------------------------------------------------

# run_sql and upsert_metrics call db.get_connection() (through the
# `import shared.db as db` alias), NOT the locally imported get_connection.
# The mock_mcp_db fixture patches lambdas.mcp.tools.data.get_connection,
# which is the wrong path. We patch lambdas.mcp.tools.data.db.get_connection
# directly for these tests.


def _make_db_conn_mock():
    """Create a mock connection + cursor pair matching db.get_connection() usage."""
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    cursor.__enter__ = lambda s: s
    cursor.__exit__ = MagicMock(return_value=False)
    return conn, cursor


def test_run_sql_allows_select():
    conn, cursor = _make_db_conn_mock()
    cursor.description = [("count",)]
    cursor.fetchall.return_value = [(11,)]

    with patch("lambdas.mcp.tools.data.db.get_connection", return_value=conn):
        from lambdas.mcp.tools.data import run_sql

        result = asyncio.run(run_sql(sql="SELECT count(*) FROM episodes"))

    assert result["columns"] == ["count"]
    assert result["rows"] == [[11]]
    assert result["row_count"] == 1


def test_run_sql_rejects_insert():
    from lambdas.mcp.tools.data import run_sql

    with pytest.raises(ValueError, match="SELECT"):
        asyncio.run(run_sql(sql="INSERT INTO episodes (repo_name) VALUES ('x')"))


def test_run_sql_rejects_delete():
    from lambdas.mcp.tools.data import run_sql

    with pytest.raises(ValueError, match="SELECT"):
        asyncio.run(run_sql(sql="DELETE FROM episodes"))


def test_run_sql_rejects_drop():
    from lambdas.mcp.tools.data import run_sql

    with pytest.raises(ValueError, match="SELECT"):
        asyncio.run(run_sql(sql="DROP TABLE episodes"))


def test_run_sql_rejects_update():
    from lambdas.mcp.tools.data import run_sql

    with pytest.raises(ValueError, match="SELECT"):
        asyncio.run(run_sql(sql="UPDATE episodes SET repo_name = 'x'"))


def test_run_sql_leading_whitespace_select():
    conn, cursor = _make_db_conn_mock()
    cursor.description = [("x",)]
    cursor.fetchall.return_value = [(1,)]

    with patch("lambdas.mcp.tools.data.db.get_connection", return_value=conn):
        from lambdas.mcp.tools.data import run_sql

        result = asyncio.run(run_sql(sql="   SELECT 1"))

    assert result["row_count"] == 1


def test_run_sql_case_insensitive():
    conn, cursor = _make_db_conn_mock()
    cursor.description = [("x",)]
    cursor.fetchall.return_value = [(1,)]

    with patch("lambdas.mcp.tools.data.db.get_connection", return_value=conn):
        from lambdas.mcp.tools.data import run_sql

        result = asyncio.run(run_sql(sql="select 1"))

    assert result["row_count"] == 1


def test_run_sql_sets_statement_timeout():
    conn, cursor = _make_db_conn_mock()
    cursor.description = [("x",)]
    cursor.fetchall.return_value = [(1,)]

    with patch("lambdas.mcp.tools.data.db.get_connection", return_value=conn):
        from lambdas.mcp.tools.data import run_sql

        asyncio.run(run_sql(sql="SELECT 1"))

    # Verify statement_timeout was set before the query
    execute_calls = [str(c) for c in cursor.execute.call_args_list]
    assert any("statement_timeout" in c for c in execute_calls)


def test_run_sql_closes_connection():
    conn, cursor = _make_db_conn_mock()
    cursor.description = [("x",)]
    cursor.fetchall.return_value = [(1,)]

    with patch("lambdas.mcp.tools.data.db.get_connection", return_value=conn):
        from lambdas.mcp.tools.data import run_sql

        asyncio.run(run_sql(sql="SELECT 1"))

    conn.close.assert_called_once()


# ---------------------------------------------------------------------------
# upsert_metrics
# ---------------------------------------------------------------------------


def test_upsert_metrics_inserts():
    conn, cursor = _make_db_conn_mock()
    cursor.fetchone.return_value = (5, True)  # metric_id=5, is_insert=True (xmax=0)

    with patch("lambdas.mcp.tools.data.db.get_connection", return_value=conn):
        from lambdas.mcp.tools.data import upsert_metrics

        result = asyncio.run(upsert_metrics(episode_id=1, views=100, likes=10))

    sql = cursor.execute.call_args_list[-1][0][0]
    assert "INSERT" in sql
    assert "ON CONFLICT" in sql
    assert result["metric_id"] == 5
    assert result["action"] == "inserted"


def test_upsert_metrics_updates():
    conn, cursor = _make_db_conn_mock()
    cursor.fetchone.return_value = (5, False)  # metric_id=5, is_insert=False (xmax != 0)

    with patch("lambdas.mcp.tools.data.db.get_connection", return_value=conn):
        from lambdas.mcp.tools.data import upsert_metrics

        result = asyncio.run(upsert_metrics(episode_id=1, views=200, likes=20))

    assert result["metric_id"] == 5
    assert result["action"] == "updated"


def test_upsert_metrics_commits():
    conn, cursor = _make_db_conn_mock()
    cursor.fetchone.return_value = (1, True)

    with patch("lambdas.mcp.tools.data.db.get_connection", return_value=conn):
        from lambdas.mcp.tools.data import upsert_metrics

        asyncio.run(upsert_metrics(episode_id=1))

    conn.commit.assert_called_once()


def test_upsert_metrics_closes_connection():
    conn, cursor = _make_db_conn_mock()
    cursor.fetchone.return_value = (1, True)

    with patch("lambdas.mcp.tools.data.db.get_connection", return_value=conn):
        from lambdas.mcp.tools.data import upsert_metrics

        asyncio.run(upsert_metrics(episode_id=1))

    conn.close.assert_called_once()


def test_upsert_metrics_passes_all_params():
    conn, cursor = _make_db_conn_mock()
    cursor.fetchone.return_value = (1, True)

    with patch("lambdas.mcp.tools.data.db.get_connection", return_value=conn):
        from lambdas.mcp.tools.data import upsert_metrics

        asyncio.run(
            upsert_metrics(
                episode_id=7,
                linkedin_post_url="https://linkedin.com/post/7",
                views=500,
                likes=50,
                comments=15,
                shares=8,
            )
        )

    # Check the params tuple passed to execute
    call_args = cursor.execute.call_args
    params = call_args[0][1]
    assert params[0] == 7  # episode_id
    assert params[1] == "https://linkedin.com/post/7"  # linkedin_post_url
    assert params[2] == 500  # views
    assert params[3] == 50   # likes
    assert params[4] == 15   # comments
    assert params[5] == 8    # shares
