from __future__ import annotations


def test_episodes_resource_returns_list(mock_mcp_db):
    from lambdas.mcp.resources import read_episodes_resource

    conn, cursor = mock_mcp_db
    cursor.description = [("episode_id",), ("air_date",), ("repo_name",)]
    cursor.fetchall.return_value = [(1, "2025-07-06", "repo")]

    result = read_episodes_resource()

    assert len(result) == 1
    assert result[0]["episode_id"] == 1


def test_pipeline_status_resource(mock_sfn_client):
    from lambdas.mcp.resources import read_pipeline_status_resource

    mock_sfn_client.list_executions.side_effect = [
        {"executions": []},  # RUNNING
        {
            "executions": [
                {
                    "executionArn": "arn:...",
                    "name": "test",
                    "status": "SUCCEEDED",
                    "startDate": "2025-07-13T09:00:00Z",
                    "stopDate": "2025-07-13T09:12:00Z",
                },
            ]
        },  # recent completed
    ]

    result = read_pipeline_status_resource()

    assert result["currently_running"] == []
    assert len(result["recent"]) == 1


def test_featured_developers_resource(mock_mcp_db):
    from lambdas.mcp.resources import read_featured_developers_resource

    conn, cursor = mock_mcp_db
    cursor.description = [("developer_github",), ("episode_id",), ("featured_date",)]
    cursor.fetchall.return_value = [("user1", 1, "2025-07-06")]

    result = read_featured_developers_resource()

    assert result[0]["developer_github"] == "user1"


def test_episode_detail_resource_returns_full_row(mock_mcp_db):
    from lambdas.mcp.resources import read_episode_detail_resource

    conn, cursor = mock_mcp_db
    cursor.description = [
        ("episode_id",),
        ("script_text",),
        ("research_json",),
        ("cover_art_prompt",),
        ("air_date",),
        ("repo_name",),
    ]
    cursor.fetchone.return_value = (
        1,
        "**Hype:** Hello!",
        '{"key": "val"}',
        "art prompt",
        "2025-07-06",
        "repo",
    )

    result = read_episode_detail_resource(episode_id=1)

    assert result["episode_id"] == 1
    assert result["script_text"] == "**Hype:** Hello!"
    assert result["research_json"] == '{"key": "val"}'


def test_metrics_resource_returns_list(mock_mcp_db):
    from lambdas.mcp.resources import read_metrics_resource

    conn, cursor = mock_mcp_db
    cursor.description = [("episode_id",), ("repo_name",), ("views",), ("likes",)]
    cursor.fetchall.return_value = [(1, "repo", 1200, 45)]

    result = read_metrics_resource()

    assert len(result) == 1
    assert result[0]["views"] == 1200
