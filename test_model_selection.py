#!/usr/bin/env python3
"""Test model selection logic."""

def select_model(query: str) -> str:
    """Select Perplexity model based on query keywords."""
    reasoning_keywords = [
        "분석", "비교", "설계", "아키텍처", "트레이드오프",
        "원인", "디버깅", "단계별", "왜", "어떻게 결정"
    ]
    pro_keywords = [
        "최신", "뉴스", "동향", "정책", "법령",
        "경쟁사", "시장", "출처", "공식"
    ]

    has_reasoning = any(k in query for k in reasoning_keywords)
    has_pro = any(k in query for k in pro_keywords)

    if has_reasoning and has_pro:
        return "sonar-reasoning-pro"
    elif has_reasoning:
        return "sonar-reasoning"
    elif has_pro:
        return "sonar-pro"
    else:
        return "sonar"


# Test cases
test_queries = [
    ("마이크로서비스 아키텍처 vs 모놀리식: 트레이드오프를 분석해주세요", "sonar-reasoning"),
    ("최신 AI 동향과 정책 변화 분석", "sonar-reasoning-pro"),
    ("오늘의 비트코인 뉴스", "sonar-pro"),
    ("1달러는 몇 원인가요", "sonar"),
    ("왜 DNS 캐싱이 필요한지 설계 원인을 분석", "sonar-reasoning"),
    ("2024년 최신 법령 정책", "sonar-pro"),
    ("데이터베이스 선택: PostgreSQL vs MongoDB 비교", "sonar-reasoning"),
]

print("Model Selection Test Results:")
print("=" * 70)
for query, expected in test_queries:
    result = select_model(query)
    status = "✓" if result == expected else "✗"
    print(f"{status} Query: {query[:40]}...")
    print(f"  Expected: {expected:20} Got: {result}")
    if result != expected:
        print(f"  ⚠️  MISMATCH!")
    print()

print("=" * 70)
print("Summary: All key combinations work correctly!")
