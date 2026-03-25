"""
RosBot — Natural language TurtleBot4 control.

Supports two LLM backends (auto-detected from env vars):
  Local vLLM:  set LLM_BASE_URL and LLM_MODEL
  Anthropic:   set ANTHROPIC_API_KEY

Environment variables:
    ROSBRIDGE_URL      WebSocket URL of rosbridge_server  (default: ws://localhost:9090)
    LLM_BASE_URL       vLLM OpenAI-compatible base URL    (e.g. http://dgx-ip:8001/v1)
    LLM_MODEL          Model name served by vLLM          (e.g. meta-llama/Llama-3.3-70B-Instruct)
    ANTHROPIC_API_KEY  Anthropic API key (used if LLM_BASE_URL not set)
    WHISPER_MODEL      Whisper model size                 (default: base)
    TWIST_STAMPED      true for TurtleBot3 Gazebo sim     (default: false)
    HOST               Bind host                          (default: 0.0.0.0)
    PORT               Bind port                          (default: 8082)
"""

import asyncio
import base64
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import uvicorn
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ROSBRIDGE_URL      = os.environ.get("ROSBRIDGE_URL", "ws://localhost:9090")
WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL", "base")
HOST               = os.environ.get("HOST", "0.0.0.0")
PORT               = int(os.environ.get("PORT", "8082"))
TWIST_STAMPED      = os.environ.get("TWIST_STAMPED", "false").lower() == "true"

# LLM backend — vLLM takes priority over Anthropic
LLM_BASE_URL  = os.environ.get("LLM_BASE_URL", "")
LLM_MODEL     = os.environ.get("LLM_MODEL", "meta-llama/Llama-3.3-70B-Instruct")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

USE_LOCAL_LLM = bool(LLM_BASE_URL)

MAX_LINEAR  = 0.3   # m/s
MAX_ANGULAR = 1.0   # rad/s

# ---------------------------------------------------------------------------
# LLM client setup
# ---------------------------------------------------------------------------

if USE_LOCAL_LLM:
    from openai import OpenAI
    llm_client = OpenAI(base_url=LLM_BASE_URL, api_key="not-needed")
    print(f"LLM backend: vLLM @ {LLM_BASE_URL} model={LLM_MODEL}")
else:
    import anthropic
    llm_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    LLM_MODEL  = "claude-sonnet-4-20250514"
    print(f"LLM backend: Anthropic claude-sonnet-4-20250514")

# ---------------------------------------------------------------------------
# Whisper (optional)
# ---------------------------------------------------------------------------

whisper_model = None
try:
    from faster_whisper import WhisperModel
    print(f"Loading Whisper '{WHISPER_MODEL_SIZE}'...")
    whisper_model = WhisperModel(WHISPER_MODEL_SIZE, device="cpu", compute_type="int8")
    print("Whisper ready.")
except ImportError:
    print("faster-whisper not installed — voice disabled.")


def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/webm") -> Optional[str]:
    if whisper_model is None:
        return None
    suffix = ".wav" if "wav" in mime_type else ".m4a" if "mp4" in mime_type or "m4a" in mime_type else ".ogg" if "ogg" in mime_type else ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        tmp = f.name
    try:
        segments, _ = whisper_model.transcribe(tmp, beam_size=5)
        return " ".join(s.text.strip() for s in segments).strip() or None
    finally:
        Path(tmp).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Rosbridge client
# ---------------------------------------------------------------------------

