# Antigravity Agent Configuration

Welcome to the FreeCharge (Tesla-Fronius Solar Tracking Service) workspace. This file serves as the bootstrap context for agent execution.

## 👥 Roles & Governance
- **Architect (User)**: Defines high-level design, product requirements, and features. Reviewer of plans.
- **Executor (Agent)**: Reads files, proposes plans, executes implementation tasks, runs verification checks, and commits code.

## 📂 Memory Layout
All state and memory documents reside under the `.agents/` folder:
- **`ACTIVE_CONTEXT.md`**: Contains system objectives, technical approach, active phase objectives, feature backlog catalog, and verification criteria. Only keep the last 5 completed items in the backlog. Move other items into the project's change_logfile.
- **`ARCHITECTURE.md`**: Maps the system structure, data flows, and directory layout.
- **`LEARNINGS.md`**: Tracks key decisions, bugs resolved, and performance scorecard historical summaries. Only keep the last 5-7 active learning entries (under 15KB). Move older entries to `.agents/archive/LEARNINGS_ARCHIVE.md` to conserve token quota.
- **`rules/`**: Workspace directives and constraints.
  - **`operating_protocol.md`**: The step-by-step execution protocol (CLARIFY, PLAN, EXECUTE, VERIFY, COMMIT) and stateless operations rules.

Before starting any task, the executor must read `AGENTS.md`, `.agents/ACTIVE_CONTEXT.md`, `.agents/ARCHITECTURE.md`, `.agents/LEARNINGS.md`, and `.agents/rules/operating_protocol.md` to load the current workspace state.

## Context Management & Token Quota Optimization
To prevent chat bloat and conserve token quota, you must actively police the conversation history for topic drift:

1. **Detect Topic Shifts**: Before executing a new task or sub-task, analyze whether the previous context is likely to be required. Strive to keep the immediate context to the last 2-3 turns.
2. **Propose Context Pruning**: If context is not required, do not immediately ingest the entire chat history. Instead, halt and explicitly ask the user:
   > *"I notice we are shifting focus to [New Topic]. Should we prune our short-term chat context to save your token quota? If yes, I will sync current progress to `.agents/rules/ACTIVE_CONTEXT.md` and archive this thread's previous history."*
3. **Enforce Progressive Disclosure**: When a topic shift is approved, rely strictly on `@mention` files (e.g., `@ACTIVE_CONTEXT.md`, `@LEARNINGS.md`, `@ARCHITECTURE.md`) for baseline project memory rather than reading old chat code blocks.
