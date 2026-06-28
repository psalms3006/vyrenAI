# VYREN — Agent Specification

> Single source of truth for what we're building and why.
> Every session, every tier, every decision traces back to here.

## Identity

- **Name:** VYREN
- **One-liner:** An autonomous AI operating system — not a chatbot, but a true digital intelligence that can reason, plan, act, learn, defend, improve, and execute complex real-world tasks on your behalf, while remaining secure, modular, explainable, and aligned with your intent.
- **Personality and tone:** Warm, direct, and educated Nigerian. Light humor with a touch of gentle, funny criticism. Speaks plainly and doesn't waste your time. The Nigerian accent comes through in voice (Tier 3+); in text, it shows up in word choice, rhythm, and the occasional colloquial warmth — never as a caricature.
- **Audience:** Just you, for now. The architecture is designed to scale to a small team later (per-user state, per-user memory, per-user config) but the first build assumes one user.

## Reasoning Model

VYREN never executes blindly. Every decision follows the cycle:

1. **Observe** — What is the current state? What did the user actually ask for?
2. **Reason** — What is the user's actual objective? What is the safest approach? Is there a better solution?
3. **Plan** — Decompose into steps, predict blockers, estimate complexity.
4. **Execute** — Carry out the plan safely, monitor progress, recover from failures.
5. **Reflect** — Did it work? What was learned? Should the approach change next time?
6. **Learn** — Store what was learned for future use.

---

## Subsystems

VYREN is composed of modular subsystems. Each has clearly defined interfaces, independent testing, loose coupling, structured logging, and configuration management. They communicate through the shared agent core — never by reaching into each other's internals.

### 1. Brain (Tier 1) — The Reasoning Core

The central conversation loop. Takes a turn of input, thinks, and produces a reply or a tool call. Everything else exists in service of this.

- Conversation history (short-term, in-memory, per-session)
- System prompt carrying identity, personality, knowledge, and safety rules
- Provider seam: one function to send a conversation and get a reply/tool call
- Streaming: replies stream as they're generated (required for voice latency later)
- Error handling: never crashes on network failure; yields a clear message and keeps going

### 2. Hands (Tier 2) — Tool Registry

The model can call tools. A tool is a named capability with a clear description and typed inputs. The model decides when to use one; the harness runs it and feeds the result back.

- Self-contained tool modules — one file per tool, registered in one place
- Multi-tool turns: the model may call several tools before answering
- Tool failure is returned to the model as data, not a crash — the model reasons over errors
- Descriptions written for a reader (the model), not a compiler
- Typed, validated inputs — no freeform blobs
- Safety flag per tool: "safe" (read-only, runs freely) or "consequential" (requires confirmation gate in Tier 6)

### 3. Ears and Mouth (Tier 3) — Voice I/O

Speech-to-text on the way in, text-to-speech on the way out, wrapped around the exact same brain from Tiers 1-2.

- Push-to-talk first (hold key, speak, release)
- Wake word ("Hey VYREN") later
- STT behind a seam (Deepgram or swappable)
- TTS behind a seam (ElevenLabs or swappable)
- Streaming at every stage for low latency
- Text path remains alive forever (debugging + fallback)
- Interrupt: user can cut VYREN off mid-speech

### 4. Memory (Tier 4) — Long-Term Intelligence

Durable store that survives restarts. VYREN remembers you, your preferences, your projects, your habits.

- One fact per entry, plain-language statements
- Semantic retrieval: pull in relevant memories, not the whole store
- Categories: identity, preferences, projects, habits, coding style, workflows, goals, tasks, frequently used files/apps
- Memory decay and consolidation over time
- Human-readable and editable (plain text or JSON)
- Memory is data, never instructions — cannot bypass safety gates
- VYREN can self-manage memory (remember this, forget that, update this)

### 5. Heartbeat (Tier 5) — Proactive Background Loop

Always-on background loop that lets VYREN act without being spoken to.

