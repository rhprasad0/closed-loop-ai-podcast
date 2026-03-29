> Part of the [Implementation Spec](../../IMPLEMENTATION_SPEC.md)

# Step Functions ASL Definition

The state machine definition as ASL (Amazon States Language). This gets placed inside `jsonencode()` in `terraform/step-functions.tf`.

### State Machine Flow

```
Start
  → InitializeMetadata (Pass — sets execution_id from $$.Execution.Id, script_attempt = 1)
  → ResumeRouter (Choice — routes to resume_from step if set, otherwise Discovery)
  → Discovery
  → Research
  → Script
  → Producer
  → EvaluateVerdict (Choice)
      ├── FAIL + attempts < 3 → IncrementAttempt → Script (loop back)
      ├── FAIL + attempts >= 3 → PipelineFailed (Fail state)
      └── PASS → CoverArt
  → TTS
  → PostProduction
  → Done (Succeed)
```

### Key Design Decisions

- **ResultPath**: Each Lambda writes to its own key using `ResultPath: "$.lambda_name"` so the full state accumulates without overwriting.
- **Retry on transient errors**: Every Lambda task has a `Retry` block for `States.TaskFailed` with exponential backoff (1s, 2s, 4s) and max 3 attempts. This handles Bedrock throttling, API timeouts, etc. `States.TaskFailed` catches all errors except `States.Timeout` — a Lambda hitting its 300s timeout is non-retriable by design and falls through to Catch.
- **Catch**: Each Lambda has a `Catch` block that routes to a `HandleError` state (Pass) before entering the `PipelineFailed` Fail state. The Catch captures error details at `$.error_info` via `ResultPath` so they're visible in the execution history.
- **Evaluator loop**: The Producer Lambda returns a verdict. A Choice state checks `$.producer.verdict` with three explicit rules evaluated in order: (1) PASS → CoverArt, (2) FAIL with `$.metadata.script_attempt >= 3` → PipelineFailed, (3) FAIL → IncrementAttempt (loop back). The `Default` routes to HandleError, catching unexpected verdict values and surfacing Producer bugs immediately rather than silently retrying.
- **Counter increment**: The `IncrementAttempt` Pass state uses `States.MathAdd($.metadata.script_attempt, 1)` in `Parameters` with `ResultPath: "$.metadata"` to increment the counter while preserving all other state keys.
- **Script retry input**: When looping back to Script, the state object includes `$.producer.feedback` from the failed evaluation. The Script Lambda reads this and incorporates it.

### ASL Definition

Lambda Resource ARNs are shown as `<discovery_lambda_arn>` etc. In Terraform's `jsonencode()`, these become `aws_lambda_function.discovery.arn` references. The mapping is:

| Placeholder | Terraform Reference |
|-------------|-------------------|
| `<discovery_lambda_arn>` | `aws_lambda_function.discovery.arn` |
| `<research_lambda_arn>` | `aws_lambda_function.research.arn` |
| `<script_lambda_arn>` | `aws_lambda_function.script.arn` |
| `<producer_lambda_arn>` | `aws_lambda_function.producer.arn` |
| `<cover_art_lambda_arn>` | `aws_lambda_function.cover_art.arn` |
| `<tts_lambda_arn>` | `aws_lambda_function.tts.arn` |
| `<post_production_lambda_arn>` | `aws_lambda_function.post_production.arn` |

