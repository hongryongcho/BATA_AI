#!/usr/bin/env bash
set -euo pipefail

cat <<'TXT'
This script changes system power settings for server use.
It requires sudo and affects all users on this Mac.
TXT

sudo pmset -c sleep 0 disksleep 0 displaysleep 10 tcpkeepalive 1 powernap 1
sudo pmset -a autorestart 1

cat <<'TXT'
Applied:
- Computer sleep disabled on charger (display can still sleep)
- Auto restart after power loss enabled

Current pmset:
TXT
pmset -g
