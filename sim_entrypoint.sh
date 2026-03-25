#!/bin/bash
set -e

source /opt/ros/jazzy/setup.bash

echo "[rosbot] Starting TurtleBot4 Gazebo Harmonic (headless server)..."
echo "[rosbot] Model: ${TURTLEBOT4_MODEL:-standard}"
echo "[rosbot] To view GUI from laptop: gz sim -g"

# Launch TB4 sim — headless=True runs gz sim -s (server only, no GUI)
# world: empty (fastest) or warehouse (more realistic)
ros2 launch turtlebot4_gz_bringup turtlebot4_gz.launch.py \
    headless:=True \
    world:=${TB4_WORLD:-empty} &

SIM_PID=$!
echo "[rosbot] Waiting for simulation to initialize (~20s)..."
sleep 20

# Verify sim is up by checking for /cmd_vel
if ! ros2 topic list 2>/dev/null | grep -q "/cmd_vel"; then
    echo "[rosbot] WARNING: /cmd_vel not found yet, sim may still be loading..."
fi

echo "[rosbot] Starting rosbridge_server on :9090..."
exec ros2 launch rosbridge_server rosbridge_websocket_launch.xml