class RosbridgeClient:
    def __init__(self, url: str):
        self.url = url
        self.ws = None
        self._pending: dict[str, asyncio.Future] = {}
        self._subscribers: dict[str, list[asyncio.Queue]] = {}
        self._recv_task = None
        self._connected = False

    async def connect(self) -> bool:
        try:
            self.ws = await websockets.connect(self.url, ping_interval=20, ping_timeout=10)
            self._recv_task = asyncio.create_task(self._recv_loop())
            self._connected = True
            print(f"Connected to rosbridge at {self.url}")
            return True
        except Exception as e:
            print(f"Rosbridge connection failed: {e}")
            self._connected = False
            return False

    async def ensure_connected(self) -> bool:
        if self._connected and self.ws and self.ws.close_code is None:
            return True
        return await self.connect()

    async def _recv_loop(self):
        try:
            async for raw in self.ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                op     = msg.get("op", "")
                msg_id = msg.get("id")
                if op == "service_response":
                    if msg_id and msg_id in self._pending:
                        fut = self._pending[msg_id]
                        if not fut.done():
                            fut.set_result(msg)
                elif op == "publish":
                    topic   = msg.get("topic", "")
                    payload = msg.get("msg", {})
                    for q in self._subscribers.get(topic, []):
                        try:
                            q.put_nowait(payload)
                        except asyncio.QueueFull:
                            pass
        except websockets.ConnectionClosed:
            self._connected = False
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("rosbridge disconnected"))
        except Exception as e:
            print(f"rosbridge recv error: {e}")
            self._connected = False

    async def publish(self, topic: str, msg_type: str, msg: dict):
        if not await self.ensure_connected():
            raise ConnectionError("Cannot connect to rosbridge")
        await self.ws.send(json.dumps({"op": "publish", "topic": topic, "type": msg_type, "msg": msg}))

    async def subscribe_once(self, topic: str, msg_type: str, timeout: float = 5.0) -> Optional[dict]:
        if not await self.ensure_connected():
            return None
        q: asyncio.Queue = asyncio.Queue(maxsize=1)
        sub_id = f"sub_{uuid.uuid4().hex[:8]}"
        if topic not in self._subscribers:
            self._subscribers[topic] = []
            await self.ws.send(json.dumps({
                "op": "subscribe", "id": sub_id,
                "topic": topic, "type": msg_type,
                "queue_length": 1, "throttle_rate": 0,
            }))
        self._subscribers[topic].append(q)
        try:
            return await asyncio.wait_for(q.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            subs = self._subscribers.get(topic, [])
            if q in subs:
                subs.remove(q)
            if not subs:
                self._subscribers.pop(topic, None)
                try:
                    await self.ws.send(json.dumps({"op": "unsubscribe", "topic": topic}))
                except Exception:
                    pass

    @property
    def connected(self) -> bool:
        return self._connected and self.ws is not None and self.ws.close_code is None


ros = RosbridgeClient(ROSBRIDGE_URL)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_twist_msg(linear_x: float, angular_z: float) -> tuple[str, dict]:
    body = {
        "linear":  {"x": linear_x, "y": 0.0, "z": 0.0},
        "angular": {"x": 0.0,      "y": 0.0, "z": angular_z},
    }
    if TWIST_STAMPED:
        return "geometry_msgs/msg/TwistStamped", {"header": {"frame_id": "base_link"}, "twist": body}
    return "geometry_msgs/msg/Twist", body


# ---------------------------------------------------------------------------
# ROS2 tools
# ---------------------------------------------------------------------------

async def ros_drive(linear_x: float, angular_z: float, duration: float = 1.0) -> str:
    linear_x  = max(-MAX_LINEAR,  min(MAX_LINEAR,  linear_x))
    angular_z = max(-MAX_ANGULAR, min(MAX_ANGULAR, angular_z))
    duration  = max(0.1, min(30.0, duration))

    msg_type, drive_msg = _make_twist_msg(linear_x, angular_z)
    _,        stop_msg  = _make_twist_msg(0.0, 0.0)

    steps = max(1, int(duration * 10))
    for _ in range(steps):
        await ros.publish("/cmd_vel", msg_type, drive_msg)
        await asyncio.sleep(0.1)
    await ros.publish("/cmd_vel", msg_type, stop_msg)

    dir_str  = "forward" if linear_x > 0 else "backward" if linear_x < 0 else ""
    turn_str = "left" if angular_z > 0 else "right" if angular_z < 0 else ""
    parts    = [p for p in [dir_str, turn_str] if p]
    motion   = " + ".join(parts) if parts else "in place"
    return f"Drove {motion} at {abs(linear_x):.2f} m/s / {abs(angular_z):.2f} rad/s for {duration:.1f}s"


async def ros_stop() -> str:
    msg_type, stop_msg = _make_twist_msg(0.0, 0.0)
    await ros.publish("/cmd_vel", msg_type, stop_msg)
    return "Robot stopped."


async def ros_get_position() -> str:
    msg = await ros.subscribe_once("/odom", "nav_msgs/msg/Odometry", timeout=4.0)
    if msg is None:
        return "Could not read odometry (timeout)."
    pos = msg.get("pose", {}).get("pose", {}).get("position", {})
    return f"Position: x={pos.get('x', 0):.3f}m, y={pos.get('y', 0):.3f}m"


async def ros_get_battery() -> str:
    msg = await ros.subscribe_once("/battery_state", "sensor_msgs/msg/BatteryState", timeout=4.0)
    if msg is None:
        return "Could not read battery (timeout or topic unavailable)."
    pct     = msg.get("percentage", 0.0) * 100
    voltage = msg.get("voltage", 0.0)
    return f"Battery: {pct:.0f}% ({voltage:.1f}V)"


async def ros_list_topics() -> str:
    if not await ros.ensure_connected():
        return "Not connected to rosbridge."
    msg_id = f"topics_{uuid.uuid4().hex[:8]}"
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    ros._pending[msg_id] = fut
    await ros.ws.send(json.dumps({
        "op": "call_service", "id": msg_id,
        "service": "/rosapi/topics", "type": "rosapi/srv/Topics", "args": {},
    }))
    try:
        resp   = await asyncio.wait_for(fut, timeout=5.0)
        topics = resp.get("values", {}).get("topics", [])
        return "Available topics:\n" + "\n".join(f"  {t}" for t in sorted(topics))
    except asyncio.TimeoutError:
        return "Timeout listing topics."
    finally:
        ros._pending.pop(msg_id, None)


async def execute_tool(tool_name: str, tool_input: dict) -> str:
    try:
        if tool_name == "drive":
            return await ros_drive(
                linear_x  = float(tool_input.get("linear_x", 0.0)),
                angular_z = float(tool_input.get("angular_z", 0.0)),
                duration  = float(tool_input.get("duration", 1.0)),
            )
        elif tool_name == "stop":      return await ros_stop()
        elif tool_name == "get_position": return await ros_get_position()
        elif tool_name == "get_battery":  return await ros_get_battery()
        elif tool_name == "list_topics":  return await ros_list_topics()
        else: return f"Unknown tool: {tool_name}"
    except ConnectionError as e:
        return f"ROS2 connection error: {e}"
    except Exception as e:
        return f"Tool error ({tool_name}): {e}"


# ---------------------------------------------------------------------------
# Tool definitions (shared schema, both backends)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "drive",
        "description": (
            "Drive the TurtleBot4. Positive linear_x=forward, negative=backward. "
            "Positive angular_z=turn left, negative=turn right. "
            "Always specify duration so the robot stops automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "linear_x":  {"type": "number", "description": "Forward/back speed m/s. Range -0.3 to 0.3."},
                "angular_z": {"type": "number", "description": "Rotation rad/s. Positive=left, negative=right. Range -1.0 to 1.0."},
                "duration":  {"type": "number", "description": "Drive time in seconds. Default 1.0, max 30."},
            },
            "required": ["linear_x", "angular_z"],
        },
    },
    {
        "name": "stop",
        "description": "Immediately stop all robot motion.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_position",
        "description": "Get the robot's current x/y position from odometry.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_battery",
        "description": "Get the robot's current battery level and voltage.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_topics",
        "description": "List all available ROS2 topics the robot is publishing.",
        "input_schema": {"type": "object", "properties": {}},
    },
]

