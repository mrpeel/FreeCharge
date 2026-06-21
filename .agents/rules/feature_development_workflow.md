# Feature Development Workflow

This workflow provides a safe, step-by-step procedure to analyze, plan, implement, and verify a new feature cleanly in the Pitch Analytix Pro workspace.

## Workflow Steps

1.  **Clarification (`CLARIFY`)**
    *   Review the user's requirements.
    *   Trigger the `/grill-me` command to resolve any design ambiguities, logical gaps, or sensor calibration parameters with the architect.

2.  **Context Alignment**
    *   Read [.agents/ACTIVE_CONTEXT.md](../ACTIVE_CONTEXT.md) and [.agents/ARCHITECTURE.md](../ARCHITECTURE.md) to ensure alignment with established coding patterns, kinematics configurations, and system boundaries.

3.  **Planning (`PLAN`)**
    *   Write a brief Implementation Plan (using the `implementation_plan.md` artifact template).
    *   Outline target files for modification and the verification strategy.
    *   Wait for the user's explicit confirmation/approval before modifying any core code.

4.  **Implementation (`EXECUTE`)**
    *   Apply code changes iteratively in the workspace files.
    *   Keep changes confined and incremental. If needed, delegate isolated tasks to subagents with constrained context limits.

5.  **Test Verification (`VERIFY`)**
    *   Execute the project's test suite to verify that the modifications compile and pass:
        *   **Android/Wear OS**: Run `./gradlew test` (or module-specific tests like `./gradlew :wear:testDebugUnitTest`).
        *   **Python Pipeline**: Run unit tests or simulation checks.

6.  **Code Styling & Linting**
    *   Check for code syntax, quality, and formatting by running:
        *   **Android/Wear OS**: Run `./gradlew lintDebug` or compiler checks.
        *   **Python**: Check syntax/formatting using static checking tooling if applicable.

7.  **Status Sync**
    *   Once changes are verified, update the status table inside [.agents/ACTIVE_CONTEXT.md](../ACTIVE_CONTEXT.md) to reflect the updated feature status (e.g., mark completed features).

8.  **Knowledge Base Update**
    *   If any unique bugs were resolved or critical design decisions made, document them as bullet points inside [.agents/LEARNINGS.md](../LEARNINGS.md).

9.  **Staging & Commits (`COMMIT`)**
    *   Stage the completed files and generate semantic git commits (e.g., `feat: implement Option B audio recorder UI` or `fix: resolve Pull shot false positive threshold`).
    *   Push commits to the remote repository.
