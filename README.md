# Agentic Microservice Deployer

Deploy an agentic automation flow as an internal FastAPI microservice on Coolify, accessible only from n8n via the internal Docker network (no public URL).

## What it does

Automates the **full deployment pipeline** for AI agent microservices:

1. Creates a private GitHub repo
2. Links the Coolify GitHub App to the new repo (via API — no manual steps per repo)
3. Pushes your code
4. Creates the Coolify application with the correct endpoint (`/private-github-app`)
5. Configures internal-only network (no public FQDN) 
6. Deploys and monitors healthcheck

## Prerequisites

- `GITHUB_TOKEN` — PAT with `repo` scope
- `COOLIFY_URL` + `COOLIFY_TOKEN` + `COOLIFY_PROJECT_UUID`
- A GitHub App created in Coolify **once** (5 min setup, never again)
- Helper scripts: `execution/github_manager.py` + `execution/coolify_manager.py`

## Install

```bash
npx skills add kevinrivm/agentic-microservice-deployer
```

## Key learnings documented

- Correct Coolify API endpoint for private repos: `/api/v1/applications/private-github-app`
- Granting repo access to GitHub App via `PUT /user/installations/{id}/repositories/{repo_id}`
- Field `domains` (not `fqdn`) to remove public URL
- API key is **optional** for internal services — skill asks user their preference
- `secrets.token_hex(32)` for secure API keys — never hardcoded strings

## Stack

FastAPI · Coolify · GitHub API · Docker · n8n internal network
