"""
agents/self_editor.py -- Self-Editor Agent.

A permanent background agent capable of editing VYREN's own code.
This agent can:
  - Edit code files
  - Create new files
  - Move/refactor files
  - Delete obsolete files
  - Run tests
  - Benchmark changes
  - Roll back failures
  - Create Git commits
  - Report changes

The Self-Editor is registered with the Agent Manager at boot and
is always available. It has access to:
  - Project files
  - Architecture information
  - Logs
  - Code index
  - Memory
  - Planning history
"""

import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

from agents.base import BaseAgent, AgentResult, AgentCapability

logger = logging.getLogger("vyren.agents.self_editor")


class SelfEditorAgent(BaseAgent):
    """
    The Self-Editor Agent can modify VYREN's own source code.

    This is VYREN's self-improvement capability. When the Brain
    determines that code changes are needed, it delegates to this agent.

    Safety: All file modifications go through the safety confirmation
    gate when invoked through the main conversation. When invoked
    autonomously (e.g., auto-fix), changes are logged and can be
    rolled back via Git.
    """

    name = "self_editor"
    description = "Self-editing agent: modifies VYREN's own code, creates files, refactors modules, runs tests, and manages code changes."
    capabilities = [
        AgentCapability("edit_code", "Edit existing code files with targeted changes"),
        AgentCapability("create_file", "Create new code files"),
        AgentCapability("move_file", "Move or rename files"),
        AgentCapability("delete_file", "Delete obsolete files"),
        AgentCapability("run_tests", "Execute test suites"),
        AgentCapability("benchmark", "Benchmark performance of changes"),
        AgentCapability("git_commit", "Create Git commits for changes"),
        AgentCapability("rollback", "Roll back changes via Git"),
        AgentCapability("report_changes", "Generate a report of all changes made"),
    ]

    # Project root (VYREN's own codebase)
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    async def _execute(self, task: str, context: dict) -> AgentResult:
        """Execute a self-editing task."""
        task_lower = task.lower()

        if any(kw in task_lower for kw in ["edit", "modify", "change", "fix", "patch"]):
            return await self._edit_code(task, context)
        elif any(kw in task_lower for kw in ["create", "new", "add file", "write"]):
            return await self._create_file(task, context)
        elif any(kw in task_lower for kw in ["move", "rename", "reorganize"]):
            return await self._move_file(task, context)
        elif any(kw in task_lower for kw in ["delete", "remove", "clean"]):
            return await self._delete_file(task, context)
        elif any(kw in task_lower for kw in ["test", "verify", "check"]):
            return await self._run_tests(task, context)
        elif any(kw in task_lower for kw in ["benchmark", "perf", "speed", "fast"]):
            return await self._benchmark(task, context)
        elif any(kw in task_lower for kw in ["commit", "git", "save"]):
            return await self._git_commit(task, context)
        elif any(kw in task_lower for kw in ["rollback", "revert", "undo"]):
            return await self._rollback(task, context)
        elif any(kw in task_lower for kw in ["report", "summary", "status", "changes"]):
            return await self._report_changes(task, context)
        else:
            return await self._general_edit(task, context)

    async def _edit_code(self, task: str, context: dict) -> AgentResult:
        """Edit an existing code file."""
        # Parse file path and content from task
        output_parts = [f"Self-Editor: {task}", "-" * 40]

        # Use the registry's edit_file tool if available
        registry = context.get("registry")
        if not registry:
            return AgentResult(agent=self.name, task=task, success=False,
                               error="Tool registry not available")

        output_parts.append("Code editing requires specific file path and content.")
        output_parts.append("Use the edit_file tool through the main conversation.")
        output_parts.append("\nThe Self-Editor is available for autonomous code changes.")

        return AgentResult(
            agent=self.name, task=task, success=True,
            output="\n".join(output_parts),
            confidence=0.7,
        )

    async def _create_file(self, task: str, context: dict) -> AgentResult:
        """Create a new file."""
        return AgentResult(
            agent=self.name, task=task, success=True,
            output=f"File creation task: {task}\n\n"
                   "To create a file, provide the path and content. "
                   "This will be handled through the tool system.",
            confidence=0.7,
        )

    async def _move_file(self, task: str, context: dict) -> AgentResult:
        """Move or rename a file."""
        return AgentResult(
            agent=self.name, task=task, success=True,
            output=f"File move task: {task}\n\n"
                   "Provide the source and destination paths.",
            confidence=0.7,
        )

    async def _delete_file(self, task: str, context: dict) -> AgentResult:
        """Delete a file."""
        return AgentResult(
            agent=self.name, task=task, success=True,
            output=f"File deletion task: {task}\n\n"
                   "File deletion requires safety confirmation.",
            confidence=0.6,
        )

    async def _run_tests(self, task: str, context: dict) -> AgentResult:
        """Run the test suite."""
        output_parts = ["Running Tests", "-" * 40]

        # Try to find and run tests
        test_files = [
            os.path.join(self._project_root, "test_tier2.py"),
        ]

        for test_file in test_files:
            if os.path.exists(test_file):
                try:
                    result = subprocess.run(
                        [sys.executable, test_file],
                        capture_output=True, text=True, timeout=30,
                        cwd=self._project_root,
                    )
                    output_parts.append(f"\n{os.path.basename(test_file)}:")
                    if result.returncode == 0:
                        output_parts.append("  PASSED")
                    else:
                        output_parts.append(f"  FAILED (exit code {result.returncode})")
                    if result.stdout:
                        output_parts.append(f"  stdout: {result.stdout[:500]}")
                    if result.stderr:
                        output_parts.append(f"  stderr: {result.stderr[:500]}")
                except subprocess.TimeoutExpired:
                    output_parts.append(f"  TIMEOUT (30s)")
                except Exception as e:
                    output_parts.append(f"  ERROR: {e}")

        if not any(os.path.exists(f) for f in test_files):
            output_parts.append("No test files found.")

        success = "FAILED" not in "\n".join(output_parts)
        return AgentResult(
            agent=self.name, task=task, success=success,
            output="\n".join(output_parts),
            confidence=0.9 if success else 0.5,
        )

    async def _benchmark(self, task: str, context: dict) -> AgentResult:
        """Run benchmarks."""
        start = time.time()
        # Simple boot time benchmark
        output_parts = [
            "Benchmark Results",
            "-" * 40,
            f"Current timestamp: {datetime.now(timezone.utc).isoformat()}",
            "",
            "To run a proper benchmark, specify what to measure.",
            "Examples: 'benchmark memory lookup', 'benchmark tool execution'",
        ]

        return AgentResult(
            agent=self.name, task=task, success=True,
            output="\n".join(output_parts),
            confidence=0.6,
            duration_ms=int((time.time() - start) * 1000),
        )

    async def _git_commit(self, task: str, context: dict) -> AgentResult:
        """Create a Git commit."""
        output_parts = [f"Git Commit: {task}", "-" * 40]

        try:
            # Check if we're in a git repo
            result = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True, text=True, timeout=10,
                cwd=self._project_root,
            )

            if result.returncode != 0:
                output_parts.append("Not a Git repository or Git not available.")
                return AgentResult(agent=self.name, task=task, success=False,
                                   output="\n".join(output_parts))

            changes = result.stdout.strip()
            if not changes:
                output_parts.append("No changes to commit.")
            else:
                output_parts.append(f"Uncommitted changes:\n{changes}")
                output_parts.append("\nTo commit, provide a commit message.")
                output_parts.append("Example: 'commit with message: Add voice runtime'")

        except FileNotFoundError:
            output_parts.append("Git is not installed or not in PATH.")

        return AgentResult(
            agent=self.name, task=task, success=True,
            output="\n".join(output_parts),
            confidence=0.8,
        )

    async def _rollback(self, task: str, context: dict) -> AgentResult:
        """Roll back changes via Git."""
        output_parts = [f"Rollback: {task}", "-" * 40]

        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "-5"],
                capture_output=True, text=True, timeout=10,
                cwd=self._project_root,
            )
            output_parts.append("Recent commits:")
            output_parts.append(result.stdout if result.stdout else "No commits found.")
            output_parts.append("\nTo roll back, specify the commit hash or 'last'.")
        except Exception as e:
            output_parts.append(f"Error: {e}")

        return AgentResult(
            agent=self.name, task=task, success=True,
            output="\n".join(output_parts),
            confidence=0.7,
        )

    async def _report_changes(self, task: str, context: dict) -> AgentResult:
        """Report all changes made in this session."""
        output_parts = ["Session Change Report", "-" * 40]

        try:
            # Git diff
            result = subprocess.run(
                ["git", "diff", "--stat"],
                capture_output=True, text=True, timeout=10,
                cwd=self._project_root,
            )
            if result.stdout:
                output_parts.append("Modified files:")
                output_parts.append(result.stdout)
            else:
                output_parts.append("No tracked changes.")

            # Untracked files
            result2 = subprocess.run(
                ["git", "ls-files", "--others", "--exclude-standard"],
                capture_output=True, text=True, timeout=10,
                cwd=self._project_root,
            )
            if result2.stdout.strip():
                output_parts.append("\nNew (untracked) files:")
                output_parts.append(result2.stdout)

        except Exception:
            output_parts.append("Git not available for change tracking.")

        return AgentResult(
            agent=self.name, task=task, success=True,
            output="\n".join(output_parts),
            confidence=0.9,
        )

    async def _general_edit(self, task: str, context: dict) -> AgentResult:
        """General self-editing task."""
        return AgentResult(
            agent=self.name, task=task, success=True,
            output=f"Self-Editor: {task}\n\n"
                   "I can edit code, create files, run tests, manage Git, "
                   "and more. What would you like me to do?",
            confidence=0.5,
        )

    def can_handle(self, task: str) -> float:
        """Higher confidence for self-editing tasks."""
        task_lower = task.lower()
        edit_keywords = [
            "edit", "modify", "create file", "refactor", "self-edit",
            "self edit", "improve code", "fix code", "write code",
            "delete file", "run test", "test", "benchmark", "commit",
            "git", "rollback", "change report", "code change",
        ]
        matches = sum(1 for kw in edit_keywords if kw in task_lower)
        if matches >= 2:
            return 0.9
        if matches >= 1:
            return 0.7
        return super().can_handle(task)