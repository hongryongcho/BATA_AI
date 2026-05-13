# 04_BATA_SECRETARY

Dedicated project workspace for BATA Secretary.

## Scope
- Mobile app driven real-time meeting and counseling capture
- Internal-only processing for source analysis data
- Draft -> review -> confirm -> signed final records

## Documents
- **PRODUCT_INTRODUCTION_KO.md** (한글 제품소개서)
- docs/SCREEN_FLOW_AND_API.md
- WORKSHEET_TODO.md

## Specifications
- docs/specs/DEVELOPMENT_SPEC_MASTER.md
- docs/specs/DEVELOPMENT_SPEC_HW.md
- docs/specs/DEVELOPMENT_SPEC_SERVER_FW.md
- docs/specs/DEVELOPMENT_SPEC_APP_PG.md
- docs/specs/WORKSHEET_SPEC_PROGRESS.md

## Approval Gate (Specification Sign-Off)
- docs/specs/APPROVAL_GATE_CHECKLIST.md
  - **Use this checklist before implementation begins**
  - Confirms all specs are finalized and approved
  - Requires sign-off from PM, engineers, security, and ops

## Operating Principles
- Separate from other BATAGOTA projects by folder boundary
- Sensitive source data is processed only in internal server environment
- Messenger channel is command/notification only for sensitive deployments
