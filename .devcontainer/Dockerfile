FROM mcr.microsoft.com/devcontainers/python:3.12

ARG TERRAFORM_VERSION=1.11.2
ARG NODE_MAJOR=22

# System packages
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        unzip \
        zip \
        jq \
        git \
        gnupg \
        lsb-release \
        ffmpeg \
        postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Terraform
RUN curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
        -o /tmp/terraform.zip \
    && unzip /tmp/terraform.zip -d /usr/local/bin/ \
    && rm /tmp/terraform.zip \
    && terraform version

# Node.js (required for Claude Code)
RUN curl -fsSL https://deb.nodesource.com/setup_${NODE_MAJOR}.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && node --version && npm --version

# Claude Code
RUN npm install -g @anthropic-ai/claude-code \
    && claude --version

# AWS SAM CLI
RUN curl -fsSL "https://github.com/aws/aws-sam-cli/releases/latest/download/aws-sam-cli-linux-x86_64.zip" \
        -o /tmp/sam.zip \
    && unzip /tmp/sam.zip -d /tmp/sam-install \
    && /tmp/sam-install/install \
    && rm -rf /tmp/sam.zip /tmp/sam-install \
    && sam --version

# AWS CLI v2
RUN curl -fsSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" \
        -o /tmp/awscliv2.zip \
    && unzip -q /tmp/awscliv2.zip -d /tmp \
    && /tmp/aws/install --update \
    && rm -rf /tmp/awscliv2.zip /tmp/aws \
    && aws --version

# GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/* \
    && gh --version

# Python dev tools + runtime deps
RUN pip install --no-cache-dir \
        ruff \
        boto3 \
        "boto3-stubs[bedrock-runtime,s3,secretsmanager]" \
        psycopg2-binary \
        jinja2 \
        requests \
        aws-lambda-powertools \
        mypy \
        pytest \
        pytest-cov \
        moto

# uv (provides uvx, used by Claude Code MCP servers)
RUN pip install --no-cache-dir uv
