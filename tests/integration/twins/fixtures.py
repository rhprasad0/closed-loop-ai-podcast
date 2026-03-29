"""Fixture data for Digital Twin Universe (DTU) twin servers in integration tests."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# GITHUB_USERS — 5 users with varied profiles
# ---------------------------------------------------------------------------
GITHUB_USERS: dict[str, dict[str, object]] = {
    "torvalds": {
        "login": "torvalds",
        "name": "Linus Torvalds",
        "bio": "Just a random Linux kernel developer",
        "public_repos": 7,
        "followers": 230000,
        "created_at": "2011-09-03T15:26:22Z",
        "html_url": "https://github.com/torvalds",
    },
    "kelseyhightower": {
        "login": "kelseyhightower",
        "name": "Kelsey Hightower",
        "bio": "Developer advocate, Go enthusiast, and Kubernetes contributor",
        "public_repos": 42,
        "followers": 15000,
        "created_at": "2012-04-17T18:09:00Z",
        "html_url": "https://github.com/kelseyhightower",
    },
    "prql-dev": {
        "login": "prql-dev",
        "name": "PRQL Dev",
        "bio": "Building a modern pipelined relational query language",
        "public_repos": 8,
        "followers": 120,
        "created_at": "2022-01-10T09:00:00Z",
        "html_url": "https://github.com/prql-dev",
    },
    "zxkane": {
        "login": "zxkane",
        "name": "Kane Wang",
        "bio": "Cloud-native engineer. Shipping side projects on weekends.",
        "public_repos": 31,
        "followers": 47,
        "created_at": "2014-07-22T11:30:00Z",
        "html_url": "https://github.com/zxkane",
    },
    "iximiuz": {
        "login": "iximiuz",
        "name": "Ivan Velichko",
        "bio": "Container and Linux internals. Writing labs and tools for engineers.",
        "public_repos": 19,
        "followers": 3200,
        "created_at": "2015-03-05T08:44:00Z",
        "html_url": "https://github.com/iximiuz",
    },
}

# ---------------------------------------------------------------------------
# GITHUB_REPOS — 7 repos, 4 with stargazers_count < 10
# ---------------------------------------------------------------------------
GITHUB_REPOS: dict[str, dict[str, object]] = {
    "prql-dev/prql": {
        "name": "prql",
        "full_name": "prql-dev/prql",
        "description": "PRQL is a modern language for transforming data — a simple, powerful, pipelined SQL replacement",
        "stargazers_count": 8432,
        "forks_count": 214,
        "language": "Rust",
        "topics": ["sql", "query-language", "data", "rust", "prql"],
        "created_at": "2022-01-10T09:00:00Z",
        "pushed_at": "2026-03-28T14:22:00Z",
        "open_issues_count": 87,
        "license": {"spdx_id": "Apache-2.0"},
        "owner": {"type": "Organization"},
        "html_url": "https://github.com/prql-dev/prql",
        "default_branch": "main",
    },
    "zxkane/cdk-collections": {
        "name": "cdk-collections",
        "full_name": "zxkane/cdk-collections",
        "description": "A collection of reusable AWS CDK constructs for common serverless patterns",
        "stargazers_count": 6,
        "forks_count": 1,
        "language": "TypeScript",
        "topics": ["aws-cdk", "serverless", "typescript", "aws"],
        "created_at": "2021-09-14T07:20:00Z",
        "pushed_at": "2026-02-10T09:45:00Z",
        "open_issues_count": 3,
        "license": {"spdx_id": "MIT"},
        "owner": {"type": "User"},
        "html_url": "https://github.com/zxkane/cdk-collections",
        "default_branch": "main",
    },
    "iximiuz/ptyme": {
        "name": "ptyme",
        "full_name": "iximiuz/ptyme",
        "description": "Peek inside running processes — a lightweight ptrace-based time profiler for Linux",
        "stargazers_count": 7,
        "forks_count": 0,
        "language": "Go",
        "topics": ["ptrace", "profiling", "linux", "go"],
        "created_at": "2023-06-01T16:00:00Z",
        "pushed_at": "2026-01-15T11:30:00Z",
        "open_issues_count": 1,
        "license": {"spdx_id": "MIT"},
        "owner": {"type": "User"},
        "html_url": "https://github.com/iximiuz/ptyme",
        "default_branch": "main",
    },
    "iximiuz/cdebug": {
        "name": "cdebug",
        "full_name": "iximiuz/cdebug",
        "description": "A swiss army knife of container debugging",
        "stargazers_count": 1240,
        "forks_count": 55,
        "language": "Go",
        "topics": ["containers", "debugging", "docker", "kubernetes"],
        "created_at": "2022-11-20T10:00:00Z",
        "pushed_at": "2026-03-20T08:00:00Z",
        "open_issues_count": 12,
        "license": {"spdx_id": "Apache-2.0"},
        "owner": {"type": "User"},
        "html_url": "https://github.com/iximiuz/cdebug",
        "default_branch": "main",
    },
    "zxkane/s3-upload-proxy": {
        "name": "s3-upload-proxy",
        "full_name": "zxkane/s3-upload-proxy",
        "description": "Minimal Lambda proxy for direct S3 multipart uploads from the browser without exposing AWS credentials",
        "stargazers_count": 4,
        "forks_count": 0,
        "language": "Python",
        "topics": ["aws", "s3", "lambda", "serverless", "upload"],
        "created_at": "2023-03-18T13:00:00Z",
        "pushed_at": "2025-11-22T17:10:00Z",
        "open_issues_count": 0,
        "license": None,
        "owner": {"type": "User"},
        "html_url": "https://github.com/zxkane/s3-upload-proxy",
        "default_branch": "main",
    },
    "kelseyhightower/nocode": {
        "name": "nocode",
        "full_name": "kelseyhightower/nocode",
        "description": "No code is the best code. Write nothing; deploy nowhere.",
        "stargazers_count": 58000,
        "forks_count": 3200,
        "language": None,
        "topics": ["nocode", "best-practices"],
        "created_at": "2019-01-01T00:00:00Z",
        "pushed_at": "2023-05-01T00:00:00Z",
        "open_issues_count": 900,
        "license": {"spdx_id": "Apache-2.0"},
        "owner": {"type": "User"},
        "html_url": "https://github.com/kelseyhightower/nocode",
        "default_branch": "main",
    },
    "iximiuz/iptables-tabler": {
        "name": "iptables-tabler",
        "full_name": "iximiuz/iptables-tabler",
        "description": "Render iptables rules as human-readable ASCII tables",
        "stargazers_count": 9,
        "forks_count": 2,
        "language": "Go",
        "topics": ["iptables", "networking", "linux", "cli"],
        "created_at": "2024-02-14T09:00:00Z",
        "pushed_at": "2026-03-01T12:00:00Z",
        "open_issues_count": 2,
        "license": {"spdx_id": "MIT"},
        "owner": {"type": "User"},
        "html_url": "https://github.com/iximiuz/iptables-tabler",
        "default_branch": "main",
    },
}

# ---------------------------------------------------------------------------
# GITHUB_USER_REPOS — per-user repo summary lists (reference repos in GITHUB_REPOS)
# ---------------------------------------------------------------------------
GITHUB_USER_REPOS: dict[str, list[dict[str, object]]] = {
    "zxkane": [
        {
            "name": "cdk-collections",
            "description": "A collection of reusable AWS CDK constructs for common serverless patterns",
            "stargazers_count": 6,
            "language": "TypeScript",
            "html_url": "https://github.com/zxkane/cdk-collections",
            "pushed_at": "2026-02-10T09:45:00Z",
            "fork": False,
        },
        {
            "name": "s3-upload-proxy",
            "description": "Minimal Lambda proxy for direct S3 multipart uploads from the browser without exposing AWS credentials",
            "stargazers_count": 4,
            "language": "Python",
            "html_url": "https://github.com/zxkane/s3-upload-proxy",
            "pushed_at": "2025-11-22T17:10:00Z",
            "fork": False,
        },
    ],
    "iximiuz": [
        {
            "name": "cdebug",
            "description": "A swiss army knife of container debugging",
            "stargazers_count": 1240,
            "language": "Go",
            "html_url": "https://github.com/iximiuz/cdebug",
            "pushed_at": "2026-03-20T08:00:00Z",
            "fork": False,
        },
        {
            "name": "ptyme",
            "description": "Peek inside running processes — a lightweight ptrace-based time profiler for Linux",
            "stargazers_count": 7,
            "language": "Go",
            "html_url": "https://github.com/iximiuz/ptyme",
            "pushed_at": "2026-01-15T11:30:00Z",
            "fork": False,
        },
        {
            "name": "iptables-tabler",
            "description": "Render iptables rules as human-readable ASCII tables",
            "stargazers_count": 9,
            "language": "Go",
            "html_url": "https://github.com/iximiuz/iptables-tabler",
            "pushed_at": "2026-03-01T12:00:00Z",
            "fork": False,
        },
    ],
    "kelseyhightower": [
        {
            "name": "nocode",
            "description": "No code is the best code. Write nothing; deploy nowhere.",
            "stargazers_count": 58000,
            "language": None,
            "html_url": "https://github.com/kelseyhightower/nocode",
            "pushed_at": "2023-05-01T00:00:00Z",
            "fork": False,
        },
    ],
}

# ---------------------------------------------------------------------------
# GITHUB_READMES — short README strings for repos
# ---------------------------------------------------------------------------
GITHUB_READMES: dict[str, str] = {
    "prql-dev/prql": (
        "PRQL (Pipelined Relational Query Language) is a modern alternative to SQL "
        "designed for readable, composable data transformations. "
        "It compiles to SQL and works with any database that speaks SQL."
    ),
    "zxkane/cdk-collections": (
        "A library of AWS CDK L3 constructs for common serverless patterns including "
        "API Gateway + Lambda stacks and S3-triggered processing pipelines. "
        "Drop these into any CDK app to avoid rewriting the same boilerplate."
    ),
    "iximiuz/ptyme": (
        "ptyme attaches to a running Linux process via ptrace and samples its "
        "call stack at configurable intervals to produce a flame-graph-friendly output. "
        "No recompilation or instrumentation required."
    ),
    "iximiuz/cdebug": (
        "cdebug lets you exec into containers that have no shell, attach ephemeral "
        "sidecar debugger containers, and inspect network namespaces — all from one CLI. "
        "Works with Docker, containerd, and Kubernetes pods."
    ),
    "zxkane/s3-upload-proxy": (
        "A single AWS Lambda function that issues pre-signed S3 URLs and coordinates "
        "multipart uploads so browsers can stream large files directly to S3. "
        "No credentials leave the server."
    ),
    "kelseyhightower/nocode": (
        "The most reliable software is software that does not exist. "
        "This repository contains no code and should be kept that way."
    ),
    "iximiuz/iptables-tabler": (
        "iptables-tabler reads live iptables rules and renders them as ASCII tables "
        "grouped by chain and table, making it easier to audit firewall configurations at a glance. "
        "Supports ip6tables too."
    ),
}

# ---------------------------------------------------------------------------
# FEATURED_DEVELOPERS — 2 usernames previously featured; Discovery agent must exclude them
# ---------------------------------------------------------------------------
FEATURED_DEVELOPERS: list[str] = ["torvalds", "kelseyhightower"]

# ---------------------------------------------------------------------------
# EXA_SEARCH_RESULTS — 5 results; at least 2 point to repos with stargazers_count < 10
# ---------------------------------------------------------------------------
EXA_SEARCH_RESULTS: list[dict[str, object]] = [
    {
        "title": "iximiuz/ptyme",
        "url": "https://github.com/iximiuz/ptyme",
        "id": "exa-001",
        "publishedDate": "2023-06-01T16:00:00.000Z",
        "author": "iximiuz",
        # stargazers_count = 7 (<10) in GITHUB_REPOS
        "text": "ptyme attaches to a running Linux process via ptrace and samples its call stack at configurable intervals.",
    },
    {
        "title": "zxkane/s3-upload-proxy",
        "url": "https://github.com/zxkane/s3-upload-proxy",
        "id": "exa-002",
        "publishedDate": "2023-03-18T13:00:00.000Z",
        "author": "zxkane",
        # stargazers_count = 4 (<10) in GITHUB_REPOS
        "text": "Minimal Lambda proxy for direct S3 multipart uploads from the browser without exposing AWS credentials.",
    },
    {
        "title": "iximiuz/iptables-tabler",
        "url": "https://github.com/iximiuz/iptables-tabler",
        "id": "exa-003",
        "publishedDate": "2024-02-14T09:00:00.000Z",
        "author": "iximiuz",
        # stargazers_count = 9 (<10) in GITHUB_REPOS
        "text": "Render iptables rules as human-readable ASCII tables grouped by chain.",
    },
    {
        "title": "iximiuz/cdebug",
        "url": "https://github.com/iximiuz/cdebug",
        "id": "exa-004",
        "publishedDate": "2022-11-20T10:00:00.000Z",
        "author": "iximiuz",
        # stargazers_count = 1240 (>=10) in GITHUB_REPOS
        "text": "A swiss army knife of container debugging that works with Docker, containerd, and Kubernetes.",
    },
    {
        "title": "prql-dev/prql",
        "url": "https://github.com/prql-dev/prql",
        "id": "exa-005",
        "publishedDate": "2022-01-10T09:00:00.000Z",
        "author": "prql-dev",
        # stargazers_count = 8432 (>=10) in GITHUB_REPOS
        "text": "PRQL is a modern language for transforming data — a simple, powerful, pipelined SQL replacement.",
    },
]

# ---------------------------------------------------------------------------
# SILENT_MP3_BYTES — minimal valid MPEG audio frame (Layer III, 128kbps, 44100Hz, stereo)
# The sync word is 0xFFE0..0xFFFF; 0xFFFA = MPEG1 Layer3 no-CRC stereo.
# This is a single silent MP3 frame (~418 bytes) padded with zeros.
# ---------------------------------------------------------------------------
# fmt: off
SILENT_MP3_BYTES: bytes = (
    # ID3v2 header (minimal, 10 bytes) so decoders recognise the file
    b"ID3"            # magic
    b"\x03\x00"       # version 2.3, no flags
    b"\x00"           # flags
    b"\x00\x00\x00\x0a"  # size = 10 (empty tag body, syncsafe)
    # MPEG1 Layer3, 128 kbps, 44100 Hz, stereo, no padding, no private bit
    # Frame header: FF FB 90 00
    #   FF FB = sync + MPEG1 + Layer3 + no CRC
    #   90    = 128kbps, 44100 Hz, no padding, private=0
    #   00    = stereo, no joint stereo, no copyright, original, no emphasis
    b"\xff\xfb\x90\x00"
    # Side information (32 bytes for stereo MPEG1) — all zeros (silent)
    + b"\x00" * 32
    # Main data — pad to standard 417-byte frame body with zeros (silent frame)
    + b"\x00" * (417 - 32)
)
# fmt: on
