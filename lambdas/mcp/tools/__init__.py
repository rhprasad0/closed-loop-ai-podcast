"""MCP tools package.

Re-exports the six tool modules and provides register_all_tools() so
handler.py can register all 26 tools in one call if desired.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from tools import agents, assets, data, observation, pipeline, site

__all__ = [
    "agents",
    "assets",
    "data",
    "observation",
    "pipeline",
    "site",
    "register_all_tools",
]


def register_all_tools(server: FastMCP) -> None:
    """Register all 26 MCP tools onto *server*.

    Groups mirror the tool module layout:
    - pipeline   (5): start_pipeline, stop_pipeline, get_execution_status,
                       list_executions, retry_from_step
    - agents     (7): invoke_discovery, invoke_research, invoke_script,
                       invoke_producer, invoke_cover_art, invoke_tts,
                       invoke_post_production
    - observation (3): get_agent_logs, get_execution_history, get_pipeline_health
    - data        (6): query_episodes, get_episode_detail, query_metrics,
                       query_featured_developers, run_sql, upsert_metrics
    - assets      (3): get_episode_assets, list_s3_assets, get_presigned_url
    - site        (2): invalidate_cache, get_site_status
    """
    # Pipeline control (5)
    server.add_tool(pipeline.start_pipeline)
    server.add_tool(pipeline.stop_pipeline)
    server.add_tool(pipeline.get_execution_status)
    server.add_tool(pipeline.list_executions)
    server.add_tool(pipeline.retry_from_step)

    # Agent invocation (7)
    server.add_tool(agents.invoke_discovery)
    server.add_tool(agents.invoke_research)
    server.add_tool(agents.invoke_script)
    server.add_tool(agents.invoke_producer)
    server.add_tool(agents.invoke_cover_art)
    server.add_tool(agents.invoke_tts)
    server.add_tool(agents.invoke_post_production)

    # Observation (3)
    server.add_tool(observation.get_agent_logs)
    server.add_tool(observation.get_execution_history)
    server.add_tool(observation.get_pipeline_health)

    # Data (6)
    server.add_tool(data.query_episodes)
    server.add_tool(data.get_episode_detail)
    server.add_tool(data.query_metrics)
    server.add_tool(data.query_featured_developers)
    server.add_tool(data.run_sql)
    server.add_tool(data.upsert_metrics)

    # Assets (3)
    server.add_tool(assets.get_episode_assets)
    server.add_tool(assets.list_s3_assets)
    server.add_tool(assets.get_presigned_url)

    # Site (2)
    server.add_tool(site.invalidate_cache)
    server.add_tool(site.get_site_status)
