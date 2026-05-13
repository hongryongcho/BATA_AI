# Development Specification - H/W

## 1. Objective
Define hardware requirements for pilot and scale-up operation of BATA Secretary.

## 2. Deployment Assumption
- Primary server: Mac mini (16GB RAM / 512GB SSD)
- Mobile clients: smartphone app users (iOS/Android)
- Network: primarily local network, optional remote access via VPN

## 3. Server Hardware Baseline (MVP)
- CPU: Apple Silicon class suitable for speech processing workloads
- RAM: 16GB minimum
- Storage: 512GB minimum
- Network: wired Ethernet preferred for stable ingestion
- Power: UPS recommended for session continuity

## 4. Storage Planning
### 4.1 Source Audio (C1)
- Codec target: Opus 24~32 kbps
- Retention: 90 days
- Estimated volume (360h): approx 3.8~5.1 GB at 24~32 kbps

### 4.2 Supporting Data
- Image uploads, transcript, draft, final docs, logs
- Allocate dedicated partitions/paths for:
  - /data/source_audio
  - /data/source_images
  - /data/transcripts
  - /data/final_docs
  - /data/audit_logs

### 4.3 Capacity Policy
- Warning threshold: 70%
- Critical threshold: 85%
- Auto-block new sessions if critical threshold exceeded

## 5. Client Device Requirements
- OS: iOS/Android supported versions to be defined
- Mic quality: built-in smartphone mic (minimum)
- Camera: basic camera sufficient for whiteboard capture
- Local cache: app must support offline queue for chunk retries

## 6. Network Requirements
- Internal mode: LAN preferred
- External mode: VPN-only exposure (no direct open public endpoint)
- QoS targets for chunk upload:
  - average RTT under 150 ms in primary operation
  - chunk retry success over 99% in normal conditions

## 7. Redundancy and Availability
- Single server mode for MVP
- Optional active-standby strategy for next stage
- Daily encrypted backup for metadata and final docs
- Weekly restore drill required

## 8. Monitoring Sensors
- CPU utilization
- Memory utilization
- Storage utilization
- Network drop/retry ratio
- Session ingest queue length

## 9. Physical and Operational Controls
- Device access restriction (admin only)
- Locked room or secured rack recommended
- Screen lock and automatic idle lock policy
- Emergency shutdown and restart SOP documented

## 10. Expansion Path
- Phase 1: 1 concurrent active session
- Phase 2: 2 concurrent active sessions after benchmark validation
- Phase 3: scale by adding second server node

## 11. H/W Acceptance Checklist
| Item | Criteria | Result |
|---|---|---|
| RAM headroom | >= 25% free during 1 active session | TBD |
| Storage headroom | >= 30% free after 1 month pilot | TBD |
| Network stability | chunk retry < 1% on LAN | TBD |
| Thermal stability | no throttling under 2h run | TBD |
| Backup recoverability | restore success within RTO target | TBD |
