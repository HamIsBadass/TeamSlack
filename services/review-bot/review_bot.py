"""
Review bot: review Jira drafts for quality, completeness, and duplicates.

Checks:
- Completeness: required fields, clarity, acceptance criteria
- Quality: is the issue actionable and well-defined?
- Duplicates: similarity to existing issues
- Process: does the issue follow team conventions?

Uses LLM for semantic analysis and duplicate detection.
"""

import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


def review_drafts(drafts: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Review drafts for quality and compliance.
    
    Args:
        drafts: List from action_items_to_drafts()
    
    Returns:
        {
            "passed": [
                {
                    "draft": {...},
                    "confidence": 0.95,
                    "notes": "Ready to submit. All fields complete and clear."
                }
            ],
            "needs_revision": [
                {
                    "draft": {...},
                    "reason": "Description too vague",
                    "suggestion": "Add acceptance criteria with specific endpoints"
                }
            ],
            "rejected": [
                {
                    "draft": {...},
                    "reason": "Duplicate of existing issue TS-123",
                    "existing_issue_key": "TS-123"
                }
            ]
        }
    """
    logger.info(f"Reviewing {len(drafts)} drafts")
    
    passed = []
    needs_revision = []
    rejected = []
    
    # TODO: For each draft:
    #   1. Check summary clarity (min 10 chars, max 100, actionable)
    #   2. Check description has acceptance criteria or steps
    #   3. Check priority level is justified by task urgency
    #   4. Check if priority/assignee seems right for owner's team
    #   5. Check for duplicates using semantic similarity
    #   6. Check labels are valid and not too many (max 5)
    
    return {
        "passed": passed,
        "needs_revision": needs_revision,
        "rejected": rejected
    }


def check_duplicates(
    drafts: List[Dict[str, Any]],
    existing_issues: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Check if drafts are similar to existing Jira issues (potential duplicates).
    
    Args:
        drafts: List from action_items_to_drafts()
        existing_issues: Recent issues from Jira project
                        [{
                            "key": "TS-123",
                            "summary": "Implement login",
                            "description": "...",
                            "status": "In Progress"
                        }]
    
    Returns:
        List of potential duplicates (sorted by similarity):
        [
            {
                "draft_idx": 0,
                "existing_issue_key": "TS-123",
                "similarity_score": 0.92,
                "reason": "Same summary and description",
                "existing_status": "In Progress"
            },
            ...
        ]
    """
    logger.info(f"Checking {len(drafts)} drafts against {len(existing_issues)} existing issues")
    
    duplicates = []
    
    # TODO: For each draft:
    #   1. Compare draft.summary with existing_issue.summary
    #   2. Use LLM or semantic similarity (embedding) to compute similarity
    #   3. If similarity_score > 0.75, add to duplicates list
    #   4. Include existing_status to assist decision-making
    
    return sorted(duplicates, key=lambda x: x["similarity_score"], reverse=True)


def assess_completeness(draft: Dict[str, Any]) -> Dict[str, Any]:
    """
    Assess how complete a draft is.
    
    Args:
        draft: Single draft
    
    Returns:
        {
            "completeness_score": 0.85,  # 0-1, percentage of required fields filled
            "missing_sections": [
                {"field": "acceptance_criteria", "impact": "high"}
            ],
            "quality_score": 0.80
        }
    """
    logger.info(f"Assessing completeness for: {draft.get('summary', '')}")
    
    score = 0.0
    missing = []
    
    # Check each key field
    if draft.get("summary"):
        score += 0.2
    else:
        missing.append({"field": "summary", "impact": "critical"})
    
    if draft.get("description"):
        score += 0.2
    else:
        missing.append({"field": "description", "impact": "high"})
    
    if draft.get("priority"):
        score += 0.1
    else:
        missing.append({"field": "priority", "impact": "medium"})
    
    if draft.get("assignee_hint"):
        score += 0.1
    else:
        missing.append({"field": "assignee_hint", "impact": "medium"})
    
    if draft.get("labels"):
        score += 0.1
    else:
        missing.append({"field": "labels", "impact": "low"})
    
    if draft.get("due_date"):
        score += 0.1
    else:
        missing.append({"field": "due_date", "impact": "low"})
    
    # Bonus: check for acceptance criteria in description
    if "Acceptance" in draft.get("description", "") or "acceptance" in draft.get("description", "").lower():
        score += 0.1
    
    return {
        "completeness_score": min(score, 1.0),
        "missing_sections": missing,
        "quality_score": score * 0.85  # Slightly discounted estimate
    }


def generate_review_summary(review_result: Dict[str, Any]) -> str:
    """
    Generate human-readable review summary.
    
    Args:
        review_result: Output from review_drafts()
    
    Returns:
        Markdown formatted review summary
    """
    logger.info("Generating review summary")
    
    summary = "## 검수 결과\n\n"
    
    passed = review_result.get("passed", [])
    needs_revision = review_result.get("needs_revision", [])
    rejected = review_result.get("rejected", [])
    
    summary += f"✅ **통과**: {len(passed)}개\n"
    summary += f"🔄 **수정 필요**: {len(needs_revision)}개\n"
    summary += f"❌ **거절**: {len(rejected)}개\n\n"
    
    if needs_revision:
        summary += "### 수정이 필요한 항목\n"
        for item in needs_revision[:5]:
            summary += f"- {item.get('reason', '')}\n"
    
    if rejected:
        summary += "\n### 거절된 항목\n"
        for item in rejected[:5]:
            summary += f"- {item.get('reason', '')}\n"
    
    return summary


# Stub: complete implementation in next phase
logger.info("Review bot module loaded")
