#!/usr/bin/env python3
"""Test Slack formatter to verify markdown ↔ Slack style conversion."""

import re


def to_slack_format(text: str) -> str:
    """Convert markdown formatting to Slack format."""
    # Use temporary markers to prevent conflicting conversions
    BOLD_MARKER = "\x00BOLD_MARKER\x00"
    HEADING_MARKER = "\x00HEADING_MARKER\x00"
    
    # First: **bold** → marker (preserve double asterisk bold)
    text = re.sub(r'\*\*(.+?)\*\*', BOLD_MARKER + r'\1' + BOLD_MARKER, text)
    
    # Second: __bold__ → marker (preserve underscore bold)
    text = re.sub(r'__(.+?)__', BOLD_MARKER + r'\1' + BOLD_MARKER, text)
    
    # Third: ### heading → marker (preserve heading)
    text = re.sub(r'#{1,6}\s(.+)', HEADING_MARKER + r'\1' + HEADING_MARKER, text)
    
    # Fourth: *italic* → _italic_ (only remaining single asterisks)
    text = re.sub(r'\*(.+?)\*', r'_\1_', text)
    
    # Fifth: Replace markers with final Slack format
    text = text.replace(BOLD_MARKER, '*')
    text = text.replace(HEADING_MARKER, '*')
    
    # Sixth: --- 구분선 제거
    text = re.sub(r'\n---+\n', '\n\n', text)

    return text.strip()


# Test cases: Markdown input → Expected Slack output
test_cases = [
    # Case 1: Bold
    (
        "**마이크로서비스 아키텍처**는 좋다.",
        "*마이크로서비스 아키텍처*는 좋다."
    ),
    # Case 2: Double underscore bold
    (
        "__Docker__를 사용해야 한다.",
        "*Docker*를 사용해야 한다."
    ),
    # Case 3: Single asterisk italic (after bold conversion)
    (
        "이것은 *중요한* 포인트이다.",
        "이것은 _중요한_ 포인트이다."
    ),
    # Case 4: Heading
    (
        "### 장점\n확장성이 우수하다.",
        "*장점*\n확장성이 우수하다."
    ),
    # Case 5: Mixed formatting
    (
        "**API 게이트웨이**는 *진짜* 중요하다.",
        "*API 게이트웨이*는 _진짜_ 중요하다."
    ),
    # Case 6: Separator line
    (
        "첫 부분\n---\n둘째 부분",
        "첫 부분\n\n둘째 부분"
    ),
    # Case 7: Complex example with headers and emphasis
    (
        "### 개요\n**Kubernetes**는 container orchestration 도구이다. *자동화*가 핵심이다.",
        "*개요*\n*Kubernetes*는 container orchestration 도구이다. _자동화_가 핵심이다."
    ),
]

print("🐻‍❄️ Slack Formatter Style Consistency Test 🐻‍❄️")
print("=" * 120)

all_pass = True
for i, (markdown_input, expected_slack) in enumerate(test_cases, 1):
    result = to_slack_format(markdown_input)
    match = result == expected_slack
    status = "✓" if match else "✗"
    
    if not match:
        all_pass = False
    
    print(f"\nTest {i}: {status}")
    print(f"Markdown Input:  {repr(markdown_input)}")
    print(f"Expected Output: {repr(expected_slack)}")
    print(f"Actual Output:   {repr(result)}")
    
    if not match:
        print("⚠️  MISMATCH - Style not preserved!")

print("\n" + "=" * 120)
if all_pass:
    print("✓ All tests passed! Styles are consistent between Markdown and Slack.")
else:
    print("✗ Some tests failed. Style conversions need review.")
