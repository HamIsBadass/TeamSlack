"""SRT skill — SRT 좌석 조회 (`SRTrain` 라이브러리 경유, 조회 전용).

구현 디테일은 `srt_engine`. credential 과 예약 미자동화 정책은
[srt_skill.md](srt_skill.md) 참조.
"""

from typing import Optional

import srt_engine

from ._base import SkillBase, SkillContext


class SrtSkill(SkillBase):
    name = "srt"
    status_message = "SRT 열차 조회 중입니다..."

    def matches(self, ctx: SkillContext) -> bool:
        return srt_engine.is_srt_query(ctx.text)

    def handle(self, ctx: SkillContext) -> Optional[str]:
        return srt_engine.build_srt_reply(ctx.text)
