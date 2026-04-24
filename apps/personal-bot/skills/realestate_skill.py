"""Real-estate skill — MOLIT 실거래/전월세 조회 (k-skill-proxy 경유).

구현 디테일은 `realestate_engine`. k-skill 통합 경로와 intent 필터는
[realestate_skill.md](realestate_skill.md) 참조.
"""

from typing import Optional

import realestate_engine

from ._base import SkillBase, SkillContext


class RealEstateSkill(SkillBase):
    name = "realestate"
    status_message = "부동산 실거래 조회 중입니다..."

    def matches(self, ctx: SkillContext) -> bool:
        return realestate_engine.is_real_estate_query(ctx.text)

    def handle(self, ctx: SkillContext) -> Optional[str]:
        return realestate_engine.build_real_estate_reply(ctx.text)
