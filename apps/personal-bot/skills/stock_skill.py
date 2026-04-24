"""Korean stock skill — KRX 공식 데이터 기반 국내 주식 조회 (k-skill-proxy 경유).

구현 디테일은 `stock_engine`. k-skill 통합 경로와 exclusion 규칙은
[stock_skill.md](stock_skill.md) 참조.
"""

from typing import Optional

import stock_engine

from ._base import SkillBase, SkillContext


class StockSkill(SkillBase):
    name = "stock"
    status_message = "국내 주식 시세 조회 중입니다..."

    def matches(self, ctx: SkillContext) -> bool:
        return stock_engine.is_korean_stock_query(ctx.text)

    def handle(self, ctx: SkillContext) -> Optional[str]:
        return stock_engine.build_korean_stock_reply(ctx.text)
