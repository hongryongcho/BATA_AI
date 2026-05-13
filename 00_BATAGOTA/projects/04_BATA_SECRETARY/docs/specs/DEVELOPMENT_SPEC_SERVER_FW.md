# Development Specification - Server F/W

## 1. Objective
Define backend and processing service requirements for BATA Secretary server stack.

## 2. Service Boundaries
- API Gateway Service
- Session Orchestrator
- Ingestion Service (audio/image/note)
- Processing Workers (STT/diarization/OCR/summarization)
- Record Service (draft/final/signature)
- Audit Service
- Retention Service

## 3. API Domains
- /api/v1/auth
- /api/v1/sessions
- /api/v1/ingestion
- /api/v1/live
- /api/v1/drafts
- /api/v1/final
- /api/v1/signatures
- /api/v1/audit
- /api/v1/admin/retention

## 4. Session State Machine
- INIT
- RECORDING
- REVIEW
- CONFIRMED
- SIGNED
- ARCHIVED
- PURGED

State rules:
- INIT -> RECORDING only with authorized user
- RECORDING -> REVIEW only by explicit stop action
- REVIEW -> CONFIRMED only with required fields validated
- CONFIRMED -> SIGNED only with valid signature payload
- No backward transition from SIGNED except versioned amendment flow

## 5. Ingestion Contract
### 5.1 Audio Chunks
- Required fields: session_id, chunk_index, started_at, duration_ms, codec
- Chunk order must be validated
- Missing chunks must be tracked and recoverable

### 5.2 Images
- Required fields: session_id, captured_at, source_type
- OCR processing queued asynchronously

### 5.3 Notes
- Required fields: session_id, author_id, timestamp, text

## 6. Processing Pipeline Requirements
- STT output includes timestamps and confidence
- Speaker diarization labels as S1/S2/S3...
- Summarization must provide evidence links to transcript segments
- Separate templates for meeting and counseling modes

## 7. Data Model (Core Entities)
- User
- Role
- Session
- SessionParticipant
- AudioChunk
- ImageAsset
- TranscriptSegment
- TopicCard
- DraftDocument
- FinalDocument
- SignatureEvent
- AuditEvent

## 8. Security and Access Control
- RBAC mandatory on every endpoint
- Token validation at gateway layer
- Endpoint-level scope checks
- Sensitive endpoints require elevated scope:
  - final export
  - signature submission
  - retention run

## 9. Audit Requirements
Mandatory events:
- login, logout
- session create/start/stop
- chunk/image/note upload
- draft generate/edit
- confirm
- sign
- export
- purge

Audit fields:
- actor_id
- action
- target_type
- target_id
- timestamp
- result
- source_ip

## 10. Retention and Purge
- Daily scheduled purge job
- C1 data older than 90 days must be deleted
- Purge execution must generate immutable audit event
- Purge preview mode is required before hard delete in production

## 11. Performance Targets
- ingest API p95 response < 500ms (excluding media transfer time)
- queue-to-transcript first result < 10s target in LAN
- final draft generation < 120s for 1-hour session

## 12. Reliability Targets
- Graceful recovery after restart
- idempotent processing for retried chunk uploads
- no duplicate finalization on repeated confirm/sign calls

## 13. Operational Endpoints
- /health
- /metrics
- /api/v1/admin/diagnostics
- /api/v1/admin/queue-status

## 14. Server F/W Acceptance Checklist
| Area | Criteria | Result |
|---|---|---|
| Auth/RBAC | Unauthorized access blocked | TBD |
| Ingestion | Chunk ordering and retry stable | TBD |
| Pipeline | STT + summary output valid | TBD |
| Finalization | Confirm/sign immutable flow works | TBD |
| Retention | 90-day purge job verified | TBD |
| Audit | All mandatory events recorded | TBD |
