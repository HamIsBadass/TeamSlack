#!/usr/bin/env python3
"""Test 곰 emoji formatter with duplicate prevention."""

def add_gom_emojis(text: str) -> str:
    """Add 곰 and emojis to first and last sentences in bot responses.
    
    Format:
    - First sentence ends with: "~곰.🐻‍❄️"
    - Last sentence ends with: "~곰. :king_gom:"
    
    Avoids duplicate "곰" if already present in API response.
    """
    if not text or len(text.strip()) == 0:
        return text
    
    # 첫 번째 마침표 찾기
    first_period = text.find('.')
    last_period = text.rfind('.')
    has_multiple_sentences = (first_period != last_period)
    
    if first_period != -1:
        # "." 앞 문자가 "곰"이 아닐 경우에만 추가
        if first_period > 0 and text[first_period - 1] != '곰':
            # 첫 문장 처리: "." 앞에 "곰" 추가, 뒤의 공백 제거 후 이모티콘 추가
            text = text[:first_period] + "곰.🐻‍❄️ " + text[first_period+1:].lstrip()
        else:
            # 이미 "곰"이 있으면 "곰." 뒤에 이모티콘만 추가
            text = text[:first_period+1] + "🐻‍❄️ " + text[first_period+1:].lstrip()
    
    # 마지막 마침표 처리 (여러 문장인 경우만)
    if has_multiple_sentences:
        last_period = text.rfind('.')  # 수정된 텍스트에서 다시 찾기
        if last_period != -1:
            # "." 앞 문자가 "곰"이 아닐 경우에만 추가
            if last_period > 0 and text[last_period - 1] != '곰':
                # 마지막 문장 처리: "." 앞에 "곰" 추가, :king_gom: 추가
                text = text[:last_period] + "곰. :king_gom:"
            else:
                # 이미 "곰"이 있으면 "곰. " 뒤에 :king_gom:만 추가
                text = text[:last_period+1] + " :king_gom:"
    else:
        # 한 문장인 경우, 이미 첫 이모티콘이 추가되었으므로 마지막 이모티콘만 추가
        last_period = text.rfind('.')
        if last_period != -1:
            # 이모티콘 뒤에 :king_gom: 추가 (기존 emoji 다음)
            if "🐻‍❄️" in text:
                # emoji 뒤에 추가
                emoji_pos = text.rfind("🐻‍❄️")
                text = text[:emoji_pos + len("🐻‍❄️")] + " :king_gom:"
            else:
                # emoji가 없으면 마지막 마침표 뒤에 추가
                text = text[:last_period+1] + " :king_gom:"
    
    return text


# Test cases
test_cases = [
    # Case 1: API response WITHOUT "곰" (should add it)
    (
        "지금 기준으로 1달러는 약 1480원이다. 최근 6개월 환율 흐름을 고려할 때 현재는 상대적으로 저점에 가깝다.",
        "지금 기준으로 1달러는 약 1480원이다곰.🐻‍❄️ 최근 6개월 환율 흐름을 고려할 때 현재는 상대적으로 저점에 가깝다곰. :king_gom:"
    ),
    # Case 2: API response WITH "곰" (should NOT duplicate)
    (
        "지금 기준으로 1달러는 약 1480원이다곰. 최근 6개월 환율 흐름을 고려할 때 현재는 상대적으로 저점에 가깝다곰.",
        "지금 기준으로 1달러는 약 1480원이다곰.🐻‍❄️ 최근 6개월 환율 흐름을 고려할 때 현재는 상대적으로 저점에 가깝다곰. :king_gom:"
    ),
    # Case 3: Single sentence without "곰"
    (
        "비트코인이 상승했다.",
        "비트코인이 상승했다곰.🐻‍❄️ :king_gom:"
    ),
    # Case 4: Single sentence WITH "곰"
    (
        "비트코인이 상승했다곰.",
        "비트코인이 상승했다곰.🐻‍❄️ :king_gom:"
    ),
]

print("🐻‍❄️ Gom Emoji Formatter Test (Duplicate Prevention) 🐻‍❄️")
print("=" * 100)

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

print("\n" + "=" * 100)
print("✓ All tests completed!")
