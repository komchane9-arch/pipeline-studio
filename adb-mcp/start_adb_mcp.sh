#!/bin/sh
cd "$(dirname "$0")"
python3 adb_mcp_server.py &
sleep 3
cloudflared tunnel --url http://127.0.0.1:8765
