from __future__ import annotations


def test_handler_registers_all_tools():
    """Verify the MCP server registers all 26 tools."""
    from lambdas.mcp.handler import create_mcp_server

    server = create_mcp_server()
    tool_names = {t.name for t in server.list_tools()}

    expected = {
        "start_pipeline",
        "stop_pipeline",
        "get_execution_status",
        "list_executions",
        "retry_from_step",
        "invoke_discovery",
        "invoke_research",
        "invoke_script",
        "invoke_producer",
        "invoke_cover_art",
        "invoke_tts",
        "invoke_post_production",
        "get_agent_logs",
        "get_execution_history",
        "get_pipeline_health",
        "query_episodes",
        "get_episode_detail",
        "query_metrics",
        "query_featured_developers",
        "run_sql",
        "upsert_metrics",
        "get_episode_assets",
        "list_s3_assets",
        "get_presigned_url",
        "invalidate_cache",
        "get_site_status",
    }
    assert tool_names == expected


def test_handler_registers_all_resources():
    """Verify the MCP server registers all 5 resources."""
    from lambdas.mcp.handler import create_mcp_server

    server = create_mcp_server()
    resource_uris = {r.uri for r in server.list_resources()}

    expected = {
        "zerostars://episodes",
        "zerostars://episodes/{episode_id}",
        "zerostars://metrics",
        "zerostars://pipeline/status",
        "zerostars://featured-developers",
    }
    assert resource_uris == expected
