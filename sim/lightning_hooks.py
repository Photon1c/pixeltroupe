"""AgentLightning integration helpers with graceful fallback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    import agentlightning as _agl
except Exception:  # pragma: no cover - dependency is optional
    _agl = None


@dataclass
class ActionOutcome:
    """Result of applying an action to the world state."""

    moved: bool = False
    said: bool = False
    hit_wall: bool = False
    blocked_by_agent: bool = False
    invalid_action: bool = False
    user_bonus: float = 0.0


class LightningHooks:
    """Small wrapper around AgentLightning emit APIs."""

    def __init__(self) -> None:
        self.available = _agl is not None

    def _safe_emit(self, method_name: str, payload: Any) -> None:
        if not self.available:
            return
        emitter = getattr(_agl, method_name, None)
        if callable(emitter):
            try:
                emitter(payload)
            except Exception:
                # Emission should never break the sim loop.
                return

    def emit_state(self, payload: dict[str, Any]) -> None:
        self._safe_emit("emit_state", payload)

    def emit_action(self, payload: dict[str, Any]) -> None:
        self._safe_emit("emit_action", payload)

    def emit_reward(self, reward: float) -> None:
        self._safe_emit("emit_reward", reward)

    def compute_reward(
        self,
        parsed_action: dict[str, Any],
        outcome: ActionOutcome,
    ) -> float:
        """Simple first-pass shaping for visible behavior."""
        reward = 0.0
        action_name = parsed_action.get("action", "idle")

        if action_name == "move" and outcome.moved:
            reward += 0.05
        if action_name == "move_and_say" and outcome.moved:
            reward += 0.08
        if outcome.hit_wall or outcome.blocked_by_agent:
            reward -= 0.2
        if outcome.invalid_action:
            reward -= 0.1

        content = parsed_action.get("content")
        if content:
            reward += 0.2 + min(len(content), 60) * 0.01

        reward += outcome.user_bonus
        return reward

    def train_now(self) -> bool:
        """
        Best-effort train trigger.

        Returns True if a known train method was found and invoked.
        """
        if not self.available:
            return False

        for method_name in ("train", "optimize", "step"):
            fn = getattr(_agl, method_name, None)
            if not callable(fn):
                continue
            try:
                fn()
                return True
            except TypeError:
                continue
            except Exception:
                return False
        return False

