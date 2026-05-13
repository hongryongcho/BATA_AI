# Development Specification - App P/G

## 1. Objective
Define mobile application behavior for real-time capture and review workflows.

## 2. App Modes
### Meeting Mode
- Visible live cards for topics and action items
- Facilitator review and correction during session

### Counseling Mode
- Minimal UI exposure during active dialog
- Post-session counselor review and confirmation

## 3. Core Screens
- Login Screen
- Mode Selection Screen
- Session Lobby Screen
- Recording Screen
- Live Summary Cards Screen (meeting)
- Quiet Review Screen (counseling)
- Draft Review Screen
- Confirm and Sign Screen
- Session History Screen

## 4. UX Flows
### 4.1 Standard Flow
Login -> Select mode -> Create session -> Start recording -> Upload chunks/images -> Stop -> Review draft -> Confirm -> Sign -> Final view

### 4.2 Network Failure Flow
- Detect connectivity loss
- Continue local buffering of chunks
- Show sync backlog counter
- Auto-retry when network restored

### 4.3 App Crash Recovery Flow
- Recover local unsent chunks
- Resume upload by last acknowledged chunk_index
- Rebind to existing active session if available

## 5. Audio Capture and Upload Rules
- Chunk duration: 5~15 seconds (configurable)
- Preferred codec: Opus
- Sequence number required for every chunk
- Retry policy:
  - exponential backoff
  - max retry count configurable
  - manual force-sync button provided

## 6. Image Capture Rules
- Direct camera capture and upload
- Session binding required before upload
- Metadata:
  - captured_at
  - device_id
  - source_tag (whiteboard, document, etc.)

## 7. Draft Review and Signature UX
- Draft must show:
  - key topics
  - action items
  - unresolved questions
  - evidence references
- Confirm step must be explicit (double-check prompt)
- Signature step must show immutable warning before submit

## 8. Role-based App Behavior
- counselor/facilitator: create and manage sessions
- manager: review and approve organizational records
- auditor: read-only access to permitted records and audit trails
- admin: policy and user management

## 9. Privacy and Security Requirements
- No raw source media in push notification contents
- Local cache encrypted at rest
- Auto wipe local cache after successful sync and retention threshold
- Screen capture policy configurable for counseling mode

## 10. Notification Policy
- Allowed:
  - session start/stop confirmation
  - processing complete alerts
  - final document ready alerts
- Restricted:
  - transcript body in notifications
  - sensitive content previews

## 11. App Telemetry (Internal Only)
- upload success/failure rates
- chunk retry counts
- average sync delay
- crash reports without sensitive payload

## 12. App P/G Acceptance Checklist
| Item | Criteria | Result |
|---|---|---|
| Login | Token flow stable across app relaunch | TBD |
| Recording | Continuous chunk upload with ordering | TBD |
| Offline retry | Backlog auto-sync after reconnect | TBD |
| Draft review | Mode-specific template correctly shown | TBD |
| Confirm/sign | Signature workflow completed and logged | TBD |
| Privacy | No sensitive content in notifications | TBD |
