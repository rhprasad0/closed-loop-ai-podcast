# ─── MCP Lambda Deployment Package ───────────────────────────────────────────

data "archive_file" "mcp" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/mcp"
  output_path = "${path.module}/../build/mcp.zip"
}

# ─── MCP CloudWatch Log Group ─────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "mcp" {
  name              = "/aws/lambda/${var.project_prefix}-mcp"
  retention_in_days = 14
}

# ─── MCP IAM Role ─────────────────────────────────────────────────────────────

resource "aws_iam_role" "mcp" {
  name = "${var.project_prefix}-mcp"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "mcp" {
  name = "${var.project_prefix}-mcp"
  role = aws_iam_role.mcp.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # Own log writes
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.mcp.arn}:*"
      },
      # Step Functions — pipeline control
      {
        Effect = "Allow"
        Action = [
          "states:StartExecution",
          "states:ListExecutions",
        ]
        Resource = aws_sfn_state_machine.pipeline.arn
      },
      {
        Effect = "Allow"
        Action = [
          "states:StopExecution",
          "states:DescribeExecution",
          "states:GetExecutionHistory",
        ]
        Resource = "*"
      },
      # Lambda — direct agent invocation (synchronous)
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
      # CloudWatch Logs — agent log retrieval (get_agent_logs tool)
      {
        Effect = "Allow"
        Action = "logs:FilterLogEvents"
        Resource = [
          "${aws_cloudwatch_log_group.discovery.arn}",
          "${aws_cloudwatch_log_group.research.arn}",
          "${aws_cloudwatch_log_group.script.arn}",
          "${aws_cloudwatch_log_group.producer.arn}",
          "${aws_cloudwatch_log_group.cover_art.arn}",
          "${aws_cloudwatch_log_group.tts.arn}",
          "${aws_cloudwatch_log_group.post_production.arn}",
          "${aws_cloudwatch_log_group.site.arn}",
          "${aws_cloudwatch_log_group.mcp.arn}",
        ]
      },
      # S3 — episode assets read (presigned URLs, list objects)
      {
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.episodes.arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = "s3:ListBucket"
        Resource = aws_s3_bucket.episodes.arn
      },
      # CloudFront — cache invalidation and distribution status
      {
        Effect = "Allow"
        Action = [
          "cloudfront:CreateInvalidation",
          "cloudfront:GetDistribution",
        ]
        Resource = aws_cloudfront_distribution.site.arn
      },
      # ACM — certificate status (get_site_status tool)
      {
        Effect   = "Allow"
        Action   = "acm:DescribeCertificate"
        Resource = aws_acm_certificate.site.arn
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "mcp_xray" {
  role       = aws_iam_role.mcp.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXrayWriteOnlyAccess"
}

# ─── MCP Lambda Function ──────────────────────────────────────────────────────

resource "aws_lambda_function" "mcp" {
  function_name    = "${var.project_prefix}-mcp"
  filename         = data.archive_file.mcp.output_path
  source_code_hash = data.archive_file.mcp.output_base64sha256
  role             = aws_iam_role.mcp.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  memory_size      = 512
  timeout          = 300
  layers           = [aws_lambda_layer_version.shared.arn]

  environment {
    variables = {
      POWERTOOLS_SERVICE_NAME            = "mcp"
      POWERTOOLS_LOG_LEVEL               = "INFO"
      POWERTOOLS_METRICS_NAMESPACE       = "ZeroStars"
      POWERTOOLS_TRACER_CAPTURE_RESPONSE = "false"
      DB_CONNECTION_STRING               = var.db_connection_string
      STATE_MACHINE_ARN                  = aws_sfn_state_machine.pipeline.arn
      S3_BUCKET                          = aws_s3_bucket.episodes.id
      CLOUDFRONT_DISTRIBUTION_ID         = aws_cloudfront_distribution.site.id
      ACM_CERTIFICATE_ARN                = aws_acm_certificate.site.arn
      SITE_DOMAIN                        = var.domain_name
    }
  }

  logging_config {
    log_format            = "JSON"
    application_log_level = "INFO"
    system_log_level      = "WARN"
  }

  tracing_config {
    mode = "Active"
  }

  depends_on = [
    aws_iam_role_policy.mcp,
    aws_iam_role_policy_attachment.mcp_xray,
    aws_cloudwatch_log_group.mcp,
  ]
}

# ─── MCP Function URL ─────────────────────────────────────────────────────────

resource "aws_lambda_function_url" "mcp" {
  function_name      = aws_lambda_function.mcp.function_name
  authorization_type = "AWS_IAM"
  invoke_mode        = "RESPONSE_STREAM" # required for Streamable HTTP SSE transport
}

# ─── MCP Function URL Permission ──────────────────────────────────────────────

resource "aws_lambda_permission" "mcp_invoke" {
  statement_id           = "AllowMCPPrincipalInvoke"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.mcp.function_name
  principal              = var.mcp_allowed_principal
  function_url_auth_type = "AWS_IAM"
}
