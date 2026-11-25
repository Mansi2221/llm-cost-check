#!/usr/bin/env python3
"""Detect LLM-related changes in a git diff and estimate cost impact."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

MODEL_PATTERN = re.compile(
    r"""(?:model\s*[=:]\s*|model_name\s*[=:]\s*|engine\s*[=:]\s*)"""
    r"""["']([a-zA-Z0-9_./-]+)["']""",
    re.IGNORECASE,
)

PROMPT_PATTERNS = [
    re.compile(r"""(?:prompt|system_prompt|user_prompt|template)\s*[=:]\s*["']{1,3}""", re.I),
    re.compile(r"""messages\s*[=:]\s*\[""", re.I),
    re.compile(r"""(?:content|text)\s*[=:]\s*["']{1,3}""", re.I),
]

TOKEN_PATTERN = re.compile(
    r"""(?:max_tokens|max_output_tokens|max_completion_tokens)\s*[=:]\s*(\d+)""",
    re.IGNORECASE,
)

CHARS_PER_TOKEN = 4


@dataclass
class FileChange:
    path: str
    added_models: list[str] = field(default_factory=list)
    removed_models: list[str] = field(default_factory=list)
    added_tokens: int | None = None
    removed_tokens: int | None = None
    added_prompt_chars: int = 0
    removed_prompt_chars: int = 0
    has_prompt_change: bool = False


def parse_diff(diff_text: str) -> list[FileChange]:
    """Parse a unified diff into per-file change records."""
    changes: list[FileChange] = []
    current: FileChange | None = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            match = re.search(r"b/(.+)$", line)
            if match:
                current = FileChange(path=match.group(1))
                changes.append(current)
            continue

        if current is None:
            continue

        if line.startswith("+++") or line.startswith("---"):
            continue

        is_add = line.startswith("+")
        is_remove = line.startswith("-")
        if not is_add and not is_remove:
            continue

        content = line[1:]

        for m in MODEL_PATTERN.finditer(content):
            model_name = m.group(1)
            if is_add:
                current.added_models.append(model_name)
            else:
                current.removed_models.append(model_name)

        token_match = TOKEN_PATTERN.search(content)
        if token_match:
            val = int(token_match.group(1))
            if is_add:
                current.added_tokens = val
            else:
                current.removed_tokens = val

        for pat in PROMPT_PATTERNS:
            if pat.search(content):
                current.has_prompt_change = True
                if is_add:
                    current.added_prompt_chars += len(content)
                else:
                    current.removed_prompt_chars += len(content)
                break

    return [c for c in changes if c.added_models or c.removed_models or c.has_prompt_change]


def estimate_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    pricing: dict,
    calls: int,
) -> float | None:
    """Estimate monthly cost for a model."""
    prices = pricing.get("models", {})
    key = model.lower().strip()

    price = prices.get(key)
    if price is None:
        for pkey, pval in prices.items():
            if pkey in key or key in pkey:
                price = pval
                break

    if price is None:
        return None

    input_cost = (input_tokens / 1_000_000) * price["input"] * calls
    output_cost = (output_tokens / 1_000_000) * price["output"] * calls
    return round(input_cost + output_cost, 2)


def build_report(changes: list[FileChange], pricing: dict, calls_per_month: int) -> str:
    """Build a markdown cost report."""
    lines: list[str] = []
    lines.append("## LLM Cost Check")
    lines.append("")
    lines.append("| File | Change | Model | Est. Input Tokens | Est. Output Tokens | Monthly Cost (est.) |")
    lines.append("|------|--------|-------|------------------:|-------------------:|--------------------:|")

    total_before = 0.0
    total_after = 0.0
    has_data = False

    for change in changes:
        # Determine before/after models
        old_models = change.removed_models or ["(unchanged)"]
        new_models = change.added_models or ["(unchanged)"]

        old_output = change.removed_tokens or 1024
        new_output = change.added_tokens or old_output

        old_input = max(change.removed_prompt_chars, 200) // CHARS_PER_TOKEN
        new_input = max(change.added_prompt_chars, old_input * CHARS_PER_TOKEN) // CHARS_PER_TOKEN

        for model in set(old_models):
            if model == "(unchanged)":
                continue
            cost = estimate_cost(model, old_input, old_output, pricing, calls_per_month)
            if cost is not None:
                total_before += cost
                has_data = True

        for model in set(new_models):
            if model == "(unchanged)":
                continue
            cost = estimate_cost(model, new_input, new_output, pricing, calls_per_month)
            cost_str = f"${cost:,.2f}" if cost is not None else "unknown"
            if cost is not None:
                total_after += cost
                has_data = True
            lines.append(
                f"| `{change.path}` | "
                f"{'model swap' if change.removed_models and change.added_models else 'prompt/config'} | "
                f"`{model}` | "
                f"{new_input:,} | {new_output:,} | {cost_str} |"
            )

        if not change.added_models and not change.removed_models and change.has_prompt_change:
            lines.append(
                f"| `{change.path}` | prompt change | - | "
                f"+{change.added_prompt_chars - change.removed_prompt_chars:,} chars | - | - |"
            )
            has_data = True

    if not has_data:
        return ""

    lines.append("")

    if total_before > 0 or total_after > 0:
        delta = total_after - total_before
        emoji = "\U0001f7e2" if delta <= 0 else ("\U0001f7e1" if delta < 50 else "\U0001f534")
        lines.append(f"**Projected monthly cost change:** {emoji} **${delta:+,.2f}/mo** "
                      f"(at {calls_per_month:,} calls/month)")
        if total_before > 0:
            lines.append(f"  - Before: ${total_before:,.2f}/mo")
        lines.append(f"  - After: ${total_after:,.2f}/mo")
    else:
        lines.append("*LLM-related changes detected but cost could not be estimated (unknown models).*")

    lines.append("")
    lines.append("---")
    lines.append("*Generated by [llm-cost-check](https://github.com/Mansi2221/llm-cost-check)*")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect LLM cost changes in a diff")
    parser.add_argument("--diff", required=True, help="Path to the diff file")
    parser.add_argument("--pricing", required=True, help="Path to pricing JSON")
    parser.add_argument("--calls-per-month", type=int, default=10000)
    args = parser.parse_args()

    diff_text = Path(args.diff).read_text(encoding="utf-8", errors="replace")
    pricing = json.loads(Path(args.pricing).read_text(encoding="utf-8"))

    changes = parse_diff(diff_text)
    if not changes:
        print("No LLM-related changes detected.", file=sys.stderr)
        sys.exit(1)

    report = build_report(changes, pricing, args.calls_per_month)
    if not report:
        print("No LLM-related changes detected.", file=sys.stderr)
        sys.exit(1)

    print(report)
    sys.exit(0)


if __name__ == "__main__":
    main()
