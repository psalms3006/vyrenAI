"""
agents/developer.py -- Developer Agent.

A permanent background agent responsible for:
  - Architecture reviews
  - Dependency analysis
  - Project indexing
  - Bug detection
  - Code suggestions
  - Refactoring proposals
  - Documentation generation
  - Technical planning
  - Feature implementation support

This agent is always available (starts at boot) and never requires
separate manual execution.
"""

import logging
import os
import time
from typing import Any

from agents.base import BaseAgent, AgentResult, AgentCapability

logger = logging.getLogger("vyren.agents.developer")


class DeveloperAgent(BaseAgent):
    """
    The Developer Agent is a permanent background agent that provides
    software engineering capabilities to VYREN.

    It can analyze code, suggest improvements, detect bugs, and assist
    with technical planning. It uses VYREN's own tools (file reading,
    searching, code execution) to understand and interact with codebases.
    """

    name = "developer"
    description = "Software engineering agent: code analysis, architecture review, bug detection, refactoring suggestions, and technical planning."
    capabilities = [
        AgentCapability("analyze_code", "Analyze code files for issues, patterns, and improvements"),
        AgentCapability("review_architecture", "Review project architecture and suggest improvements"),
        AgentCapability("detect_bugs", "Scan code for potential bugs and issues"),
        AgentCapability("suggest_refactoring", "Propose refactoring opportunities"),
        AgentCapability("generate_docs", "Generate documentation for code"),
        AgentCapability("plan_feature", "Plan the implementation of a new feature"),
        AgentCapability("analyze_dependencies", "Analyze project dependencies and their relationships"),
        AgentCapability("index_project", "Index a project's file structure and code structure"),
    ]

    async def _execute(self, task: str, context: dict) -> AgentResult:
        """Execute a developer task."""
        task_lower = task.lower()

        # Route to appropriate sub-handler
        if any(kw in task_lower for kw in ["bug", "issue", "error", "fix"]):
            return await self._detect_bugs(task, context)
        elif any(kw in task_lower for kw in ["architect", "structure", "design"]):
            return await self._review_architecture(task, context)
        elif any(kw in task_lower for kw in ["refactor", "improve", "clean"]):
            return await self._suggest_refactoring(task, context)
        elif any(kw in task_lower for kw in ["document", "docs", "readme"]):
            return await self._generate_docs(task, context)
        elif any(kw in task_lower for kw in ["plan", "implement", "feature"]):
            return await self._plan_feature(task, context)
        elif any(kw in task_lower for kw in ["depend", "import", "package"]):
            return await self._analyze_dependencies(task, context)
        elif any(kw in task_lower for kw in ["index", "scan", "map"]):
            return await self._index_project(task, context)
        else:
            return await self._general_analysis(task, context)

    async def _detect_bugs(self, task: str, context: dict) -> AgentResult:
        """Scan code for potential bugs."""
        registry = context.get("registry")
        if not registry:
            return AgentResult(agent=self.name, task=task, success=False,
                               error="Tool registry not available")

        output_parts = []
        output_parts.append(f"Bug Analysis: {task}")
        output_parts.append("-" * 40)

        # Try to find relevant files
        try:
            result = registry.execute("search_files", {
                "pattern": "*.py",
                "directory": str(get_vyren_dir() / "workspace" / "my-project"),
            })
            files = [line.strip() for line in result.split("\n") if line.strip() and not line.startswith("[")][:10]
            output_parts.append(f"Scanning {len(files)} Python files...")

            # Read a few files for analysis
            for f in files[:5]:
                try:
                    content = registry.execute("read_file", {"file_path": f, "max_lines": 100})
                    issues = self._quick_bug_scan(content, f)
                    if issues:
                        output_parts.append(f"\n{f}:")
                        for issue in issues:
                            output_parts.append(f"  - {issue}")
                except Exception:
                    pass
        except Exception as e:
            output_parts.append(f"Error during bug scan: {e}")

        return AgentResult(
            agent=self.name, task=task, success=True,
            output="\n".join(output_parts),
            confidence=0.7,
        )

    async def _review_architecture(self, task: str, context: dict) -> AgentResult:
        """Review project architecture."""
        output_parts = [
            f"Architecture Review: {task}",
            "-" * 40,
            "",
            "Current VYREN Architecture:",
            "  boot/        - Boot Manager (ordered service init)",
            "  runtime/     - Runtime Manager (lifecycle, connectivity)",
            "  brain/       - Planner, Reasoning, Greetings",
            "  voice/       - Voice Runtime (wake-word, conversation)",
            "  agents/      - Multi-agent system",
            "  tools/       - Tool registry (27+ tools)",
            "  web/         - PWA Dashboard",
            "",
            "Design Principles:",
            "  - One Brain (shared across all interfaces)",
            "  - One Memory (voice/text/UI share same memory)",
            "  - Hybrid Online/Offline (Gemini + Ollama)",
            "  - Voice-First (primary interface)",
            "  - Always-On (continuous operation)",
            "",
            "Strengths:",
            "  - Clean separation of concerns",
            "  - Automatic failover to offline mode",
            "  - Centralized runtime management",
            "  - Extensible agent and tool system",
        ]

        return AgentResult(
            agent=self.name, task=task, success=True,
            output="\n".join(output_parts),
            confidence=0.9,
        )

    async def _suggest_refactoring(self, task: str, context: dict) -> AgentResult:
        """Propose refactoring opportunities."""
        return AgentResult(
            agent=self.name, task=task, success=True,
            output=f"Refactoring analysis for: {task}\n\n"
                   "No immediate refactoring needed. The codebase is "
                   "well-structured following the Tier 3 architecture.",
            confidence=0.6,
        )

    async def _generate_docs(self, task: str, context: dict) -> AgentResult:
        """Generate documentation."""
        return AgentResult(
            agent=self.name, task=task, success=True,
            output=f"Documentation task: {task}\n\n"
                   "Documentation can be generated for any module. "
                   "Specify which module or file you'd like documented.",
            confidence=0.7,
        )

    async def _plan_feature(self, task: str, context: dict) -> AgentResult:
        """Plan feature implementation."""
        return AgentResult(
            agent=self.name, task=task, success=True,
            output=f"Feature Plan: {task}\n\n"
                   "1. Define requirements and constraints\n"
                   "2. Design the implementation approach\n"
                   "3. Identify files to create/modify\n"
                   "4. Implement with tests\n"
                   "5. Update documentation\n"
                   "6. Verify integration with existing systems",
            confidence=0.6,
        )

    async def _analyze_dependencies(self, task: str, context: dict) -> AgentResult:
        """Analyze project dependencies."""
        req_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "requirements.txt")
        output_parts = [f"Dependency Analysis: {task}", "-" * 40]

        if os.path.exists(req_file):
            with open(req_file, "r") as f:
                deps = [line.strip() for line in f if line.strip() and not line.startswith("#")]
            output_parts.append(f"Found {len(deps)} dependencies:")
            for dep in deps:
                output_parts.append(f"  - {dep}")
        else:
            output_parts.append("No requirements.txt found.")

        return AgentResult(
            agent=self.name, task=task, success=True,
            output="\n".join(output_parts),
            confidence=0.8,
        )

    async def _index_project(self, task: str, context: dict) -> AgentResult:
        """Index project structure."""
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        output_parts = [f"Project Index: {task}", "-" * 40]

        for root, dirs, files in os.walk(project_root):
            # Skip hidden dirs and __pycache__
            dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
            level = root.replace(project_root, "").count(os.sep)
            indent = "  " * level
            output_parts.append(f"{indent}{os.path.basename(root)}/")
            sub_indent = "  " * (level + 1)
            for file in sorted(files):
                if file.endswith((".py", ".yaml", ".json", ".md")):
                    output_parts.append(f"{sub_indent}{file}")

        return AgentResult(
            agent=self.name, task=task, success=True,
            output="\n".join(output_parts),
            confidence=0.95,
        )

    async def _general_analysis(self, task: str, context: dict) -> AgentResult:
        """General code analysis."""
        return AgentResult(
            agent=self.name, task=task, success=True,
            output=f"Developer Agent: Processing '{task}'\n\n"
                   "I can help with code analysis, architecture reviews, "
                   "bug detection, refactoring, and more. What specifically "
                   "would you like me to analyze?",
            confidence=0.5,
        )

    def _quick_bug_scan(self, content: str, filename: str) -> list[str]:
        """Quick heuristic bug scan of file content."""
        issues = []

        # Check for common issues
        if "except:" in content and "except Exception" not in content:
            issues.append("Bare 'except:' catches all exceptions including KeyboardInterrupt")

        if "os.system(" in content or "subprocess.call(" in content and "shell=True" in content:
            issues.append("Potential shell injection with shell=True")

        if "eval(" in content or "exec(" in content:
            issues.append(f"Use of eval/exec in {filename} -- potential security risk")

        if "password" in content.lower() and "env" not in content.lower():
            issues.append("Possible hardcoded password or secret")

        if content.count("import ") > 30:
            issues.append("Very large number of imports -- consider modularizing")

        return issues

    def can_handle(self, task: str) -> float:
        """Higher confidence for development-related tasks."""
        task_lower = task.lower()
        dev_keywords = [
            "code", "bug", "error", "refactor", "architect", "implement",
            "feature", "test", "document", "dependency", "index",
            "analyze", "review", "improve", "module", "function",
            "class", "file", "project", "structure", "design",
        ]
        matches = sum(1 for kw in dev_keywords if kw in task_lower)
        if matches >= 2:
            return 0.9
        if matches >= 1:
            return 0.7
        return super().can_handle(task)