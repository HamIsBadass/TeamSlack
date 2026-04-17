#!/usr/bin/env python3
"""Diagnostic script to test channel parsing and name resolution."""

# Simulate the parser logic
def test_parsing():
    test_input = "아 시원해서 너무 좋다햄 콘텐츠-기획제작"
    
    print("=" * 60)
    print("TEST: 채널명 파싱 검증")
    print("=" * 60)
    print(f"입력: {test_input}")
    print()
    
    words = test_input.split()
    print(f"분割된 단어: {words}")
    print(f"마지막 단어: {words[-1]}")
    print(f"'-' 포함 여부: {'-' in words[-1]}")
    print()
    
    if "-" in words[-1] or "_" in words[-1]:
        channel_ref = words[-1]
        message_text = " ".join(words[:-1])
        print(f"✓ 채널명 인식됨: '{channel_ref}'")
        print(f"✓ 메시지: '{message_text}'")
    else:
        print("✗ 채널명 인식 실패")
    
    print()
    print("=" * 60)
    print("다음 단계: 봇 로그에서 아래 메시지 확인")
    print("=" * 60)
    print("""
1. 채널 해석 로그:
   - "채널 '{channel_ref}'을 찾지 못했습니다" → 채널명이 Slack workspace에 없음
   - "동일 이름 채널이 여러 개입니다" → 채널명 확인 필요
   - "Perplexity API HTTP error" → API 문제

2. 발송 로그:
   - "<#CXXXXXX>에 메시지를 게시했습니다" → 성공
   - "전송 실패: " → 권한 문제 또는 채널 접근 불가

3. 채널 이름 확인:
   - Slack 채널 설정에서 정확한 이름 확인
   - 봇이 해당 채널에 참여했는지 확인 (초대해야 할 수도)
""")

if __name__ == "__main__":
    test_parsing()
