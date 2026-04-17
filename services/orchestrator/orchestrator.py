"""
Main orchestrator service.

Coordinates request lifecycle:
RECEIVED → PARSING → MEETING_DONE → JIRA_DRAFTED → REVIEW_DONE → WAITING_APPROVAL → APPROVED → DONE
"""

import logging
from uuid import uuid4
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from threading import RLock
from copy import deepcopy

logger = logging.getLogger(__name__)


class Orchestrator:
    """Main request orchestrator."""

    def __init__(self):
        """Initialize orchestrator with DB and queue connections."""
        logger.info("Initializing Orchestrator")
        self._lock = RLock()
        self._requests: Dict[str, Dict[str, Any]] = {}
        
        # PoC stage: in-memory storage for rapid iteration.
        # Next stage: switch to PostgreSQL + Redis + Celery-backed storage.

    def receive_request(
        self,
        user_id: str,
        tenant_id: str,
        raw_text: str
    ) -> Dict[str, Any]:
        """
        Receive new request from user (usually via DM).
        
        Creates a new row in requests table with status=RECEIVED,
        generates request_id and trace_id.
        
        Args:
            user_id: Slack user ID
            tenant_id: Team/organization ID
            raw_text: Raw request text or request_type identifier
        
        Returns:
            {
                "request_id": "550e8400-e29b-41d4-a716-446655440000",
                "trace_id": "660f9501-f30c-52e5-b827-556765655111",
                "status": "RECEIVED",
                "created_at": "2026-04-09T10:30:45.123Z"
            }
        """
        logger.info(f"Receive request from {user_id}")
        
        request_id = uuid4()
        trace_id = uuid4()
        created_at = datetime.utcnow()
        expires_at = created_at + timedelta(days=1)

        with self._lock:
            request_key = str(request_id)
            self._requests[request_key] = {
                "request_id": request_key,
                "trace_id": str(trace_id),
                "tenant_id": tenant_id,
                "user_id": user_id,
                "raw_text": raw_text,
                "status": "RECEIVED",
                "current_step": "PARSING",
                "created_at": created_at.isoformat(),
                "updated_at": created_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "steps": [
                    {
                        "step_name": "PARSING",
                        "status": "PENDING",
                        "retry_count": 0,
                        "started_at": None,
                        "finished_at": None,
                        "error_message": None,
                    }
                ],
                "logs": [
                    {
                        "level": "INFO",
                        "message": f"Request received from {user_id}",
                        "created_at": created_at.isoformat(),
                    }
                ],
                "approvals": [],
            }
        
        return {
            "request_id": str(request_id),
            "trace_id": str(trace_id),
            "status": "RECEIVED",
            "created_at": created_at.isoformat()
        }

    def route_to_worker(self, request_id: str, step_name: str) -> bool:
        """
        Route request to appropriate worker (meeting-bot, jira-bot, review-bot).
        
        Enqueues a Celery task or similar async job based on step_name.
        
        Args:
            request_id: Request UUID
            step_name: "PARSING" | "MEETING_DONE" | "JIRA_DRAFTED" | "REVIEW_DONE"
        
        Returns:
            True if task enqueued successfully
        """
        logger.info(f"Routing request {request_id} to step {step_name}")
        
        with self._lock:
            req = self._requests.get(request_id)
            if not req:
                return False

            now = datetime.utcnow().isoformat()
            req["current_step"] = step_name
            req["updated_at"] = now
            req["logs"].append(
                {
                    "level": "INFO",
                    "message": f"Started worker step: {step_name}",
                    "created_at": now,
                }
            )

            # Mark existing step running or append if not yet present.
            for step in req["steps"]:
                if step["step_name"] == step_name:
                    step["status"] = "RUNNING"
                    step["started_at"] = now
                    break
            else:
                req["steps"].append(
                    {
                        "step_name": step_name,
                        "status": "RUNNING",
                        "retry_count": 0,
                        "started_at": now,
                        "finished_at": None,
                        "error_message": None,
                    }
                )

            return True

    def update_status(self, request_id: str, new_status: str) -> bool:
        """
        Update request status in DB and post update to Slack thread.
        
        Also manages state transitions and triggers next steps.
        
        Args:
            request_id: Request UUID
            new_status: New status enum value (e.g., "PARSING", "MEETING_DONE")
        
        Returns:
            True if successful
        """
        logger.info(f"Update status for {request_id} to {new_status}")
        
        with self._lock:
            req = self._requests.get(request_id)
            if not req:
                return False

            now = datetime.utcnow().isoformat()
            req["status"] = new_status
            req["updated_at"] = now
            req["logs"].append(
                {
                    "level": "INFO",
                    "message": f"Status changed to {new_status}",
                    "created_at": now,
                }
            )

            # Keep current_step roughly aligned with status progression.
            status_to_step = {
                "RECEIVED": "PARSING",
                "PARSING": "PARSING",
                "MEETING_DONE": "JIRA_DRAFTED",
                "JIRA_DRAFTED": "REVIEW_DONE",
                "REVIEW_DONE": "WAITING_APPROVAL",
                "WAITING_APPROVAL": "WAITING_APPROVAL",
                "APPROVED": "DONE",
                "DONE": "DONE",
                "FAILED": "FAILED",
                "CANCELED": "CANCELED",
            }
            req["current_step"] = status_to_step.get(new_status, req.get("current_step", "PARSING"))

            return True

    def handle_approval(
        self,
        request_id: str,
        action: str,
        approved_by: str
    ) -> bool:
        """
        Handle user approval/rejection/cancel action.
        
        Updates approval record and transitions state.
        
        Args:
            request_id: Request UUID
            action: "APPROVED" | "REJECTED" | "CANCELED"
            approved_by: Slack user ID of approver
        
        Returns:
            True if successful
        """
        logger.info(f"Approval action: {action} by {approved_by}")
        
        with self._lock:
            req = self._requests.get(request_id)
            if not req:
                return False

            normalized = action.upper()
            now = datetime.utcnow().isoformat()

            req["approvals"].append(
                {
                    "action": normalized,
                    "approved_by": approved_by,
                    "approved_at": now,
                }
            )

            if normalized == "APPROVED":
                req["status"] = "DONE"
                req["current_step"] = "DONE"
            elif normalized in ("REJECTED", "REQUEST_REVISION"):
                req["status"] = "PARSING"
                req["current_step"] = "PARSING"
            elif normalized == "CANCELED":
                req["status"] = "CANCELED"
                req["current_step"] = "CANCELED"
            else:
                return False

            req["updated_at"] = now
            req["logs"].append(
                {
                    "level": "APPROVAL",
                    "message": f"Approval action={normalized} by {approved_by}",
                    "created_at": now,
                }
            )
            return True

    def handle_failure(
        self,
        request_id: str,
        step_name: str,
        error: str
    ) -> bool:
        """
        Handle failure in a step.
        
        Decides: retry, escalate to manual intervention, or terminal failure.
        
        Args:
            request_id: Request UUID
            step_name: Which step failed
            error: Error message
        
        Returns:
            True if handled (retry or escalation succeeded)
        """
        logger.info(f"Handle failure: {request_id}/{step_name}: {error}")
        
        with self._lock:
            req = self._requests.get(request_id)
            if not req:
                return False

            now = datetime.utcnow().isoformat()
            req["status"] = "FAILED"
            req["current_step"] = step_name
            req["updated_at"] = now
            req["logs"].append(
                {
                    "level": "ERROR",
                    "message": f"Failure on {step_name}: {error}",
                    "created_at": now,
                }
            )

            for step in req["steps"]:
                if step["step_name"] == step_name:
                    step["status"] = "FAILED"
                    step["error_message"] = error
                    step["finished_at"] = now
                    break

            return True

    def check_timeout(self, request_id: str) -> Optional[str]:
        """
        Check if request has timed out and handle accordingly.
        
        Called periodically (e.g., every minute by a scheduled task).
        
        Args:
            request_id: Request UUID
        
        Returns:
            New status if timeout occurred, None otherwise
        """
        logger.info(f"Checking timeout for {request_id}")
        
        with self._lock:
            req = self._requests.get(request_id)
            if not req:
                return None

            expires_at = datetime.fromisoformat(req["expires_at"])
            if datetime.utcnow() <= expires_at:
                return None

            req["status"] = "CANCELED"
            req["current_step"] = "CANCELED"
            now = datetime.utcnow().isoformat()
            req["updated_at"] = now
            req["logs"].append(
                {
                    "level": "WARN",
                    "message": "Timeout: request expired",
                    "created_at": now,
                }
            )
            return "CANCELED"

    def get_request_status(self, request_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve full request status including steps and logs.
        
        Args:
            request_id: Request UUID
        
        Returns:
            {
                "request_id": "...",
                "user_id": "...",
                "status": "PARSING",
                "steps": [...],
                "logs": [...]
            }
            or None if request not found
        """
        logger.info(f"Querying status for {request_id}")
        
        with self._lock:
            req = self._requests.get(request_id)
            if not req:
                return None
            return deepcopy(req)

    def list_user_requests(self, user_id: str, limit: int = 20) -> Dict[str, Any]:
        """Return recent requests for a user."""
        with self._lock:
            rows = [r for r in self._requests.values() if r.get("user_id") == user_id]
            rows.sort(key=lambda x: x.get("created_at", ""), reverse=True)
            sliced = rows[: max(1, limit)]
            return {
                "user_id": user_id,
                "total": len(rows),
                "requests": deepcopy(sliced),
            }


# ============ Background tasks ============

def check_all_timeouts():
    """
    Periodic task to check and handle timeouts for all pending requests.
    
    Should be called every 60 seconds (via Celery beat or similar).
    """
    logger.info("Running timeout check")
    
    # TODO: Query all requests with status = WAITING_APPROVAL and expires_at < now
    # TODO: For each expired request, call handle_timeout()
    
    pass


# Stub: complete implementation in next phase
logger.info("Orchestrator module loaded")
