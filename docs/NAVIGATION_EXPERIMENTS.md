# Navigation and vision experiments

Branch: `codex/navigation-vlm-experiments`. Navigation and vision are now connected to the AutoCtrl ROS UI. The standalone
experiment commands below remain available for reproducing the original controller tests.

## Coordinate navigation in Isaac Sim

Start Isaac Sim and press Play. The experiment consumes `/sim/odom` and publishes
only `/sim/ackermann_cmd` on ROS domain 2. Stop other driving programs first so
there is a single command owner. The default coordinate frame starts at the car's
position and heading when each task begins: +x forward, +y left, metres.

```bash
scripts/test-navigation waypoints --points '[[0.7,0],[1.4,0.3]]' --output results/navigation-vlm/waypoints.json
scripts/test-navigation figure8 --radius 0.8 --output results/navigation-vlm/figure8.json
```

`--frame odom` uses fixed odometry coordinates. For the generated figure eight,
that means its crossing is at the odometry origin; prefer the default relative
frame. `--speed` defaults to 0.3 m/s (maximum 0.4); `--timeout` defaults to 300 wall
clock seconds. Ctrl+C cancels and sends repeated zero-speed commands.

This implementation uses feedback-based ordered target pursuit, with a 0.24 m
steering conversion length matching the installed Isaac converter. Sparse
waypoints are reached within 0.10 m in order, without stopping at each intermediate
point. The eight is two tangent circles, each sampled at 120 points. Dense interior
points use 0.22 m lookahead; the final point uses 0.10 m tolerance. Ordered progress
prevents the shared crossing from skipping a loop. Pose receipt time is used for
freshness because this simulator currently emits zero odometry timestamps.

A stale odometry stream (1 s), changed coordinate frame, deadline, or Ctrl+C aborts
the task and publishes zero speed. These are software checks, not an independent
watchdog: forcibly killing the process can leave the simulator holding its last
command. No map, obstacle avoidance, localization recovery, reversing, or final
heading constraint is implemented. Use a clear simulated area with gentle turns;
unreachable goals can circle until timeout. This is not a Nav2 deployment or a
real-vehicle acceptance test.

## Local VLM snapshot experiment

The installed `qwen3.6:35b` advertises vision support. With an RGB snapshot saved
locally and Ollama running:

```bash
scripts/capture-sim-camera results/navigation-vlm/camera-before.jpg
scripts/test-vision results/navigation-vlm/camera-before.jpg --output results/navigation-vlm/vision.json
```

This command sends the image only to localhost and produces text and a JSON
artifact. It has no ROS publisher or motion tools. Camera `/sim/rgb` provides
1280×720 RGB; `/sim/depth` is also present but not consumed here. A useful next
step is grounding a selected object using calibrated depth and transforming it
to the navigation frame. The snapshot description alone cannot determine metric
goals or certify obstacle clearance.

## Acceptance evidence

Run `uv run pytest -q` for the existing suite plus kinematic navigation tests.
The simulation JSON records every pose, command, ordered target index, final
error, and cancellation reason. The report and plotted trajectories in
`results/navigation-vlm/` capture this branch's actual simulator runs. Results are
ignored by Git; the summary below records the measured outcome for reviewers.

Measured in Isaac Sim on 2026-09-11:

| Task | Outcome | Wall time | Final position error |
| --- | --- | --- | --- |
| Relative waypoints `(0.7, 0)`, `(1.4, 0.3)` | 2/2 reached in order | 17.3 s | 8.3 cm |
| Figure eight, radius 0.8 m | 240/240 path samples reached, both loops | 137.5 s | 8.4 cm |
| Local VLM snapshot | Identified car, cube, cone, grid floor | 9.0 s | Not a metric localization test |

These are single-run measurements on the current scene, not a reliability rate.
The final vehicle heading is unconstrained. The VLM called the yellow part a rear
wing; the snapshot supports coarse object recognition but not detailed component
accuracy. Object-goal navigation (for example, driving to a visually identified cube) is not connected yet.

Final checks: **185 tests passed**. Simulator fault injection stopped delivering
odometry to the controller after 5 s; it aborted on stale feedback. A separate
SIGINT run also aborted cleanly. An independent ROS subscriber observed 10
zero-speed commands after each cancellation; displacement over the final 0.5 s
was 0.0096 m in each run. Geometric path RMS error was 1.8 cm for the waypoint run
and 3.1 cm for the eight (nearest reference segment, separate from endpoint error).


