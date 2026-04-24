"""Skill 공통 인터페이스.

쥐피티(personal-bot) 의 DM 핸들러는 이 프로토콜을 따르는 스킬들을 우선순위대로
`matches()` 검사, 첫 매치의 `handle()` 을 실행한다.

설계 원칙
- k-skill 스킬 모델의 경량 버전. SKILL.md (co-located `<name>.md`) 로 데이터 출처·
  k-skill-proxy 연동 경로·실패 모드를 문서화한다.
- 상태 관리는 각 스킬 내부에서 처리 (예: fortune 의 pending registration).
  런너는 최소한의 컨텍스트(client/user_id/channel_id/text) 만 전달.
- 런너 재진입을 줄이기 위해 handle() 은 최종 문자열을 반환하고, 런너가 통일된
  status-message 업데이트 + `say()` 를 처리한다.
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class SkillContext:
    """Slack DM 핸들러가 스킬에 전달하는 최소 컨텍스트."""

    client: Any          # slack_bolt WebClient
    user_id: str
    channel_id: str
    text: str
    slack_display_name: str = ""  # 이미 조회돼 있으면 런너가 주입. 빈 문자열이면 스킬이 필요 시 재조회


class SkillBase:
    """모든 쥐피티 스킬의 베이스.

    서브클래스는 `name`, `status_message`(선택) 를 설정하고
    `matches()`, `handle()` 을 구현한다.
    """

    # 등록/로깅에 쓰이는 고유 키. 한 단어 ASCII 권장.
    name: str = ""

    # handle() 중 런너가 먼저 채널에 띄울 상태 메시지. 비어 있으면 상태 메시지 없이 바로 응답.
    status_message: str = ""

    def matches(self, ctx: SkillContext) -> bool:
        """이 스킬이 현재 DM 을 처리할지 판정. 부작용 없는 순수 판정 로직이어야 한다."""
        return False

    def handle(self, ctx: SkillContext) -> Optional[str]:
        """최종 회신 텍스트를 반환.

        - 정상 응답: Slack markdown 이 포함된 문자열
        - `None`: 처리 의사 없음 (런너가 후속 분기로 폴백)
        """
        return None
