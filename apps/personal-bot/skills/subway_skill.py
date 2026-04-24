"""Subway skill — 서울 지하철 실시간 도착 정보 (k-skill-proxy 경유).

구현 디테일은 `subway_engine`. k-skill 통합 경로와 역명 처리 규칙은
[subway_skill.md](subway_skill.md) 참조.
"""

from typing import Optional

import subway_engine

from ._base import SkillBase, SkillContext


class SubwaySkill(SkillBase):
    name = "subway"
    status_message = "지하철 도착 정보 조회 중입니다..."

    def matches(self, ctx: SkillContext) -> bool:
        return subway_engine.is_subway_query(ctx.text)

    def handle(self, ctx: SkillContext) -> Optional[str]:
        return subway_engine.build_subway_reply(ctx.text)
