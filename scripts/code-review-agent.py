#!/usr/bin/env python3
"""
Code Review Agent - Analyzes PR diffs and produces review feedback.
Uses OpenAI for deep review when OPENAI_API_KEY is set; otherwise runs
comprehensive heuristic checks (security, quality, style, multi-language).
No API key required for full heuristic review.
"""

import os
import re
import sys
from pathlib import Path
from collections import defaultdict


def load_diff(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def get_file_extension(file_path: str) -> str:
    """Return lowercase extension for language-specific rules."""
    if not file_path or file_path == "unknown":
        return ""
    p = Path(file_path)
    return (p.suffix or "").lower()


def parse_diff_by_file(diff: str) -> dict:
    """Parse diff into per-file added lines. Returns { file_path: [ (line_num, code_line), ... ] }."""
    lines = diff.split("\n")
    by_file = defaultdict(list)
    current_file = None
    for i, line in enumerate(lines):
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
        elif line.startswith("+") and not line.startswith("+++"):
            code = line[1:]
            if current_file:
                by_file[current_file].append((i + 1, code))
    return dict(by_file)


# ---------------------------------------------------------------------------
# Heuristic patterns: (regex, message, optional_extensions)
# Empty extensions = apply to all; otherwise list e.g. [".py", ".js"]
# ---------------------------------------------------------------------------

# Security – secrets & credentials
SECRETS_PATTERNS = [
    (r"password\s*=\s*['\"]", "Possible hardcoded password – use env/secrets"),
    (r"api[_-]?key\s*=\s*['\"]", "Possible hardcoded API key – use secrets"),
    (r"secret\s*=\s*['\"]", "Possible hardcoded secret – use secrets"),
    (r"token\s*=\s*['\"][a-zA-Z0-9_-]{20,}", "Possible hardcoded token – use env/secrets"),
    (r"aws_access_key|aws_secret", "AWS credentials in code – use IAM/env"),
    (r"private[_-]?key\s*=\s*['\"]", "Private key in code – use secure storage"),
    (r"Bearer\s+['\"][a-zA-Z0-9_.-]+['\"]", "Hardcoded Bearer token – use env/headers"),
]

# Security – injection & XSS
INJECTION_PATTERNS = [
    (r"eval\s*\(", "Avoid eval() – security and maintainability risk"),
    (r"Function\s*\(", "Avoid Function() – similar to eval"),
    (r"innerHTML\s*=", "Prefer textContent or safe DOM APIs to avoid XSS"),
    (r"document\.write\s*\(", "Avoid document.write – XSS risk"),
    (r"dangerouslySetInnerHTML", "Sanitize content when using dangerouslySetInnerHTML"),
    (r"exec\s*\(|os\.system\s*\(|subprocess\.(call|run).*shell\s*=\s*True", "Shell/command injection risk – avoid shell=True or unsanitized input"),
    (r"execute\s*\(.*%s|\.format\s*\(.*SELECT|f['\"].*SELECT", "Possible SQL string formatting – use parameterized queries"),
    (r"pickle\.loads\s*\(|yaml\.load\s*\([^,)]+\)", "Unsafe deserialization – use safe loaders (e.g. yaml.safe_load)"),
]

# Security – crypto & auth
CRYPTO_PATTERNS = [
    (r"md5\s*\(|\.md5\s*\(|hashlib\.md5", "MD5 is weak for security – use SHA-256 or bcrypt for passwords"),
    (r"sha1\s*\(|\.sha1\s*\(|hashlib\.sha1", "SHA-1 is weak for security – prefer SHA-256"),
    (r"random\.randint|Math\.random\s*\(\s*\)\s*for\s*.*token", "Use crypto.randomBytes / secrets for tokens"),
]

# Code quality – debug & leftovers
DEBUG_PATTERNS = [
    (r"console\.log\s*\(", "Consider removing or replacing with proper logging before merge"),
    (r"console\.(debug|info|warn)\s*\(", "Consider removing debug/info/warn or gating behind log level"),
    (r"print\s*\(\s*['\"]?(debug|test|temp)", "Remove or gate debug print statements"),
    (r"debugger\s*;?", "Remove debugger statement before merging"),
    (r"var_dump|print_r\s*\(", "Remove debug output before merge"),
    (r"\.only\s*\(|\.skip\s*\(|it\.only|describe\.only", "Remove .only/.skip from tests before merge"),
]

# Code quality – TODOs & placeholders
TODO_PATTERNS = [
    (r"\bTODO\b", "Consider addressing or tracking TODO before merge"),
    (r"\bFIXME\b", "Consider addressing or tracking FIXME before merge"),
    (r"\bXXX\b", "Consider addressing or tracking XXX before merge"),
    (r"\bHACK\b", "Document or fix HACK before merge"),
    (r"raise\s+NotImplementedError", "Implement or track NotImplementedError"),
    (r"pass\s*#.*implement", "Consider implementing or tracking"),
    (r"\.\.\.\s*#.*later", "Placeholder – consider implementing"),
]

# Error handling
ERROR_HANDLING_PATTERNS = [
    (r"\.catch\s*\(\s*\)", "Empty catch block – handle or log errors"),
    (r"\.catch\s*\(\s*\(\)\s*=>\s*\{\s*\}\s*\)", "Empty catch block – handle or log errors"),
    (r"\.catch\s*\(\s*_\s*\)", "Silent catch – consider logging or rethrowing"),
    (r"except\s*:\s*$", "Bare except – specify exception type"),
    (r"except\s+Exception\s*:", "Catching Exception is broad – catch specific exceptions where possible"),
    (r"except\s*:\s*pass", "Bare except + pass – errors are swallowed"),
    (r"except\s*:\s*continue", "Bare except – specify exception type"),
    (r"@SuppressWarnings\s*\(\s*[\"']all[\"']\s*\)", "Suppressing all warnings – prefer narrowing scope"),
]

# Imports & dependencies
IMPORT_PATTERNS = [
    (r"import\s+\*\s+", "Avoid wildcard imports – be explicit"),
    (r"from\s+\S+\s+import\s+\*", "Avoid wildcard imports – be explicit"),
    (r"^\s*#\s*type:\s*ignore", "Type ignore – consider fixing the underlying issue"),
    (r"@ts-ignore|@ts-nocheck", "Consider fixing type issues instead of ignoring"),
]

# Performance & async
PERF_PATTERNS = [
    (r"sleep\s*\(\s*\d+\s*\)", "Arbitrary sleep – consider events/retries or document why needed"),
    (r"for\s*\([^)]+\)\s*\{\s*await\s+", "Sequential awaits in loop – consider Promise.all for parallelism"),
    (r"\.then\s*\([^)]*\.then\s*\([^)]*\.then", "Deep promise nesting – consider async/await"),
]

# Complexity & style
STYLE_PATTERNS = [
    (r"^\s*#\s*pylint:\s*disable", "Pylint disabled – consider fixing the issue"),
    (r"^\s*#\s*noqa", "Linter suppressed – consider fixing the issue"),
    (r"eslint-disable-next-line", "ESLint disabled – consider fixing the issue"),
    (r"any\s*\)\s*;?\s*$", "Avoid 'any' type when possible – use proper types"),
    (r"\.length\s*>\s*500|len\s*\(\s*\w+\s*\)\s*>\s*500", "Very long line/block – consider splitting"),
]

# Deprecated / risky APIs
DEPRECATED_PATTERNS = [
    (r"\.each\s*\(", "jQuery .each – consider native forEach or modern iteration"),
    (r"new\s+Date\s*\(\s*\)\s*\.getYear\s*\(", "getYear() is deprecated – use getFullYear()"),
    (r"componentWillMount|componentWillReceiveProps|UNSAFE_", "Deprecated React lifecycle – use recommended alternatives"),
    (r"createClass\s*\(", "React.createClass is deprecated – use class or function components"),
]

# Accessibility (HTML/JSX/TSX)
A11Y_PATTERNS = [
    (r"<img\s+(?![^>]*\balt=)", "Image may need alt – add alt for accessibility"),
    (r"<div\s+[^>]*onClick\s*=", "Clickable div – consider <button> or role='button' + keyboard"),
    (r"tabIndex\s*=\s*[2-9]", "Avoid tabIndex > 1 – can break tab order"),
]

# Language-specific: Python
PYTHON_PATTERNS = [
    (r"assert\s+.*\s+in\s+production", "Avoid assert for runtime checks in production"),
    (r"def\s+\w+\s*\([^)]*=\s*\[\]", "Mutable default (list) – use None and assign inside"),
    (r"def\s+\w+\s*\([^)]*=\s*\{\}", "Mutable default (dict) – use None and assign inside"),
    (r"except\s*:\s*$", "Bare except – use except Exception or specific type"),
    (r"import\s+os\s*;\s*os\.system", "Avoid os.system with user input"),
]

# Language-specific: JavaScript/TypeScript
JS_PATTERNS = [
    (r"==\s*null|!=\s*null", "Prefer === / !== for null checks"),
    (r"typeof\s+\w+\s*==\s*['\"]undefined['\"]", "Prefer strict equality for undefined checks"),
    (r"new\s+Array\s*\(|new\s+Object\s*\(\)", "Prefer [] and {} literals"),
    (r"\.then\s*\(\s*function\s*\(\)\s*\{\s*\}\s*\)", "Empty then handler – handle or remove"),
]

# Language-specific: Shell
SHELL_PATTERNS = [
    (r"curl\s+.*\s*\|\s*sh\s*$", "Piping curl to sh is risky – verify URL and use checksums"),
    (r"rm\s+-rf\s+/\s*|rm\s+-rf\s+\$\{", "Dangerous rm – ensure path is validated"),
]

# Build a single list with (pattern, message, extensions)
def _build_pattern_list():
    out = []
    for pattern, msg in (
        SECRETS_PATTERNS + INJECTION_PATTERNS + CRYPTO_PATTERNS +
        DEBUG_PATTERNS + TODO_PATTERNS + ERROR_HANDLING_PATTERNS +
        IMPORT_PATTERNS + PERF_PATTERNS + STYLE_PATTERNS + DEPRECATED_PATTERNS
    ):
        out.append((pattern, msg, []))  # all files
    for pattern, msg in A11Y_PATTERNS:
        out.append((pattern, msg, [".html", ".jsx", ".tsx", ".vue"]))
    for pattern, msg in PYTHON_PATTERNS:
        out.append((pattern, msg, [".py"]))
    for pattern, msg in JS_PATTERNS:
        out.append((pattern, msg, [".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"]))
    for pattern, msg in SHELL_PATTERNS:
        out.append((pattern, msg, [".sh", ".bash", ".zsh"]))
    return out


HEURISTIC_PATTERNS = _build_pattern_list()

# Files to skip (agent's own code, lockfiles, generated)
SKIP_PATHS = (
    "scripts/code-review-agent.py",
    "code-review-agent.py",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Pipfile.lock",
    ".min.js",
    ".bundle.js",
    "dist/",
    "build/",
    "__pycache__",
    ".pyc",
)


def should_skip_file(file_path: str) -> bool:
    if not file_path or file_path == "unknown":
        return True
    return any(skip in file_path for skip in SKIP_PATHS)


def applies_to_file(pattern_extensions: list, ext: str) -> bool:
    if not pattern_extensions:
        return True
    return ext in pattern_extensions


def run_heuristic_checks(by_file: dict) -> list:
    """Run all heuristic patterns on parsed diff. Returns list of findings."""
    findings = []
    for file_path, line_tuples in by_file.items():
        if should_skip_file(file_path):
            continue
        ext = get_file_extension(file_path)
        for line_num, code in line_tuples:
            for pattern, message, exts in HEURISTIC_PATTERNS:
                if not applies_to_file(exts, ext):
                    continue
                if re.search(pattern, code, re.IGNORECASE):
                    findings.append({
                        "file": file_path,
                        "line": line_num,
                        "code": code.strip()[:100],
                        "message": message,
                        "severity": "warning",
                    })
                    break  # one finding per line per pattern set
    return findings


def analyze_structure(by_file: dict) -> list:
    """Structure/complexity hints from the diff (no regex, just metrics)."""
    hints = []
    for file_path, line_tuples in by_file.items():
        if should_skip_file(file_path):
            continue
        added = len(line_tuples)
        if added > 400:
            hints.append({
                "file": file_path,
                "message": f"Large change ({added} added lines) – consider splitting into smaller PRs or commits.",
            })
        long_lines = [c for _, c in line_tuples if len(c) > 120]
        if long_lines:
            hints.append({
                "file": file_path,
                "message": f"Long lines detected ({len(long_lines)} over 120 chars) – consider wrapping for readability.",
            })
        # Deep nesting (rough: count indent jumps in added lines)
        for _, code in line_tuples:
            stripped = code.lstrip()
            if stripped and len(code) - len(stripped) > 24:  # > 6 levels at 4 spaces
                hints.append({
                    "file": file_path,
                    "message": "Very deep indentation – consider extracting functions to reduce nesting.",
                })
                break
    return hints


def heuristic_review(diff: str) -> str:
    """Run pattern-based and structure checks; return markdown report."""
    by_file = parse_diff_by_file(diff)
    findings = run_heuristic_checks(by_file)
    hints = analyze_structure(by_file)

    md = ["## 🤖 Code Review Agent", ""]
    if not findings and not hints:
        md.extend([
            "✅ **Heuristic checks passed.** No obvious issues found in the diff.",
            "",
            "_Tip: Add `OPENAI_API_KEY` as a repository secret for AI-powered review._",
        ])
        return "\n".join(md)

    if findings:
        md.append("### ⚠️ Findings")
        md.append("")
        by_f = defaultdict(list)
        for f in findings:
            by_f[f["file"]].append(f)
        for file_path, items in sorted(by_f.items()):
            md.append(f"**`{file_path}`**")
            for item in items:
                md.append(f"- {item['message']}")
                md.append(f"  - `{item['code']}`")
            md.append("")

    if hints:
        md.append("### 📐 Structure / complexity")
        md.append("")
        for h in hints:
            md.append(f"- **`{h['file']}`**: {h['message']}")
        md.append("")

    md.append("---")
    md.append("_No API key: review is heuristic-only. Add `OPENAI_API_KEY` for deeper AI review._")
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
        print("## 🤖 Code Review Agent\n\n⚠️ No diff file found at `{}`.".format(diff_path), file=sys.stderr)
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
