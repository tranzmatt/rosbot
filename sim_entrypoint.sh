#!/bin/bash
set -e

source /opt/ros/jazzy/setup.bash

WORLD="${TB4_WORLD:-warehouse}"
MODEL="${TURTLEBOT4_MODEL:-standard}"

echo "[rosbot] Starting TurtleBot4 sim (headless server only)"
echo "[rosbot] World: ${WORLD}  Model: ${MODEL}"

WORLD_FILE="/opt/ros/jazzy/share/turtlebot4_gz_bringup/worlds/${WORLD}.sdf"
if [ ! -f "$WORLD_FILE" ]; then
    echo "[rosbot] ERROR: World file not found: $WORLD_FILE"
    echo "[rosbot] Available worlds:"
    ls /opt/ros/jazzy/share/turtlebot4_gz_bringup/worlds/
    exit 1
fi

# Use our custom launch file that runs gz sim -s (server only, no GUI process)
# This avoids all Ogre/Qt/OpenGL GUI crashes entirely
echo "[rosbot] Launching headless sim (server-only, no GUI process)..."
ros2 launch /headless_sim.launch.py \
    world:=${WORLD} \
    model:=${MODEL} &

LAUNCH_PID=$!
echo "[rosbot] Waiting for sim to initialize (~35s)..."
sleep 35

if ! kill -0 $LAUNCH_PID 2>/dev/null; then
    echo "[rosbot] ERROR: Sim launch exited unexpectedly"
    exit 1
fi

if ros2 topic list 2>/dev/null | grep -q "/cmd_vel"; then
    echo "[rosbot] ✓ Sim ready — /cmd_vel is live"
else
    echo "[rosbot] WARNING: /cmd_vel not found yet"
fi

echo "[rosbot] Starting rosbridge_server on :9090..."
exec ros2 launch rosbridge_server rosbridge_websocket_launch.xml