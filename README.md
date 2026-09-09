# GitHub Daily Commit Automator

A centralized, secure, and robust GitHub Actions automation system that pushes a daily `git commit --allow-empty` to the default branch of every repository owned by your GitHub account.

---

## Key Features

- **Centralized & Clean**: Resides in a single dedicated repository. No need to install workflows into every individual repository.
- **Dynamic Discovery**: Uses the GitHub REST API (`/user/repos`) to automatically find all repositories you own—including newly created repositories, both public and private.
- **True Git Empty Commits**:
  ```bash
  git commit --allow-empty -m "chore: daily automated commit"
  ```
  **Zero file modifications**. No fake files or synthetic code edits.
- **Fail-Safe & Resilient**: Errors on protected branches or repositories with restricted write permissions are caught, classified, and reported without aborting processing of other repositories.
- **Zero Third-Party Dependencies**: Pure Python 3 standard library (`urllib`, `subprocess`, `tempfile`, `json`).
- **Security-First**: Uses GitHub Secret masking (`::add-mask::`) and credential sanitization so tokens are never exposed in terminal outputs or commit logs.
- **Rich Summaries**: Publishes a formatted Markdown table directly to GitHub Actions `$GITHUB_STEP_SUMMARY`.

---

## Architecture Overview

```
github-daily-committer/
├── .github/
│   └── workflows/
│       └── daily-commits.yml       # Scheduled (24h) and manual dispatch workflow
├── commit_automator.py             # Discovery, clone, empty-commit, and push engine
├── requirements.txt                # Standard library reference
├── .gitignore                      # Python and temp file exclusions
└── README.md                       # Complete setup and operations guide
```

---

## 1. Token Creation (Least Privilege)

Cross-repository pushing requires a Personal Access Token (PAT).

### Option A: Fine-Grained Personal Access Token (Recommended)
1. In GitHub, go to **Settings** → **Developer Settings** → **Personal access tokens** → **Fine-grained tokens**.
2. Click **Generate new token**.
3. **Token name**: `daily-commit-automator`
4. **Expiration**: Choose an expiration period (e.g. 90 days, 1 year).
5. **Repository access**: Select **All repositories** (or choose specific repositories).
6. **Permissions**:
   - **Repository permissions** → **Contents**: Select **Access: Read and write**.
   - *(Note: `Metadata: Read-only` will be granted automatically).*
   - Ensure all other permissions are set to **No access**.
7. Click **Generate token** and copy it immediately.

### Option B: Classic Personal Access Token
1. Go to **Settings** → **Developer Settings** → **Personal access tokens** → **Tokens (classic)**.
2. Click **Generate new token (classic)**.
3. Select the `repo` scope (Full control of private repositories).
4. Generate and copy the token.

---

## 2. Setting Up the Automation Repository

1. Create a new repository on your GitHub account (e.g., `github-daily-committer`). Can be private or public.
2. In the new repository, go to **Settings** → **Secrets and variables** → **Actions**.
3. Click **New repository secret**:
   - **Name**: `AUTO_COMMIT_PAT`
   - **Secret**: Paste your Personal Access Token generated above.
4. Push these files to your newly created repository:
   ```bash
   git init
   git add .
   git commit -m "feat: initial commit for daily commit automator"
   git branch -M main
   git remote add origin https://github.com/<YOUR_USERNAME>/github-daily-committer.git
   git push -u origin main
   ```

---

## 3. Manual Testing & Verification

### Test via GitHub Actions
1. Go to your repository on GitHub.
2. Click the **Actions** tab.
3. Click **Daily Git Commit Automator** in the left sidebar.
4. Click **Run workflow**:
   - Check **Dry run mode** to test repository discovery without pushing any commits.
   - Leave un-checked to perform live commits.
5. Inspect the job output and verify the Markdown summary table under **Summary**.

### Test Locally (Optional)
```bash
# Dry run test
python commit_automator.py --token "YOUR_PAT" --dry-run

# Live test (with exclusion of important repos if desired)
python commit_automator.py --token "YOUR_PAT" --exclude "my-production-repo"
```

---

## 4. Scheduling & Cadence

The workflow is scheduled via GitHub Actions cron:
```yaml
on:
  schedule:
    - cron: '0 0 * * *'  # Runs daily at 00:00 UTC
```

> **Note**: GitHub Actions scheduled workflows are queued and may experience a slight delay (typically 5 to 15 minutes) during peak platform load.

---

## 5. Error Handling & Troubleshooting

| Issue | Cause | Resolution |
|---|---|---|
| **Protected branch rule prevented direct push** | The repository's default branch has branch protection rules (e.g. required PR reviews). | By design, the script logs this failure and safely moves on. If you want commits there, grant bypass permissions to the PAT user or exempt automated empty commits. |
| **Insufficient permissions (403 / Access Denied)** | Token does not have `Contents: Read and write` or access to that repository. | Check your PAT settings and confirm "All repositories" or the specific repository is selected with `Contents: Read and write`. |
| **Repository has no default branch** | The repository was just created and is completely empty (no initial commit). | Create an initial commit (e.g., README) in that repository first. |
| **Workflow didn't run at exact minute** | GitHub Actions schedule queue latency. | Normal behavior. GitHub guarantees execution within a reasonable window, not down to the exact second. |
