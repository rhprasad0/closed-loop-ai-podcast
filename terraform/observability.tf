# script_character_count_threshold is defined here (not in variables.tf) because
# it is only consumed by observability.tf. Terraform allows variable definitions
# in any .tf file within the module.
variable "script_character_count_threshold" {
  type        = number
  default     = 4900
  description = "ScriptCharacterCount maximum that triggers the script-too-long alarm. Set below the 5,000-char ElevenLabs hard limit as an early warning."
}

# ─── SNS Alerts Topic ─────────────────────────────────────────────────────────

resource "aws_sns_topic" "alerts" {
  name = "${var.project_prefix}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ─── Pipeline-Level Alarms ────────────────────────────────────────────────────

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

resource "aws_cloudwatch_metric_alarm" "pipeline_timeout" {
  alarm_name          = "${var.project_prefix}-pipeline-timeout"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionsTimedOut"
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

resource "aws_cloudwatch_metric_alarm" "pipeline_throttle" {
  alarm_name          = "${var.project_prefix}-pipeline-throttle"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "ExecutionThrottled"
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

# ─── Per-Lambda Alarms: Discovery ─────────────────────────────────────────────

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

resource "aws_cloudwatch_metric_alarm" "discovery_duration" {
  alarm_name          = "${var.project_prefix}-discovery-duration"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  extended_statistics = "p99"
  threshold           = var.lambda_timeout_threshold_ms
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.discovery.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "discovery_throttles" {
  alarm_name          = "${var.project_prefix}-discovery-throttles"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
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

# ─── Per-Lambda Alarms: Research ──────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "research_errors" {
  alarm_name          = "${var.project_prefix}-research-errors"
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
    FunctionName = aws_lambda_function.research.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "research_duration" {
  alarm_name          = "${var.project_prefix}-research-duration"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  extended_statistics = "p99"
  threshold           = var.lambda_timeout_threshold_ms
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.research.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "research_throttles" {
  alarm_name          = "${var.project_prefix}-research-throttles"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = var.lambda_error_threshold
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.research.function_name
  }
}

# ─── Per-Lambda Alarms: Script ────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "script_errors" {
  alarm_name          = "${var.project_prefix}-script-errors"
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
    FunctionName = aws_lambda_function.script.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "script_duration" {
  alarm_name          = "${var.project_prefix}-script-duration"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  extended_statistics = "p99"
  threshold           = var.lambda_timeout_threshold_ms
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.script.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "script_throttles" {
  alarm_name          = "${var.project_prefix}-script-throttles"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = var.lambda_error_threshold
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.script.function_name
  }
}

# ─── Per-Lambda Alarms: Producer ──────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "producer_errors" {
  alarm_name          = "${var.project_prefix}-producer-errors"
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
    FunctionName = aws_lambda_function.producer.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "producer_duration" {
  alarm_name          = "${var.project_prefix}-producer-duration"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  extended_statistics = "p99"
  threshold           = var.lambda_timeout_threshold_ms
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.producer.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "producer_throttles" {
  alarm_name          = "${var.project_prefix}-producer-throttles"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = var.lambda_error_threshold
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.producer.function_name
  }
}

# ─── Per-Lambda Alarms: Cover Art ─────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "cover_art_errors" {
  alarm_name          = "${var.project_prefix}-cover-art-errors"
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
    FunctionName = aws_lambda_function.cover_art.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "cover_art_duration" {
  alarm_name          = "${var.project_prefix}-cover-art-duration"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  extended_statistics = "p99"
  threshold           = var.lambda_timeout_threshold_ms
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.cover_art.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "cover_art_throttles" {
  alarm_name          = "${var.project_prefix}-cover-art-throttles"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = var.lambda_error_threshold
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.cover_art.function_name
  }
}

# ─── Per-Lambda Alarms: TTS ───────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "tts_errors" {
  alarm_name          = "${var.project_prefix}-tts-errors"
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
    FunctionName = aws_lambda_function.tts.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "tts_duration" {
  alarm_name          = "${var.project_prefix}-tts-duration"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  extended_statistics = "p99"
  threshold           = var.lambda_timeout_threshold_ms
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.tts.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "tts_throttles" {
  alarm_name          = "${var.project_prefix}-tts-throttles"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = var.lambda_error_threshold
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.tts.function_name
  }
}

# ─── Per-Lambda Alarms: Post-Production ───────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "post_production_errors" {
  alarm_name          = "${var.project_prefix}-post-production-errors"
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
    FunctionName = aws_lambda_function.post_production.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "post_production_duration" {
  alarm_name          = "${var.project_prefix}-post-production-duration"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  extended_statistics = "p99"
  threshold           = var.lambda_timeout_threshold_ms
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.post_production.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "post_production_throttles" {
  alarm_name          = "${var.project_prefix}-post-production-throttles"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = var.lambda_error_threshold
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.post_production.function_name
  }
}

# ─── Per-Lambda Alarms: Site ──────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "site_errors" {
  alarm_name          = "${var.project_prefix}-site-errors"
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
    FunctionName = aws_lambda_function.site.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "site_duration" {
  alarm_name          = "${var.project_prefix}-site-duration"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  extended_statistics = "p99"
  # Site Lambda timeout is 30s; 90% = 27,000ms. The shared variable defaults to 270,000ms (90% of 300s).
  # Override not possible without a separate variable — operators should set lambda_timeout_threshold_ms
  # to 27000 if they want accurate near-timeout alerting for the site Lambda.
  threshold      = var.lambda_timeout_threshold_ms
  alarm_actions  = [aws_sns_topic.alerts.arn]
  treat_missing_data = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.site.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "site_throttles" {
  alarm_name          = "${var.project_prefix}-site-throttles"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = var.lambda_error_threshold
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.site.function_name
  }
}

# ─── Per-Lambda Alarms: MCP ───────────────────────────────────────────────────

resource "aws_cloudwatch_metric_alarm" "mcp_errors" {
  alarm_name          = "${var.project_prefix}-mcp-errors"
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
    FunctionName = aws_lambda_function.mcp.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "mcp_duration" {
  alarm_name          = "${var.project_prefix}-mcp-duration"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  extended_statistics = "p99"
  threshold           = var.lambda_timeout_threshold_ms
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.mcp.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "mcp_throttles" {
  alarm_name          = "${var.project_prefix}-mcp-throttles"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Throttles"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = var.lambda_error_threshold
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.mcp.function_name
  }
}

# ─── Custom Metric Alarms ─────────────────────────────────────────────────────

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
