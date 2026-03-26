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

# Check if gz-ros2-control plugin exists
GZ_CONTROL_LIB=$(find /opt/ros/jazzy -name "libgz_ros2_control*" 2>/dev/null | head -1)
if [ -n "$GZ_CONTROL_LIB" ]; then
    echo "[rosbot] gz-ros2-control found: $GZ_CONTROL_LIB"
else
    echo "[rosbot] WARNING: libgz_ros2_control not found — controllers may fail"
fi

# The TB4 camera sensor requires Ogre rendering even in server mode.
# xvfb-run provides a virtual framebuffer so Ogre can initialize without
# a physical display. LIBGL_ALWAYS_SOFTWARE=1 uses Mesa software rendering.
echo "[rosbot] Launching sim via xvfb-run (virtual framebuffer for sensor rendering)..."
xvfb-run --auto-servernum --server-args="-screen 0 1280x1024x24" \
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
    ros2 topic list 2>/dev/null || true
fi

echo "[rosbot] Starting rosbridge_server on :9090..."
exec ros2 launch rosbridge_server rosbridge_websocket_launch.xml