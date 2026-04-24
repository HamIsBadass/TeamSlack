"""
API Cost Tracking System.

Tracks API usage and costs for Perplexity, Gemini, and other LLM services.
Provides per-user, per-session, and daily cost summaries.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from threading import RLock
from collections import defaultdict

logger = logging.getLogger(__name__)


class ApiCostTracker:
    """Track API costs in memory with thread-safe access."""

    # Blended cost per 1K tokens (rough estimate; actual billing comes from provider).
    # Sourced from public pricing as of 2025-Q3; update when providers change rates.
    COST_MAPPING = {
        # Perplexity: per-query estimate (provider bills per query, not tokens).
        "perplexity_research": 0.020,      # sonar-reasoning / sonar-pro 계열 ≈ $0.02/query
        "perplexity_standard": 0.005,      # sonar 기본 ≈ $0.005/query
        # Gemini 2.5 family: approximate blended in+out per 1K tokens.
        "gemini_flash_lite": 0.00025,      # $0.10 in / $0.40 out per 1M
        "gemini_flash": 0.0014,            # $0.30 in / $2.50 out per 1M
        "gemini_pro": 0.0056,              # $1.25 in / $10.00 out per 1M
        "openai_gpt4_turbo": 0.001,
        "openai_gpt35": 0.0005,
    }

    def __init__(self):
        """Initialize cost tracker."""
        self._lock = RLock()
        # Structure: {user_id: {date: {api_name: cost}}}
        self._user_daily_costs: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(float))
        )
        # Structure: {session_id: {api_name: cost}}
        self._session_costs: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
        # Structure: {request_id: {api_name: [calls]}}
        self._request_costs: Dict[str, Dict[str, list]] = defaultdict(
            lambda: defaultdict(list)
        )

    def record_api_call(
        self,
        api_name: str,
        cost_or_tokens: float,
        user_id: Optional[str] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Record an API call and its cost.

        Args:
            api_name: "perplexity_research", "gemini_pro", etc.
            cost_or_tokens: Actual cost in USD or token count (auto-converts if token count)
            user_id: Slack user ID for daily tracking
            request_id: Request ID for tracing
            session_id: Session/conversation ID
            metadata: Additional metadata ({"query": "...", "model": "..."})

        Returns:
            {
                "cost_usd": 0.005,
                "daily_total_usd": 0.150,
                "session_total_usd": 0.025,
                ...
            }
        """
        # Convert token count to USD if necessary
        if cost_or_tokens > 1.0:  # Likely a token count (> 1.0 means tokens)
            tokens = cost_or_tokens
            api_cost_per_1k = self.COST_MAPPING.get(api_name, 0.001)
            cost_usd = (tokens / 1000.0) * api_cost_per_1k
        else:
            cost_usd = cost_or_tokens

        with self._lock:
            # Record in session
            if session_id:
                self._session_costs[session_id][api_name] += cost_usd

            # Record in request
            if request_id:
                self._request_costs[request_id][api_name].append(
                    {
                        "cost": cost_usd,
                        "timestamp": datetime.utcnow().isoformat(),
                        "metadata": metadata or {},
                    }
                )

            # Record daily cost per user
            daily_total = 0.0
            if user_id:
                today = datetime.utcnow().strftime("%Y-%m-%d")
                self._user_daily_costs[user_id][today][api_name] += cost_usd
                # Sum daily total for user
                daily_total = sum(
                    costs.values() for costs in self._user_daily_costs[user_id][today].values()
                )

            # Calculate session total
            session_total = sum(
                costs for costs in self._session_costs.get(session_id, {}).values()
            )

            # Calculate request total
            request_total = sum(
                sum(calls)
                for calls in self._request_costs.get(request_id, {}).values()
            )

            return {
                "cost_usd": round(cost_usd, 4),
                "api_name": api_name,
                "daily_total_usd": round(daily_total, 2) if user_id else None,
                "session_total_usd": round(session_total, 4),
                "request_total_usd": round(request_total, 4),
                "timestamp": datetime.utcnow().isoformat(),
            }

    def get_daily_summary(self, user_id: str, date: Optional[str] = None) -> Dict[str, Any]:
        """
        Get daily cost summary for a user.

        Args:
            user_id: Slack user ID
            date: "YYYY-MM-DD" format (default: today)

        Returns:
            {
                "user_id": "U123456789",
                "date": "2026-04-20",
                "apis": {
                    "perplexity_research": 0.100,
                    "gemini_pro": 0.050
                },
                "total_usd": 0.150
            }
        """
        if date is None:
            date = datetime.utcnow().strftime("%Y-%m-%d")

        with self._lock:
            apis = self._user_daily_costs.get(user_id, {}).get(date, {})
            total = sum(apis.values())

            return {
                "user_id": user_id,
                "date": date,
                "apis": {k: round(v, 4) for k, v in apis.items()},
                "total_usd": round(total, 2),
            }

    def get_monthly_summary(
        self,
        user_id: str,
        month: Optional[str] = None,
        api_name_prefix: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Sum daily costs for a user within a YYYY-MM window.

        Args:
            user_id: Slack user ID
            month: "YYYY-MM" (default: current UTC month)
            api_name_prefix: if set, only api_name starting with this prefix is counted
                (e.g., "gemini_" to exclude Perplexity).
        """
        if month is None:
            month = datetime.utcnow().strftime("%Y-%m")

        with self._lock:
            user_days = self._user_daily_costs.get(user_id, {})
            apis: Dict[str, float] = defaultdict(float)
            for date, day_apis in user_days.items():
                if not date.startswith(month):
                    continue
                for api_name, cost in day_apis.items():
                    if api_name_prefix and not api_name.startswith(api_name_prefix):
                        continue
                    apis[api_name] += cost

            total = sum(apis.values())
            return {
                "user_id": user_id,
                "month": month,
                "apis": {k: round(v, 4) for k, v in apis.items()},
                "total_usd": round(total, 4),
            }

    def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """Get session cost summary."""
        with self._lock:
            apis = self._session_costs.get(session_id, {})
            total = sum(apis.values())

            return {
                "session_id": session_id,
                "apis": {k: round(v, 4) for k, v in apis.items()},
                "total_usd": round(total, 4),
            }

    def get_request_summary(self, request_id: str) -> Dict[str, Any]:
        """Get request-level cost breakdown."""
        with self._lock:
            request_data = self._request_costs.get(request_id, {})
            summary = {}
            total_cost = 0.0

            for api_name, calls in request_data.items():
                api_total = sum(call["cost"] for call in calls)
                summary[api_name] = {
                    "call_count": len(calls),
                    "total_usd": round(api_total, 4),
                    "calls": calls,
                }
                total_cost += api_total

            return {
                "request_id": request_id,
                "apis": summary,
                "total_usd": round(total_cost, 4),
            }

    def format_cost_footer(
        self,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        compact: bool = True,
    ) -> str:
        """
        Format cost summary as Slack-friendly text footer.

        Args:
            user_id: If provided, include daily total
            session_id: If provided, include session total
            compact: If True, use abbreviated format

        Returns:
            "💰 API: $0.005 | 오늘: $0.15"
        """
        parts = []

        if session_id:
            session_summary = self.get_session_summary(session_id)
            session_cost = session_summary["total_usd"]
            if compact:
                parts.append(f"💰 {session_cost:.3f}$")
            else:
                parts.append(f"이 대화비용: ${session_cost:.4f}")

        if user_id:
            daily_summary = self.get_daily_summary(user_id)
            daily_cost = daily_summary["total_usd"]
            parts.append(f"오늘: ${daily_cost:.2f}")

        if not parts:
            return ""

        if compact:
            return " | ".join(parts)
        else:
            return "\n".join(parts)

    def reset_session(self, session_id: str) -> None:
        """Clear session costs (e.g., at conversation reset)."""
        with self._lock:
            if session_id in self._session_costs:
                del self._session_costs[session_id]
                logger.info(f"Session {session_id} costs cleared")

    def reset_user_daily(self, user_id: str, date: Optional[str] = None) -> None:
        """Clear daily costs for a user (admin action)."""
        if date is None:
            date = datetime.utcnow().strftime("%Y-%m-%d")

        with self._lock:
            if user_id in self._user_daily_costs and date in self._user_daily_costs[user_id]:
                del self._user_daily_costs[user_id][date]
                logger.info(f"User {user_id} daily costs for {date} cleared")


# Global singleton
_tracker = None


def get_cost_tracker() -> ApiCostTracker:
    """Get or create the global cost tracker instance."""
    global _tracker
    if _tracker is None:
        _tracker = ApiCostTracker()
    return _tracker