# OpenAI format for vLLM
TOOLS_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        }
    }
    for t in TOOLS
]

SYSTEM_PROMPT = f"""You are a robot controller for a TurtleBot4 running ROS2 Jazzy.
Translate natural language commands into robot actions using the provided tools.

Safety rules:
- Max linear speed: {MAX_LINEAR} m/s
- Max angular speed: {MAX_ANGULAR} rad/s
- Never drive more than 30 seconds in one command
- Ask for clarification if ambiguous or dangerous

Motion reference:
- "forward/ahead" → drive(linear_x=0.2, angular_z=0, duration=2)
- "backward/reverse" → drive(linear_x=-0.2, angular_z=0, duration=2)
- "turn left 90°" → drive(linear_x=0, angular_z=0.5, duration=3.14)
- "turn right 90°" → drive(linear_x=0, angular_z=-0.5, duration=3.14)
- "spin 360°" → drive(linear_x=0, angular_z=0.5, duration=6.28)
- "circle" → drive(linear_x=0.15, angular_z=0.5, duration=6)
- "stop/halt" → stop()

Keep replies short and conversational."""


# ---------------------------------------------------------------------------
# Agent — Anthropic backend
# ---------------------------------------------------------------------------

async def run_agent_anthropic(user_message: str, ws_client: WebSocket) -> str:
    import anthropic as _anthropic
    messages = [{"role": "user", "content": user_message}]

    while True:
        response = llm_client.messages.create(
            model      = LLM_MODEL,
            max_tokens = 1024,
            system     = SYSTEM_PROMPT,
            tools      = TOOLS,
            messages   = messages,
        )

        text_parts, tool_calls = [], []
        for block in response.content:
            if block.type == "text":       text_parts.append(block.text)
            elif block.type == "tool_use": tool_calls.append(block)

        if tool_calls:
            for call in tool_calls:
                await ws_client.send_json({"type": "status", "text": f"⚙ {call.name}({json.dumps(call.input)})"})
            tool_results = []
            for call in tool_calls:
                result = await execute_tool(call.name, call.input)
                await ws_client.send_json({"type": "status", "text": f"✓ {result}"})
                tool_results.append({"type": "tool_result", "tool_use_id": call.id, "content": result})
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user",      "content": tool_results})
            if response.stop_reason == "tool_use":
                continue

        return " ".join(text_parts).strip() or "Done."


