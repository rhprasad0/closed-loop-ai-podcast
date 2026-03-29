# ─── Step Functions Execution Role ────────────────────────────────────────────

resource "aws_iam_role" "sfn_pipeline" {
  name = "${var.project_prefix}-sfn-pipeline"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "sfn_pipeline" {
  name = "${var.project_prefix}-sfn-pipeline"
  role = aws_iam_role.sfn_pipeline.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "lambda:InvokeFunction"
        Resource = [
          aws_lambda_function.discovery.arn,
          aws_lambda_function.research.arn,
          aws_lambda_function.script.arn,
          aws_lambda_function.producer.arn,
          aws_lambda_function.cover_art.arn,
          aws_lambda_function.tts.arn,
          aws_lambda_function.post_production.arn,
        ]
      },
      {
        # X-Ray tracing for Step Functions
        Effect   = "Allow"
        Action   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
        Resource = "*"
      },
      {
        # CloudWatch Logs for Step Functions execution logging
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery",
          "logs:CreateLogStream",
          "logs:GetLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutLogEvents",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups",
        ]
        Resource = "*"
      },
    ]
  })
}

# ─── Pipeline State Machine ───────────────────────────────────────────────────

resource "aws_sfn_state_machine" "pipeline" {
  name     = "${var.project_prefix}-pipeline"
  role_arn = aws_iam_role.sfn_pipeline.arn
  type     = "STANDARD"

  definition = jsonencode({
    Comment = "0 Stars, 10/10 — fully autonomous podcast pipeline"
    StartAt = "InitializeMetadata"
    States = {
      InitializeMetadata = {
        Type = "Pass"
        Parameters = {
          metadata = {
            "execution_id.$" = "$$.Execution.Id"
            script_attempt   = 1
            resume_from      = ""
          }
        }
        Next = "ResumeRouter"
      }

      ResumeRouter = {
        Type    = "Choice"
        Comment = "Routes to a mid-pipeline step when resume_from is set (MCP retry_from_step). Normal executions fall through to Discovery via Default."
        Choices = [
          { Variable = "$.metadata.resume_from", StringEquals = "Research", Next = "Research" },
          { Variable = "$.metadata.resume_from", StringEquals = "Script", Next = "Script" },
          { Variable = "$.metadata.resume_from", StringEquals = "Producer", Next = "Producer" },
          { Variable = "$.metadata.resume_from", StringEquals = "CoverArt", Next = "CoverArt" },
          { Variable = "$.metadata.resume_from", StringEquals = "TTS", Next = "TTS" },
          { Variable = "$.metadata.resume_from", StringEquals = "PostProduction", Next = "PostProduction" },
        ]
        Default = "Discovery"
      }

      Discovery = {
        Type       = "Task"
        Resource   = aws_lambda_function.discovery.arn
        ResultPath = "$.discovery"
        Retry = [
          {
            ErrorEquals  = ["States.TaskFailed"]
            IntervalSeconds = 1
            MaxAttempts  = 3
            BackoffRate  = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error_info"
            Next        = "HandleError"
          }
        ]
        Next = "Research"
      }

      Research = {
        Type       = "Task"
        Resource   = aws_lambda_function.research.arn
        ResultPath = "$.research"
        Retry = [
          {
            ErrorEquals     = ["States.TaskFailed"]
            IntervalSeconds = 1
            MaxAttempts     = 3
            BackoffRate     = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error_info"
            Next        = "HandleError"
          }
        ]
        Next = "Script"
      }

      Script = {
        Type       = "Task"
        Resource   = aws_lambda_function.script.arn
        ResultPath = "$.script"
        Retry = [
          {
            ErrorEquals     = ["States.TaskFailed"]
            IntervalSeconds = 1
            MaxAttempts     = 3
            BackoffRate     = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error_info"
            Next        = "HandleError"
          }
        ]
        Next = "Producer"
      }

      Producer = {
        Type       = "Task"
        Resource   = aws_lambda_function.producer.arn
        ResultPath = "$.producer"
        Retry = [
          {
            ErrorEquals     = ["States.TaskFailed"]
            IntervalSeconds = 1
            MaxAttempts     = 3
            BackoffRate     = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error_info"
            Next        = "HandleError"
          }
        ]
        Next = "EvaluateVerdict"
      }

      EvaluateVerdict = {
        Type = "Choice"
        Choices = [
          {
            Variable     = "$.producer.verdict"
            StringEquals = "PASS"
            Next         = "CoverArt"
          },
          {
            And = [
              {
                Variable     = "$.producer.verdict"
                StringEquals = "FAIL"
              },
              {
                Variable              = "$.metadata.script_attempt"
                NumericGreaterThanEquals = 3
              }
            ]
            Next = "PipelineFailed"
          },
          {
            Variable     = "$.producer.verdict"
            StringEquals = "FAIL"
            Next         = "IncrementAttempt"
          },
        ]
        Default = "HandleError"
      }

      IncrementAttempt = {
        Type = "Pass"
        Parameters = {
          "execution_id.$"    = "$.metadata.execution_id"
          "script_attempt.$"  = "States.MathAdd($.metadata.script_attempt, 1)"
          resume_from         = null
        }
        ResultPath = "$.metadata"
        Next       = "Script"
      }

      CoverArt = {
        Type       = "Task"
        Resource   = aws_lambda_function.cover_art.arn
        ResultPath = "$.cover_art"
        Retry = [
          {
            ErrorEquals     = ["States.TaskFailed"]
            IntervalSeconds = 1
            MaxAttempts     = 3
            BackoffRate     = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error_info"
            Next        = "HandleError"
          }
        ]
        Next = "TTS"
      }

      TTS = {
        Type       = "Task"
        Resource   = aws_lambda_function.tts.arn
        ResultPath = "$.tts"
        Retry = [
          {
            ErrorEquals     = ["States.TaskFailed"]
            IntervalSeconds = 1
            MaxAttempts     = 3
            BackoffRate     = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error_info"
            Next        = "HandleError"
          }
        ]
        Next = "PostProduction"
      }

      PostProduction = {
        Type       = "Task"
        Resource   = aws_lambda_function.post_production.arn
        ResultPath = "$.post_production"
        Retry = [
          {
            ErrorEquals     = ["States.TaskFailed"]
            IntervalSeconds = 1
            MaxAttempts     = 3
            BackoffRate     = 2.0
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error_info"
            Next        = "HandleError"
          }
        ]
        Next = "Done"
      }

      HandleError = {
        Type = "Pass"
        Next = "PipelineFailed"
      }

      PipelineFailed = {
        Type  = "Fail"
        Error = "PipelineError"
        Cause = "Pipeline execution failed — check execution history for details"
      }

      Done = {
        Type = "Succeed"
      }
    }
  })

  tracing_configuration {
    enabled = true
  }

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn_pipeline.arn}:*"
    include_execution_data = false
    level                  = "ERROR"
  }

  depends_on = [aws_cloudwatch_log_group.sfn_pipeline]
}

resource "aws_cloudwatch_log_group" "sfn_pipeline" {
  name              = "/aws/states/${var.project_prefix}-pipeline"
  retention_in_days = 14
}
