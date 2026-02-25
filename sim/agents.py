"""Agent builders for PixelTroupe Lightning."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from typing import Any

from config import DEFAULT_AGENT_COUNT

PERSONA_SEEDS: list[dict[str, str]] = [
    {"name": "Ivy", "goal": "Start a cozy evening market."},
    {"name": "Rook", "goal": "Tell one good joke to everyone nearby."},
    {"name": "Mira", "goal": "Collect gossip and make friends."},
    {"name": "Theo", "goal": "Host a late-night dance party."},
    {"name": "Nova", "goal": "Explore every corner of the village."},
    {"name": "Pax", "goal": "Keep the peace and reduce arguments."},
    {"name": "Jun", "goal": "Find somebody to share tea with."},
    {"name": "Ash", "goal": "Build a reputation for being helpful."},
]

_DIRECTIONS = ("north", "south", "east", "west")


@dataclass
class MockTinyPerson:
    """Simple fallback persona that emits JSON actions."""

    name: str
    goal: str
    persona: dict[str, Any] = field(default_factory=dict)
    mood: str = "neutral"
    last_said: str = ""
    x: int = 0
    y: int = 0
    total_reward: float = 0.0
    user_bonus: float = 0.0

    def __post_init__(self) -> None:
        if not self.persona:
            self.persona = {"goal": self.goal}

    def listen_and_act(self, observation: str) -> str:
        """
        Return a JSON action string.

        This keeps the local experience runnable without TinyTroupe.
        """
        observation_lower = observation.lower()
        nearby_someone = "nearby people: nobody" not in observation_lower
        should_talk = nearby_someone and random.random() < 0.45
        should_move = random.random() < 0.8

        if should_move and should_talk:
            return json.dumps(
                {
                    "action": "move_and_say",
                    "direction": random.choice(_DIRECTIONS),
                    "content": random.choice(
                        [
                            "Anyone up for a snack run?",
                            "Night shift squad, assemble!",
                            "I have a plan for my goal.",
                            "This village is alive tonight!",
                        ]
                    ),
                }
            )

        if should_move:
            return json.dumps(
                {"action": "move", "direction": random.choice(_DIRECTIONS)}
            )

        if should_talk:
            return json.dumps(
                {
                    "action": "say",
                    "content": random.choice(
                        [
                            "I am checking in with everyone.",
                            "I think we can do better together!",
                            "Who wants to team up?",
                            "Tonight feels lucky.",
                        ]
                    ),
                }
            )

        return json.dumps({"action": "idle"})

    def receive_user_message(self, message: str) -> None:
        self.last_said = f"(to user) {message[:80]}"


def _try_build_tinytroupe_agents(count: int) -> list[Any]:
    """Best-effort TinyTroupe construction with API-shape tolerance."""
    try:
        from tinytroupe import TinyPersonFactory  # type: ignore
    except Exception:
        return []

    try:
        factory = TinyPersonFactory()
    except Exception:
        return []

    created: list[Any] = []
    for i in range(count):
        seed = PERSONA_SEEDS[i % len(PERSONA_SEEDS)]
        built = None
        for method_name in ("generate_person", "create_person", "generate"):
            method = getattr(factory, method_name, None)
            if not callable(method):
                continue

            attempts = (
                {"name": seed["name"], "persona": seed},
                {"name": seed["name"]},
                {},
            )
            for kwargs in attempts:
                try:
                    built = method(**kwargs)
                    break
                except TypeError:
                    continue
                except Exception:
                    built = None
                    break
            if built is not None:
                break

        if built is None:
            continue

        if not getattr(built, "name", None):
            setattr(built, "name", seed["name"])
        if not getattr(built, "persona", None):
            setattr(built, "persona", {"goal": seed["goal"]})
        if not getattr(built, "goal", None):
            setattr(built, "goal", seed["goal"])

        created.append(built)

    return created


def _build_mock_agents(count: int, used_names: set[str] | None = None) -> list[MockTinyPerson]:
    used_names = used_names or set()
    created: list[MockTinyPerson] = []
    idx = 0
    while len(created) < count:
        seed = PERSONA_SEEDS[idx % len(PERSONA_SEEDS)]
        name = seed["name"]
        if name in used_names:
            name = f"{name}{idx + 1}"
        used_names.add(name)
        created.append(MockTinyPerson(name=name, goal=seed["goal"]))
        idx += 1
    return created


def build_default_agents(count: int = DEFAULT_AGENT_COUNT) -> list[Any]:
    """
    Build TinyTroupe agents when possible, otherwise return mock agents.
    """
    tiny_agents = _try_build_tinytroupe_agents(count)
    if len(tiny_agents) == count:
        return tiny_agents

    used = {str(getattr(agent, "name", "")) for agent in tiny_agents}
    fallback = _build_mock_agents(count - len(tiny_agents), used_names=used)
    return tiny_agents + fallback


def spawn_agent(existing_agents: list[Any]) -> Any:
    """Create a single new villager."""
    existing_names = {str(getattr(agent, "name", "")) for agent in existing_agents}
    return _build_mock_agents(1, used_names=existing_names)[0]

