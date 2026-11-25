# LLM Cost Check

A GitHub Action that estimates LLM API cost changes on pull requests. When someone swaps a model, edits a prompt, or changes `max_tokens`, this action comments a cost breakdown so the team knows what it means for the bill.

## Why?

A one-line model swap (`gpt-4` to `gpt-4o`) can cut your LLM bill in half. A prompt that grew by 500 tokens might add $200/month at scale. This action catches those changes at review time, before they hit production.

## Quick Start

```yaml
# .github/workflows/llm-cost.yml
name: LLM Cost Check

on:
  pull_request:
    types: [opened, synchronize]

permissions:
  pull-requests: write

jobs:
  cost-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: Mansi2221/llm-cost-check@v1
```

No API keys needed. The action reads the diff locally and uses a built-in pricing table.

## What It Detects

- **Model swaps** — `model="gpt-4"` changed to `model="gpt-4o"`
- **Token limit changes** — `max_tokens=4096` changed to `max_tokens=8192`
- **Prompt changes** — added/removed prompt text, system messages, templates
- **Config changes** — any file touching LLM-related parameters

## Example Comment

> ## LLM Cost Check
>
> | File | Change | Model | Est. Input Tokens | Est. Output Tokens | Monthly Cost (est.) |
> |------|--------|-------|------------------:|-------------------:|--------------------:|
> | `src/agent.py` | model swap | `gpt-4o` | 500 | 1,024 | $125.00 |
>
> **Projected monthly cost change:** :green_circle: **-$175.00/mo** (at 10,000 calls/month)

## Inputs

| Input | Description | Default |
|-------|-------------|---------|
| `github-token` | Token for posting PR comments | `${{ github.token }}` |
| `base-ref` | Base ref to diff against | PR base SHA |
| `head-ref` | Head ref | PR head SHA |
| `comment-threshold` | Min cost change (USD) to comment | `0` |
| `calls-per-month` | Estimated monthly LLM calls | `10000` |

## Outputs

| Output | Description |
|--------|-------------|
| `cost-report` | Markdown cost report |
| `has-llm-changes` | `true` if LLM-related changes found |

## Supported Models

Built-in pricing for 24 models across providers:

- **Anthropic** — Claude Opus 4, Sonnet 4, Haiku 3.5, Claude 3 family
- **OpenAI** — GPT-4o, GPT-4o mini, GPT-4 Turbo, GPT-4, o1, o3-mini
- **Google** — Gemini 2.5 Pro, 2.0 Flash, 1.5 Pro, 1.5 Flash
- **Cohere** — Command R+, Command R
- **Mistral** — Large, Small
- **Meta** — Llama 3.1 70B, 8B

Pricing is in `scripts/pricing.json` — PRs to update it are welcome.

## How It Works

1. Fetches the PR diff
2. Scans for LLM-related patterns (`model=`, `max_tokens=`, prompt strings, `messages=[`)
3. Extracts before/after model names and token counts
4. Looks up per-token pricing from the built-in table
5. Projects monthly cost at your configured call volume
6. Comments on the PR with a cost comparison

## License

MIT
