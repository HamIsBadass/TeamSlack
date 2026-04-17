#!/usr/bin/env python3
"""Test the fixed direct send request parser."""

import re
from typing import Optional, Tuple


def _normalize_user_reference(user_ref: str) -> str:
    cleaned = (user_ref or "").strip()
    cleaned = re.sub(r"^@+", "", cleaned).strip()
    cleaned = re.sub(r"\s*님\s*$", "", cleaned).strip()
    cleaned = re.sub(r"(에게|한테|으로|로|에)$", "", cleaned).strip()
    return cleaned


def _looks_like_user_reference(text: str) -> bool:
    raw = (text or "").strip()
    return raw.startswith("@") and len(_normalize_user_reference(raw)) >= 2


def _extract_direct_send_request(text: str) -> Tuple[Optional[str], Optional[str], bool]:
    normalized = (text or "").strip()
    if not normalized:
        return None, None, False

    trigger_verbs = ["보내주세요", "전송해주세요", "발송해주세요", "보내줘", "전송해줘", "발송해줘", "보내", "전송", "발송"]
    trigger_index = -1
    trigger_verb = ""
    for verb in trigger_verbs:
        idx = normalized.find(verb)
        if idx != -1 and (trigger_index == -1 or idx < trigger_index or (idx == trigger_index and len(verb) > len(trigger_verb))):
            trigger_index = idx
            trigger_verb = verb

    if trigger_index == -1:
        return None, None, False

    body = normalized[:trigger_index].strip().rstrip(".?!, ")
    if not body:
        return None, None, True

    channel_ref = ""
    remainder = body

    # 2) [채널] notation
    if not channel_ref:
        bracket = re.search(r"\[([^\]]+)\]", remainder)
        if bracket:
            channel_ref = (bracket.group(1) or "").strip()
            remainder = re.sub(r"\[[^\]]+\]\s*(에게|한테|에|으로|로)?", " ", remainder, count=1)

    # 3) #channel notation
    if not channel_ref:
        hash_channel = re.search(r"#([\w\-가-힣]+)", remainder)
        if hash_channel:
            channel_ref = (hash_channel.group(1) or "").strip()
            remainder = re.sub(r"#[\w\-가-힣]+\s*(에게|한테|에|으로|로)?", " ", remainder, count=1)

    # 4) plain "채널" suffix notation: 콘텐츠-기획제작 채널
    if not channel_ref:
        named_channel = re.search(r"([\w\-가-힣]+)\s*채널", remainder)
        if named_channel:
            channel_ref = (named_channel.group(1) or "").strip()
            remainder = re.sub(r"[\w\-가-힣]+\s*채널\s*(에게|한테|에|으로|로)?", " ", remainder, count=1)

    # Fallback to legacy pattern if channel not found.
    if not channel_ref:
        channel_message_match = re.match(r"^(?P<channel>.+?)(?:에게|한테|에|으로|로)\s*(?P<message>.*)$", body)
        if channel_message_match:
            channel_ref = (channel_message_match.group("channel") or "").strip()
            remainder = (channel_message_match.group("message") or "").strip()
        else:
            # Try to identify channel in "message channel" format (most common user input order)
            # Channel names typically have hyphens or underscores; otherwise look at position
            words = body.split()
            if len(words) >= 2:
                # Check if the last word/phrase looks like a channel name (contains hyphen or underscore)
                last_phrase = " ".join(words[-2:]) if len(words) >= 2 else words[-1]
                if "-" in words[-1] or "_" in words[-1]:
                    # Last word looks like channel (has hyphen/underscore), treat it as channel
                    channel_ref = words[-1]
                    remainder = " ".join(words[:-1])
                else:
                    # Fall back to original "channel message" assumption
                    parts = body.split(maxsplit=1)
                    if len(parts) == 2:
                        channel_ref, remainder = parts[0].strip(), parts[1].strip()
                    else:
                        channel_ref = body.strip()
            else:
                channel_ref = body.strip()

    # Build message text from quoted content first, then remainder fallback.
    message_text = remainder
    message_text = re.sub(r"\s+", " ", message_text).strip()
    message_text = re.sub(r"^(메시지|문구|내용)\s*(를|을)?\s*", "", message_text).strip()
    message_text = message_text.strip("\"'""` ")

    return channel_ref or None, message_text or None, True


# Test cases
test_cases = [
    ("아 시원해서 너무 좋다햄 콘텐츠-기획제작 발송", ("콘텐츠-기획제작", "아 시원해서 너무 좋다햄", True)),
    ("[일반]안녕하세요 발송", ("[일반]", None, True)),  # Should fail parsing
    ("#채널 메시지입니다 보내", ("채널", "메시지입니다", True)),
    ("메시지텍스트 channel_name 전송", ("channel_name", "메시지텍스트", True)),
    ("콘텐츠-기획제작 메시지 보내", ("콘텐츠-기획제작", "메시지", True)),
]

print("Testing fixed _extract_direct_send_request():\n")
for i, (input_text, expected) in enumerate(test_cases, 1):
    result = _extract_direct_send_request(input_text)
    channel, message, success = result
    exp_channel, exp_message, exp_success = expected
    
    status = "✓" if (channel == exp_channel and message == exp_message) else "✗"
    print(f"{status} Test {i}: {input_text}")
    print(f"   Expected: channel={exp_channel!r}, message={exp_message!r}")
    print(f"   Got:      channel={channel!r}, message={message!r}")
    if channel != exp_channel or message != exp_message:
        print(f"   MISMATCH!")
    print()
