# rosbot

Natural language control of ROS2 robots via a local LLM and rosbridge. Send a text or voice command from any browser — the robot moves.

```
Browser (phone/laptop)
  └─ http://dgx-ip:8082
       └─ FastAPI server
            ├─ Whisper  (voice → text)
            ├─ vLLM / Claude  (text → tool calls)
            └─ rosbridge ws://robot:9090
                 └─ ROS2 /cmd_vel, /odom, /battery_state ...
```

## Features

- **Natural language control** — "go forward 1 meter", "turn left 90 degrees", "spin in a circle"
- **Voice input** — hold the mic button, speak, release (Whisper transcription, runs locally)
- **Local LLM** — works with any OpenAI-compatible endpoint (vLLM, Ollama, LM Studio) or Anthropic API
- **Safety limits** — velocity clamped before publishing, configurable per deployment
- **Quick command buttons** — forward/back/left/right/stop/spin/battery/position
- **Sim + real robot** — one env var to switch between TurtleBot4 sim and real hardware
- **Single command startup** — `./rosbot.sh sim` or `./rosbot.sh real`

## Status

**Confirmed working (sim):**
- Natural language → tool call → robot motion, verified by position change in Gazebo
- Turn + forward in correct relative directions (navigation geometry correct)
- Headless Gazebo Harmonic on NVIDIA DGX A100 with Ogre2/EGL (no display needed)
- Sim clock bridged → physics ticks at real RTF
- diffdrive_controller reliably activates on every startup
- Single command startup: `./rosbot.sh sim`

**Known issues / next steps:**
- Voice input disabled (faster-whisper install in Dockerfile.rosbot needs fixing)
- Real TurtleBot4 untested (change `ROSBRIDGE_URL` in `.env`)

## Hardware / Software

- ROS2 Jazzy
- TurtleBot4 (standard or lite) — sim or real
- Any machine with Docker for the server (tested on NVIDIA DGX A100)
- Any browser for the UI (tested on desktop + iOS Safari)

## Quick Start

### Prerequisites

- Docker + Docker Compose
- A running LLM endpoint — either:
  - **Local vLLM** (recommended): `vllm serve meta-llama/Llama-3.3-70B-Instruct --port 8001 --enable-auto-tool-choice --tool-call-parser hermes`
  - **Anthropic API**: set `ANTHROPIC_API_KEY`

### Sim mode (TurtleBot4 in Gazebo Harmonic)

```bash
git clone https://github.com/mclark/rosbot.git
cd rosbot
cp .env.example .env
# Edit .env — set LLM_BASE_URL, SIM_GPU UUID, HuggingFace token

./rosbot.sh sim
```

Open `http://localhost:8082` (or `http://your-server-ip:8082` from any device on the network).

To watch the simulation from your laptop:

```bash
./rosbot.sh gui   # prints the gz sim -g connect command
```

### Real TurtleBot4

First, start rosbridge on the robot:

```bash
# SSH into TurtleBot4
ssh ubuntu@turtlebot4.local
ros2 launch rosbridge_server rosbridge_websocket_launch.xml
```

Then start the rosbot server pointing at it:

```bash
./rosbot.sh real                        # uses turtlebot4.local
./rosbot.sh real 192.168.1.50          # or explicit IP
```

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` to override defaults.

| Variable | Default | Description |
|---|---|---|
| `LLM_BASE_URL` | `http://host-gateway:8001/v1` | vLLM or any OpenAI-compatible endpoint |
| `LLM_MODEL` | `meta-llama/Llama-3.3-70B-Instruct` | Model name |
| `ANTHROPIC_API_KEY` | — | Use Anthropic instead of local LLM |
| `ROSBRIDGE_URL` | `ws://sim:9090` | rosbridge WebSocket URL |
| `TWIST_STAMPED` | `true` | TwistStamped (true) or Twist (false) on /cmd_vel |
| `WHISPER_MODEL` | `base` | Whisper model: `tiny`, `base`, `small`, `medium` |
| `TURTLEBOT4_MODEL` | `standard` | `standard` or `lite` |
| `TB4_WORLD` | `depot` | Gazebo world: `depot`, `maze`, or `warehouse` |
| `SIM_GPU` | — | NVIDIA GPU UUID for sim container (e.g. `GPU-57456950-...`) |
| `VLLM_GPUS` | — | Comma-separated GPU UUIDs for vLLM |
| `VLLM_TP` | `4` | vLLM tensor parallel size |
| `PORT` | `8082` | Web UI port |

