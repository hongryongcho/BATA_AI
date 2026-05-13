# Development Specification Master

## 1. Document Purpose
This master specification defines mandatory requirements and integration boundaries for BATA Secretary project.
It is the source of truth for:
- H/W specification
- Server F/W specification
- App P/G specification

## 2. Product Goal
Build a mobile-first assistant for:
- Meeting mode: real-time capture and structured minutes
- Counseling mode: low-visibility structured counseling records

Primary constraints:
- Source analysis data must not be sent to external AI services
- Source audio retention is 90 days by policy
- User login is required for access
- Final artifacts require confirmation and electronic signature

## 3. Scope
### In Scope
- Real-time audio chunk ingestion from mobile app
- Image upload for whiteboard or supporting notes
- STT + speaker labeling + summary draft generation
- Confirm and signature workflow
- Role-based access control
- Retention purge and audit log

### Out of Scope (MVP)
- Multi-language legal compliance automation
- Advanced medical diagnosis support
- Public cloud external AI inference

## 4. Mode Definition
### Mode A: Meeting
- Multi-party discussion
- Topic/subtopic cards shown during session
- Action item extraction (owner, due date)

### Mode B: Counseling
- Quiet operation UX
- Structured QnA extraction
- Restricted access records with counselor confirmation

## 5. System Components
- Mobile App (capture, upload, review, confirm)
- Server API (auth, sessions, ingestion, finalization)
- Processing Workers (STT, diarization, OCR, summarization)
- Data Store (source media, transcript, draft, final)
- Audit Store (access/edit/confirm/export events)

## 6. Integration Rules
- Mobile app and server must communicate via authenticated HTTPS
- Session IDs are globally unique and immutable
- Every chunk/image/note must be linked to a session_id
- Confirm and signature operations must be immutable events

## 7. Data Classification
### Class C1 (Sensitive Source)
- Raw audio chunks
- Uploaded images
- Raw transcript with timestamps

### Class C2 (Operational)
- Topic cards
- Draft summaries
- Non-final comments

### Class C3 (Final Business Record)
- Confirmed final minutes/counseling notes
- Signature metadata

Handling rules:
- C1 must never be exported externally by default
- C1 retention = 90 days then purge
- C3 retention policy configurable by organization

## 8. Non-Functional Requirements
- Concurrency: 1 active session (expand to 2 after profiling)
- Chunk ingest latency (LAN): <= 2 sec average
- Draft generation (1-hour session): <= 120 sec target
- Availability target for MVP: 99.0%
- Full auditability for view/edit/confirm/sign/export

## 9. Security Requirements
- RBAC roles: counselor, facilitator, manager, admin, auditor
- JWT or equivalent token auth with refresh control
- Encryption in transit (TLS)
- Encryption at rest for sensitive stores
- Access and modification logs are mandatory and queryable

## 10. Lifecycle and Retention
- Session states:
  INIT -> RECORDING -> REVIEW -> CONFIRMED -> SIGNED -> ARCHIVED -> PURGED
- Daily purge job deletes C1 data older than 90 days
- Purge action must write immutable audit records

## 11. Release and Update Policy
- Repository: private only
- Release strategy: tagged release with rollback path
- No direct hot patch to production branch without log
- Dependency versions must be pinned

## 12. Traceability Matrix (Must Fill During Build)
| Req ID | Requirement | Source Spec | Design Ref | API Ref | Test Case | Status |
|---|---|---|---|---|---|---|
| R-001 | Real-time audio chunk ingest | MASTER |  |  |  | TODO |
| R-002 | 90-day source audio retention purge | MASTER |  |  |  | TODO |
| R-003 | Confirm + signature immutability | MASTER |  |  |  | TODO |
| R-004 | RBAC restricted access | MASTER |  |  |  | TODO |
| R-005 | Internal-only source analysis | MASTER |  |  |  | TODO |

## 13. Open Items
- Decide exact e-signature standard (internal hash-sign vs certified)
- Define C3 retention period by domain (meeting/counseling)
- Define optional email policy per mode
