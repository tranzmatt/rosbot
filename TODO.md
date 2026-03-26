# rosbot TODO

## Bugs

- [x] **Voice input fixed** — `faster-whisper` fails to install in `Dockerfile.rosbot`.
      `docker exec rosbot-rosbot-1 pip list | grep whisper` returns nothing.
      Fix the pip install or switch to `openai-whisper` as fallback.

- [x] **Robot spawns facing -x** — TurtleBot4 spawns with its forward axis pointing
      in the -x world direction. Not a functional bug (relative navigation works correctly)
      but confusing when checking `sim_ground_truth_pose`. Add a `yaw` spawn arg to
      `headless_sim.launch.py` → `turtlebot4_spawn.launch.py` to spawn facing +x.

- [x] **`get_position` tool unverified** — `/odom` had 0 publishers for most of the
      debugging session. Confirm it has a publisher now that diffdrive is active, and
      test that "where am I?" returns correct coordinates.

- [x] **Low RTF (real-time factor)** — `GALLIUM_DRIVER=softpipe` was baked into the
      image via Dockerfile.sim ENV, forcing Mesa software rendering even when NVIDIA GPU
      was available. Removed all three software-rendering ENV defaults from the Dockerfile;
      the no-GPU fallback path in sim_entrypoint.sh sets them at runtime when needed.

- [x] **diffdrive_controller spawner race** — TB4's own spawner (spawner-46) still
      fails with "already loaded" on every boot. Our spawner-70 recovers it, but the
      error is noisy. Fixed by expanding `turtlebot4_spawn.launch.py` manually in
      `headless_sim.launch.py`, excluding `create3_nodes.launch.py` (the source of
      spawner-46). Our `diffdrive_spawner` at t=30s is now the sole spawner.

- [x] **Clock bridge topic hardcoded** — `headless_sim.launch.py` reads `TB4_WORLD`
      env var to construct the clock topic `/world/depot/clock`. If world changes,
      the bridge topic must match. Make this fully dynamic from the `world` launch arg.

## Improvements

- [ ] **Distance accuracy** — `drive()` uses fixed velocity × duration to estimate
      distance. At low RTF this is way off. Use `/odom` feedback to drive a measured
      distance instead of timed velocity.

- [x] **`get_position` should use sim_ground_truth_pose in sim mode** — `/odom` drifts;
      `/sim_ground_truth_pose` is exact. Auto-detect sim vs real and pick the right topic.

- [ ] **Spawn orientation** — Add `x`, `y`, `yaw` launch args to `headless_sim.launch.py`
      so spawn pose is configurable without editing source.

- [x] **`.env.example` GPU section** — Add commented-out examples for `SIM_GPU` and
      `VLLM_GPUS` with instructions for finding UUIDs via `nvidia-smi -L`.

- [ ] **`rosbot.sh gui` command** — Currently just prints the gz sim -g connect command.
      Should also check if gz is installed locally and warn if not.

- [ ] **Health check in docker-compose** — Add a healthcheck to the sim service so
      rosbot container waits for rosbridge to be ready instead of relying on timing.

- [x] **Ogre1 rename is permanent** — `sim_entrypoint.sh` renames `libgz-rendering-ogre.so`
      to `.bak` inside the container. This persists across restarts (same container).
      Fine for now but if the image is rebuilt the rename is lost — document this or
      move the rename into the Dockerfile build step instead.

## Real Robot

- [ ] **Test with real TurtleBot4** — Change `ROSBRIDGE_URL=ws://turtlebot4.local:9090`
      and `TWIST_STAMPED=true` in `.env`, run `./rosbot.sh real`. Verify drive/stop/
      get_position/get_battery all work on hardware.

- [ ] **Real robot: `/cmd_vel` type** — Confirm whether the real TB4 expects `Twist`
      or `TwistStamped`. May differ between firmware versions.

## Nice to Have

- [ ] **Nav2 integration** — Add a `navigate_to(x, y)` tool that sends a goal to
      Nav2 action server instead of raw velocity commands.

- [ ] **Map tool** — `get_map()` tool that returns a base64 occupancy grid image
      from `/map` topic for display in the web UI.

- [ ] **Multi-robot** — Namespace support is already in the launch file. Wire it
      through docker-compose so multiple robots can be controlled from one server.
