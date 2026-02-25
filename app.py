"""Flask + Socket.IO entrypoint for PixelTroupe Lightning."""

from __future__ import annotations

import threading
import time
from typing import Any

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO

from config import DEFAULT_AGENT_COUNT, TICK_INTERVAL_SECONDS
from sim.agents import build_default_agents, spawn_agent
from sim.world import PixelTinyWorld

app = Flask(__name__)
socketio = SocketIO(app, async_mode="threading")

world = PixelTinyWorld("PixelVillage Lightning", build_default_agents(DEFAULT_AGENT_COUNT))
world_lock = threading.Lock()
runtime_state = {"paused": False, "speed_multiplier": 1.0}

_sim_thread_guard = threading.Lock()
_sim_thread_started = False


def _state_payload() -> dict[str, Any]:
    with world_lock:
        payload = world.get_state_json()
    payload["paused"] = runtime_state["paused"]
    payload["speed_multiplier"] = runtime_state["speed_multiplier"]
    payload["agentlightning_enabled"] = world.hooks.available
    return payload


def _emit_state() -> None:
    socketio.emit("world_update", _state_payload())


def _sim_loop() -> None:
    while True:
        if not runtime_state["paused"]:
            with world_lock:
                world.tick()
            _emit_state()
        sleep_for = max(0.05, TICK_INTERVAL_SECONDS / runtime_state["speed_multiplier"])
        time.sleep(sleep_for)


def _ensure_sim_thread() -> None:
    global _sim_thread_started
    with _sim_thread_guard:
        if _sim_thread_started:
            return
        socketio.start_background_task(_sim_loop)
        _sim_thread_started = True


@app.route("/")
def index() -> str:
    _ensure_sim_thread()
    return render_template("index.html")


@app.route("/api/state")
def state() -> Any:
    _ensure_sim_thread()
    return jsonify(_state_payload())


@app.post("/api/control")
def control() -> Any:
    _ensure_sim_thread()
    payload = request.get_json(silent=True) or {}
    action = str(payload.get("action", "")).strip().lower()

    if action == "pause":
        runtime_state["paused"] = True
    elif action == "resume":
        runtime_state["paused"] = False
    elif action == "toggle_pause":
        runtime_state["paused"] = not runtime_state["paused"]
    elif action == "speed":
        try:
            requested = float(payload.get("value", 1.0))
        except (TypeError, ValueError):
            requested = 1.0
        runtime_state["speed_multiplier"] = max(0.25, min(requested, 8.0))
    elif action == "speed_x4":
        runtime_state["speed_multiplier"] = (
            4.0 if runtime_state["speed_multiplier"] < 3.9 else 1.0
        )
    elif action == "train_now":
        with world_lock:
            triggered = world.hooks.train_now()
            if triggered:
                world.chat_log.append("System: AgentLightning train step triggered.")
            else:
                world.chat_log.append(
                    "System: AgentLightning train requested (module unavailable/no-op)."
                )
    elif action == "spawn":
        with world_lock:
            world.add_agent(spawn_agent(world.agents))

    _emit_state()
    return jsonify({"ok": True, "state": _state_payload()})


@app.post("/api/agent/<agent_name>/message")
def message_agent(agent_name: str) -> Any:
    _ensure_sim_thread()
    payload = request.get_json(silent=True) or {}
    message = str(payload.get("message", ""))
    with world_lock:
        ok = world.send_user_message(agent_name, message)
    if ok:
        _emit_state()
    return jsonify({"ok": ok})


@socketio.on("connect")
def on_connect() -> None:
    _ensure_sim_thread()
    socketio.emit("world_update", _state_payload(), to=request.sid)


if __name__ == "__main__":
    _ensure_sim_thread()
    socketio.run(app, host="0.0.0.0", port=5000, allow_unsafe_werkzeug=True)

