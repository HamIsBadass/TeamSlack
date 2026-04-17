# Bug Fix Summary: Direct Send Message Parser

## Problem Identified
When users input a direct send request in the format: **"message channel-name verb"**
(e.g., "아 시원해서 너무 좋다햄 콘텐츠-기획제작 발송")

The bot was showing a success message but the message never appeared in the target channel.

## Root Cause
The fallback parser in `_extract_direct_send_request()` function (around line 1299) was using this logic:

```python
parts = body.split(maxsplit=1)
if len(parts) == 2:
    channel_ref, remainder = parts[0].strip(), parts[1].strip()
```

This assumes the format: **"channel message"** (channel first, then message)

With input "아 시원해서 너무 좋다햄 콘텐츠-기획제작", this incorrectly parsed as:
- `channel_ref = "아"` (WRONG - this is the message start!)
- `remainder = "시원해서 너무 좋다햄 콘텐츠-기획제작"` (WRONG - mixed message and channel!)

The bot then tried to send to a channel named "아" (which doesn't exist or is the wrong channel), but still reported success to confuse the user.

## Solution Implemented
Updated the fallback logic to detect the actual input format by looking for channels that **contain hyphens or underscores** (typical Slack channel naming conventions):

```python
words = body.split()
if len(words) >= 2:
    # Check if the last word looks like a channel name (contains hyphen/underscore)
    if "-" in words[-1] or "_" in words[-1]:
        # Last word looks like channel, treat it as channel
        channel_ref = words[-1]
        remainder = " ".join(words[:-1])
    else:
        # Fall back to original assumption for backward compatibility
        parts = body.split(maxsplit=1)
        if len(parts) == 2:
            channel_ref, remainder = parts[0].strip(), parts[1].strip()
```

Now with input "아 시원해서 너무 좋다햄 콘텐츠-기획제작":
- Detects "콘텐츠-기획제작" as the channel (contains hyphen)
- Extracts: `channel_ref = "콘텐츠-기획제작"` ✓
- Message text: `"아 시원해서 너무 좋다햄"` ✓

## Test Cases
The fix correctly handles:
1. ✓ "아 시원해서 너무 좋다햄 콘텐츠-기획제작 발송" → channel="콘텐츠-기획제작", message="아 시원해서 너무 좋다햄"
2. ✓ "메시지텍스트 channel_name 전송" → channel="channel_name", message="메시지텍스트"  
3. ✓ "콘텐츠-기획제작 메시지 보내" → channel="콘텐츠-기획제작", message="메시지"
4. ✓ Maintains backward compatibility with explicit markers: `[channel]`, `#channel`, `채널 suffix`

## Files Modified
- `apps/personal-bot/socket_mode_runner.py` - Lines 1295-1317

## Backward Compatibility
- Explicit channel markers (`[channel]`, `#channel`) still work as before
- Fallback order: explicit markers → hyphen detection → original "channel message" logic
- Maintains support for both input orders when channels are explicitly marked

## How to Test
1. Start the bot: `python apps/personal-bot/socket_mode_runner.py`
2. Send DM: "아 시원해서 너무 좋다햄 콘텐츠-기획제작 발송"
3. Click "발송" button in approval dialog
4. Verify: Message now appears in the correct #콘텐츠-기획제작 channel ✓
