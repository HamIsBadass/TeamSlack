"""
Jira bot: convert action items into Jira issue drafts.

Generates Jira issue fields (summary, description, priority, assignee, labels)
from action items, but does NOT create actual issues.
(Actual creation happens after user approval in a later phase.)

Uses LLM-assisted inference for priority, labels, and assignee hints.
"""

import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


def action_items_to_drafts(action_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Convert action items into Jira draft schema.
    
    Args:
        action_items: List from parse_transcript()["action_items"]
                     Each item: {
                         "task": "Implement login",
                         "owner": "alice",
                         "due_date": "2026-04-15",
                         "priority": "high"  # optional
                     }
    
    Returns:
        List of draft Jira issues:
        [
            {
                "summary": "Implement login",
                "description": "Create user authentication endpoint
                    
Acceptance Criteria:
- Support email/password login
- Return JWT token
- Handle invalid credentials gracefully",
                "priority": "High",  # Inferred from context
                "assignee_hint": "alice",  # Best guess, may be wrong
                "due_date": "2026-04-15",
                "labels": ["backend", "auth"],
                "issue_type": "Task"  # or "Story", "Bug", etc.
            },
            ...
        ]
    """
    logger.info(f"Converting {len(action_items)} action items to Jira drafts")
    
    drafts = []
    
    # TODO: For each action_item:
    #   1. Use LLM to generate detailed description with acceptance criteria
    #   2. Infer priority from context (urgency, owner, due_date)
    #   3. Suggest labels based on task type and owner
    #   4. Suggest assignee (might be different from owner hint)
    #   5. Determine issue_type (Task, Story, Bug, etc.)
    
    return drafts


def validate_draft(draft: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate single Jira draft against schema.
    
    Args:
        draft: Single draft from action_items_to_drafts()
    
    Returns:
        {
            "is_valid": bool,
            "missing_fields": ["priority", "assignee_hint"],  # Required fields not present
            "warnings": [
                "Assignee 'alice' not found in Jira",
                "Label 'unknown_label' not in project"
            ]  # Non-blocking issues
        }
    """
    logger.info(f"Validating draft: {draft.get('summary', 'unknown')}")
    
    required_fields = ["summary", "description", "priority", "issue_type"]
    missing = [f for f in required_fields if not draft.get(f)]
    
    warnings = []
    
    # TODO: Check if summary is clear and actionable (min 10 chars, max 255)
    # TODO: Check if description has acceptance criteria (look for "Acceptance" keyword)
    # TODO: Check if priority is valid (High, Medium, Low)
    # TODO: Check if assignee_hint exists in Jira workspace
    # TODO: Check if labels are valid in project configuration
    # TODO: Check if issue_type exists in project workflow
    
    return {
        "is_valid": len(missing) == 0 and len(warnings) == 0,
        "missing_fields": missing,
        "warnings": warnings
    }


def batch_validate_drafts(drafts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Validate multiple drafts.
    
    Args:
        drafts: List of drafts from action_items_to_drafts()
    
    Returns:
        {
            "all_valid": bool,
            "total": 5,
            "valid_count": 4,
            "invalid_count": 1,
            "results": [
                {
                    "index": 0,
                    "summary": "Implement login",
                    "is_valid": True,
                    "errors": []
                },
                {
                    "index": 1,
                    "summary": "...",
                    "is_valid": False,
                    "errors": ["missing: description"]
                },
                ...
            ]
        }
    """
    logger.info(f"Batch validating {len(drafts)} drafts")
    
    results = []
    for idx, draft in enumerate(drafts):
        validation = validate_draft(draft)
        results.append({
            "index": idx,
            "summary": draft.get("summary", ""),
            "is_valid": validation["is_valid"],
            "errors": validation["missing_fields"] + validation["warnings"]
        })
    
    all_valid = all(r["is_valid"] for r in results)
    valid_count = sum(1 for r in results if r["is_valid"])
    
    return {
        "all_valid": all_valid,
        "total": len(drafts),
        "valid_count": valid_count,
        "invalid_count": len(drafts) - valid_count,
        "results": results
    }


def suggest_assignee(task: str, owner_hint: str) -> Dict[str, Any]:
    """
    Suggest best match for task assignee.
    
    Uses LLM to understand task type and suggests appropriate assignee,
    starting with owner_hint if available.
    
    Args:
        task: Task description
        owner_hint: Suggested owner from meeting
    
    Returns:
        {
            "suggested_user_id": "U12345678",
            "confidence": 0.9,
            "alternatives": [
                {"user_id": "U87654321", "confidence": 0.7}
            ]
        }
    """
    logger.info(f"Suggesting assignee for task: {task[:50]}...")
    
    # TODO: Look up owner_hint in Jira/Slack directory
    # TODO: Use LLM to infer task type (backend, frontend, design, etc.)
    # TODO: Find matching assignees with that expertise
    # TODO: Return ranked list
    
    return {
        "suggested_user_id": owner_hint,
        "confidence": 0.5,
        "alternatives": []
    }


# Stub: complete implementation in next phase
logger.info("Jira bot module loaded")
