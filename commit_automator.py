#!/usr/bin/env python3
"""
GitHub Daily Commit Automator
=============================
Discovers all repositories owned by the authenticated GitHub user,
creates a daily empty Git commit on each repository's default branch,
and pushes the commit safely without modifying or creating any project files.
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple


def get_env_or_arg(arg_value: Optional[str], env_name: str, default: Optional[str] = None) -> Optional[str]:
    """Retrieve value from CLI argument or environment variable."""
    if arg_value:
        return arg_value
    return os.environ.get(env_name, default)


def sanitize_text(text: str, token: str) -> str:
    """Mask token from any output or exception messages."""
    if token and token in text:
        return text.replace(token, "***")
    return text


def github_api_request(
    endpoint: str,
    token: str,
    method: str = "GET",
    params: Optional[Dict[str, str]] = None
) -> Tuple[int, dict, dict]:
    """
    Make an authenticated request to the GitHub REST API.
    Returns (status_code, response_data, headers).
    """
    url = f"https://api.github.com{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "DailyCommitAutomator/1.0",
    }

    req = urllib.request.Request(url, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            status_code = response.status
            res_headers = dict(response.headers)
            body = response.read().decode("utf-8")
            data = json.loads(body) if body else {}
            return status_code, data, res_headers
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            error_data = json.loads(body)
        except Exception:
            error_data = {"message": body}
        return e.code, error_data, dict(e.headers)


def get_authenticated_user(token: str) -> str:
    """Retrieve username of the authenticated token."""
    status, data, _ = github_api_request("/user", token)
    if status != 200:
        msg = data.get("message", "Unknown error")
        raise RuntimeError(f"Failed to authenticate with GitHub API (Status {status}): {msg}")
    return data["login"]


def fetch_all_owned_repositories(
    token: str,
    username: str,
    include_forks: bool = False,
    exclude_repos: Optional[List[str]] = None
) -> List[dict]:
    """
    Fetch all repositories owned by the user using pagination.
    Excludes archived repositories and optionally forks.
    """
    exclude_set = set(exclude_repos or [])
    repositories = []
    page = 1
    per_page = 100

    while True:
        status, data, headers = github_api_request(
            "/user/repos",
            token,
            params={
                "visibility": "all",
                "affiliation": "owner",
                "per_page": str(per_page),
                "page": str(page),
                "sort": "updated",
                "direction": "asc",
            }
        )

        if status != 200:
            msg = data.get("message", "Unknown error")
            raise RuntimeError(f"Error fetching repositories on page {page} (Status {status}): {msg}")

        if not data:
            break

        for repo in data:
            repo_name = repo.get("name", "")
            full_name = repo.get("full_name", "")
            is_fork = repo.get("fork", False)
            is_archived = repo.get("archived", False)
            owner_login = repo.get("owner", {}).get("login", "")

            # Filter: must be owned by user
            if owner_login.lower() != username.lower():
                continue

            # Filter: skip archived
            if is_archived:
                print(f"[SKIP] {full_name} is archived.")
                continue

            # Filter: skip forks unless explicitly enabled
            if is_fork and not include_forks:
                print(f"[SKIP] {full_name} is a fork (enable --include-forks to include).")
                continue

            # Filter: skip explicitly excluded repositories
            if repo_name in exclude_set or full_name in exclude_set:
                print(f"[SKIP] {full_name} is in exclude list.")
                continue

            repositories.append(repo)

        # Check pagination Link header
        link_header = headers.get("link") or headers.get("Link", "")
        if 'rel="next"' not in link_header:
            break
        page += 1

    return repositories


def run_git_command(
    cmd: List[str],
    cwd: str,
    token: str,
    extra_env: Optional[Dict[str, str]] = None
) -> str:
    """Run a git command in cwd, ensuring output does not leak token."""
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)

    # Disable terminal prompt for credentials to prevent hanging
    env["GIT_TERMINAL_PROMPT"] = "0"

    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        sanitized_stderr = sanitize_text(e.stderr.strip(), token)
        sanitized_stdout = sanitize_text(e.stdout.strip(), token)
        error_msg = sanitized_stderr or sanitized_stdout or f"Process exited with code {e.returncode}"
        raise RuntimeError(error_msg)


def process_repository(
    repo: dict,
    token: str,
    commit_message: str,
    git_name: str,
    git_email: str,
    dry_run: bool = False
) -> Tuple[bool, str]:
    """
    Clone default branch, create empty commit, and push.
    Returns (success: bool, detail: str).
    """
    repo_name = repo.get("name")
    full_name = repo.get("full_name")
    default_branch = repo.get("default_branch")

    if not default_branch:
        return False, "Repository has no default branch (empty repository)"

    if dry_run:
        return True, f"[DRY-RUN] Would create empty commit on branch '{default_branch}'"

    # Authenticated URL with token
    # GitHub token is embedded in URL for cloning, and sanitized in all outputs
    auth_clone_url = f"https://x-access-token:{token}@github.com/{full_name}.git"

    with tempfile.TemporaryDirectory(prefix=f"commit_auto_{repo_name}_") as temp_dir:
        try:
            # 1. Shallow clone only the default branch
            run_git_command(
                [
                    "git", "clone",
                    "--depth", "1",
                    "--branch", default_branch,
                    "--single-branch",
                    auth_clone_url,
                    temp_dir
                ],
                cwd=".",
                token=token
            )

            # 2. Configure local committer identity
            run_git_command(["git", "config", "user.name", git_name], cwd=temp_dir, token=token)
            run_git_command(["git", "config", "user.email", git_email], cwd=temp_dir, token=token)

            # 3. Ensure no dirty working directory exists
            status_output = run_git_command(["git", "status", "--porcelain"], cwd=temp_dir, token=token)
            if status_output:
                return False, "Working directory has unexpected dirty files"

            # 4. Create Git empty commit
            run_git_command(
                ["git", "commit", "--allow-empty", "-m", commit_message],
                cwd=temp_dir,
                token=token
            )

            # 5. Push to default branch
            run_git_command(
                ["git", "push", "origin", default_branch],
                cwd=temp_dir,
                token=token
            )

            return True, f"Committed and pushed to '{default_branch}'"

        except Exception as e:
            error_reason = str(e)

            # Friendly categorizations
            if "protected branch" in error_reason.lower() or "pre-receive hook declined" in error_reason.lower():
                return False, f"Protected branch rule prevented direct push to '{default_branch}'"
            if "403" in error_reason or "permission to" in error_reason.lower() or "access denied" in error_reason.lower():
                return False, "Insufficient permissions (token lacks write access to this repository)"
            if "could not resolve host" in error_reason.lower():
                return False, "Network error resolving github.com"
            if "repository not found" in error_reason.lower():
                return False, "Repository not found or access denied"

            return False, error_reason


def write_step_summary(successful: List[Tuple[str, str]], failed: List[Tuple[str, str, str]], dry_run: bool):
    """Write GitHub Actions step summary markdown if in GitHub Actions environment."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    lines = []
    lines.append("## 🚀 Daily Commit Automation Summary")
    if dry_run:
        lines.append("> [!NOTE]\n> **Run Mode:** DRY-RUN (no actual commits were created or pushed).")
    lines.append("")
    lines.append(f"- **Total Succeeded:** {len(successful)}")
    lines.append(f"- **Total Failed:** {len(failed)}")
    lines.append("")

    if successful:
        lines.append("### ✅ Succeeded Repositories")
        lines.append("| Repository | Status / Details |")
        lines.append("|---|---|")
        for repo_name, detail in successful:
            lines.append(f"| `{repo_name}` | {detail} |")
        lines.append("")

    if failed:
        lines.append("### ❌ Failed Repositories")
        lines.append("| Repository | Default Branch | Reason |")
        lines.append("|---|---|---|")
        for repo_name, branch, reason in failed:
            lines.append(f"| `{repo_name}` | `{branch}` | {reason} |")
        lines.append("")

    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception as e:
        print(f"Warning: Unable to write to GITHUB_STEP_SUMMARY: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Automate daily Git empty commits across all owned GitHub repositories.")
    parser.add_argument("--token", help="GitHub Personal Access Token (or set AUTO_COMMIT_PAT env var)")
    parser.add_argument("--message", default=None, help="Commit message")
    parser.add_argument("--git-name", default=None, help="Git committer name")
    parser.add_argument("--git-email", default=None, help="Git committer email")
    parser.add_argument("--include-forks", action="store_true", help="Include forked repositories")
    parser.add_argument("--exclude", nargs="*", default=[], help="Repository names or full names to exclude")
    parser.add_argument("--dry-run", action="store_true", help="Discover repositories without creating or pushing commits")
    parser.add_argument("--fail-on-error", action="store_true", help="Exit with non-zero code if any repository fails")

    args = parser.parse_args()

    token = get_env_or_arg(args.token, "AUTO_COMMIT_PAT") or get_env_or_arg(None, "GITHUB_TOKEN")
    if not token:
        print("ERROR: GitHub token must be provided via --token or AUTO_COMMIT_PAT environment variable.", file=sys.stderr)
        sys.exit(1)

    commit_message = get_env_or_arg(args.message, "COMMIT_MESSAGE") or "chore: daily automated commit"
    git_name = get_env_or_arg(args.git_name, "GIT_NAME") or "github-actions[bot]"
    git_email = get_env_or_arg(args.git_email, "GIT_EMAIL") or "github-actions[bot]@users.noreply.github.com"
    dry_run = args.dry_run or (os.environ.get("DRY_RUN", "").lower() == "true")
    include_forks = args.include_forks or (os.environ.get("INCLUDE_FORKS", "").lower() == "true")

    # Mask token in GitHub Actions logs if running in runner
    print(f"::add-mask::{token}")

    print("Authenticating with GitHub...")
    try:
        auth_user = get_authenticated_user(token)
        print(f"Authenticated as user: {auth_user}")
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # Automatically exclude current automation repository if running in GitHub Actions
    current_repo = os.environ.get("GITHUB_REPOSITORY")
    exclude_list = list(args.exclude)
    if current_repo:
        exclude_list.append(current_repo)
        exclude_list.append(current_repo.split("/")[-1])

    print("\nDiscovering eligible repositories...")
    try:
        repos = fetch_all_owned_repositories(
            token=token,
            username=auth_user,
            include_forks=include_forks,
            exclude_repos=exclude_list
        )
    except Exception as e:
        print(f"ERROR discovering repositories: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(repos)} eligible repositories.\n")
    if not repos:
        print("No repositories to process.")
        sys.exit(0)

    successful: List[Tuple[str, str]] = []
    failed: List[Tuple[str, str, str]] = []

    for idx, repo in enumerate(repos, 1):
        repo_name = repo["name"]
        default_branch = repo.get("default_branch", "unknown")
        print(f"[{idx}/{len(repos)}] Processing '{repo_name}' (default branch: '{default_branch}')...")

        success, detail = process_repository(
            repo=repo,
            token=token,
            commit_message=commit_message,
            git_name=git_name,
            git_email=git_email,
            dry_run=dry_run
        )

        if success:
            print(f"  -> SUCCESS: {detail}")
            successful.append((repo_name, detail))
        else:
            print(f"  -> FAILED: {detail}")
            failed.append((repo_name, default_branch, detail))

    # Print Final Summary
    print("\n" + "=" * 50)
    print("DAILY COMMIT AUTOMATION SUMMARY")
    print("=" * 50)

    print(f"\nSUCCESS ({len(successful)}):")
    for r_name, det in successful:
        print(f"  - {r_name}: {det}")

    if failed:
        print(f"\nFAILED ({len(failed)}):")
        for r_name, br, err in failed:
            print(f"  - {r_name} (branch: {br}) — {err}")
    else:
        print("\nFAILED (0): None")

    print("\n" + "=" * 50)

    # Write GitHub Actions Step Summary Markdown
    write_step_summary(successful, failed, dry_run)

    if failed and args.fail_on_error:
        print("Completed with errors (--fail-on-error was enabled).", file=sys.stderr)
        sys.exit(1)

    print("Automation execution completed successfully.")
    sys.exit(0)


if __name__ == "__main__":
    main()
