"""Agent builders for PixelTroupe Lightning."""

from __future__ import annotations

import json
import os
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
    if not _tinytroupe_runtime_enabled():
        return []

    try:
        from tinytroupe.agent import TinyPerson  # type: ignore
    except Exception:
        return []

    use_factory = os.getenv("PIXELTROUPE_USE_FACTORY", "0") == "1"
    seeded_agents: list[Any] = []
    used_names: set[str] = set()
    for i in range(count):
        seed = PERSONA_SEEDS[i % len(PERSONA_SEEDS)]
        name = _dedupe_name(seed["name"], used_names)
        person = _build_seeded_tinytroupe_person(TinyPerson, name=name, goal=seed["goal"])
        if person is not None:
            seeded_agents.append(person)

    if len(seeded_agents) == count and not use_factory:
        return seeded_agents

    # Optional factory mode for richer generated personas.
    if not use_factory:
        return seeded_agents

    # In factory mode, we still keep the seeded agents as fallback.
    created: list[Any] = []

    try:
        from tinytroupe.factory import TinyPersonFactory  # type: ignore
    except Exception:
        return seeded_agents

    try:
        factory = TinyPersonFactory(context="A cozy pixel-art village with quirky nighttime residents.")
    except Exception:
        try:
            factory = TinyPersonFactory()
        except Exception:
            return seeded_agents

    generated: list[Any] = []
    generate_people = getattr(factory, "generate_people", None)
    if callable(generate_people):
        try:
            generated = list(
                generate_people(
                    number_of_people=max(count - len(created), 0),
                    agent_particularities=(
                        "Villager in a pixel-art town. "
                        "Be socially active and respond concisely."
                    ),
                    attempts=2,
                    parallelize=False,
                    verbose=False,
                )
            )
        except TypeError:
            try:
                generated = list(
                    generate_people(
                        number_of_people=max(count - len(created), 0),
                        agent_particularities="Villager in a pixel-art town.",
                    )
                )
            except Exception:
                generated = []
        except Exception:
            generated = []

    generate_person = getattr(factory, "generate_person", None)
    while len(generated) + len(created) < count and callable(generate_person):
        loop_idx = len(generated) + len(created)
        seed = PERSONA_SEEDS[loop_idx % len(PERSONA_SEEDS)]
        particularities = f"Name: {seed['name']}. Goal: {seed['goal']}"
        try:
            built = generate_person(agent_particularities=particularities, attempts=2)
        except TypeError:
            try:
                built = generate_person(agent_particularities=particularities)
            except Exception:
                built = None
        except Exception:
            built = None
        if built is not None:
            generated.append(built)

    for i, built in enumerate(generated):
        if len(created) >= count:
            break
        seed = PERSONA_SEEDS[i % len(PERSONA_SEEDS)]
        desired_name = _dedupe_name(str(getattr(built, "name", seed["name"])), used_names)
        if str(getattr(built, "name", "")) != desired_name:
            try:
                setattr(built, "name", desired_name)
            except Exception:
                pass
        _set_goal_metadata(built, seed["goal"])
        created.append(built)

    if len(created) >= count:
        return created[:count]

    # Top up with seeded local personas if factory under-produced.
    for seeded in seeded_agents:
        if len(created) >= count:
            break
        seeded_name = str(getattr(seeded, "name", "Villager"))
        unique_name = _dedupe_name(seeded_name, used_names)
        if unique_name != seeded_name:
            try:
                setattr(seeded, "name", unique_name)
            except Exception:
                pass
        created.append(seeded)

    return created[:count]


def _set_goal_metadata(agent: Any, goal: str) -> None:
    try:
        setattr(agent, "goal", goal)
    except Exception:
        pass

    define_persona = getattr(agent, "define", None)
    if callable(define_persona):
        try:
            define_persona("goal", goal, overwrite_scalars=False)
        except TypeError:
            try:
                define_persona("goal", goal)
            except Exception:
                pass
        except Exception:
            pass


def _build_seeded_tinytroupe_person(TinyPerson: Any, name: str, goal: str) -> Any | None:
    try:
        person = TinyPerson(name)
    except Exception:
        return None

    _set_goal_metadata(person, goal)
    define_persona = getattr(person, "define", None)
    if callable(define_persona):
        try:
            define_persona("occupation", "villager", overwrite_scalars=False)
            define_persona("personality_traits", ["curious", "social"], overwrite_scalars=False)
        except TypeError:
            try:
                define_persona("occupation", "villager")
                define_persona("personality_traits", ["curious", "social"])
            except Exception:
                pass
        except Exception:
            pass

    return person


def _tinytroupe_runtime_enabled() -> bool:
    if os.getenv("PIXELTROUPE_FORCE_TINYTROUPE", "0") == "1":
        return True
    return bool(os.getenv("OPENAI_API_KEY") or os.getenv("AZURE_OPENAI_KEY"))


def _dedupe_name(name: str, used_names: set[str]) -> str:
    if name not in used_names:
        used_names.add(name)
        return name
    suffix = 2
    while f"{name}{suffix}" in used_names:
        suffix += 1
    deduped = f"{name}{suffix}"
    used_names.add(deduped)
    return deduped


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
    should_try_tinytroupe = any(
        type(agent).__module__.startswith("tinytroupe") for agent in existing_agents
    )
    if should_try_tinytroupe:
        maybe_tiny = _try_build_tinytroupe_agents(1)
        if maybe_tiny:
            tiny_agent = maybe_tiny[0]
            current_name = str(getattr(tiny_agent, "name", "Villager"))
            unique_name = _dedupe_name(current_name, existing_names)
            if unique_name != current_name:
                try:
                    setattr(tiny_agent, "name", unique_name)
                except Exception:
                    pass
            return tiny_agent

    return _build_mock_agents(1, used_names=existing_names)[0]

