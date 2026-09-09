#!/usr/bin/env python3
"""
Unit and Integration Tests for commit_automator.py
"""

import os
import subprocess
import tempfile
import unittest
from commit_automator import sanitize_text, write_step_summary, run_git_command, process_repository


class TestCommitAutomator(unittest.TestCase):

    def test_sanitize_text(self):
        token = "ghp_secretToken9999"
        raw_error = f"fatal: unable to access 'https://x-access-token:{token}@github.com/user/repo.git/': 403"
        sanitized = sanitize_text(raw_error, token)
        self.assertNotIn(token, sanitized)
        self.assertIn("***", sanitized)

    def test_git_empty_commit_local(self):
        """Verify that an empty commit is created and project files remain untouched."""
        token = "test_token"
        with tempfile.TemporaryDirectory() as temp_dir:
            # Initialize a git repo
            run_git_command(["git", "init"], cwd=temp_dir, token=token)
            run_git_command(["git", "config", "user.name", "Test Bot"], cwd=temp_dir, token=token)
            run_git_command(["git", "config", "user.email", "bot@test.local"], cwd=temp_dir, token=token)

            # Create an initial file to set up main branch
            dummy_file = os.path.join(temp_dir, "initial.txt")
            with open(dummy_file, "w") as f:
                f.write("initial content")

            run_git_command(["git", "add", "initial.txt"], cwd=temp_dir, token=token)
            run_git_command(["git", "commit", "-m", "initial commit"], cwd=temp_dir, token=token)

            # Count files and commits before
            commits_before = run_git_command(["git", "rev-list", "--count", "HEAD"], cwd=temp_dir, token=token)
            files_before = set(os.listdir(temp_dir))

            # Run empty commit
            commit_msg = "chore: daily automated commit"
            run_git_command(["git", "commit", "--allow-empty", "-m", commit_msg], cwd=temp_dir, token=token)

            # Check commits count incremented by 1
            commits_after = run_git_command(["git", "rev-list", "--count", "HEAD"], cwd=temp_dir, token=token)
            self.assertEqual(int(commits_after), int(commits_before) + 1)

            # Check that files were NOT modified or added
            files_after = set(os.listdir(temp_dir))
            self.assertEqual(files_before, files_after)

            # Verify latest commit message
            latest_msg = run_git_command(["git", "log", "-1", "--pretty=%B"], cwd=temp_dir, token=token)
            self.assertEqual(latest_msg.strip(), commit_msg)

    def test_write_step_summary(self):
        with tempfile.NamedTemporaryFile(mode="w+", delete=False) as f:
            summary_path = f.name

        os.environ["GITHUB_STEP_SUMMARY"] = summary_path
        try:
            successful = [("repo-1", "Committed and pushed to 'main'")]
            failed = [("repo-2", "main", "Protected branch rule prevented direct push")]
            write_step_summary(successful, failed, dry_run=False)

            with open(summary_path, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertIn("Daily Commit Automation Summary", content)
            self.assertIn("repo-1", content)
            self.assertIn("repo-2", content)
            self.assertIn("Protected branch rule", content)
        finally:
            if os.path.exists(summary_path):
                os.remove(summary_path)
            if "GITHUB_STEP_SUMMARY" in os.environ:
                del os.environ["GITHUB_STEP_SUMMARY"]


if __name__ == "__main__":
    unittest.main()
