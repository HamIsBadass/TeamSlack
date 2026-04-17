"""
Meeting bot: summarize transcripts and extract action items.

Parses raw meeting transcripts (or text) into structured sections:
- Decisions: decisions made
- Action items: tasks with assignees
- Open questions: topics to discuss later

Uses LLM to perform intelligent parsing.
"""

import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


def parse_transcript(raw_text: str) -> Dict[str, Any]:
    """
    Parse raw meeting transcript into structured sections.
    
    Uses LLM (via ModelGateway) to extract:
    - decisions: list of decisions made
    - action_items: list of tasks (task, owner, due_date)
    - open_questions: unresolved topics
    
    Args:
        raw_text: Raw transcript text (can be from Slack, recording transcription, etc.)
    
    Returns:
        {
            "decisions": [
                {"text": "Use React for frontend", "owner": "eng.lead"},
                ...
            ],
            "action_items": [
                {
                    "task": "Implement login",
                    "owner": "alice",
                    "due_date": "2026-04-15",
                    "priority": "high"
                },
                ...
            ],
            "open_questions": [
                {"question": "Should we use GraphQL?", "raised_by": "bob"}
            ]
        }
    """
    logger.info(f"Parsing transcript ({len(raw_text)} chars)")
    
    # TODO: Call ModelGateway.call() with prompt optimized for meeting parsing
    # TODO: Parse LLM response into structured format
    # TODO: Validate output schema (all lists are non-empty lists)
    # TODO: Handle parsing failures gracefully
    
    return {
        "decisions": [],
        "action_items": [],
        "open_questions": []
    }


def format_summary(parsed: Dict[str, Any], style: str) -> str:
    """
    Format structured meeting summary for user persona.
    
    Args:
        parsed: Output from parse_transcript()
        style: "pm" | "developer" | "designer" | "concise"
    
    Returns:
        Formatted summary string (markdown)
    
    Styling guide:
    - pm: Focus on business impact, risks, milestones, decision owners
    - developer: Focus on technical tasks, dependencies, technical decisions
    - designer: Focus on UX/design decisions, user experience impacts
    - concise: Short bullet list, 5-10 items max (default)
    """
    logger.info(f"Formatting summary for style={style}")
    
    decisions = parsed.get("decisions", [])
    action_items = parsed.get("action_items", [])
    open_questions = parsed.get("open_questions", [])
    
    if style == "pm":
        # Business perspective
        summary = "📊 **Business Summary**\n\n"
        
        if decisions:
            summary += "**결정사항:**\n"
            for d in decisions[:5]:
                summary += f"- {d.get('text', '')}\n"
        
        if action_items:
            summary += "\n**주요 액션:**\n"
            for ai in action_items[:5]:
                summary += f"- {ai.get('task', '')} (@{ai.get('owner', '?')})\n"
        
        if open_questions:
            summary += "\n**위험요소/검토 필요:**\n"
            for q in open_questions[:3]:
                summary += f"- {q.get('question', '')}\n"
    
    elif style == "developer":
        # Technical perspective
        summary = "💻 **기술 요약**\n\n"
        
        if decisions:
            summary += "**기술 결정:**\n"
            for d in decisions[:5]:
                summary += f"- {d.get('text', '')}\n"
        
        if action_items:
            summary += "\n**구현 태스크:**\n"
            for ai in action_items[:5]:
                summary += f"- [ ] {ai.get('task', '')} (@{ai.get('owner', '?')}) - {ai.get('due_date', '?')}\n"
        
    elif style == "designer":
        # UX/Design perspective
        summary = "🎨 **디자인 요약**\n\n"
        
        if decisions:
            summary += "**UX 결정:**\n"
            for d in decisions[:5]:
                summary += f"- {d.get('text', '')}\n"
        
        if action_items:
            summary += "\n**디자인 태스크:**\n"
            for ai in action_items[:5]:
                summary += f"- {ai.get('task', '')} (@{ai.get('owner', '?')})\n"
    
    else:  # concise (default)
        # Minimal bullet list
        summary = "📝 **회의 요약**\n\n"
        
        items = []
        for d in decisions[:3]:
            items.append(f"✅ {d.get('text', '')}")
        for ai in action_items[:3]:
            items.append(f"📌 {ai.get('task', '')} (@{ai.get('owner', '?')})")
        for q in open_questions[:2]:
            items.append(f"❓ {q.get('question', '')}")
        
        summary += "\n".join(items)
    
    return summary


def validate_parsed_output(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate parsed transcript output.
    
    Args:
        parsed: Output from parse_transcript()
    
    Returns:
        {
            "is_valid": bool,
            "errors": []
        }
    """
    logger.info("Validating parsed output")
    
    errors = []
    
    # Check for required keys
    required_keys = ["decisions", "action_items", "open_questions"]
    for key in required_keys:
        if key not in parsed:
            errors.append(f"Missing key: {key}")
        elif not isinstance(parsed[key], list):
            errors.append(f"{key} is not a list")
    
    # Check for empty output (might indicate parsing failure)
    total_items = (
        len(parsed.get("decisions", [])) +
        len(parsed.get("action_items", [])) +
        len(parsed.get("open_questions", []))
    )
    if total_items == 0:
        errors.append("Output is completely empty (no decisions, actions, or questions)")
    
    return {
        "is_valid": len(errors) == 0,
        "errors": errors
    }


# Stub: complete implementation in next phase
logger.info("Meeting bot module loaded")
