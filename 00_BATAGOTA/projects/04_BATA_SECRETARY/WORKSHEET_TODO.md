# BATA Secretary Worksheet (ToDo)

Status values:
- TODO
- IN_PROGRESS
- BLOCKED
- DONE

## 1. Planning and Policy

| ID | Task | Owner | Status | Priority | Start | Due | Done Criteria |
|---|---|---|---|---|---|---|---|
| P-01 | Confirm mode scope (meeting, counseling) | PM | TODO | High |  |  | Scope document approved |
| P-02 | Define sensitive data policy and allowed channels | PM/Sec | TODO | High |  |  | Policy checklist approved |
| P-03 | Define retention policy (audio 90d, logs/docs) | PM/Sec | TODO | High |  |  | Retention matrix signed |
| P-04 | Finalize role model (counselor/manager/admin/auditor) | PM | TODO | High |  |  | RBAC matrix approved |

## 2. Backend and Data

| ID | Task | Owner | Status | Priority | Start | Due | Done Criteria |
|---|---|---|---|---|---|---|---|
| B-01 | Create session APIs | BE | TODO | High |  |  | Create/start/stop/get endpoints working |
| B-02 | Build chunk ingestion API | BE | TODO | High |  |  | Audio chunk upload and ordering validated |
| B-03 | Build image upload API | BE | TODO | Medium |  |  | Whiteboard image upload saved |
| B-04 | Implement draft generation endpoint | BE/ML | TODO | High |  |  | Draft generated from transcript |
| B-05 | Implement confirm and signature endpoints | BE | TODO | High |  |  | Confirm and signature persisted |
| B-06 | Add audit logging for view/edit/confirm/export | BE | TODO | High |  |  | Audit logs queryable by session |

## 3. Processing Pipeline

| ID | Task | Owner | Status | Priority | Start | Due | Done Criteria |
|---|---|---|---|---|---|---|---|
| M-01 | STT worker integration | ML | TODO | High |  |  | Transcript generated from chunks |
| M-02 | Speaker diarization integration | ML | TODO | Medium |  |  | Speaker labels A/B/C available |
| M-03 | OCR worker integration | ML | TODO | Medium |  |  | Text extracted from uploaded images |
| M-04 | Live topic card extraction | ML | TODO | Medium |  |  | Topic cards refresh during session |
| M-05 | Template formatter (meeting/counseling) | BE/ML | TODO | High |  |  | Drafts align with template schema |

## 4. Mobile App

| ID | Task | Owner | Status | Priority | Start | Due | Done Criteria |
|---|---|---|---|---|---|---|---|
| A-01 | Login and token handling | APP | TODO | High |  |  | Login flow stable |
| A-02 | Session lobby and mode selector | APP | TODO | High |  |  | Meeting/counseling mode selectable |
| A-03 | Audio capture and chunk upload | APP | TODO | High |  |  | Continuous upload with retry |
| A-04 | Image capture and upload | APP | TODO | Medium |  |  | Camera upload linked to session |
| A-05 | Live summary card screen | APP | TODO | Medium |  |  | Card list updates in near real-time |
| A-06 | Confirm and sign UI | APP | TODO | High |  |  | Final confirmation flow complete |

## 5. Operations and Release

| ID | Task | Owner | Status | Priority | Start | Due | Done Criteria |
|---|---|---|---|---|---|---|---|
| O-01 | Retention purge scheduler (audio 90d) | OPS | TODO | High |  |  | Daily purge with audit logs |
| O-02 | Backup and restore test | OPS | TODO | High |  |  | Restore test passed |
| O-03 | Health dashboard for sessions and queue | OPS | TODO | Medium |  |  | Key metrics visible |
| O-04 | Release pipeline with rollback | OPS | TODO | High |  |  | Deploy and rollback runbook validated |
| O-05 | GitHub private release cadence | PM/OPS | TODO | Medium |  |  | 2-week release cycle agreed |

## 6. Test and Acceptance

| ID | Task | Owner | Status | Priority | Start | Due | Done Criteria |
|---|---|---|---|---|---|---|---|
| T-01 | End-to-end meeting mode test | QA | TODO | High |  |  | Record -> draft -> sign flow passes |
| T-02 | End-to-end counseling mode test | QA | TODO | High |  |  | Quiet mode flow passes |
| T-03 | Retention and purge verification | QA | TODO | High |  |  | 90d purge validated in test data |
| T-04 | Role-based access test | QA | TODO | High |  |  | Unauthorized access blocked |
| T-05 | Performance test for 1 concurrent session | QA | TODO | Medium |  |  | SLA met for ingest and draft |
| T-06 | Pilot run with real users | PM/QA | TODO | High |  |  | Pilot sign-off completed |

## Weekly Update Log

| Week | Summary | Risks | Next Actions |
|---|---|---|---|
| YYYY-WW |  |  |  |
