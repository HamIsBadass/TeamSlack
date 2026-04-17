#!/usr/bin/env python3
"""Test 곰 emoji formatter."""

def add_gom_emojis(text: str) -> str:
    """Add 곰 and emojis to first and last sentences in bot responses.
    
    Format:
    - First sentence: "~곰.🐻‍❄️"
    - Last sentence: "~곰. :king_gom:"
    """
    if not text or len(text.strip()) == 0:
        return text
    
    # 첫 번째 마침표 찾기
    first_period = text.find('.')
    if first_period != -1:
        # 첫 문장 처리: "." 앞에 "곰" 추가, 뒤의 공백 제거 후 이모티콘 추가
        text = text[:first_period] + "곰.🐻‍❄️ " + text[first_period+1:].lstrip()
    
    # 마지막 마침표 찾기 (현재 수정된 텍스트에서)
    last_period = text.rfind('.')
    if last_period != -1 and last_period != first_period:
        # 마지막 문장 처리: "." 앞에 "곰" 추가, :king_gom: 추가
        text_before = text[:last_period]
        text_after = text[last_period+1:].rstrip()
        text = text_before + "곰. :king_gom:"
    
    return text


# Test cases
test_cases = [
    (
        "지금 기준으로 1달러는 약 1480원이다. 최근 6개월 환율 흐름을 고려할 때 현재는 상대적으로 저점에 가깝다.",
        "지금 기준으로 1달러는 약 1480원이다곰.🐻‍❄️ 최근 6개월 환율 흐름을 고려할 때 현재는 상대적으로 저점에 가깝다곰. :king_gom:"
    ),
    (
        "비트코인이 오늘 상승했다. 시장 심리가 긍정적이다.",
        "비트코인이 오늘 상승했다곰.🐻‍❄️ 시장 심리가 긍정적이다곰. :king_gom:"
    ),
]

print("🐻‍❄️ Gom Emoji Formatter Test 🐻‍❄️")
print("=" * 80)

for i, (input_text, expected) in enumerate(test_cases, 1):
    result = add_gom_emojis(input_text)
    match = result == expected
    status = "✓" if match else "✗"
    
    print(f"\nTest {i}: {status}")
    print(f"Input:    {input_text}")
    print(f"Expected: {expected}")
    print(f"Got:      {result}")
    if not match:
        print("⚠️  MISMATCH!")

print("\n" + "=" * 80)
print("✓ Emoji formatter ready for bot!")
