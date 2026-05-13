# Worksheet - Spec Progress Tracker

Use this worksheet to track specification completeness before implementation.

Status values:
- TODO
- IN_PROGRESS
- REVIEW
- APPROVED

| ID | Spec Area | Task | Owner | Status | Target Date | Evidence |
|---|---|---|---|---|---|---|
| S-001 | MASTER | Freeze scope and constraints | PM | TODO |  |  |
| S-002 | MASTER | Approve data classification C1/C2/C3 | PM/Sec | TODO |  |  |
| S-003 | MASTER | Finalize retention and purge policy | PM/Sec | TODO |  |  |
| S-004 | H/W | Validate server baseline and capacity | OPS | TODO |  |  |
| S-005 | H/W | Approve network topology (LAN/VPN) | OPS/Sec | TODO |  |  |
| S-006 | SERVER F/W | Confirm session state machine | BE/PM | TODO |  |  |
| S-007 | SERVER F/W | Confirm API domain and endpoint list | BE | TODO |  |  |
| S-008 | SERVER F/W | Define audit mandatory events | BE/Sec | TODO |  |  |
| S-009 | APP P/G | Confirm mode-specific UX flow | APP/PM | TODO |  |  |
| S-010 | APP P/G | Confirm offline and retry behavior | APP | TODO |  |  |
| S-011 | APP P/G | Confirm signature UX and warnings | APP/PM | TODO |  |  |
| S-012 | CROSS | Traceability matrix mapping complete | PM/QA | TODO |  |  |
| S-013 | CROSS | Risk register reviewed | PM | TODO |  |  |
| S-014 | CROSS | Final spec package approval | PM/Stakeholders | TODO |  |  |

## Risk Register (Spec Phase)

| Risk ID | Risk Description | Impact | Mitigation | Owner | Status |
|---|---|---|---|---|---|
| RSK-01 | Scope creep before MVP freeze | High | Enforce scope gate per milestone | PM | TODO |
| RSK-02 | Ambiguous signature requirement | High | Freeze legal/operational signature policy | PM/Sec | TODO |
| RSK-03 | Retention policy conflicts by domain | Medium | Separate mode-level retention profiles | PM | TODO |
| RSK-04 | Underestimated mobile network instability | Medium | Define mandatory offline queue behavior | APP | TODO |
| RSK-05 | Audit schema missing key fields | High | Review audit event schema with security team | BE/Sec | TODO |
