#!/bin/bash
# rosbot.sh — single entry point for the RosBot stack
#
# Usage:
#   ./rosbot.sh sim           Start headless sim + rosbot server
#   ./rosbot.sh real          Start rosbot server pointed at real TurtleBot4
#   ./rosbot.sh real TB4_IP   Start rosbot pointed at specific TB4 IP
#   ./rosbot.sh down          Stop everything
#   ./rosbot.sh logs          Follow logs from all services
#   ./rosbot.sh status        Show running containers and ports
#   ./rosbot.sh build         Rebuild all images
#   ./rosbot.sh gui           Show command to connect Gazebo GUI from laptop

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# DGX IP — used in help text
DGX_IP="${DGX_IP:-172.32.1.250}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${BLUE}[rosbot]${NC} $1"; }
ok()   { echo -e "${GREEN}[rosbot]${NC} $1"; }
warn() { echo -e "${YELLOW}[rosbot]${NC} $1"; }
err()  { echo -e "${RED}[rosbot]${NC} $1"; }

# Check vLLM is reachable
check_vllm() {
    if curl -sf http://localhost:8001/v1/models > /dev/null 2>&1; then
        ok "vLLM reachable at :8001"
    else
        warn "vLLM not responding at :8001 — LLM features will fail"
        warn "Start vLLM with: CUDA_VISIBLE_DEVICES=1,2,4 vllm serve meta-llama/Llama-3.3-70B-Instruct --port 8001 --enable-auto-tool-choice --tool-call-parser hermes"
    fi
}

cmd="${1:-help}"

case "$cmd" in

    sim)
        log "Starting TurtleBot3 sim (headless) + rosbot server..."
        check_vllm
        docker compose --profile sim up -d --build
        echo ""
        ok "Stack running!"
        echo ""
        echo "  Web UI:      http://${DGX_IP}:8082"
        echo "  Rosbridge:   ws://${DGX_IP}:9090"
        echo ""
        echo "  Watch logs:  ./rosbot.sh logs"
        echo "  Gazebo GUI:  ./rosbot.sh gui"
        ;;

    real)
        TB4_IP="${2:-}"
        if [ -n "$TB4_IP" ]; then
            ROSBRIDGE_URL="ws://${TB4_IP}:9090"
        else
            ROSBRIDGE_URL="${ROSBRIDGE_URL:-ws://turtlebot4.local:9090}"
        fi
        log "Starting rosbot server → real TurtleBot4 at ${ROSBRIDGE_URL}..."
        check_vllm
        ROSBRIDGE_URL="$ROSBRIDGE_URL" TWIST_STAMPED=false \
            docker compose --profile real up -d --build
        echo ""
        ok "Stack running!"
        echo ""
        echo "  Web UI:      http://${DGX_IP}:8082"
        echo "  Rosbridge:   ${ROSBRIDGE_URL}"
        echo ""
        echo "  Make sure rosbridge is running on TB4:"
        echo "    ssh ubuntu@turtlebot4.local"
        echo "    ros2 launch rosbridge_server rosbridge_websocket_launch.xml"
        ;;

    down)
        log "Stopping all services..."
        docker compose --profile sim --profile real down
        ok "Stopped."
        ;;

    logs)
        SERVICE="${2:-}"
        if [ -n "$SERVICE" ]; then
            docker compose logs -f "$SERVICE"
        else
            docker compose --profile sim --profile real logs -f
        fi
        ;;

    status)
        echo ""
        docker compose --profile sim --profile real ps
        echo ""
        echo "Ports in use:"
        ss -tlnp 2>/dev/null | grep -E ':8082|:9090|:8001|:11345' || true
        ;;

    build)
        log "Rebuilding all images..."
        docker compose --profile sim --profile real build --no-cache
        ok "Build complete."
        ;;

    gui)
        echo ""
        echo "To connect Gazebo GUI from your laptop to the headless sim on DGX:"
        echo ""
        echo "  On your laptop (with ROS2 Jazzy installed):"
        echo ""
        echo "    export GZ_IP=${DGX_IP}"
        echo "    gz sim -g"
        echo ""
        echo "  Or if using Docker on laptop:"
        echo ""
        echo "    DISPLAY=\$DISPLAY docker run --rm \\"
        echo "      -e DISPLAY=\$DISPLAY \\"
        echo "      -e GZ_IP=${DGX_IP} \\"
        echo "      -v /tmp/.X11-unix:/tmp/.X11-unix \\"
        echo "      osrf/ros:jazzy-desktop \\"
        echo "      gz sim -g"
        echo ""
        echo "  Alternatively, just use rviz2 on the laptop to visualize topics:"
        echo ""
        echo "    ROS_DOMAIN_ID=0 rviz2"
        ;;

    help|--help|-h|*)
        echo ""
        echo "Usage: ./rosbot.sh <command> [args]"
        echo ""
        echo "Commands:"
        echo "  sim              Start headless TurtleBot3 sim + rosbot on DGX"
        echo "  real [TB4_IP]    Start rosbot pointed at real TurtleBot4"
        echo "  down             Stop all services"
        echo "  logs [service]   Follow logs (all, or specific service)"
        echo "  status           Show running containers"
        echo "  build            Rebuild Docker images"
        echo "  gui              Show how to connect Gazebo GUI from laptop"
        echo ""
        echo "Examples:"
        echo "  ./rosbot.sh sim"
        echo "  ./rosbot.sh real 192.168.1.50"
        echo "  ./rosbot.sh logs rosbot"
        echo "  ./rosbot.sh down"
        echo ""
        ;;
esac
