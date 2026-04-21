"""
Personal Bot API Cost Tracking Integration Example.

This shows how to integrate API cost tracking into personal-bot/socket_mode_runner.py
"""

import logging
import sys
from pathlib import Path

# Setup paths
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.api_cost_tracker import get_cost_tracker

logger = logging.getLogger(__name__)


class PersonalBotWithCostTracking:
    """Example of integrating cost tracking into personal bot responses."""
    
    def __init__(self):
        """Initialize personal bot with cost tracker."""
        self.cost_tracker = get_cost_tracker()
        self.user_id = None
        self.session_id = None
    
    def set_context(self, user_id: str, session_id: str):
        """Set user and session context for cost tracking."""
        self.user_id = user_id
        self.session_id = session_id
    
    def answer_perplexity_query(
        self,
        query: str,
        model: str = "sonar-pro"
    ) -> dict:
        """
        Answer user query using Perplexity API.
        
        Example: "날씨가 어때?" or "오늘 운세" (업무 무관 쿼리)
        
        Returns answera with API cost footer.
        """
        logger.info(f"Answering query with Perplexity: {query}")
        
        # Step 1: Call Perplexity API (mock implementation)
        response_text = self._call_perplexity(query, model)
        api_cost = 0.005  # $0.005 per standard query
        tokens_used = 450  # Estimated tokens
        
        # OR: If you have actual token count:
        # api_cost = (tokens_used / 1000.0) * self.cost_tracker.COST_MAPPING["perplexity_standard"]
        
        # Step 2: Record API cost
        cost_info = self.cost_tracker.record_api_call(
            api_name="perplexity_standard",
            cost_or_tokens=api_cost,  # Use actual cost or token count
            user_id=self.user_id,
            session_id=self.session_id,
            metadata={
                "query": query[:50],
                "model": model,
                "tokens": tokens_used
            }
        )
        
        logger.info(f"Cost tracked: {cost_info}")
        
        # Step 3: Get daily total for cost footer
        daily_summary = self.cost_tracker.get_daily_summary(self.user_id)
        cost_footer = self.cost_tracker.format_cost_footer(
            user_id=self.user_id,
            session_id=self.session_id,
            compact=True
        )
        
        # Step 4: Format response with footer
        return {
            "answer": response_text,
            "cost_this_query": f"${cost_info['cost_usd']:.4f}",
            "cost_today": f"${daily_summary['total_usd']:.2f}",
            "cost_footer": cost_footer,  # "💰 $0.005 | 오늘: $0.15"
            "formatted_message": self._format_slack_message(response_text, cost_footer)
        }
    
    def _call_perplexity(self, query: str, model: str) -> str:
        """Mock Perplexity API call."""
        # In real implementation:
        # import requests
        # response = requests.post(
        #     "https://api.perplexity.ai/chat/completions",
        #     headers={"Authorization": f"Bearer {PERPLEXITY_API_KEY}"},
        #     json={
        #         "model": model,
        #         "messages": [{"role": "user", "content": query}]
        #     }
        # )
        # return response.json()["choices"][0]["message"]["content"]
        
        return f"[Mock Response] {query}에 대한 답변입니다. 실제 Perplexity 응답이 여기 나타납니다."
    
    def _format_slack_message(self, answer: str, cost_footer: str) -> str:
        """Format Slack-friendly message with cost footer."""
        return f"""{answer}

---
{cost_footer}"""


# ============ Integration with Slack message submission ============

def submit_query_response_to_orchestrator(
    user_id: str,
    query: str,
    response: dict,
    request_id: str = None
):
    """
    Submit query response to orchestrator via /api/orchestrator/submit endpoint.
    
    This bridges personal-bot responses into the orchestration channel.
    """
    import requests
    import json
    
    orchestrator_url = "http://localhost:8000/api/orchestrator/submit"
    
    payload = {
        "source_bot": "personal_bot",
        "source_user": user_id,
        "output_type": "query_response",
        "request_id": request_id,  # Optional: link to existing request
        "payload": {
            "query": query,
            "answer": response["answer"],
            "cost_this_query": response["cost_this_query"],
            "timestamp": datetime.utcnow().isoformat()
        },
        "api_cost_usd": float(response["cost_this_query"].replace("$", "")),
        "api_name": "perplexity_standard"
    }
    
    logger.info(f"Submitting response to orchestrator: {request_id}")
    
    try:
        resp = requests.post(orchestrator_url, json=payload)
        result = resp.json()
        logger.info(f"Orchestrator response: {result}")
        return result
    except Exception as e:
        logger.exception(f"Failed to submit to orchestrator: {e}")
        return None


# ============ Example usage ============

if __name__ == "__main__":
    from datetime import datetime
    
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    # Initialize bot
    bot = PersonalBotWithCostTracking()
    bot.set_context(user_id="U123456789", session_id="conv-20260420-001")
    
    # Example 1: Simple weather query
    print("\n=== Example 1: Weather Query ===")
    result = bot.answer_perplexity_query("내일 서울 날씨는?")
    print(f"Answer: {result['answer']}")
    print(f"Cost this query: {result['cost_this_query']}")
    print(f"Cost today: {result['cost_today']}")
    print(f"Slack format:\n{result['formatted_message']}")
    
    # Example 2: Fortune query
    print("\n=== Example 2: Fortune Query ===")
    result = bot.answer_perplexity_query("오늘 운세 봐줘")
    print(f"Cost footer: {result['cost_footer']}")
    
    # Example 3: Multiple queries to show daily accumulation
    print("\n=== Example 3: Multiple Queries (Cost Accumulation) ===")
    for i in range(3):
        result = bot.answer_perplexity_query(f"Query {i+1}")
        print(f"Query {i+1} - Daily total: {result['cost_today']}")
    
    # Example 4: Submit to orchestrator
    print("\n=== Example 4: Submit to Orchestrator ===")
    result = bot.answer_perplexity_query("롱런 기업이 뭐 있을까?")
    submit_result = submit_query_response_to_orchestrator(
        user_id="U123456789",
        query="롱런 기업이 뭐 있을까?",
        response=result,
        request_id=None  # New request (no linking)
    )
    if submit_result:
        print(f"Submitted! Request ID: {submit_result.get('request_id')}")
    
    # Print daily summary
    print("\n=== Daily Summary ===")
    daily = bot.cost_tracker.get_daily_summary("U123456789")
    print(f"User: {daily['user_id']}")
    print(f"Date: {daily['date']}")
    print(f"APIs: {daily['apis']}")
    print(f"Total: ${daily['total_usd']}")
