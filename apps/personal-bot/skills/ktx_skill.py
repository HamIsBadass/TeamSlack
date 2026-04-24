"""KTX skill — KTX/Korail 좌석 조회 (`korail2` 라이브러리 경유, 조회 전용).

구현 디테일은 `ktx_engine`. credential 과 예약 미자동화 정책은
[ktx_skill.md](ktx_skill.md) 참조.
"""

from typing import Optional

import ktx_engine

from ._base import SkillBase, SkillContext


class KtxSkill(SkillBase):
    name = "ktx"
    status_message = "KTX 열차 조회 중입니다..."

    def matches(self, ctx: SkillContext) -> bool:
        return ktx_engine.is_ktx_query(ctx.text)

    def handle(self, ctx: SkillContext) -> Optional[str]:
        return ktx_engine.build_ktx_reply(ctx.text)
