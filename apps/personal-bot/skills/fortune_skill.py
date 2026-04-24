"""Fortune skill — 일진·사주·별자리 기반 오늘의 운세.

구현 디테일은 `fortune_engine` 모듈에 있고, 이 파일은 DM 분기 라우터를 위한 얇은
wrapper. 자세한 흐름/출처/실패 모드는 [fortune_skill.md](fortune_skill.md) 참조.
"""

from typing import Optional

import fortune_engine

from ._base import SkillBase, SkillContext


class FortuneSkill(SkillBase):
    name = "fortune"
    status_message = "운세 준비 중입니다..."

    def matches(self, ctx: SkillContext) -> bool:
        return fortune_engine.is_fortune_query(ctx.text)

    def handle(self, ctx: SkillContext) -> Optional[str]:
        target_name = fortune_engine.extract_fortune_target(ctx.text)
        slack_matched_key: Optional[str] = None

        if target_name:
            _, resolved_profile = fortune_engine.resolve_profile(target_name)
            if resolved_profile is None:
                canonical = fortune_engine.canonicalize_target(target_name or "")
                return fortune_engine.start_registration(ctx.user_id, canonical, mode="create")
        else:
            # 텍스트에 이름이 없으면 Slack display_name → 3글자 풀네임 substring 매칭.
            # 런너가 pre-fetch 해서 주입.
            sk_key, sk_profile, ambiguous = (
                fortune_engine.resolve_profile_for_slack_name(ctx.slack_display_name)
            )
            if ambiguous:
                return (
                    "Slack 이름에서 여러 프로필이 매칭됐다. "
                    "`이름 운세` 형식으로 지정해달라!"
                )
            if sk_profile is not None:
                slack_matched_key = sk_key

        return fortune_engine.build_fortune_reply(
            ctx.text,
            target_override=slack_matched_key,
        )
