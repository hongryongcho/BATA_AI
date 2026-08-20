# BATAGOTA Family Photo Service

This directory is intentionally isolated from the existing BATAGOTA projects.

## Goals
- keep existing BATAGOTA services untouched
- run Immich as a separate Docker service
- expose it only through picture.batagota.com
- maintain a separate 4-person family account structure
- keep personal folders and shared family folders isolated

## Structure
- `docker-compose.yml` : isolated Immich stack
- `.env.example` : environment template
- `data/` : uploaded photos and metadata
- `library/` : media library root
- `pgdata/` : Postgres data

## Important safety rules
1. Do not modify [10_AI_BATA/00_BATAGOTA/project.contract.yaml](../00_BATAGOTA/project.contract.yaml)
2. Do not modify [10_AI_BATA/00_BATAGOTA/scripts/run_mqtt_app_dashboard.py](../00_BATAGOTA/scripts/run_mqtt_app_dashboard.py)
3. Do not modify [10_AI_BATA/01_BATA_STOCK/backend/src/index.js](../01_BATA_STOCK/backend/src/index.js)
4. Use a separate folder and separate port from existing services
5. Route only `picture.batagota.com` to this service

## Suggested user layout
- father
- mother
- son
- daughter
- family_shared

## Deployment
1. Copy `.env.example` to `.env` and set real secrets.
2. Run `docker compose up -d` from this folder.
3. Access the web UI at `http://localhost:2283` or through reverse proxy at `https://picture.batagota.com`.
4. Create the four family accounts after first login.
5. Create personal libraries/folders and one shared family album.

## Notes
- The service is intentionally separated from the existing BATAGOTA apps.
- No existing BATAGOTA port or start script is changed.
