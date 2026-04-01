# ─── Site Lambda Function URL ─────────────────────────────────────────────────

resource "aws_lambda_function_url" "site" {
  function_name      = aws_lambda_function.site.function_name
  authorization_type = "NONE" # CloudFront is the public entry point; Lambda URL is not directly exposed
}

resource "aws_lambda_permission" "site_function_url" {
  statement_id           = "FunctionURLAllowPublicAccess"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.site.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "site_function_url_invoke" {
  statement_id  = "FunctionURLAllowPublicInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.site.function_name
  principal     = "*"
}

# ─── CloudFront OAC (Origin Access Control for S3 cover art) ─────────────────

resource "aws_cloudfront_origin_access_control" "episodes" {
  name                              = "${var.project_prefix}-episodes"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# ─── ACM Certificate (must be in us-east-1 for CloudFront) ────────────────────
# Provider is already us-east-1 (see main.tf), so no alias needed.

resource "aws_acm_certificate" "site" {
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# ─── Route53 Hosted Zone (existing zone for parent domain) ────────────────────

data "aws_route53_zone" "root" {
  # Derive parent domain: podcast.ryans-lab.click → ryans-lab.click
  name         = join(".", slice(split(".", var.domain_name), 1, length(split(".", var.domain_name))))
  private_zone = false
}

# ─── ACM DNS Validation Record ────────────────────────────────────────────────

resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.site.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = data.aws_route53_zone.root.zone_id
}

resource "aws_acm_certificate_validation" "site" {
  certificate_arn         = aws_acm_certificate.site.arn
  validation_record_fqdns = [for record in aws_route53_record.cert_validation : record.fqdn]
}

# ─── CloudFront Distribution ──────────────────────────────────────────────────

locals {
  # Lambda Function URL format: https://<id>.lambda-url.<region>.on.aws/
  # CloudFront custom_origin_config needs only the domain (no scheme, no trailing slash).
  site_lambda_domain = trimsuffix(replace(aws_lambda_function_url.site.function_url, "https://", ""), "/")
}

resource "aws_cloudfront_distribution" "site" {
  enabled         = true
  is_ipv6_enabled = true
  aliases         = [var.domain_name]
  # PriceClass_100: US/Canada/Europe — cheapest tier, appropriate for a portfolio project
  price_class = "PriceClass_100"

  # Origin 1: Site Lambda Function URL — serves HTML pages
  origin {
    origin_id   = "site-lambda"
    domain_name = local.site_lambda_domain

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # Origin 2: S3 bucket via OAC — serves cover art images at /assets/*
  origin {
    origin_id                = "episodes-s3"
    domain_name              = aws_s3_bucket.episodes.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.episodes.id
  }

  # Default behavior: proxy all requests to the site Lambda (~1 hour TTL for HTML)
  default_cache_behavior {
    target_origin_id       = "site-lambda"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    forwarded_values {
      query_string = true # pass query params so Lambda can handle pagination etc.
      cookies {
        forward = "none"
      }
    }

    min_ttl     = 0
    default_ttl = 3600  # 1 hour
    max_ttl     = 86400 # 24 hours
  }

  # /episodes/* behavior: serve cover art from S3 via OAC (long TTL — images are immutable)
  ordered_cache_behavior {
    path_pattern           = "/episodes/*"
    target_origin_id       = "episodes-s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    min_ttl     = 0
    default_ttl = 86400   # 24 hours
    max_ttl     = 2592000 # 30 days — cover art is immutable once written
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.site.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }
}

# ─── Route53 A Record (alias to CloudFront) ───────────────────────────────────

resource "aws_route53_record" "site" {
  zone_id = data.aws_route53_zone.root.zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.site.domain_name
    zone_id                = aws_cloudfront_distribution.site.hosted_zone_id
    evaluate_target_health = false
  }
}
