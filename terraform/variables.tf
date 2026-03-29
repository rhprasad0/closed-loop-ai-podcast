variable "elevenlabs_api_key" {
  type        = string
  sensitive   = true
  description = "ElevenLabs API key for TTS generation"
}

variable "exa_api_key" {
  type        = string
  sensitive   = true
  description = "Exa Search API key for the Discovery agent"
}

variable "db_connection_string" {
  type        = string
  sensitive   = true
  description = "Postgres connection string (postgresql://user:pass@host:5432/dbname?sslmode=require)"
}

variable "domain_name" {
  type        = string
  default     = "podcast.ryans-lab.click"
  description = "Domain name for the podcast site"
}

variable "project_prefix" {
  type        = string
  default     = "zerostars"
  description = "Prefix applied to resource names"
}

variable "alert_email" {
  type        = string
  default     = ""
  description = "Email address for CloudWatch alarm notifications. Empty string disables the SNS subscription."
}

variable "mcp_allowed_principal" {
  type        = string
  description = "IAM principal ARN permitted to invoke the MCP Lambda Function URL"
}

variable "pipeline_failure_threshold" {
  type        = number
  default     = 1
  description = "ExecutionsFailed count that triggers the pipeline failure alarm"
}

variable "lambda_error_threshold" {
  type        = number
  default     = 1
  description = "Per-Lambda error count that triggers a Lambda error alarm"
}

variable "lambda_timeout_threshold_ms" {
  type        = number
  default     = 270000 # 90% of the 300s Lambda timeout
  description = "Per-Lambda p99 duration (ms) that triggers a Lambda timeout alarm"
}

variable "producer_fail_threshold" {
  type        = number
  default     = 3
  description = "Consecutive Producer FAIL verdicts that trigger the producer failure alarm"
}