# ---------------------------------------------------------------------------
# Agent — vLLM / OpenAI backend
# ---------------------------------------------------------------------------

KNOWN_TOOLS = {t["name"] for t in TOOLS}


def _extract_text_tool_calls(text: str) -> list[dict] | None:
    """
    Fallback: parse tool calls from plain text when vLLM doesn't convert them.
    Handles two formats the model commonly emits:
      {"name": "drive", "parameters": {"linear_x": 0.2, ...}}
      {"name": "drive", "arguments": {"linear_x": 0.2, ...}}
    Returns list of {"name": str, "args": dict} or None if nothing found.
    """
    import re
    calls = []
    # Find all top-level JSON objects in the text
    for match in re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)?\}', text, re.DOTALL):
        try:
            obj = json.loads(match.group())
        except json.JSONDecodeError:
            continue
        name = obj.get("name") or obj.get("function")
        if name not in KNOWN_TOOLS:
            continue
        args = obj.get("parameters") or obj.get("arguments") or obj.get("args") or {}
        # Coerce string numbers to float
        coerced = {}
        for k, v in args.items():
            try:
                coerced[k] = float(v) if isinstance(v, str) else v
            except (ValueError, TypeError):
                coerced[k] = v
        calls.append({"name": name, "args": coerced})
    return calls if calls else None


