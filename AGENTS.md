# BATA Orchestrator Rules

## Purpose
- This repository root acts as the central orchestrator for multi-project operations under /Users/batagota/BATAGOTA/10_AI_BATA.
- The assistant named BATA routes natural-language requests to project-level controls.

## Project Source of Truth
- Read project registry first: ops/projects.registry.yaml.
- For each target project, read project.contract.yaml before any execution.

## Execution Policy
1. Status first, then action.
- Always run status and health checks before start/stop/restart.

2. Prefer deterministic scripts.
- Use project scripts in scripts/control/start.ps1, stop.ps1, status.ps1, health.ps1.

3. Approval boundary.
- Destructive actions require explicit user confirmation.
- Non-destructive checks can run immediately.

4. Error reporting format.
- Report: project, action, result, evidence, next action.

5. Logging discipline.
- Include log path from each project contract in responses.

## Routing Rule
- Identify intent from user request:
  - health-check
  - status
  - start
  - stop
  - restart
  - run-job
  - inspect-logs
- Select project by registry metadata and keywords.

## Priority Projects
- 00_BATAGOTA
- 01_BATA_STOCK/backend
- 02_BATA_MQTT

## Safety
- Never kill unrelated processes.
- Filter processes by both script name and project path.
- Never modify .env values without explicit request.
