# Development Container

VS Code devcontainer for the "0 Stars, 10/10" podcast pipeline.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) running
- [VS Code](https://code.visualstudio.com/) with the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)
- AWS CLI configured on your host machine (`~/.aws/config` and `~/.aws/credentials`)

## Getting Started

1. Open this repo in VS Code
2. When prompted, click **"Reopen in Container"** — or run the command palette action: `Dev Containers: Reopen in Container`
3. Wait for the container to build (first time takes 3-5 minutes, subsequent opens are fast)
4. The post-create script will print all tool versions to confirm everything installed correctly

## What's Included

| Tool | Purpose |
|------|---------|
| Python 3.12 | Lambda runtime |
| Terraform | Infrastructure as code |
| AWS CLI v2 | AWS resource management |
| AWS SAM CLI | Local Lambda testing |
| Claude Code | AI-assisted development |
| Node.js 22 | Claude Code runtime |
| PostgreSQL client | Database access (psql) |
| ffmpeg | Audio/video processing |
| Docker-in-Docker | Container builds inside the devcontainer |
| Ruff | Python linting and formatting |
| jq, zip, curl | General utilities |

### Python Packages (pre-installed)

- `boto3` + `boto3-stubs` (Bedrock, S3, Secrets Manager type hints)
- `psycopg2-binary` (PostgreSQL driver)
- `jinja2` (HTML templating for site Lambda)
- `requests` (HTTP client for external APIs)
- `ruff` (linter/formatter)

### VS Code Extensions (auto-installed)

Python, Pylance, Ruff, Terraform, Docker, AWS Toolkit, YAML, Mermaid preview, GitLens

## AWS Credentials

Your host `~/.aws` directory is bind-mounted read-only into the container. Any profiles and credentials you have locally will be available inside the container.

**If `~/.aws` doesn't exist on your host**, the container will fail to start. Fix this by running on your host:

```bash
aws configure
```

Or, to skip the mount entirely, remove the `mounts` entry from `devcontainer.json` and configure credentials inside the container instead.

Verify credentials work inside the container:

```bash
aws sts get-caller-identity
```

## Claude Code

Claude Code is pre-installed but requires authentication on first use. After the container starts:

```bash
claude
```

Follow the prompts to log in. Your authentication persists across container rebuilds if you use a volume for the home directory.

## Rebuilding the Container

Rebuild when the `Dockerfile` or `devcontainer.json` changes:

- Command palette: `Dev Containers: Rebuild Container`
- Or: `Dev Containers: Rebuild Without Cache` for a clean build

The post-create script runs again after each rebuild.

## Troubleshooting

**Container fails to start with mount error**
Your host `~/.aws` directory likely doesn't exist. Run `aws configure` on your host, or remove the mount from `devcontainer.json`.

**Docker commands fail inside the container**
The Docker-in-Docker feature needs a moment to start the daemon after the container opens. Wait a few seconds and retry, or check `docker info`.

**Terraform commands fail**
Run `terraform init` in the `terraform/` directory. The post-create script does this automatically if the directory exists.

**SAM local invoke fails**
SAM uses Docker-in-Docker to run Lambda containers. Ensure `docker info` succeeds first. SAM commands are slower in devcontainers due to nested container overhead.
