# VYREN v2 -- Architecture Report

## Overview

VYREN v2 is a complete architectural redesign of the personal AI agent system. The original flat structure (all .py files in one directory) has been reorganized into a modular, production-grade system with 24+ directories, clear interfaces, and independent testability.

## Architecture

### Directory Structure

```
vyren-v2/
  core/            -- Kernel: initializes and wires ALL subsystems via VYRENCtx
  brain/           -- Central cognition engine (input -> reason -> plan -> execute -> reflect)
  planner/         -- Goal decomposition, multi-step plans, dynamic replanning
  reasoning/       -- Multi-mode reasoning (fast, deep, creative, research, debug, etc.)
  learning/        -- Continuous learning from corrections, mistakes, preferences, patterns
  security/        -- Permission system, credential vault, tool isolation
  context/         -- Dynamic context management, token budgeting, history compression
  execution/       -- Task execution with checkpoints, rollback support
  reflection/      -- Self-assessment after task completion
  memory/          -- 6-layer persistent memory (working, episodic, semantic, procedural, preference, project)
  knowledge_graph/ -- Obsidian-style graph of connected entities and relationships
  world_model/     -- User's world: projects, devices, schedules, workflows, observations
  scheduler/       -- Job scheduler: recurring, one-shot, event-triggered
  event_bus/       -- Pub/sub nervous system connecting all modules
  agents/          -- Multi-agent system: Planner, Developer, Researcher, Review agents
  tools/           -- 35+ tools: memory, files, web, dev, vision, KG, scheduler, world, screen, computer
  models/          -- Placeholder for multi-LLM orchestration (future)
  computer/        -- Computer control: clipboard, terminal, keyboard, app launching
  filesystem/      -- Enhanced file ops: tree visualization, file info, safe delete
  monitoring/      -- System health snapshots (CPU, RAM, disk, battery)
  automation/      -- Placeholder for workflow automation (future)
  browser/         -- Placeholder for browser automation (future)
  voice/           -- Push-to-talk (Deepgram STT + ElevenLabs TTS)
  vision/          -- Placeholder for vision module (future)
  ui/              -- Placeholder for UI components (future)
  api/             -- Placeholder for external API integrations (future)
  web/             -- PWA dashboard (FastAPI + WebSocket)
  logs/            -- Log directory
  tests/           -- Test directory
```

### Key Architectural Decisions

1. **VYRENCtx as the central context object**: Every module receives a reference to VYRENCtx. Modules never reach into each other's internals. This makes testing individual modules trivial -- just mock the context.

2. **Brain as the cognition orchestrator**: The brain is NOT a chatbot wrapper. It implements a full cognitive pipeline: Retrieve Context -> Select Reasoning Mode -> Build Prompt -> Execute Tools -> Post-Process (auto-learn, update context). This replaces the raw tool-calling loop in the original main.py.

3. **Multi-mode reasoning**: The reasoning engine selects from 8 modes (fast, deep, creative, research, debug, architectural, strategic, math) based on regex pattern matching against user input. Each mode injects different system prompt hints.

4. **Planner with persistent storage**: Plans are saved as JSON files. They have steps with dependencies, complexity ratings, verification criteria, and support for dynamic replanning after failures.

5. **Learning from everything**: The Learner records lessons from corrections, mistakes, preferences, and behavioral patterns. Each lesson has confidence scores that increase with reinforcement. Lessons are searchable and applied to future interactions.

6. **Context budgeting**: The ContextManager prevents context window overflow by scoring and prioritizing context blocks. It supports conversation compression, relevance scoring, and dynamic assembly.

7. **Security layering**: Permission system (allow/deny/ask per tool), credential vault with basic obfuscation, audit trail integration. All computer control tools are consequential by default.

8. **6 new tool modules**: computer_tools (6 tools: clipboard, terminal, apps, keyboard), filesystem_tools (4 tools: tree, info, safe delete, search), bringing the total from ~18 to ~35 tools.

9. **Specialized agents**: PlannerAgent, DeveloperAgent, ResearcherAgent, ReviewAgent -- each with capabilities and confidence scoring for task routing via the Coordinator.

10. **Windows-first**: All file operations use `encoding="utf-8"`. No emoji characters. `shell=True` on subprocess calls. Windows disk paths (`C:\\`). PowerShell and cmd support.

## Major Changes from v1

| Area | v1 | v2 |
|------|----|----|
| Structure | Flat (all .py in root) | 24+ module directories |
| Cognition | Raw tool-calling loop in main.py | Brain pipeline (retrieve -> reason -> plan -> execute -> reflect) |
| Reasoning | Single mode | 8 modes with auto-selection |
| Planning | None | Full planner with persistent plans |
| Learning | None | Lesson store with categories, confidence, reinforcement |
| Security | Basic safety gate (consequential/safe) | Permission system + credential vault |
| Context | Full dump into prompt | Budgeted, scored, compressed |
| Tools | 18 tools | 35+ tools |
| Agents | Base class only | 4 specialized agents + coordinator |
| Computer control | None | Clipboard, terminal, keyboard, app launching |
| Filesystem | Basic read/list/write | Tree visualization, file info, safe delete |
| Monitoring | Basic system info | System snapshots + health monitoring |
| Checkpoints | None | File checkpoint/restore for safe operations |
| Reflection | None | Post-task self-assessment |

## Remaining Limitations

1. **No true semantic search**: Memory and KG use keyword matching. Vector embeddings (sentence-transformers or Gemini embeddings) would dramatically improve relevance.

2. **No browser automation**: The browser/ directory is a placeholder. Integrating Playwright or Selenium would enable web-based agent capabilities.

3. **No multi-LLM routing**: The models/ directory is a placeholder. The planner should route reasoning tasks to stronger models and simple tasks to faster models.

4. **No code understanding/indexing**: VYREN can read files but doesn't build dependency graphs, call graphs, or architecture maps from codebases.

5. **Computer control is basic**: pyautogui-based control works but has no screen region awareness, no OCR-based interaction, and no application-specific intelligence.

6. **No true parallel execution**: The scheduler runs jobs in threads but the brain processes one turn at a time. True parallel agent execution would require an async task queue.

7. **Credential vault is basic obfuscation**: In production, use the OS keychain (keyring package) or a proper secrets manager like HashiCorp Vault.

8. **No Docker/container support**: Would be valuable for sandboxed code execution.

## Prioritized Roadmap

### Phase 1 (Immediate)
- Vector embeddings for memory search (sentence-transformers)
- Playwright browser automation
- Code indexing and dependency graph generation

### Phase 2 (Near-term)
- Multi-LLM routing (Gemini for reasoning, Ollama for fast tasks)
- Async task queue for parallel execution
- OS keychain integration for credentials
- Docker sandbox for code execution

### Phase 3 (Medium-term)
- Natural language planning (LLM generates the plan steps)
- Automated testing framework
- Plugin/extension system
- Graph visualization (D3.js or Mermaid)

### Phase 4 (Long-term)
- Self-improvement pipeline (analyze own code, suggest changes, verify, apply)
- Federated learning across multiple VYREN instances
- Mobile companion app
- Voice-first interaction mode
- Screen understanding with region-awareness