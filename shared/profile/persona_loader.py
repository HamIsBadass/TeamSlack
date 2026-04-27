"""Load bot persona specs from `shared/profile/personas/*.md`.

A persona file has a YAML front-matter block (display_name / emoji / role /
persona_id) followed by the voice-rules body used as the LLM system prompt.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

_PERSONAS_DIR = Path(__file__).parent / "personas"
_COMMON_FILE = _PERSONAS_DIR / "_common.md"


@dataclass(frozen=True)
class Persona:
    persona_id: str
    display_name: str
    emoji: str
    role: str
    voice_rules: str
    # 임곰(오케스트레이터)에게 요청을 넘길 때 쓰는 첫 문장 템플릿. "{subject}" 슬롯이
    # 실제 요청 내용으로 치환된다. 봇마다 말투가 조금씩 달라도 복종 어감을 유지.
    orchestrator_request_prefix: str = "임곰님, {subject} 승낙 부탁드립니다."

    def header_label(self) -> str:
        """Slack-friendly header e.g. ':broom: 리바이 (meeting_bot)'."""
        return f"{self.emoji} {self.display_name} ({self.persona_id})"

    def orchestrator_request(self, subject: str) -> str:
        """페르소나 prefix 를 subject 로 채워 반환."""
        template = self.orchestrator_request_prefix or "임곰님, {subject} 승낙 부탁드립니다."
        return template.replace("{subject}", subject)


_CACHE: Dict[str, Persona] = {}
_common_cache: Optional[str] = None


def _load_common_rules() -> str:
    """Read shared rules applied to every persona. Cached."""
    global _common_cache
    if _common_cache is None:
        if _COMMON_FILE.exists():
            text = _COMMON_FILE.read_text(encoding="utf-8").strip()
            if text.startswith("#"):
                text = text.split("\n", 1)[1].strip() if "\n" in text else ""
            _common_cache = text
        else:
            _common_cache = ""
    return _common_cache


def _parse(path: Path) -> Persona:
    text = path.read_text(encoding="utf-8").lstrip()
    if not text.startswith("---"):
        raise ValueError(f"{path.name}: front-matter missing")

    _, fm, body = text.split("---", 2)
    meta: Dict[str, str] = {}
    for line in fm.strip().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")

    required = ("persona_id", "display_name", "emoji", "role")
    missing = [k for k in required if k not in meta]
    if missing:
        raise ValueError(f"{path.name}: missing front-matter keys {missing}")

    voice = body.strip()
    if voice.startswith("#"):
        voice = voice.split("\n", 1)[1].strip() if "\n" in voice else ""

    common = _load_common_rules()
    if common and voice:
        voice = f"{common}\n\n{voice}"
    elif common:
        voice = common

    prefix = meta.get("orchestrator_request_prefix", "").strip()
    return Persona(
        persona_id=meta["persona_id"],
        display_name=meta["display_name"],
        emoji=meta["emoji"],
        role=meta["role"],
        voice_rules=voice,
        orchestrator_request_prefix=prefix or "임곰님, {subject} 승낙 부탁드립니다.",
    )


def get_persona(persona_id: str) -> Persona:
    """Return persona by id, loading + caching on first call.

    Raises FileNotFoundError if the md file does not exist.
    """
    if persona_id in _CACHE:
        return _CACHE[persona_id]

    path = _PERSONAS_DIR / f"{persona_id}.md"
    if not path.exists():
        raise FileNotFoundError(f"Persona spec not found: {path}")

    persona = _parse(path)
    if persona.persona_id != persona_id:
        raise ValueError(
            f"Persona id mismatch in {path.name}: "
            f"filename says '{persona_id}', front-matter says '{persona.persona_id}'"
        )
    _CACHE[persona_id] = persona
    return persona


def reload_personas() -> None:
    """Drop the cache so the next get_persona() re-reads from disk."""
    global _common_cache
    _CACHE.clear()
    _common_cache = None
