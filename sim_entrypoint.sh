#!/bin/bash
set -e

source /opt/ros/jazzy/setup.bash

# Tell gz sim where to find ROS2 control and other ROS plugins
export GZ_SIM_SYSTEM_PLUGIN_PATH=/opt/ros/jazzy/lib:${GZ_SIM_SYSTEM_PLUGIN_PATH}
export LD_LIBRARY_PATH=/opt/ros/jazzy/lib:${LD_LIBRARY_PATH}

WORLD="${TB4_WORLD:-depot}"
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

# Rendering setup.
#
# The sensors system (LIDAR/camera) forces a render engine to load even in -s server mode.
# By default gz-rendering loads Ogre 1.x (GLX-only) — which crashes without an X display.
# Fix: force Ogre2, which supports EGL and can render without any X display.
#
# GZ_RENDERING_ENGINE=ogre2 selects the Ogre-Next (2.x) plugin.
# With no DISPLAY set, Ogre2 auto-selects EGL over GLX.
export GZ_RENDERING_ENGINE=ogre2

if nvidia-smi &>/dev/null; then
    echo "[rosbot] NVIDIA GPU detected — Ogre2 + EGL (no display required)"
    unset DISPLAY
    export LIBGL_ALWAYS_SOFTWARE=0
    export __EGL_VENDOR_LIBRARY_FILENAMES=/usr/share/glvnd/egl_vendor.d/10_nvidia.json
else
    echo "[rosbot] No NVIDIA GPU — Ogre2 + Xvfb + Mesa"
    export LIBGL_ALWAYS_SOFTWARE=1
    Xvfb :99 -screen 0 1280x1024x24 -ac +extension GLX +render -noreset &
    sleep 5
    export DISPLAY=:99
fi

echo "[rosbot] Launching sim (Ogre2, engine=${GZ_RENDERING_ENGINE})..."
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

# Ensure diffdrive_controller is active (belt-and-suspenders alongside spawner in launch file)
echo "[rosbot] Ensuring diffdrive_controller is active..."
for i in 1 2 3; do
    STATE=$(ros2 control list_controllers 2>/dev/null | grep diffdrive | awk '{print $3}')
    if [ "$STATE" = "active" ]; then
        echo "[rosbot] ✓ diffdrive_controller active"
        break
    fi
    echo "[rosbot] diffdrive state: ${STATE:-unknown}, attempt $i/3..."
    ros2 control set_controller_state diffdrive_controller inactive 2>/dev/null || true
    ros2 control set_controller_state diffdrive_controller active 2>/dev/null || true
    sleep 3
done

if ros2 topic list 2>/dev/null | grep -q "/cmd_vel"; then
    echo "[rosbot] ✓ Sim ready — /cmd_vel is live"
else
    echo "[rosbot] WARNING: /cmd_vel not found yet"
    ros2 topic list 2>/dev/null || true
fi

echo "[rosbot] Starting rosbridge_server on :9090..."
exec ros2 launch rosbridge_server rosbridge_websocket_launch.xml
