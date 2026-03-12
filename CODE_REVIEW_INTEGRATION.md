# Code Review Agent – Integration Guide

This repo includes a **Code Review Agent** that runs automatically on every Pull Request and posts a review comment.

## What’s included

- **`.github/workflows/code-review.yml`** – GitHub Action that runs on PR open/update.
- **`scripts/code-review-agent.py`** – Script that analyzes the PR diff and produces a markdown review.

## How it works

1. When you open or push to a PR, the workflow runs.
2. It checks out the repo, generates the diff (base branch → PR head), and runs the review script.
3. The script either:
   - **With `OPENAI_API_KEY` set:** Sends the diff to OpenAI and posts an AI-generated review.
   - **Without it:** Runs heuristic checks (e.g. `console.log`, `debugger`, TODOs, possible secrets, `eval`, empty catches) and posts that as the review.
4. The result is posted as a comment on the PR. If the agent already commented, the same comment is updated.

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

For AI reviews instead of only heuristics:

1. In your GitHub repo: **Settings → Secrets and variables → Actions**.
2. Click **New repository secret**.
3. Name: `OPENAI_API_KEY`
4. Value: your [OpenAI API key](https://platform.openai.com/api-keys).

The workflow already uses `OPENAI_API_KEY` when present; no workflow edit needed.

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
- **Add checks:** Extend the `patterns` list in `heuristic_review()` in `scripts/code-review-agent.py` with more regex and messages.

## Troubleshooting

- **No comment on PR:** Check the **Actions** tab for the “Code Review Agent” workflow. Open the run and look for errors (e.g. missing `scripts/code-review-agent.py` or Python failure).
- **“No diff file”:** The “Get PR diff” step writes `pr_diff.txt`. If the step fails, the base ref might be wrong; ensure the PR targets the correct base branch.
- **AI review not running:** Confirm `OPENAI_API_KEY` is set as a repository secret (not an env var in the runner). If the key is invalid, the script falls back to heuristic review and may mention the error in the comment.

That’s it. Once the files are in place and (optionally) `OPENAI_API_KEY` is set, every new or updated PR will get an automatic code review comment.
