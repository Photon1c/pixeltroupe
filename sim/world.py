"""Pixel-aware TinyWorld implementation."""

from __future__ import annotations

import json
import random
import re
import time
from collections import deque
from typing import Any

from config import GRID_HEIGHT, GRID_WIDTH, MAX_CHAT_LINES
from sim.lightning_hooks import ActionOutcome, LightningHooks

try:
    from tinytroupe.agent import TinyPerson  # type: ignore
    from tinytroupe.environment import TinyWorld  # type: ignore
except Exception:  # pragma: no cover - TinyTroupe is optional during bootstrapping
    class TinyWorld:  # type: ignore
        def __init__(self, name: str, agents: list[Any]) -> None:
            self.name = name
            self.agents = agents

    class TinyPerson:  # type: ignore
        pass


_DIR_TO_DELTA: dict[str, tuple[int, int]] = {
    "north": (0, -1),
    "south": (0, 1),
    "east": (1, 0),
    "west": (-1, 0),
}

_DIRECTION_KEYWORDS: dict[str, str] = {
    "north": "north",
    "south": "south",
    "east": "east",
    "west": "west",
    "up": "north",
    "down": "south",
    "left": "west",
    "right": "east",
}


class PixelTinyWorld(TinyWorld):
    """TinyWorld with explicit positions and JSON action parsing."""

    def __init__(
        self,
        name: str,
        agents: list[TinyPerson],
        grid_w: int = GRID_WIDTH,
        grid_h: int = GRID_HEIGHT,
        hooks: LightningHooks | None = None,
    ) -> None:
        super().__init__(name, agents)
        self.grid_w = grid_w
        self.grid_h = grid_h
        self.hooks = hooks or LightningHooks()
        self.tick_count = 0
        self.chat_log: deque[str] = deque(maxlen=MAX_CHAT_LINES)

        for agent in self.agents:
            self._init_agent_state(agent)

    def _init_agent_state(self, agent: TinyPerson) -> None:
        if not hasattr(agent, "name"):
            setattr(agent, "name", f"Agent{random.randint(100, 999)}")
        if not hasattr(agent, "mood"):
            setattr(agent, "mood", "neutral")
        if not hasattr(agent, "last_said"):
            setattr(agent, "last_said", "")
        if not hasattr(agent, "total_reward"):
            setattr(agent, "total_reward", 0.0)
        if not hasattr(agent, "last_action"):
            setattr(agent, "last_action", "idle")
        if not hasattr(agent, "user_bonus"):
            setattr(agent, "user_bonus", 0.0)
        if not hasattr(agent, "goal"):
            persona_goal = None
            get_persona_value = getattr(agent, "get", None)
            if callable(get_persona_value):
                try:
                    persona_goal = get_persona_value("goal")
                except Exception:
                    persona_goal = None

            if persona_goal is None:
                persona = getattr(agent, "persona", {})
                if isinstance(persona, dict):
                    persona_goal = persona.get("goal")

            if persona_goal is None:
                private_persona = getattr(agent, "_persona", {})
                if isinstance(private_persona, dict):
                    persona_goal = private_persona.get("goal")

            setattr(agent, "goal", persona_goal or "chill")

        occupied = {
            (int(a.x), int(a.y))
            for a in self.agents
            if a is not agent and hasattr(a, "x") and hasattr(a, "y")
        }
        free_tiles = [
            (x, y)
            for x in range(1, self.grid_w - 1)
            for y in range(1, self.grid_h - 1)
            if (x, y) not in occupied
        ]

        has_position = hasattr(agent, "x") and hasattr(agent, "y")
        if has_position:
            current_x = int(getattr(agent, "x", -999))
            current_y = int(getattr(agent, "y", -999))
            in_bounds = 1 <= current_x < self.grid_w - 1 and 1 <= current_y < self.grid_h - 1
            colliding = (current_x, current_y) in occupied
        else:
            in_bounds = False
            colliding = True

        if (not has_position) or (not in_bounds) or colliding:
            if free_tiles:
                x, y = random.choice(free_tiles)
            else:
                x, y = 1, 1
            setattr(agent, "x", x)
            setattr(agent, "y", y)

    def parse_action(self, response_str: Any) -> dict[str, Any]:
        """Safely parse agent response into structured action dict."""
        action_raw = self._extract_action_payload(response_str)
        if "type" in action_raw and "action" not in action_raw:
            action_raw = self._translate_tinytroupe_action(action_raw)

        action = {str(key).lower(): value for key, value in action_raw.items()}
        if "dir" in action and "direction" not in action:
            action["direction"] = action.pop("dir")
        if "text" in action and "content" not in action:
            action["content"] = action.pop("text")
        if "message" in action and "content" not in action:
            action["content"] = action.pop("message")

        act_type = str(action.get("action", "idle")).lower().strip()
        if act_type in ("moveandsay", "move-and-say", "move_and_talk"):
            act_type = "move_and_say"

        direction = self._normalize_direction(action.get("direction"))
        content_raw = action.get("content")
        content = str(content_raw).strip() if content_raw is not None else ""
        if direction is None and act_type in ("move", "move_and_say"):
            direction = self._direction_from_text(content)

        return {
            "action": act_type or "idle",
            "direction": direction,
            "content": content if content else None,
        }

    def _extract_action_payload(self, response_value: Any) -> dict[str, Any]:
        if isinstance(response_value, dict):
            nested_action = response_value.get("action")
            if isinstance(nested_action, dict):
                return nested_action
            return response_value

        if isinstance(response_value, list):
            for item in response_value:
                if not isinstance(item, dict):
                    continue
                nested_action = item.get("action")
                if isinstance(nested_action, dict):
                    return nested_action
                if "type" in item or "action" in item:
                    return item
            return {}

        text = str(response_value or "").strip()
        if not text:
            return {}

        try:
            parsed = json.loads(text)
            return self._extract_action_payload(parsed)
        except (json.JSONDecodeError, TypeError):
            if text and not text.startswith("{"):
                return {"action": "say", "content": text}
            return {}

    def _translate_tinytroupe_action(self, action_raw: dict[str, Any]) -> dict[str, Any]:
        """
        Map TinyTroupe-native action format (`type/content/target`) to PixelTroupe actions.
        """
        action_type = str(action_raw.get("type", "")).strip().upper()
        content = str(action_raw.get("content", "") or "").strip()
        target = str(action_raw.get("target", "") or "").strip()

        if content.startswith("{"):
            try:
                nested = json.loads(content)
                if isinstance(nested, dict):
                    return nested
            except json.JSONDecodeError:
                pass

        if action_type in ("MOVE", "WALK", "GO"):
            direction = self._normalize_direction(action_raw.get("direction"))
            if direction is None:
                direction = self._direction_from_text(content)
            return {"action": "move", "direction": direction, "content": None}

        if action_type in ("TALK", "SAY"):
            return {"action": "say", "content": content or None}

        if action_type == "REACH_OUT":
            if content:
                speech = content
            elif target:
                speech = f"Trying to reach {target}."
            else:
                speech = "Trying to reach someone nearby."
            return {"action": "say", "content": speech}

        if action_type in ("THINK", "REFLECT", "PLAN", "DONE"):
            return {"action": "idle"}

        if content:
            return {"action": "say", "content": content}

        return {"action": "idle"}

    def _normalize_direction(self, direction: Any) -> str | None:
        normalized = str(direction or "").lower().strip()
        aliases = {
            "n": "north",
            "s": "south",
            "e": "east",
            "w": "west",
        }
        normalized = aliases.get(normalized, normalized)
        return normalized if normalized in _DIR_TO_DELTA else None

    def _direction_from_text(self, text: str) -> str | None:
        lowered = (text or "").lower()
        for token, direction in _DIRECTION_KEYWORDS.items():
            if re.search(rf"\b{token}\b", lowered):
                return direction
        return None

    def _mood_from_text(self, text: str) -> str:
        lowered = text.lower()
        if any(token in lowered for token in ("great", "happy", "fun", "party", "!")):
            return "happy"
        if any(token in lowered for token in ("no", "bad", "angry", "tired")):
            return "grumpy"
        return "neutral"

    def _is_occupied(self, x: int, y: int, ignore_agent: TinyPerson | None = None) -> bool:
        for other in self.agents:
            if ignore_agent is not None and other is ignore_agent:
                continue
            if int(getattr(other, "x", -999)) == x and int(getattr(other, "y", -999)) == y:
                return True
        return False

    def get_nearby(self, agent: TinyPerson, max_distance: int = 3) -> list[TinyPerson]:
        nearby = []
        for other in self.agents:
            if other is agent:
                continue
            distance = abs(int(other.x) - int(agent.x)) + abs(int(other.y) - int(agent.y))
            if distance <= max_distance:
                nearby.append(other)
        return nearby

    def apply_action(self, agent: TinyPerson, parsed_action: dict[str, Any]) -> ActionOutcome:
        """Apply a parsed action to the agent and world state."""
        act = str(parsed_action.get("action", "idle")).lower()
        outcome = ActionOutcome()

        if act in ("move", "move_and_say"):
            direction = parsed_action.get("direction")
            if direction is None:
                outcome.invalid_action = True
            else:
                dx, dy = _DIR_TO_DELTA[direction]
                new_x = int(agent.x) + dx
                new_y = int(agent.y) + dy

                if not (1 <= new_x < self.grid_w - 1 and 1 <= new_y < self.grid_h - 1):
                    outcome.hit_wall = True
                elif self._is_occupied(new_x, new_y, ignore_agent=agent):
                    outcome.blocked_by_agent = True
                else:
                    agent.x = new_x
                    agent.y = new_y
                    outcome.moved = True
        elif act not in ("say", "idle"):
            outcome.invalid_action = True

        content = parsed_action.get("content")
        if act in ("say", "move_and_say") and content:
            clean_text = str(content).strip()[:160]
            agent.last_said = clean_text
            agent.mood = self._mood_from_text(clean_text)
            self.chat_log.append(f"{agent.name}: {clean_text}")
            outcome.said = True

        outcome.user_bonus = float(getattr(agent, "user_bonus", 0.0))
        agent.user_bonus = 0.0
        agent.last_action = act
        return outcome

    def _build_observation(self, agent: TinyPerson) -> str:
        nearby_names = [str(p.name) for p in self.get_nearby(agent, max_distance=4)]
        recent_chat = " | ".join(list(self.chat_log)[-3:]) if self.chat_log else "No recent chat."
        hour = time.localtime().tm_hour % 24
        time_of_day = "night" if (hour >= 20 or hour <= 5) else "day"

        return (
            f"You are at position ({agent.x}, {agent.y}). "
            f"Nearby people: {', '.join(nearby_names) if nearby_names else 'nobody'}. "
            f"Time of day: {time_of_day}. "
            f"Recent chat: {recent_chat}. "
            f"Your current goal/mood: {getattr(agent, 'goal', 'relax')} / {getattr(agent, 'mood', 'neutral')}. "
            "Respond ONLY with valid JSON action using one of: "
            '{"action":"move","direction":"north|south|east|west"}, '
            '{"action":"say","content":"..."}, '
            '{"action":"move_and_say","direction":"east","content":"..."}, '
            '{"action":"idle"}.'
        )

    def _invoke_agent(self, agent: TinyPerson, observation: str) -> Any:
        for method_name in ("listen_and_act", "act"):
            method = getattr(agent, method_name, None)
            if not callable(method):
                continue

            if method_name == "listen_and_act":
                attempts = [
                    ((observation,), {"return_actions": True}),
                    ((observation,), {}),
                    ((), {"return_actions": True}),
                    ((), {}),
                ]
            else:
                attempts = [
                    ((), {"return_actions": True}),
                    ((observation,), {"return_actions": True}),
                    ((), {}),
                    ((observation,), {}),
                ]

            for args, kwargs in attempts:
                try:
                    response = method(*args, **kwargs)
                except TypeError:
                    continue
                except Exception:
                    continue

                return response

        return {"action": "idle"}

    def tick(self) -> dict[str, Any]:
        for agent in list(self.agents):
            observation = self._build_observation(agent)
            self.hooks.emit_state(
                {
                    "agent": agent.name,
                    "observation": observation,
                    "position": (int(agent.x), int(agent.y)),
                    "tick": self.tick_count,
                }
            )

            response = self._invoke_agent(agent, observation)
            parsed = self.parse_action(response)
            self.hooks.emit_action(parsed)

            outcome = self.apply_action(agent, parsed)
            reward = self.hooks.compute_reward(parsed, outcome)
            agent.total_reward = float(getattr(agent, "total_reward", 0.0)) + reward
            self.hooks.emit_reward(reward)

        self.tick_count += 1
        return self.get_state_json()

    def add_agent(self, agent: TinyPerson) -> None:
        self.agents.append(agent)
        self._init_agent_state(agent)
        self.chat_log.append(f"System: {agent.name} spawned into the village.")

    def send_user_message(self, agent_name: str, message: str) -> bool:
        clean_message = str(message or "").strip()
        if not clean_message:
            return False

        target = next((a for a in self.agents if str(a.name) == agent_name), None)
        if target is None:
            return False

        self.chat_log.append(f"User -> {target.name}: {clean_message[:160]}")
        target.user_bonus = float(getattr(target, "user_bonus", 0.0)) + 0.5
        target.mood = "happy"

        receive_message = getattr(target, "receive_user_message", None)
        if callable(receive_message):
            try:
                receive_message(clean_message)
            except Exception:
                target.last_said = f"(to user) {clean_message[:80]}"
        else:
            target.last_said = f"(to user) {clean_message[:80]}"
        return True

    def get_state_json(self) -> dict[str, Any]:
        return {
            "world_name": self.name,
            "grid_w": self.grid_w,
            "grid_h": self.grid_h,
            "tick": self.tick_count,
            "timestamp": time.time(),
            "agents": [
                {
                    "name": str(agent.name),
                    "x": int(getattr(agent, "x", 0)),
                    "y": int(getattr(agent, "y", 0)),
                    "mood": str(getattr(agent, "mood", "neutral")),
                    "goal": str(getattr(agent, "goal", "chill")),
                    "last_action": str(getattr(agent, "last_action", "idle")),
                    "total_reward": round(float(getattr(agent, "total_reward", 0.0)), 3),
                    "last_said": str(getattr(agent, "last_said", ""))[:80],
                }
                for agent in self.agents
            ],
            "chat_lines": list(self.chat_log)[-5:],
        }