## AutoCtrl UI — primary user entry point

Start Isaac Sim, press Play, stop other driving programs, then open the AutoCtrl UI:

```bash
scripts/start-exhibition
```

This is the regular AutoCtrl interface, including its default real + simulation
configuration. Simulation navigation uses `/sim/odom` and sends motion only to
`/sim/cmd_vel`; missing real odometry does not block it. It never sends nonzero
navigation commands to the physical-car output. UI labels these tasks “Isaac Sim
導航”. Ordinary primitive commands keep their configured control targets.

Navigation executes inside AutoCtrl's control timer. `scripts/start-sim-ui` remains
an optional simulation-only preset, not a requirement. The regular launcher already
sets up the simulation steering converter. When Isaac Sim has no fresh position,
navigation reports that missing connection rather than requiring a different UI.

Type directly in the UI:

- `先到（0.7, 0），再到（1.4, 0.3）` — ordered coordinates, relative to this task's start.
- `走八字，半徑 0.8 公尺` or `/figure8` — both loops and then stop.
- `看看前面` or `/look` — fresh camera frame, described by the configured local model.
- `停止` — cancels active navigation, queued motion and in-flight command parsing.
- `/exit` or Ctrl+C — stops and exits AutoCtrl.

UI displays task acceptance, progress every five seconds, completion error, and
failure reason. Vision runs in a background thread and returns its description in
the same UI; the input prompt stays available while waiting. It has no motion tools.
Missing/stale odometry rejects or aborts navigation; a missing/stale camera rejects
vision. A 300-second deadline stops navigation. Ordinary timed/distance commands
preempt navigation. Navigation still has no obstacle avoidance or final heading
constraint. Parser-only `scripts/autoctrl` cannot execute these ROS functions and
explains that the connected UI is required.

UI acceptance on 2026-09-11 used a real pseudo-terminal running `start-sim-ui`:

| Typed into AutoCtrl | Observed in the UI |
| --- | --- |
| `先到（0.7, 0），再到（1.4, 0.3）` | Completed in 17.95 s; reported endpoint error 9.8 cm |
| `走八字，半徑 0.8 公尺` | Full eight completed in 133.45 s; reported endpoint error 9.9 cm |
| `看看前面` | Prompt returned immediately; scene description subsequently appeared in the same UI |
| `走八字` then `停止` while waiting for vision | Navigation cancelled and stop confirmation displayed |
| `/exit` | Safe exit; converter process cleaned up |

These errors are measured when AutoCtrl declares arrival (within the 10 cm
threshold), unlike the earlier standalone script's post-stop measurements.
Local UI transcript and assertions: `results/navigation-ui/terminal.log` and
`results/navigation-ui/acceptance.json`. Final suite: 196 passed, including an
isolated ROS subprocess whose eight checks cover cancellation of an in-flight
parse, queued navigation, stale feedback and completion status.


### Unified-entry correction

The initial UI integration incorrectly required simulation-only launch parameters,
so the normal real + simulation UI advertised navigation and then rejected it.
Regression tests now reproduce the normal mirrored configuration with no real
odometry: navigation must start from fresh simulation odometry and send nonzero
commands only through the simulation publisher. Another test verifies fresh real
odometry cannot substitute for missing simulation feedback. Replacing navigation
with a rejected motion command still sends stop, preventing a latched velocity.

Normal-entry verification (2026-09-11): launched `start-exhibition --skip-robot
--skip-bridges` with its normal `/small/cmd_vel` + `/sim/cmd_vel` configuration.
Typed the two-waypoint and figure-eight requests into the UI: both completed,
in 18.22 s and 134.25 s respectively. The full-eight transcript is retained in
`results/navigation-normal-ui/`. The initial automation sent stop before the
input prompt was ready; its stop verdict is not counted. A subsequent UI run
waited for the prompt, verified vision reply and navigation cancellation, and
independently observed zero nonzero commands on `/small/cmd_vel`; see
`results/navigation-normal-ui-stop/acceptance.json` and `real-output-check.json`.
The manual UI harness now waits for the input prompt before testing stop.
Final regression suite: 196 passed, including 11 isolated ROS checks.
