#!/bin/bash
# rosbot.sh — single entry point for the RosBot stack
#
# Usage:
#   ./rosbot.sh sim           Start vLLM + headless TB4 sim + rosbot server
#   ./rosbot.sh real          Start vLLM + rosbot server → real TurtleBot4
#   ./rosbot.sh real TB4_IP   Start vLLM + rosbot server → specific TB4 IP
#   ./rosbot.sh down          Stop everything
#   ./rosbot.sh logs          Follow logs from all services
#   ./rosbot.sh logs vllm     Follow vLLM logs only
#   ./rosbot.sh logs sim      Follow sim logs only
#   ./rosbot.sh logs rosbot   Follow rosbot server logs only
#   ./rosbot.sh status        Show running containers and ports
#   ./rosbot.sh build         Rebuild all images (not vLLM — it's a pulled image)
#   ./rosbot.sh gui           Show how to connect Gazebo GUI from laptop

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env if present (for DGX_IP etc. in help text)
[ -f .env ] && source .env

DGX_IP="${DGX_IP:-$(hostname -I | awk '{print $1}')}"
PORT="${PORT:-8082}"

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

# Warn if .env is missing
check_env() {
    if [ ! -f .env ]; then
        warn ".env not found — using defaults from .env.example"
        warn "Run: cp .env.example .env && nano .env"
    fi
    if ! grep -q "HUGGING_FACE_HUB_TOKEN=hf_" .env 2>/dev/null; then
        warn "HUGGING_FACE_HUB_TOKEN not set in .env — vLLM may fail on gated models"
    fi
}

# Wait for vLLM healthcheck to pass
wait_for_vllm() {
    log "Waiting for vLLM to load model (this takes 2-5 minutes on first start)..."
    local attempts=0
    local max=60  # 60 x 5s = 5 minutes
    while [ $attempts -lt $max ]; do
        if curl -sf http://localhost:8001/v1/models > /dev/null 2>&1; then
            ok "vLLM is ready"
            return 0
        fi
        attempts=$((attempts + 1))
        printf "."
        sleep 5
    done
    echo ""
    err "vLLM did not become ready in time. Check logs: ./rosbot.sh logs vllm"
    return 1
}

cmd="${1:-help}"

case "$cmd" in

    sim)
        check_env
        log "Starting vLLM + TurtleBot4 sim (headless) + rosbot server..."
        docker compose --profile sim up -d --build
        echo ""
        wait_for_vllm
        echo ""
        ok "Stack running!"
        echo ""
        echo "  Web UI:      http://${DGX_IP}:${PORT}"
        echo "  Rosbridge:   ws://${DGX_IP}:9090"
        echo "  vLLM API:    http://${DGX_IP}:8001/v1"
        echo ""
        echo "  Watch logs:  ./rosbot.sh logs"
        echo "  Gazebo GUI:  ./rosbot.sh gui"
        ;;

    real)
        check_env
        TB4_IP="${2:-}"
        if [ -n "$TB4_IP" ]; then
            export ROSBRIDGE_URL="ws://${TB4_IP}:9090"
        else
            export ROSBRIDGE_URL="${ROSBRIDGE_URL:-ws://turtlebot4.local:9090}"
        fi
        log "Starting vLLM + rosbot server → real TurtleBot4 at ${ROSBRIDGE_URL}..."
        ROSBRIDGE_URL="$ROSBRIDGE_URL" \
            docker compose --profile real up -d --build
        echo ""
        wait_for_vllm
        echo ""
        ok "Stack running!"
        echo ""
        echo "  Web UI:      http://${DGX_IP}:${PORT}"
        echo "  Rosbridge:   ${ROSBRIDGE_URL}"
        echo "  vLLM API:    http://${DGX_IP}:8001/v1"
        echo ""
        echo "  Make sure rosbridge is running on TurtleBot4:"
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
        echo "Ports:"
        ss -tlnp 2>/dev/null | grep -E ":${PORT}|:9090|:8001|:11345" || true
        ;;

    build)
        log "Rebuilding rosbot images (sim + server)..."
        log "Note: vLLM uses a pulled image and won't be rebuilt"
        docker compose --profile sim --profile real build --no-cache
        ok "Build complete."
        ;;

    gui)
        echo ""
        echo "Connect Gazebo GUI from your laptop to the headless sim on DGX:"
        echo ""
        echo "  Option 1 — native ROS2 Jazzy on laptop:"
        echo ""
        echo "    export GZ_IP=${DGX_IP}"
        echo "    gz sim -g"
        echo ""
        if ! command -v gz &>/dev/null; then
            echo "  WARNING: 'gz' not found on this machine. Install Gazebo Harmonic:"
            echo "    https://gazebosim.org/docs/harmonic/install"
            echo ""
        fi
        echo "  Option 2 — rviz2 for topic visualization (lighter):"
        echo ""
        echo "    export ROS_DOMAIN_ID=0"
        echo "    rviz2"
        echo ""
        ;;

    help|--help|-h|*)
        echo ""
        echo "Usage: ./rosbot.sh <command> [args]"
        echo ""
        echo "Commands:"
        echo "  sim              Start vLLM + TB4 sim (headless) + rosbot server"
        echo "  real [IP]        Start vLLM + rosbot server → real TurtleBot4"
        echo "  down             Stop all services"
        echo "  logs [service]   Follow logs (all, or: vllm, sim, rosbot)"
        echo "  status           Show running containers and ports"
        echo "  build            Rebuild sim + rosbot images"
        echo "  gui              Show how to connect Gazebo GUI from laptop"
        echo ""
        echo "Examples:"
        echo "  ./rosbot.sh sim"
        echo "  ./rosbot.sh real 192.168.1.50"
        echo "  ./rosbot.sh logs vllm"
        echo "  ./rosbot.sh down"
        echo ""
        ;;
esac