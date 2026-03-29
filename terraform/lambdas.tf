# ─── Shared Lambda Layer ──────────────────────────────────────────────────────

resource "aws_lambda_layer_version" "shared" {
  layer_name               = "${var.project_prefix}-shared"
  filename                 = "${path.module}/../build/shared-layer.zip"
  compatible_runtimes      = ["python3.12"]
  compatible_architectures = ["x86_64"]
  source_code_hash         = filebase64sha256("${path.module}/../build/shared-layer.zip")
}

resource "aws_lambda_layer_version" "ffmpeg" {
  layer_name               = "${var.project_prefix}-ffmpeg"
  filename                 = "${path.module}/../layers/ffmpeg/ffmpeg-layer.zip"
  compatible_runtimes      = ["python3.12"]
  compatible_architectures = ["x86_64"]
  source_code_hash         = filebase64sha256("${path.module}/../layers/ffmpeg/ffmpeg-layer.zip")
}

# ─── Discovery ────────────────────────────────────────────────────────────────

data "archive_file" "discovery" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/discovery"
  output_path = "${path.module}/../build/discovery.zip"
}

resource "aws_cloudwatch_log_group" "discovery" {
  name              = "/aws/lambda/${var.project_prefix}-discovery"
  retention_in_days = 14
}

resource "aws_iam_role" "discovery" {
  name = "${var.project_prefix}-discovery"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "discovery" {
  name = "${var.project_prefix}-discovery"
  role = aws_iam_role.discovery.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.discovery.arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = "bedrock:InvokeModel"
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = aws_secretsmanager_secret.exa.arn
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "discovery_xray" {
  role       = aws_iam_role.discovery.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXrayWriteOnlyAccess"
}

resource "aws_lambda_function" "discovery" {
  function_name    = "${var.project_prefix}-discovery"
  filename         = data.archive_file.discovery.output_path
  source_code_hash = data.archive_file.discovery.output_base64sha256
  role             = aws_iam_role.discovery.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  memory_size      = 512
  timeout          = 900 # Agentic loop: multiple Bedrock tool-use calls + Exa + GitHub
  layers           = [aws_lambda_layer_version.shared.arn]

  environment {
    variables = {
      POWERTOOLS_SERVICE_NAME            = "discovery"
      POWERTOOLS_LOG_LEVEL               = "INFO"
      POWERTOOLS_METRICS_NAMESPACE       = "ZeroStars"
      POWERTOOLS_TRACER_CAPTURE_RESPONSE = "false"
      DB_CONNECTION_STRING               = var.db_connection_string
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

  depends_on = [aws_cloudwatch_log_group.discovery]
}

# ─── Research ─────────────────────────────────────────────────────────────────

data "archive_file" "research" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/research"
  output_path = "${path.module}/../build/research.zip"
}

resource "aws_cloudwatch_log_group" "research" {
  name              = "/aws/lambda/${var.project_prefix}-research"
  retention_in_days = 14
}

resource "aws_iam_role" "research" {
  name = "${var.project_prefix}-research"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "research" {
  name = "${var.project_prefix}-research"
  role = aws_iam_role.research.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.research.arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = "bedrock:InvokeModel"
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "research_xray" {
  role       = aws_iam_role.research.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXrayWriteOnlyAccess"
}

resource "aws_lambda_function" "research" {
  function_name    = "${var.project_prefix}-research"
  filename         = data.archive_file.research.output_path
  source_code_hash = data.archive_file.research.output_base64sha256
  role             = aws_iam_role.research.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  memory_size      = 512
  timeout          = 900 # Agentic loop: multiple Bedrock tool-use calls + GitHub API
  layers           = [aws_lambda_layer_version.shared.arn]

  environment {
    variables = {
      POWERTOOLS_SERVICE_NAME            = "research"
      POWERTOOLS_LOG_LEVEL               = "INFO"
      POWERTOOLS_METRICS_NAMESPACE       = "ZeroStars"
      POWERTOOLS_TRACER_CAPTURE_RESPONSE = "false"
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

  depends_on = [aws_cloudwatch_log_group.research]
}

# ─── Script ───────────────────────────────────────────────────────────────────

data "archive_file" "script" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/script"
  output_path = "${path.module}/../build/script.zip"
}

resource "aws_cloudwatch_log_group" "script" {
  name              = "/aws/lambda/${var.project_prefix}-script"
  retention_in_days = 14
}

resource "aws_iam_role" "script" {
  name = "${var.project_prefix}-script"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "script" {
  name = "${var.project_prefix}-script"
  role = aws_iam_role.script.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.script.arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = "bedrock:InvokeModel"
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "script_xray" {
  role       = aws_iam_role.script.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXrayWriteOnlyAccess"
}

resource "aws_lambda_function" "script" {
  function_name    = "${var.project_prefix}-script"
  filename         = data.archive_file.script.output_path
  source_code_hash = data.archive_file.script.output_base64sha256
  role             = aws_iam_role.script.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  memory_size      = 512
  timeout          = 300
  layers           = [aws_lambda_layer_version.shared.arn]

  environment {
    variables = {
      POWERTOOLS_SERVICE_NAME            = "script"
      POWERTOOLS_LOG_LEVEL               = "INFO"
      POWERTOOLS_METRICS_NAMESPACE       = "ZeroStars"
      POWERTOOLS_TRACER_CAPTURE_RESPONSE = "false"
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

  depends_on = [aws_cloudwatch_log_group.script]
}

# ─── Producer ─────────────────────────────────────────────────────────────────

data "archive_file" "producer" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/producer"
  output_path = "${path.module}/../build/producer.zip"
}

resource "aws_cloudwatch_log_group" "producer" {
  name              = "/aws/lambda/${var.project_prefix}-producer"
  retention_in_days = 14
}

resource "aws_iam_role" "producer" {
  name = "${var.project_prefix}-producer"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "producer" {
  name = "${var.project_prefix}-producer"
  role = aws_iam_role.producer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.producer.arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = "bedrock:InvokeModel"
        Resource = "*"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "producer_xray" {
  role       = aws_iam_role.producer.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXrayWriteOnlyAccess"
}

resource "aws_lambda_function" "producer" {
  function_name    = "${var.project_prefix}-producer"
  filename         = data.archive_file.producer.output_path
  source_code_hash = data.archive_file.producer.output_base64sha256
  role             = aws_iam_role.producer.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  memory_size      = 512
  timeout          = 300
  layers           = [aws_lambda_layer_version.shared.arn]

  environment {
    variables = {
      POWERTOOLS_SERVICE_NAME            = "producer"
      POWERTOOLS_LOG_LEVEL               = "INFO"
      POWERTOOLS_METRICS_NAMESPACE       = "ZeroStars"
      POWERTOOLS_TRACER_CAPTURE_RESPONSE = "false"
      DB_CONNECTION_STRING               = var.db_connection_string
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

  depends_on = [aws_cloudwatch_log_group.producer]
}

# ─── Cover Art ────────────────────────────────────────────────────────────────

data "archive_file" "cover_art" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/cover_art"
  output_path = "${path.module}/../build/cover_art.zip"
}

resource "aws_cloudwatch_log_group" "cover_art" {
  name              = "/aws/lambda/${var.project_prefix}-cover-art"
  retention_in_days = 14
}

resource "aws_iam_role" "cover_art" {
  name = "${var.project_prefix}-cover-art"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "cover_art" {
  name = "${var.project_prefix}-cover-art"
  role = aws_iam_role.cover_art.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.cover_art.arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = "bedrock:InvokeModel"
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.episodes.arn}/*"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "cover_art_xray" {
  role       = aws_iam_role.cover_art.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXrayWriteOnlyAccess"
}

resource "aws_lambda_function" "cover_art" {
  function_name    = "${var.project_prefix}-cover-art"
  filename         = data.archive_file.cover_art.output_path
  source_code_hash = data.archive_file.cover_art.output_base64sha256
  role             = aws_iam_role.cover_art.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  memory_size      = 512
  timeout          = 300
  layers           = [aws_lambda_layer_version.shared.arn]

  environment {
    variables = {
      POWERTOOLS_SERVICE_NAME            = "cover_art"
      POWERTOOLS_LOG_LEVEL               = "INFO"
      POWERTOOLS_METRICS_NAMESPACE       = "ZeroStars"
      POWERTOOLS_TRACER_CAPTURE_RESPONSE = "false"
      S3_BUCKET                          = aws_s3_bucket.episodes.id
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

  depends_on = [aws_cloudwatch_log_group.cover_art]
}

# ─── TTS ──────────────────────────────────────────────────────────────────────

data "archive_file" "tts" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/tts"
  output_path = "${path.module}/../build/tts.zip"
}

resource "aws_cloudwatch_log_group" "tts" {
  name              = "/aws/lambda/${var.project_prefix}-tts"
  retention_in_days = 14
}

resource "aws_iam_role" "tts" {
  name = "${var.project_prefix}-tts"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "tts" {
  name = "${var.project_prefix}-tts"
  role = aws_iam_role.tts.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.tts.arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = aws_secretsmanager_secret.elevenlabs.arn
      },
      {
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.episodes.arn}/*"
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "tts_xray" {
  role       = aws_iam_role.tts.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXrayWriteOnlyAccess"
}

resource "aws_lambda_function" "tts" {
  function_name    = "${var.project_prefix}-tts"
  filename         = data.archive_file.tts.output_path
  source_code_hash = data.archive_file.tts.output_base64sha256
  role             = aws_iam_role.tts.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  memory_size      = 512
  timeout          = 300
  layers           = [aws_lambda_layer_version.shared.arn]

  environment {
    variables = {
      POWERTOOLS_SERVICE_NAME            = "tts"
      POWERTOOLS_LOG_LEVEL               = "INFO"
      POWERTOOLS_METRICS_NAMESPACE       = "ZeroStars"
      POWERTOOLS_TRACER_CAPTURE_RESPONSE = "false"
      S3_BUCKET                          = aws_s3_bucket.episodes.id
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

  depends_on = [aws_cloudwatch_log_group.tts]
}

# ─── Post-Production ──────────────────────────────────────────────────────────

data "archive_file" "post_production" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/post_production"
  output_path = "${path.module}/../build/post_production.zip"
}

resource "aws_cloudwatch_log_group" "post_production" {
  name              = "/aws/lambda/${var.project_prefix}-post-production"
  retention_in_days = 14
}

resource "aws_iam_role" "post_production" {
  name = "${var.project_prefix}-post-production"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "post_production" {
  name = "${var.project_prefix}-post-production"
  role = aws_iam_role.post_production.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.post_production.arn}:*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.episodes.arn,
          "${aws_s3_bucket.episodes.arn}/*",
        ]
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "post_production_xray" {
  role       = aws_iam_role.post_production.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXrayWriteOnlyAccess"
}

resource "aws_lambda_function" "post_production" {
  function_name    = "${var.project_prefix}-post-production"
  filename         = data.archive_file.post_production.output_path
  source_code_hash = data.archive_file.post_production.output_base64sha256
  role             = aws_iam_role.post_production.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  memory_size      = 1024 # ffmpeg video processing requires more memory
  timeout          = 300
  layers = [
    aws_lambda_layer_version.shared.arn,
    aws_lambda_layer_version.ffmpeg.arn,
  ]

  environment {
    variables = {
      POWERTOOLS_SERVICE_NAME            = "post_production"
      POWERTOOLS_LOG_LEVEL               = "INFO"
      POWERTOOLS_METRICS_NAMESPACE       = "ZeroStars"
      POWERTOOLS_TRACER_CAPTURE_RESPONSE = "false"
      DB_CONNECTION_STRING               = var.db_connection_string
      S3_BUCKET                          = aws_s3_bucket.episodes.id
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

  depends_on = [aws_cloudwatch_log_group.post_production]
}

# ─── Site ─────────────────────────────────────────────────────────────────────

data "archive_file" "site" {
  type        = "zip"
  source_dir  = "${path.module}/../lambdas/site"
  output_path = "${path.module}/../build/site.zip"
}

resource "aws_cloudwatch_log_group" "site" {
  name              = "/aws/lambda/${var.project_prefix}-site"
  retention_in_days = 14
}

resource "aws_iam_role" "site" {
  name = "${var.project_prefix}-site"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "site" {
  name = "${var.project_prefix}-site"
  role = aws_iam_role.site.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.site.arn}:*"
      },
      {
        # s3:GetObject needed to generate presigned URLs for audio/video files
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.episodes.arn,
          "${aws_s3_bucket.episodes.arn}/*",
        ]
      },
    ]
  })
}

resource "aws_iam_role_policy_attachment" "site_xray" {
  role       = aws_iam_role.site.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXrayWriteOnlyAccess"
}

resource "aws_lambda_function" "site" {
  function_name    = "${var.project_prefix}-site"
  filename         = data.archive_file.site.output_path
  source_code_hash = data.archive_file.site.output_base64sha256
  role             = aws_iam_role.site.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.12"
  memory_size      = 256
  timeout          = 30
  layers           = [aws_lambda_layer_version.shared.arn]

  environment {
    variables = {
      POWERTOOLS_SERVICE_NAME            = "site"
      POWERTOOLS_LOG_LEVEL               = "INFO"
      POWERTOOLS_METRICS_NAMESPACE       = "ZeroStars"
      POWERTOOLS_TRACER_CAPTURE_RESPONSE = "false"
      DB_CONNECTION_STRING               = var.db_connection_string
      S3_BUCKET                          = aws_s3_bucket.episodes.id
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

  depends_on = [aws_cloudwatch_log_group.site]
}