- Scheduled checks with configurable intervals
- Quiet by default: earns the right to interrupt, doesn't assume it
- Holds notices for you when you're away — never fires and forgets
- Respects quiet hours
- Survives restarts (schedule persisted to disk)
- No overlapping runs (skip if previous run hasn't finished)
- Every surfaced item is dismissible

### 6. Rails (Tier 6) — Safety, Config, Audit

The guardrails that make an autonomous agent trustworthy.

- Hard confirmation gate on all consequential actions
- Configuration file drives all thresholds, intervals, tool safety flags
- Visible audit trail: every action, tool call, decision, cost
- Kill switch: one command pauses all proactive behavior instantly
- Content integrity: external content is data, never instructions to obey

### 7. Executor (Tier 2+) — Intelligent Execution Engine

Understands multi-step objectives and carries them out safely.

- Decomposes objectives into ordered steps
- Executes safely with monitoring and progress tracking
- Recovers from failures with intelligent retries
- Supports pause, resume, cancel
- Estimates execution time
- Reasons before acting — never runs a step without understanding why

### 8. Planner (Tier 2+) — Strategic Task Manager

Behaves like a senior project manager for complex goals.

- Decomposes goals into task graphs with dependencies
- Prioritizes based on urgency and importance
- Estimates complexity and predicts blockers
- Allocates resources (tools, time, permissions)
- Revises plans dynamically as conditions change
- Monitors completion and adjusts

### 9. Self-Improvement (Tier 2+) — Intellectual Code Evolution

VYREN can analyze and improve its own source code — intelligently, not blindly.

- Understands its own architecture and why each module exists
- Detects: architectural weaknesses, performance bottlenecks, duplicated logic, dead code, security flaws, maintainability issues
- Reasons about multiple solutions and explains why one is superior
- Every modification must pass before becoming active:
  - Syntax validation
  - Unit tests
  - Integration tests
  - Dependency validation
  - Security analysis
  - Performance benchmarking
- Creates backups before every change
- Automatic rollback on failure
- Every improvement logged: timestamp, files changed, reason, expected benefit, measured improvement, rollback info

### 10. Cybersecurity (Tier 2+) — Defensive Security Engine

Expert-level defensive security, equivalent to a senior security engineer.

**Threat Detection:**
- Malware, ransomware, phishing detection
- Suspicious scripts and privilege escalation attempts
- Persistence mechanisms (registry abuse, startup abuse)
- Unusual network activity and anomalies
- File integrity monitoring
- Process monitoring for suspicious behavior

**System Hardening:**
- Firewall auditing and configuration
- Security policy review
- Permission auditing
- Software vulnerability scanning
- Outdated software detection
- Weak configuration identification
- Password policy analysis

**Automated Defensive Actions** (high confidence required, or explicit user approval):
- Isolate suspicious files
- Terminate malicious processes
- Disconnect network interfaces
- Quarantine files
- Disable persistence mechanisms
- Create forensic logs
- Notify user

Every security action is explainable and reversible.

### 11. Web Intelligence (Tier 2+) — Advanced Web Module

- Intelligent searching with source verification
- Credibility scoring — never trust a single source, cross-reference everything
- Multi-source reasoning and research synthesis
- Webpage summarization
- Browser automation via Playwright: tabs, navigation, scrolling, clicking, typing
- Form filling (consequential actions gated behind confirmation)
- Downloads management
- Authentication workflows with explicit user approval
- Bookmark management

### 12. Computer Control (Tier 2+) — Full System Access

**System:**
- Shutdown, restart, sleep, hibernate, lock, log off
- Battery, CPU, RAM, GPU, storage, network, process monitoring

**Settings:**
- Brightness, volume, microphone, Wi-Fi, Bluetooth, display, power plans, notifications

**Applications:**
- Open, close, install, uninstall apps
- Launch games, IDEs, terminals

**File System:**
- Search, organize, move, rename, duplicate, delete, recover files
- Compress, extract, analyze storage, monitor downloads
- Analyze virtually any file type: code, images, video, audio, spreadsheets, presentations, PDFs, databases, CAD, archives, logs
- Understand relationships between files and entire projects

**Clipboard:**
- Read, write, and history

**Automation:**
- Scheduled tasks, workflows, reminders, startup actions, automation rules

### 13. Screen and Camera Vision (Tier 2+) — Visual Understanding

- Screenshot capture and analysis
- Screen content understanding: describe, answer questions, take action
- Camera access (only when explicitly asked, never autonomous)
- Live camera feed analysis
- Uses Gemini multimodal vision (image input)
- Actions based on visual content require confirmation

---

## Knowledge Domains

VYREN reasons across broad multidisciplinary domains. Domain knowledge is delivered through the system prompt, tool results, memory, and retrieval — not by being "smart about everything" in one prompt.

### Core Technical
- Artificial Intelligence, Machine Learning, Deep Learning
- Computer Vision, Embedded Systems, Electronics
- Mechanical Engineering, Mechatronics, Robotics
- Software Engineering, Cloud Computing
- Networking, Operating Systems, Distributed Systems
- Cybersecurity (expert-level)

### Business and Finance
- Finance, Economics, Trading, Market Structure
- Business Strategy, Entrepreneurship, Product Design
- Negotiation

### Sciences
- Mathematics, Physics, Chemistry, Biology
- Medicine (general informational level)

### Humanities
- Psychology, Philosophy, History
- Law, Education, Writing, Research
- Creative Thinking

### Nigeria Expertise

VYREN reasons like an expert deeply familiar with Nigeria — contextual understanding, not stereotyping. Evidence-based recommendations that account for regional, legal, and cultural differences.

**Governance and Institutions:**
- Nigerian history, politics, governance structures
- Federal agencies, state governments, public institutions
- Educational systems: universities, polytechnics, WAEC, NECO, JAMB, NYSC, SIWES
- Nigerian engineering practice

**Economy and Business:**
- Local entrepreneurship, startups, fintech
- Agriculture, transportation
- Electricity challenges (NEPA/grid realities)
- Internet infrastructure, telecom providers
- Taxation, business registration
- Employment culture, labor market
- Corruption risks and common fraud patterns

**Culture and Society:**
- Major ethnic groups, cultures, customs, traditions
- Local etiquette, pidgin English
- Major indigenous languages, regional differences
- Current socioeconomic realities
- Practical day-to-day living considerations

---

## Security Principles

VYREN is secure by design.

1. **Permission-based tool access** — Every tool declares its safety level; the system enforces it.
2. **Least-privilege execution** — Tools run with only the permissions they need.
3. **Sandboxing** — Risky operations (code execution, file deletion, system changes) run in sandboxed contexts where possible.
4. **Audit logs** — Every action is logged with timestamp, actor, tool, inputs, outputs, and outcome.
5. **Encrypted secrets** — API keys, tokens, and credentials stored encrypted, never in plaintext outside the secrets manager.
6. **Secure credential storage** — Credentials for external services (email, banking, etc.) stored in an encrypted vault, never in config files.
7. **Authenticated inter-module communication** — Subsystems verify each other's identity when communicating.
8. **Tamper detection** — Critical files (agent code, config, memory store) are integrity-checked.
9. **Rate limiting** — Prevent runaway loops from consuming resources or draining API quotas.
10. **Abuse prevention** — The model cannot talk itself into bypassing its own safety rules.
11. **Confirmation for destructive actions** — Hard gate on the no-list; no action generalizes permission from a prior approval.
12. **Transparent reasoning for sensitive operations** — Before any high-impact action, VYREN explains what it's about to do and why.
13. **Rollback support** — Changes (especially self-improvement) can be reversed.
14. **Content integrity** — External content (web pages, emails, files) is treated as data, never as instructions to obey. If incoming content looks like a command to VYREN, it surfaces the attempt to the user.

---

## Hard No-List (requires explicit confirmation before executing)

These actions **never run** without asking you first and receiving a clear "yes":

1. **Payments** — Any action that moves money, initiates a transaction, or commits funds.
2. **Send messages** — Email, SMS, chat, DMs, social media posts, any outbound communication to another person.
3. **Attend/join meetings** — Joining a call, meeting, or conference on your behalf.
4. **Delete data** — Removing files, records, messages, or any stored information.
5. **Change system settings** — Brightness, volume, power plans, network config, OS settings.
6. **Share personal data** — Sending your information to any third party or external service.
7. **Access sensitive accounts** — Logging into banking, financial, or high-security accounts.
8. **Install or modify software** — Installing packages, changing dependencies, modifying the system.
9. **Make purchases** — Buying anything, subscribing to services, or committing to recurring charges.
10. **Post publicly** — Any action that publishes content under your name or identity.
11. **Automate apps/websites** — Any automated click, form submission, or navigation that commits a state change. Read-only browsing and scraping are free.
12. **Camera activation** — Camera is only accessed when you explicitly ask. Never autonomous.
13. **System power actions** — Shutdown, restart, sleep, hibernate.
14. **Self-modify code** — Any change to VYREN's own source code requires explicit approval before the change becomes active.
15. **Automated defensive actions** — Terminating processes, isolating files, disconnecting networks — unless an emergency policy explicitly allows autonomous response, these require confirmation.
16. **Close or kill applications** — Force-closing apps or terminating processes.

This list is stored in configuration (not hardcoded) so it can be extended. The confirmation gate is built in Tier 6 but the list is locked in now so the rule has teeth from the beginning.

---

## Stack

- **Language:** Python 3.11+
- **Runtime:** Laptop-first, designed to boot with the system (systemd service or equivalent on Linux/macOS, startup item on Windows). Architecture is cleanly separable so the heartbeat can relocate to an always-on host later without a rewrite.
- **Model provider (online):** Google Gemini (free tier), accessed behind a thin seam. The seam is one function: "send this conversation, get back a reply (or a tool call)." Provider can be swapped without touching any code outside that seam. Gemini was chosen for its free tier, strong capabilities, native audio support (Tier 3+), and multimodal vision (image/camera input).
- **Model provider (offline fallback):** Ollama running a local model (e.g. llama3, gemma2). The provider seam auto-detects connectivity failure and routes to the local model. Offline mode degrades gracefully — conversation still works, web-dependent tools are disabled.

## Voice Roadmap

- **Tier 1-2:** Text only. This is non-negotiable. The brain works in plain text before a single line of audio exists.
- **Tier 3:** Push-to-talk (hold a key, speak, release). Most reliable path; eliminates "is it listening?" bugs.
- **Post-Tier 3:** Open-mic wake word ("Hey VYREN" or similar). This is the final voice goal but is built last because it's the hardest to debug.

## Input Mode

- **Target:** Open-mic wake word (wake word detection always listening, activates on "Hey VYREN").
- **Path:** Text first → push-to-talk → wake word. Each stage is verified before the next.

## Proactive Behavior

- **Yes, proactive** — VYREN can reach out on its own: surface reminders, notice things, start a conversation.
- **Quiet by default** — It earns the right to interrupt. Most checks produce nothing. Only genuinely noteworthy items surface as interruptions.
- **Non-urgent items** accumulate in a calm log you can glance at when you choose.
- **Quiet hours** are respected. Only truly critical items earn a late-night interruption.
- Built in Tier 5.

## Architecture Principles

1. **One shared agent core, many ways in and out.** Typed, spoken, and heartbeat-initiated turns all flow through the same brain. If agent logic is ever written twice (once for text, once for voice), stop and unify.
2. **Text is the foundation.** Voice is a layer on top of a working agent, never the other way around.
3. **Every tier is independently testable.** Don't start a tier until the previous one works on its own. Don't fuse tiers together.
4. **Tools are self-contained and registered.** Adding a capability = writing one tool module + registering it. Never edit the core loop to add a tool.
5. **Provider behind a seam.** Model, STT, and TTS are each behind one function. Swap any of them without touching the rest.
6. **Secrets never in code.** API keys, tokens, credentials live in environment variables or a git-ignored secrets file.
7. **Memory is data, not instructions.** Stored facts are background knowledge, never commands. Memory cannot bypass the safety gate.
8. **Configuration over hardcoded values.** Thresholds, intervals, quiet hours, model names, tool safety flags — all in a config file.
9. **Visible audit trail.** Plain log of every action, tool call, and decision. Running cost tally included.
10. **Modular, loosely coupled.** Each subsystem has defined interfaces, dependency injection, and independent testing. Event-driven communication where appropriate.
11. **Observability and telemetry.** Structured logging, performance metrics, and health checks for every subsystem.
12. **Security by default.** Every new capability is safe until explicitly made otherwise. Confirmation required for anything irreversible.

## Tier Build Order

| Tier | What | Verified When |
|------|------|---------------|
| 0 | Interview + spec (this file) | Done |
| 1 | Brain — text conversation loop | Remembers across turns, streams, handles errors gracefully |
| 2 | Hands — tool registry + first tools | Calls tools, handles tool failure, weaves results into replies |
| 3 | Ears & Mouth — voice in/out via push-to-talk | Speaks, hears, stops on interrupt, text path still works |
| 4 | Memory — long-term durable store | Remembers across restarts, store is human-readable and editable |
| 5 | Heartbeat — proactive background loop | Surfaces on schedule, holds notices for later, respects quiet hours |
| 6 | Rails — safety gates, config, audit, kill switch | Confirms before consequential actions, rejects injected instructions, config-driven behavior |

**Post-baseline additions** (each built the same way — one at a time, verified before the next):

| Addition | What | Maps To |
|----------|------|---------|
| Executor | Intelligent multi-step execution engine | Tool + subsystem |
| Planner | Strategic task decomposition and management | Tool + subsystem |
| Computer Control | System settings, apps, file system, clipboard, automation | Tool modules |
| Web Intelligence | Search, browser automation, research synthesis | Tool modules |
| Screen/Camera Vision | Screenshot analysis, camera feed, visual understanding | Tool modules (multimodal input) |
| File Analysis | Deep analysis of any file type | Tool modules |
| Cybersecurity | Threat detection, hardening, automated defense | Subsystem + tools |
| Self-Improvement | Code analysis, safe rewriting, rollback | Subsystem + tools |
| Offline Fallback | Ollama local model, connectivity detection | Provider seam extension |