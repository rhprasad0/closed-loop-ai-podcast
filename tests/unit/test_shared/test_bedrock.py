import json
from unittest.mock import MagicMock, patch

import pytest


def test_invoke_model_returns_text():
    with patch("shared.bedrock.boto3.client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_client.invoke_model.return_value = {
            "body": MagicMock(
                read=lambda: json.dumps(
                    {
                        "content": [{"type": "text", "text": "Hello world"}],
                        "stop_reason": "end_turn",
                    }
                ).encode()
            ),
        }
        from shared.bedrock import invoke_model

        result = invoke_model(user_message="Say hello", system_prompt="Be friendly")
    assert "Hello world" in result


def test_invoke_model_body_includes_required_fields():
    with patch("shared.bedrock.boto3.client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_client.invoke_model.return_value = {
            "body": MagicMock(
                read=lambda: json.dumps(
                    {
                        "content": [{"type": "text", "text": "ok"}],
                    }
                ).encode()
            ),
        }
        from shared.bedrock import invoke_model

        invoke_model(user_message="test", system_prompt="sys")

    body = json.loads(mock_client.invoke_model.call_args.kwargs["body"])
    assert body["anthropic_version"] == "bedrock-2023-05-31"
    assert "max_tokens" in body
    assert "system" in body
    assert "messages" in body


def test_invoke_model_passes_effort():
    with patch("shared.bedrock.boto3.client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_client.invoke_model.return_value = {
            "body": MagicMock(
                read=lambda: json.dumps(
                    {
                        "content": [{"type": "text", "text": "ok"}],
                    }
                ).encode()
            ),
        }
        from shared.bedrock import invoke_model

        invoke_model(user_message="test", system_prompt="sys", effort="high")

    body = json.loads(mock_client.invoke_model.call_args.kwargs["body"])
    assert body["output_config"]["effort"] == "high"


def test_invoke_with_tools_single_turn_returns_text():
    with patch("shared.bedrock.boto3.client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_client.invoke_model.return_value = {
            "body": MagicMock(
                read=lambda: json.dumps(
                    {
                        "content": [{"type": "text", "text": "Final answer"}],
                        "stop_reason": "end_turn",
                    }
                ).encode()
            ),
        }
        from shared.bedrock import invoke_with_tools

        result = invoke_with_tools(
            user_message="Find a repo",
            system_prompt="You are a search agent",
            tools=[{"name": "search", "description": "Search", "input_schema": {}}],
            tool_executor=lambda name, inp: '{"result": "ok"}',
        )
    assert "Final answer" in result


def test_invoke_with_tools_calls_executor_on_tool_use():
    call_log = []

    def mock_executor(name, inp):
        call_log.append(name)
        return '{"result": "found"}'

    with patch("shared.bedrock.boto3.client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_client.invoke_model.side_effect = [
            {
                "body": MagicMock(
                    read=lambda: json.dumps(
                        {
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "t1",
                                    "name": "search",
                                    "input": {"q": "test"},
                                },
                            ],
                            "stop_reason": "tool_use",
                        }
                    ).encode()
                )
            },
            {
                "body": MagicMock(
                    read=lambda: json.dumps(
                        {
                            "content": [{"type": "text", "text": "Done"}],
                            "stop_reason": "end_turn",
                        }
                    ).encode()
                )
            },
        ]
        from shared.bedrock import invoke_with_tools

        invoke_with_tools(
            user_message="Find",
            system_prompt="Agent",
            tools=[{"name": "search", "description": "S", "input_schema": {}}],
            tool_executor=mock_executor,
        )
    assert "search" in call_log


def test_invoke_with_tools_max_turns_raises():
    with patch("shared.bedrock.boto3.client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        # Always return tool_use to exhaust max_turns
        mock_client.invoke_model.return_value = {
            "body": MagicMock(
                read=lambda: json.dumps(
                    {
                        "content": [
                            {"type": "tool_use", "id": "t1", "name": "s", "input": {}},
                        ],
                        "stop_reason": "tool_use",
                    }
                ).encode()
            ),
        }
        from shared.bedrock import invoke_with_tools

        with pytest.raises(RuntimeError, match="max_turns"):
            invoke_with_tools(
                user_message="Loop forever",
                system_prompt="Agent",
                tools=[{"name": "s", "description": "S", "input_schema": {}}],
                tool_executor=lambda n, i: "{}",
                max_turns=2,
            )
