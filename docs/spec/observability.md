> Part of the [Implementation Spec](../../IMPLEMENTATION_SPEC.md)

# Observability

CloudWatch Alarms and alerting for the podcast pipeline. This spec builds on [Instrumentation](./instrumentation.md) (Logger, Tracer, Metrics) and defines the operational monitoring layer.

All alarms are defined in `terraform/observability.tf` and send notifications to a single SNS topic.

---

## SNS Topic

```hcl
variable "alert_email" {
  type        = string
  description = "Email address for CloudWatch Alarm notifications. Leave empty to skip subscription."
  default     = ""
}

resource "aws_sns_topic" "alerts" {
  name = "${var.project_prefix}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
```

The email subscription requires manual confirmation via the link AWS sends after `terraform apply`. Until confirmed, no alarm notifications are delivered.

---

## Pipeline-Level Alarms

These alarms monitor the Step Functions state machine as a whole.

| Alarm | Metric Source | Condition | Default Threshold |
|-------|--------------|-----------|-------------------|
| Pipeline Failure | `AWS/States` `ExecutionsFailed` | Sum >= threshold in 1 hour | 1 |
| Pipeline Timeout | `AWS/States` `ExecutionsTimedOut` | Sum >= threshold in 1 hour | 1 |
| Pipeline Throttled | `AWS/States` `ExecutionThrottled` | Sum >= threshold in 1 hour | 1 |

```hcl
variable "pipeline_failure_threshold" {
  type    = number
  default = 1
}

resource "aws_cloudwatch_metric_alarm" "pipeline_failure" {
  alarm_name          = "${var.project_prefix}-pipeline-failure"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsFailed"
  namespace           = "AWS/States"
  period              = 3600
  statistic           = "Sum"
  threshold           = var.pipeline_failure_threshold
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    StateMachineArn = aws_sfn_state_machine.pipeline.arn
  }
}
```

The `ExecutionsTimedOut` and `ExecutionThrottled` alarms follow the same pattern with their own threshold variables. `treat_missing_data = "notBreaching"` prevents alarms from firing during weeks with no pipeline runs.

---

## Per-Lambda Alarms

Each of the 9 Lambdas (7 pipeline + site + MCP) gets three alarms:

| Alarm | Metric Source | Condition | Default Threshold |
|-------|--------------|-----------|-------------------|
| Error Rate | `AWS/Lambda` `Errors` | Sum >= threshold in 5 min | 1 |
| Near-Timeout | `AWS/Lambda` `Duration` | p99 >= threshold in 5 min | 270,000 ms (90% of 300s budget) |
| Throttle Rate | `AWS/Lambda` `Throttles` | Sum >= threshold in 5 min | 1 |

The near-timeout alarm fires at 90% of the Lambda timeout (270s for pipeline Lambdas, 27s for the site Lambda) to catch functions trending toward timeout before they actually fail.

```hcl
variable "lambda_error_threshold" {
  type    = number
  default = 1
}

resource "aws_cloudwatch_metric_alarm" "discovery_errors" {
  alarm_name          = "${var.project_prefix}-discovery-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = var.lambda_error_threshold
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.discovery.function_name
  }
}
```

This pattern repeats for all 9 Lambdas. Threshold variables are shared across Lambdas (one `lambda_error_threshold` for all error alarms, one `lambda_timeout_threshold_ms` for all duration alarms) to keep Terraform DRY.

---

## Custom Metric Alarms

These use the `ZeroStars` namespace defined by Powertools Metrics (see [Instrumentation](./instrumentation.md#per-lambda-custom-metrics)).

| Alarm | Metric | Condition | Default Threshold | Rationale |
|-------|--------|-----------|-------------------|-----------|
| High Producer Fail Rate | `ProducerVerdict` (dimension `verdict=FAIL`) | Sum >= threshold in 24 hours | 3 | Consecutive FAIL verdicts suggest prompt regression or Bedrock model quality shift |
| Script Too Long | `ScriptCharacterCount` | Maximum >= threshold in 1 eval period | `var.script_character_count_threshold` (default 4,900) | Early warning before the 5,000-character ElevenLabs hard limit (see below) |

> **Why 4,900?** The Producer agent enforces a hard 5,000-character limit at evaluation time (scripts at or over 5,000 characters are an automatic FAIL). The 4,900-character alarm threshold is intentional as an early warning — it fires when scripts are approaching the hard limit, giving operators visibility into prompt regression or model drift before scripts start failing evaluation.

```hcl
variable "producer_fail_threshold" {
  type    = number
  default = 3
}

variable "script_character_count_threshold" {
  type    = number
  default = 4900
}

resource "aws_cloudwatch_metric_alarm" "producer_high_fail_rate" {
  alarm_name          = "${var.project_prefix}-producer-high-fail-rate"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ProducerVerdict"
  namespace           = "ZeroStars"
  period              = 86400
  statistic           = "Sum"
  threshold           = var.producer_fail_threshold
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    service = "producer"
    verdict = "FAIL"
  }
}

resource "aws_cloudwatch_metric_alarm" "script_too_long" {
  alarm_name          = "${var.project_prefix}-script-too-long"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ScriptCharacterCount"
  namespace           = "ZeroStars"
  period              = 300
  statistic           = "Maximum"
  threshold           = var.script_character_count_threshold
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    service = "script"
  }
}
```

---

## Dashboard (Future)

A CloudWatch Dashboard collecting key pipeline metrics on a single screen. Not required for launch but recommended as a follow-up:

- Pipeline success/failure rate (last 30 days)
- Per-Lambda error rate and p99 duration
- Custom metrics: producer pass/fail rate, average script character count, episode duration trend
- Cold start frequency by Lambda

The dashboard can be defined as an `aws_cloudwatch_dashboard` Terraform resource with a JSON body, or created manually in the CloudWatch console.