```json
{
  "Comment": "0 Stars, 10/10 — fully autonomous podcast pipeline",
  "StartAt": "InitializeMetadata",
  "States": {
    "InitializeMetadata": {
      "Type": "Pass",
      "Parameters": {
        "metadata": {
          "execution_id.$": "$$.Execution.Id",
          "script_attempt": 1
        }
      },
      "Next": "ResumeRouter"
    },
    "ResumeRouter": {
      "Type": "Choice",
      "Comment": "Routes to a mid-pipeline step when resume_from is set (MCP retry_from_step). Normal executions fall through to Discovery via Default.",
      "Choices": [
        { "Variable": "$.metadata.resume_from", "StringEquals": "Research", "Next": "Research" },
        { "Variable": "$.metadata.resume_from", "StringEquals": "Script", "Next": "Script" },
        { "Variable": "$.metadata.resume_from", "StringEquals": "Producer", "Next": "Producer" },
        { "Variable": "$.metadata.resume_from", "StringEquals": "CoverArt", "Next": "CoverArt" },
        { "Variable": "$.metadata.resume_from", "StringEquals": "TTS", "Next": "TTS" },
        { "Variable": "$.metadata.resume_from", "StringEquals": "PostProduction", "Next": "PostProduction" }
      ],
      "Default": "Discovery"
    },
    "Discovery": {
      "Type": "Task",
      "Resource": "<discovery_lambda_arn>",
      "ResultPath": "$.discovery",
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed"],
          "IntervalSeconds": 1,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error_info",
          "Next": "HandleError"
        }
      ],
      "Next": "Research"
    },
    "Research": {
      "Type": "Task",
      "Resource": "<research_lambda_arn>",
      "ResultPath": "$.research",
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed"],
          "IntervalSeconds": 1,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error_info",
          "Next": "HandleError"
        }
      ],
      "Next": "Script"
    },
    "Script": {
      "Type": "Task",
      "Resource": "<script_lambda_arn>",
      "ResultPath": "$.script",
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed"],
          "IntervalSeconds": 1,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error_info",
          "Next": "HandleError"
        }
      ],
      "Next": "Producer"
    },
    "Producer": {
      "Type": "Task",
      "Resource": "<producer_lambda_arn>",
      "ResultPath": "$.producer",
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed"],
          "IntervalSeconds": 1,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error_info",
          "Next": "HandleError"
        }
      ],
      "Next": "EvaluateVerdict"
    },
    "EvaluateVerdict": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.producer.verdict",
          "StringEquals": "PASS",
          "Next": "CoverArt"
        },
        {
          "And": [
            {
              "Variable": "$.producer.verdict",
              "StringEquals": "FAIL"
            },
            {
              "Variable": "$.metadata.script_attempt",
              "NumericGreaterThanEquals": 3
            }
          ],
          "Next": "PipelineFailed"
        },
        {
          "Variable": "$.producer.verdict",
          "StringEquals": "FAIL",
          "Next": "IncrementAttempt"
        }
      ],
      "Default": "HandleError"
    },
    "IncrementAttempt": {
      "Type": "Pass",
      "Parameters": {
        "execution_id.$": "$.metadata.execution_id",
        "script_attempt.$": "States.MathAdd($.metadata.script_attempt, 1)",
        "resume_from": null
      },
      "ResultPath": "$.metadata",
      "Next": "Script"
    },
    "CoverArt": {
      "Type": "Task",
      "Resource": "<cover_art_lambda_arn>",
      "ResultPath": "$.cover_art",
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed"],
          "IntervalSeconds": 1,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error_info",
          "Next": "HandleError"
        }
      ],
      "Next": "TTS"
    },
    "TTS": {
      "Type": "Task",
      "Resource": "<tts_lambda_arn>",
      "ResultPath": "$.tts",
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed"],
          "IntervalSeconds": 1,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error_info",
          "Next": "HandleError"
        }
      ],
      "Next": "PostProduction"
    },
    "PostProduction": {
      "Type": "Task",
      "Resource": "<post_production_lambda_arn>",
      "ResultPath": "$.post_production",
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed"],
          "IntervalSeconds": 1,
          "MaxAttempts": 3,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "ResultPath": "$.error_info",
          "Next": "HandleError"
        }
      ],
      "Next": "Done"
    },
    "HandleError": {
      "Type": "Pass",
      "Next": "PipelineFailed"
    },
    "PipelineFailed": {
      "Type": "Fail",
      "Error": "PipelineError",
      "Cause": "Pipeline execution failed — check execution history for details"
    },
    "Done": {
      "Type": "Succeed"
    }
  }
}
```
