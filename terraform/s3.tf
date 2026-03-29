# ─── Episode Assets Bucket ────────────────────────────────────────────────────

resource "aws_s3_bucket" "episodes" {
  bucket = "${var.project_prefix}-episodes-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "episodes" {
  bucket = aws_s3_bucket.episodes.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "episodes" {
  bucket = aws_s3_bucket.episodes.id

  # Allow CloudFront OAC to read cover art; MP3/MP4 are served via presigned URLs (no CF path needed)
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowCloudFrontOACRead"
        Effect = "Allow"
        Principal = {
          Service = "cloudfront.amazonaws.com"
        }
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.episodes.arn}/episodes/*/cover.png"
        Condition = {
          StringEquals = {
            "AWS:SourceArn" = aws_cloudfront_distribution.site.arn
          }
        }
      },
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.episodes]
}
