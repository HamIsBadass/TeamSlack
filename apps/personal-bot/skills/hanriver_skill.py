"""Han river water-level skill — HRFCO 실시간 수위/유량 조회 (k-skill-proxy 경유).

구현 디테일은 `hanriver_engine`. k-skill 통합 경로와 ambiguous 처리 규칙은
[hanriver_skill.md](hanriver_skill.md) 참조.
"""

from typing import Optional

import hanriver_engine

from ._base import SkillBase, SkillContext


class HanRiverSkill(SkillBase):
    name = "hanriver"
    status_message = "한강 수위 조회 중입니다..."

    def matches(self, ctx: SkillContext) -> bool:
        return hanriver_engine.is_han_river_query(ctx.text)

    def handle(self, ctx: SkillContext) -> Optional[str]:
        return hanriver_engine.build_han_river_reply(ctx.text)