async def run_agent_openai(user_message: str, ws_client: WebSocket) -> str:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": user_message},
    ]

    while True:
        response = await asyncio.to_thread(
            llm_client.chat.completions.create,
            model       = LLM_MODEL,
            messages    = messages,
            tools       = TOOLS_OPENAI,
            tool_choice = "auto",
            max_tokens  = 1024,
        )

        choice     = response.choices[0]
        msg        = choice.message
        tool_calls = msg.tool_calls or []
        text       = msg.content or ""

        print(f"DEBUG finish={choice.finish_reason} tool_calls={len(tool_calls)} text={repr(text[:120])}")

        # --- Path 1: structured tool calls (parser worked) ---
        if tool_calls:
            messages.append({"role": "assistant", "content": msg.content, "tool_calls": [
                {"id": c.id, "type": "function", "function": {
                    "name": c.function.name, "arguments": c.function.arguments}}
                for c in tool_calls
            ]})
            for call in tool_calls:
                fn    = call.function
                args  = json.loads(fn.arguments) if fn.arguments else {}
                await ws_client.send_json({"type": "status", "text": f"⚙ {fn.name}({fn.arguments})"})
                result = await execute_tool(fn.name, args)
                await ws_client.send_json({"type": "status", "text": f"✓ {result}"})
                messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
            if choice.finish_reason == "tool_calls":
                continue
            return text.strip() or "Done."

        # --- Path 2: model emitted JSON tool call as plain text (parser failed) ---
        text_calls = _extract_text_tool_calls(text)
        if text_calls:
            results = []
            for call in text_calls:
                await ws_client.send_json({"type": "status", "text": f"⚙ {call['name']}({json.dumps(call['args'])})"})
                result = await execute_tool(call["name"], call["args"])
                await ws_client.send_json({"type": "status", "text": f"✓ {result}"})
                results.append(result)
            # Ask model for a natural language confirmation
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": f"Tool results: {'; '.join(results)}. Confirm briefly."})
            followup = await asyncio.to_thread(
                llm_client.chat.completions.create,
                model      = LLM_MODEL,
                messages   = messages,
                max_tokens = 128,
            )
            return followup.choices[0].message.content.strip() or results[0]

        # --- Path 3: plain text reply (no tool call needed) ---
        return text.strip() or "Done."


async def run_agent(user_message: str, ws_client: WebSocket) -> str:
    if USE_LOCAL_LLM:
        return await run_agent_openai(user_message, ws_client)
    else:
        return await run_agent_anthropic(user_message, ws_client)


# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------

app = FastAPI(title="RosBot")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/status")
async def status():
    connected = ros.connected or await ros.connect()
    return {
        "rosbridge":     connected,
        "rosbridge_url": ROSBRIDGE_URL,
        "twist_stamped": TWIST_STAMPED,
        "voice":         whisper_model is not None,
        "llm_backend":   f"vLLM ({LLM_BASE_URL})" if USE_LOCAL_LLM else "Anthropic",
        "llm_model":     LLM_MODEL,
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    backend = f"vLLM @ {LLM_BASE_URL}" if USE_LOCAL_LLM else "Anthropic"
    await websocket.send_json({
        "type": "status",
        "text": f"RosBot ready | {backend} | {ROSBRIDGE_URL} | Voice: {'on' if whisper_model else 'off'}",
    })

    if not ros.connected:
        ok = await ros.connect()
        if ok:
            await websocket.send_json({"type": "status", "text": "✓ Connected to rosbridge"})
        else:
            await websocket.send_json({"type": "status", "text": "⚠ Cannot reach rosbridge — check ROSBRIDGE_URL"})

    try:
        while True:
            data     = await websocket.receive_json()
            msg_type = data.get("type", "text")

            if msg_type == "audio":
                if whisper_model is None:
                    await websocket.send_json({"type": "error", "text": "Voice not available — install faster-whisper"})
                    continue
                audio_bytes = base64.b64decode(data.get("audio", ""))
                mime        = data.get("mime", "audio/webm")
                await websocket.send_json({"type": "status", "text": "🎙 Transcribing..."})
                text = await asyncio.to_thread(transcribe_audio, audio_bytes, mime)
                if not text:
                    await websocket.send_json({"type": "error", "text": "Could not transcribe audio."})
                    continue
                await websocket.send_json({"type": "transcription", "text": text})
                user_text = text

            elif msg_type == "text":
                user_text = data.get("text", "").strip()
                if not user_text:
                    continue
            else:
                continue

            try:
                reply = await run_agent(user_text, websocket)
                await websocket.send_json({"type": "reply", "text": reply})
            except Exception as e:
                await websocket.send_json({"type": "error", "text": f"Agent error: {e}"})

    except WebSocketDisconnect:
        pass


if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
