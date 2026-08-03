#!/bin/sh
# Interactive RetroNix session: server in the background, SIMH console in
# your terminal. You are the operator; type at the retronix> prompt.
# Exit: Ctrl-E to break to the sim> prompt, then `quit`.
set -e
cd "$(dirname "$0")/.."

PORT="${RETRONIX_PORT:-5810}"
LOG="build/play-log.jsonl"

make image >/dev/null

python3 server/retronix_server.py --port "$PORT" --log "$LOG" &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null; wait $SERVER_PID 2>/dev/null' EXIT
sleep 0.5

INI="build/play.ini"
cat > "$INI" <<EOF
set cpu 8080
set ptr disabled
set ptp disabled
set m2sio1 enabled
set m2sio1 dtr
attach m2sio1 connect=127.0.0.1:$PORT;notelnet
load build/retronix.bin 0
echo
echo RetroNix interactive session. Commands: dir, type <file>, run <file>,
echo ls /dev, config, bind. Exit: Ctrl-E then quit.
echo Wire oracle: tail -f $LOG (in another terminal)
echo
go 0
EOF

exec tools/bin/altairz80 "$INI"
