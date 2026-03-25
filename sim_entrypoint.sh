#!/bin/bash
set -e

source /opt/ros/jazzy/setup.bash

WORLD="${TB4_WORLD:-warehouse}"
MODEL="${TURTLEBOT4_MODEL:-standard}"

echo "[rosbot] Starting TurtleBot4 sim (headless)"
echo "[rosbot] World: ${WORLD}  Model: ${MODEL}"

# Find the world file
WORLD_FILE="/opt/ros/jazzy/share/turtlebot4_gz_bringup/worlds/${WORLD}.sdf"
if [ ! -f "$WORLD_FILE" ]; then
    echo "[rosbot] ERROR: World file not found: $WORLD_FILE"
    echo "[rosbot] Available worlds:"
    ls /opt/ros/jazzy/share/turtlebot4_gz_bringup/worlds/
    exit 1
fi

# Run gz sim server only (-s = server, -r = run immediately, no GUI)
echo "[rosbot] Starting gz sim server with ${WORLD}.sdf..."
GZ_HEADLESS_RENDERING=1 gz sim -s -r "$WORLD_FILE" &
GZ_PID=$!

echo "[rosbot] Waiting for Gazebo server to initialize..."
sleep 8

# Check gz server is still running
if ! kill -0 $GZ_PID 2>/dev/null; then
    echo "[rosbot] ERROR: Gazebo server exited unexpectedly"
    exit 1
fi
echo "[rosbot] Gazebo server running (pid $GZ_PID)"

# Spawn the TurtleBot4 into the running world
echo "[rosbot] Spawning TurtleBot4 (${MODEL})..."
ros2 launch turtlebot4_gz_bringup turtlebot4_spawn.launch.py \
    model:=${MODEL} &
SPAWN_PID=$!

sleep 15

# Launch ROS-Gazebo bridge
echo "[rosbot] Starting ROS-Gazebo bridge..."
ros2 launch turtlebot4_gz_bringup ros_gz_bridge.launch.py \
    model:=${MODEL} &

sleep 5

# Launch turtlebot4 nodes (HMI, etc)
echo "[rosbot] Starting TurtleBot4 nodes..."
ros2 launch turtlebot4_gz_bringup turtlebot4_nodes.launch.py \
    model:=${MODEL} &

sleep 5

echo "[rosbot] Starting rosbridge_server on :9090..."
exec ros2 launch rosbridge_server rosbridge_websocket_launch.xml