### GPU configuration (DGX / multi-GPU)

The sim container needs a GPU for Ogre2/EGL rendering — without it Gazebo runs at ~0.3% real-time. Set `SIM_GPU` to any available GPU UUID (not the display GPU — use a compute GPU):

```bash
nvidia-smi -L   # find UUID
# Add to .env:
SIM_GPU=GPU-57456950-e6dd-3f97-baac-42c6a9cc3431
```

The sim uses minimal VRAM (~0MB) so it coexists fine on the same GPU as vLLM.

## Commands

```bash
./rosbot.sh sim           # Start headless TB4 sim + server
./rosbot.sh real          # Start server → real TurtleBot4
./rosbot.sh real IP       # Start server → TB4 at specific IP
./rosbot.sh down          # Stop all services
./rosbot.sh logs          # Follow all logs
./rosbot.sh logs rosbot   # Follow server logs only
./rosbot.sh logs sim      # Follow sim logs only
./rosbot.sh status        # Show running containers
./rosbot.sh build         # Rebuild Docker images
./rosbot.sh gui           # Show how to connect Gazebo GUI from laptop
```

## Architecture

```
rosbot/
├── server.py            # FastAPI server (LLM agent + rosbridge client + Whisper)
├── static/
│   └── index.html       # Web UI (vanilla JS, mobile-friendly, voice input)
├── Dockerfile.sim        # TurtleBot4 + Gazebo Harmonic + rosbridge
├── Dockerfile.rosbot     # FastAPI server + Whisper
├── docker-compose.yml    # Orchestrates sim + rosbot profiles
├── headless_sim.launch.py  # ROS2 launch: gz sim -s + clock bridge + spawner
├── sim_entrypoint.sh    # Disables Ogre1, sets up EGL, starts Gazebo + rosbridge
├── rosbot.sh            # Main control script
└── requirements.txt     # Python deps
```

### Headless sim notes

Gazebo Harmonic's sensors system loads a render engine even in server-only (`-s`) mode. The default is Ogre 1.x (GLX-only) which crashes without an X display. `sim_entrypoint.sh` renames `libgz-rendering-ogre.so` to `.bak` at startup, forcing Ogre2 which supports EGL and runs headless on NVIDIA GPUs.

The sim also requires ROS2 `/clock` to be bridged from Gazebo's internal clock — without this, `gz_ros2_control` never ticks and the robot doesn't move despite receiving velocity commands.

### LLM backends

The server auto-detects which backend to use:

- If `LLM_BASE_URL` is set → uses OpenAI-compatible client (vLLM, Ollama, etc.)
- If `ANTHROPIC_API_KEY` is set → uses Anthropic API
- vLLM takes priority if both are set

Tool call parsing includes a fallback for models that emit JSON as plain text instead of structured tool calls (common with some vLLM parser configs).

### ROS2 tools available to the agent

| Tool | Description |
|---|---|
| `drive` | Publish velocity to `/cmd_vel` for a given duration |
| `stop` | Immediately zero velocity |
| `get_position` | Read current x/y from `/odom` |
| `get_battery` | Read battery level from `/battery_state` |
| `list_topics` | Discover available ROS2 topics via rosapi |

## LLM Setup

### vLLM (recommended — fully local)

```bash
# On a machine with NVIDIA GPU(s)
vllm serve meta-llama/Llama-3.3-70B-Instruct \
  --tensor-parallel-size 4 \
  --dtype bfloat16 \
  --port 8001 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes
```

Llama 3.3 70B in bfloat16 needs ~140GB VRAM. For smaller setups:

```bash
# 8B model — fits on a single 16GB GPU
vllm serve meta-llama/Llama-3.1-8B-Instruct \
  --port 8001 \
  --enable-auto-tool-choice \
  --tool-call-parser llama3_json
```

### Anthropic API

```bash
export ANTHROPIC_API_KEY=sk-ant-...
./rosbot.sh sim
```

## Connecting from a Phone

The web UI works on any device with a browser on the same network:

```
http://YOUR_SERVER_IP:8082
```

Voice input uses the browser's MediaRecorder API — works on Chrome, Safari (iOS 14.3+), and Firefox. Hold the mic button to record, release to send.

## Switching to a Different Robot

Any ROS2 robot with rosbridge works:

1. Point `ROSBRIDGE_URL` at your robot's rosbridge instance
2. If `/cmd_vel` expects `Twist` instead of `TwistStamped`, set `TWIST_STAMPED=false`
3. Add tools to `server.py` for robot-specific topics/services

## License

Apache-2.0
