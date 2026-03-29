output "state_machine_arn" {
  description = "ARN of the podcast pipeline Step Functions state machine"
  value       = aws_sfn_state_machine.pipeline.arn
}

output "site_url" {
  description = "Public URL of the podcast website"
  value       = "https://${var.domain_name}"
}

output "s3_bucket_name" {
  description = "Name of the S3 bucket holding episode assets"
  value       = aws_s3_bucket.episodes.id
}

output "mcp_function_url" {
  description = "Function URL for the MCP server (used by claude.ai integration)"
  value       = aws_lambda_function_url.mcp.function_url
}
