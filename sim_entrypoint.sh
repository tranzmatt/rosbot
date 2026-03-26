#!/bin/bash
set -e

source /opt/ros/jazzy/setup.bash

WORLD="${TB4_WORLD:-warehouse}"
MODEL="${TURTLEBOT4_MODEL:-standard}"

echo "[rosbot] Starting TurtleBot4 sim (headless)"
echo "[rosbot] World: ${WORLD}  Model: ${MODEL}"

WORLD_FILE="/opt/ros/jazzy/share/turtlebot4_gz_bringup/worlds/${WORLD}.sdf"
if [ ! -f "$WORLD_FILE" ]; then
    echo "[rosbot] ERROR: World file not found: $WORLD_FILE"
    echo "[rosbot] Available worlds:"
    ls /opt/ros/jazzy/share/turtlebot4_gz_bringup/worlds/
    exit 1
fi

# Launch TB4 sim inside a virtual framebuffer so the GUI process
# gets a fake display and OpenGL works via software rendering
echo "[rosbot] Launching turtlebot4_gz.launch.py via xvfb-run..."
xvfb-run --auto-servernum --server-args="-screen 0 1280x1024x24" \
    ros2 launch turtlebot4_gz_bringup turtlebot4_gz.launch.py \
        headless:=True \
        model:=${MODEL} \
        world:=${WORLD} &

LAUNCH_PID=$!
echo "[rosbot] Waiting for sim to initialize (~30s)..."
sleep 30

if ! kill -0 $LAUNCH_PID 2>/dev/null; then
    echo "[rosbot] ERROR: Sim launch exited unexpectedly"
    exit 1
fi

if ros2 topic list 2>/dev/null | grep -q "/cmd_vel"; then
    echo "[rosbot] ✓ Sim ready"
else
    echo "[rosbot] WARNING: /cmd_vel not found yet — may still be loading"
fi

echo "[rosbot] Starting rosbridge_server on :9090..."
exec ros2 launch rosbridge_server rosbridge_websocket_launch.xml