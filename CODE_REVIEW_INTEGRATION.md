# Code Review Agent – Integration Guide

This repo includes a **Code Review Agent** that runs automatically on every Pull Request and posts a review comment. It works **without any API key** using comprehensive heuristic checks; optionally, you can add an API key for AI-powered review.

## What’s included

- **`.github/workflows/code-review.yml`** – GitHub Action that runs on PR open/update.
- **`scripts/code-review-agent.py`** – Script that analyzes the PR diff and produces a markdown review.

## How it works

1. When you open or push to a PR, the workflow runs.
2. It checks out the repo, generates the diff (base branch → PR head), and runs the review script.
3. The script either:
   - **With `OPENAI_API_KEY` set:** Sends the diff to OpenAI and posts an AI-generated review.
   - **Without it:** Runs **extensive heuristic checks** (see below) and posts that as the review.
4. The result is posted as a comment on the PR. If the agent already commented, the same comment is updated.

## Heuristic review (no API key) – what’s covered

When you don’t set an API key, the agent still reviews your code using many pattern-based and structure checks:

### Security
- **Secrets:** Hardcoded passwords, API keys, tokens, AWS credentials, Bearer tokens.
- **Injection:** `eval`, `Function()`, `innerHTML`, `document.write`, `dangerouslySetInnerHTML`, shell/command execution with user input, SQL string formatting, unsafe deserialization (`pickle.loads`, unsafe `yaml.load`).
- **Crypto:** MD5/SHA-1 for security-sensitive use, weak randomness for tokens.

### Code quality
- **Debug:** `console.log`/`debug`/`info`/`warn`, `print` (debug/temp), `debugger`, `var_dump`/`print_r`, test `.only`/`.skip`.
- **TODOs:** `TODO`, `FIXME`, `XXX`, `HACK`, `NotImplementedError`, “implement later” placeholders.
- **Error handling:** Empty or silent catch blocks, bare `except:`, broad `except Exception`, `@SuppressWarnings("all")`.
- **Imports:** Wildcard imports, `# type: ignore`, `@ts-ignore`/`@ts-nocheck`.

### Performance & async
- Arbitrary `sleep`, sequential `await` in loops, deep promise nesting.

### Style & maintainability
- Pylint/ESLint/noqa disabled, `any` type, very long lines, very deep indentation.

### Deprecated / risky APIs
- jQuery `.each`, deprecated Date APIs, deprecated React lifecycles, `createClass`.

### Language-specific
- **Python:** Mutable default args, bare except, `os.system` with user input.
- **JavaScript/TypeScript:** Loose equality with null/undefined, `new Array()`/`new Object()`, empty `.then()`.
- **Shell:** `curl | sh`, dangerous `rm -rf`.
- **HTML/JSX/TSX:** Images without `alt`, clickable `div` without semantics, `tabIndex` misuse.

### Structure
- Very large changes (e.g. >400 added lines), long lines (>120 chars), very deep indentation.

You can extend these by editing the `patterns` and related lists in `scripts/code-review-agent.py`.

## How to integrate into your GitHub repo

### 1. Copy the files into your repo

From this repo, copy into your project:

- `.github/workflows/code-review.yml`
- `scripts/code-review-agent.py`

So your repo has:

```
your-repo/
├── .github/
│   └── workflows/
│       └── code-review.yml
└── scripts/
    └── code-review-agent.py
```

Commit and push (e.g. to `main` or your default branch).

### 2. (Optional) Enable AI-powered reviews

For AI reviews in addition to (or instead of) heuristics:

1. In your GitHub repo: **Settings → Secrets and variables → Actions**.
2. Click **New repository secret**.
3. Name: `OPENAI_API_KEY`
4. Value: your [OpenAI API key](https://platform.openai.com/api-keys).

The workflow already uses `OPENAI_API_KEY` when present; no workflow edit needed. If the key is missing or invalid, the agent still runs and posts the heuristic review.

### 3. Open a PR

Create a new branch, make changes, and open a Pull Request. The Code Review Agent will run and post (or update) a comment with the review.

## Permissions

The workflow uses:

- `contents: read` – to fetch the repo and diff.
- `pull-requests: write` – to post/update the review comment.
- `issues: write` – needed for PR comments.

These are set in the workflow file. No extra permission setup is required.

## Customization

- **Change when it runs:** Edit `on.pull_request.types` in `.github/workflows/code-review.yml` (e.g. add `edited` if you want).
- **Change AI model:** In `scripts/code-review-agent.py`, in `openai_review()`, change `model="gpt-4o-mini"` to e.g. `"gpt-4o"`.
- **Add or tune checks:** Edit the pattern lists in `scripts/code-review-agent.py` (e.g. `SECRETS_PATTERNS`, `DEBUG_PATTERNS`, `PYTHON_PATTERNS`, etc.) and the `analyze_structure()` logic.

## Troubleshooting

- **No comment on PR:** Check the **Actions** tab for the “Code Review Agent” workflow. Open the run and look for errors (e.g. missing `scripts/code-review-agent.py` or Python failure).
- **“No diff file”:** The “Get PR diff” step writes `pr_diff.txt`. If the step fails, the base ref might be wrong; ensure the PR targets the correct base branch.
- **AI review not running:** Confirm `OPENAI_API_KEY` is set as a repository secret (not an env var in the runner). If the key is invalid, the script falls back to heuristic review and may mention the error in the comment.

That’s it. With the files in place, every new or updated PR gets an automatic code review comment—**no API key required**. Add `OPENAI_API_KEY` when you want AI-powered review on top of the heuristics.
