#!/bin/bash
set -e

source /opt/ros/jazzy/setup.bash

WORLD="${TB4_WORLD:-warehouse}"
MODEL="${TURTLEBOT4_MODEL:-standard}"

echo "[rosbot] Starting TurtleBot4 sim (headless server)"
echo "[rosbot] World: ${WORLD}  Model: ${MODEL}"

# Validate world file exists
WORLD_FILE="/opt/ros/jazzy/share/turtlebot4_gz_bringup/worlds/${WORLD}.sdf"
if [ ! -f "$WORLD_FILE" ]; then
    echo "[rosbot] ERROR: World file not found: $WORLD_FILE"
    echo "[rosbot] Available worlds:"
    ls /opt/ros/jazzy/share/turtlebot4_gz_bringup/worlds/
    exit 1
fi

# Launch full TB4 sim via the proper launch file
# headless:=True suppresses GUI, server:=True runs gz sim -s
# GZ_HEADLESS_RENDERING=1 tells Ogre not to attempt display output
echo "[rosbot] Launching turtlebot4_gz.launch.py (headless)..."
ros2 launch turtlebot4_gz_bringup turtlebot4_gz.launch.py \
    headless:=True \
    model:=${MODEL} \
    world:=${WORLD} &

LAUNCH_PID=$!

echo "[rosbot] Waiting for sim to initialize (~25s)..."
sleep 25

# Check sim is still alive
if ! kill -0 $LAUNCH_PID 2>/dev/null; then
    echo "[rosbot] ERROR: Sim launch exited unexpectedly"
    exit 1
fi

# Check for cmd_vel
if ros2 topic list 2>/dev/null | grep -q "/cmd_vel"; then
    echo "[rosbot] ✓ /cmd_vel found — sim is ready"
else
    echo "[rosbot] WARNING: /cmd_vel not found yet — sim may still be loading"
fi

echo "[rosbot] Starting rosbridge_server on :9090..."
exec ros2 launch rosbridge_server rosbridge_websocket_launch.xml