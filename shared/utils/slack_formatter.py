"""Slack message formatting utilities.

Converts markdown-style formatting to Slack's native format.
"""

import re


def to_slack_format(text: str) -> str:
    """Convert markdown formatting to Slack format.
    
    Conversions:
    - **bold** → *bold* (Slack bold)
    - __bold__ → *bold* (Slack bold)
    - *italic* → _italic_ (Slack italic)
    - ### heading → *heading* (Slack bold)
    - --- separator → removed
    
    Uses markers to prevent double-conversion keeping styles intact.
    
    Args:
        text: Text with markdown formatting
        
    Returns:
        Text formatted for Slack with styles preserved
    """
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
