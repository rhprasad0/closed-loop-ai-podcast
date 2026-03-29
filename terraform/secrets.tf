# ─── ElevenLabs API Key ───────────────────────────────────────────────────────

resource "aws_secretsmanager_secret" "elevenlabs" {
  name        = "${var.project_prefix}/elevenlabs-api-key"
  description = "ElevenLabs API key for TTS generation"
}

resource "aws_secretsmanager_secret_version" "elevenlabs" {
  secret_id     = aws_secretsmanager_secret.elevenlabs.id
  secret_string = var.elevenlabs_api_key
}

# ─── Exa API Key ──────────────────────────────────────────────────────────────

resource "aws_secretsmanager_secret" "exa" {
  name        = "${var.project_prefix}/exa-api-key"
  description = "Exa Search API key for the Discovery agent"
}

resource "aws_secretsmanager_secret_version" "exa" {
  secret_id     = aws_secretsmanager_secret.exa.id
  secret_string = var.exa_api_key
}
