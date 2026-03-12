#!/usr/bin/env python3
"""
Code Review Agent - Analyzes PR diffs and produces review feedback.
Uses OpenAI for deep review when OPENAI_API_KEY is set; otherwise runs heuristic checks.
"""

import os
import re
import sys
from pathlib import Path


def load_diff(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def heuristic_review(diff: str) -> str:
    """Run pattern-based checks on the diff and return markdown report."""
    lines = diff.split("\n")
    findings = []
    current_file = None

    # Patterns to check
    patterns = [
        (r"console\.log\s*\(", "Consider removing or replacing with proper logging before merge"),
        (r"debugger\s*;?", "Remove debugger statement before merging"),
        (r"TODO|FIXME|XXX", "Consider addressing or tracking before merge"),
        (r"password\s*=\s*['\"]", "Possible hardcoded password - use env/secrets"),
        (r"api[_-]?key\s*=\s*['\"]", "Possible hardcoded API key - use secrets"),
        (r"eval\s*\(", "Avoid eval() - security and maintainability risk"),
        (r"innerHTML\s*=", "Prefer textContent or safe DOM APIs to avoid XSS"),
        (r"\.catch\s*\(\s*\)", "Empty catch block - handle or log errors"),
        (r"except\s*:\s*$", "Bare except - specify exception type"),
        (r"import \* ", "Avoid wildcard imports - be explicit"),
        (r"^\s*#\s*type:\s*ignore", "Type ignore - consider fixing the underlying issue"),
    ]

    # Don't flag the review agent's own script (it contains pattern strings as data)
    skip_paths = ("scripts/code-review-agent.py", "code-review-agent.py")

    for i, line in enumerate(lines):
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
        if line.startswith("+") and not line.startswith("+++"):
            if current_file and any(skip in current_file for skip in skip_paths):
                continue
            code = line[1:]
            for pattern, message in patterns:
                if re.search(pattern, code, re.IGNORECASE):
                    findings.append({
                        "file": current_file or "unknown",
                        "line": i + 1,
                        "code": code.strip()[:80],
                        "message": message,
                    })
                    break

    # Build markdown
    md = ["## 🤖 Code Review Agent", ""]
    if not findings:
        md.extend([
            "✅ **Heuristic checks passed.** No obvious issues found in the diff.",
            "",
            "_Tip: Add `OPENAI_API_KEY` as a repository secret for AI-powered review._",
        ])
        return "\n".join(md)

    md.append("### ⚠️ Findings")
    md.append("")
    by_file = {}
    for f in findings:
        by_file.setdefault(f["file"], []).append(f)
    for file_path, items in by_file.items():
        md.append(f"**`{file_path}`**")
        for item in items:
            md.append(f"- {item['message']}")
            md.append(f"  - `{item['code']}`")
        md.append("")
    md.append("---")
    md.append("_Run with `OPENAI_API_KEY` secret for deeper AI review._")
    return "\n".join(md)


def openai_review(diff: str) -> str:
    """Use OpenAI to review the diff. Requires OPENAI_API_KEY."""
    try:
        from openai import OpenAI
    except ImportError:
        return heuristic_review(diff) + "\n\n_Install `openai` for AI review: `pip install openai`_"

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return heuristic_review(diff)

    client = OpenAI(api_key=api_key)
    prompt = """You are a thorough code reviewer. Review the following git diff for a pull request.

Focus on:
- Correctness and potential bugs
- Security issues (injection, secrets, auth)
- Performance and scalability
- Readability and maintainability
- Error handling and edge cases
- Consistency with common best practices

Respond in markdown with:
1. A short summary (2-3 sentences)
2. "What looks good" (if anything)
3. "Suggestions / Issues" with clear, actionable items
4. Optional "Minor / Nitpicks"

Keep the review concise but useful. Be constructive.

DIFF:
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a helpful code reviewer. Output only valid markdown."},
                {"role": "user", "content": prompt + "\n```diff\n" + diff[:120000] + "\n```"},
            ],
            max_tokens=2000,
        )
        body = response.choices[0].message.content
        return "## 🤖 Code Review Agent\n\n" + body
    except Exception as e:
        return heuristic_review(diff) + f"\n\n_AI review failed ({e}); heuristic results above._"


def main():
    if len(sys.argv) < 2:
        print("Usage: code-review-agent.py <diff_file>", file=sys.stderr)
        sys.exit(1)
    diff_path = sys.argv[1]
    if not Path(diff_path).exists():
        print(f"## 🤖 Code Review Agent\n\n⚠️ No diff file found at `{diff_path}`.", file=sys.stderr)
        sys.exit(1)
    diff = load_diff(diff_path)
    if not diff.strip():
        print("## 🤖 Code Review Agent\n\nNo changes in diff to review.")
        return
    if os.environ.get("OPENAI_API_KEY"):
        report = openai_review(diff)
    else:
        report = heuristic_review(diff)
    print(report)


if __name__ == "__main__":
    main()
