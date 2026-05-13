# macOS Server Persistence

## What this setup guarantees
- Services keep running when VS Code is closed.
- Services auto-restart if they crash.
- Services auto-start after reboot.

## Services covered
- MQTT logger: `02_BATA_MQTT/workers/mqtt_logger.py`
- MQTT app dashboard: `00_BATAGOTA/scripts/run_mqtt_app_dashboard.py` (port 8787)
- Telegram bot: `00_BATAGOTA/interfaces/telegram/bot.py`
- Stock backend: `01_BATA_STOCK/backend/src/index.js` (port 4000)

## 1) Login-session persistence (already applied)
LaunchAgents run after the user logs in.

```bash
chmod +x ops/macos/*.sh
ops/macos/install_launchagents.sh
ops/macos/check_services.sh
```

## 2) Boot persistence before login (recommended for true server)
LaunchDaemons start at boot, even before GUI login.

```bash
sudo ops/macos/install_launchdaemons.sh
```

If you use LaunchDaemons, remove LaunchAgents to avoid duplicates:

```bash
ops/macos/uninstall_launchagents.sh
```

## 3) Power settings for server mode
This keeps the machine running while only the display sleeps.

```bash
sudo ops/macos/set_server_power.sh
```

## Useful commands
```bash
ops/macos/check_services.sh
curl -sf http://127.0.0.1:8787/health
curl -sf http://127.0.0.1:4000/health
```

## Rollback
```bash
ops/macos/uninstall_launchagents.sh
sudo ops/macos/uninstall_launchdaemons.sh
```
