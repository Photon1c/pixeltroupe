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
        self._legacy_state_emitter = (
            getattr(_agl, "emit_state", None) if self.available else None
        )
        self._legacy_action_emitter = (
            getattr(_agl, "emit_action", None) if self.available else None
        )

    def _has_active_tracer(self) -> bool:
        if not self.available:
            return False

        get_active_tracer = getattr(_agl, "get_active_tracer", None)
        if callable(get_active_tracer):
            try:
                return get_active_tracer() is not None
            except Exception:
                return False
        return False

    def _safe_call(self, fn: Any, *args: Any, **kwargs: Any) -> None:
        if not callable(fn):
            return
        try:
            fn(*args, **kwargs)
        except TypeError:
            if kwargs:
                try:
                    fn(*args)
                except Exception:
                    return
        except Exception:
            # Emission should never break the sim loop.
            return

    def emit_state(self, payload: dict[str, Any]) -> None:
        if not self.available:
            return

        if callable(self._legacy_state_emitter):
            self._safe_call(self._legacy_state_emitter, payload)
            return

        emit_object = getattr(_agl, "emit_object", None)
        self._safe_call(
            emit_object,
            payload,
            attributes={"pixeltroupe.event": "state"},
            propagate=self._has_active_tracer(),
        )

    def emit_action(self, payload: dict[str, Any]) -> None:
        if not self.available:
            return

        if callable(self._legacy_action_emitter):
            self._safe_call(self._legacy_action_emitter, payload)
            return

        emit_object = getattr(_agl, "emit_object", None)
        self._safe_call(
            emit_object,
            payload,
            attributes={"pixeltroupe.event": "action"},
            propagate=self._has_active_tracer(),
        )

    def emit_reward(self, reward: float) -> None:
        if not self.available:
            return
        emit_reward = getattr(_agl, "emit_reward", None)
        self._safe_call(
            emit_reward,
            reward,
            propagate=self._has_active_tracer(),
        )

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

        for method_name in ("train", "optimize", "step", "fit", "dev"):
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

