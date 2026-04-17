"""
Slack bot FastAPI application entry point.

Main server that receives Slack events, routes them to orchestrator,
and serves internal status APIs.
"""

import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from urllib.parse import parse_qs

# Ensure local module imports work for app-dir and direct module loading.
BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from slack_handler import SlackHandler, parse_dm_event, parse_button_action

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="TeamSlack Bot",
    version="0.1.0",
    description="Slack-based request orchestrator with meeting, Jira, and review bots"
)

slack_handler = SlackHandler()
orchestrator = slack_handler.orchestrator


# ============ Routes ============

@app.post("/slack/events")
async def slack_events(request: Request):
    """
    Receives Slack Events API events (messages, app mentions, etc.).
    
    Slack sends events to this endpoint after app subscription.
    Handles URL verification challenge during app setup.
    """
    logger.info("Received Slack event")
    body = await request.json()
    
    # Challenge handshake for Slack app verification
    if body.get("type") == "url_verification":
        logger.info("Slack URL verification challenge")
        return JSONResponse({"challenge": body.get("challenge")})
    
    event_type = body.get("event", {}).get("type")
    logger.info(f"Event received: {event_type}")

    if event_type == "message" and body.get("event", {}).get("channel_type") == "im":
        user_id, text, _, _ = parse_dm_event(body)
        result = slack_handler.handle_dm_message(user_id=user_id, text=text)
        return JSONResponse(result)

    if event_type == "app_mention":
        event = body.get("event", {})
        result = slack_handler.handle_app_mention(
            user_id=event.get("user", ""),
            text=event.get("text", ""),
        )
        return JSONResponse(result)

    return JSONResponse({"ok": True})


@app.post("/slack/actions")
async def slack_actions(request: Request):
    """
    Receives Slack interactive components (buttons, modals, shortcuts).
    
    Handles approval/rejection/cancel button clicks and modal submissions.
    """
    logger.info("Received Slack interactive action")

    content_type = request.headers.get("content-type", "")
    body = {}
    if "application/json" in content_type:
        body = await request.json()
    else:
        form = await request.body()
        parsed = parse_qs(form.decode("utf-8"))
        if "payload" in parsed and parsed["payload"]:
            import json

            body = json.loads(parsed["payload"][0])

    user_id, action_type, payload, _ = parse_button_action(body)
    result = slack_handler.handle_button_action(action_type=action_type or "", user_id=user_id or "", payload=payload)
    return JSONResponse(result)


@app.get("/api/requests/{request_id}")
async def get_request_status(request_id: str):
    """
    Retrieves current status of a request.
    
    Query parameters (optional):
    - include_steps: bool (include request_steps table rows)
    - include_logs: bool (include audit_logs)
    
    Returns:
        {
            "request_id": "...",
            "status": "PARSING",
            "user_id": "U...",
            "trace_id": "...",
            "created_at": "2026-04-09T10:30:45Z",
            "steps": [...],
            "logs": [...]
        }
    """
    logger.info(f"Querying status for request_id={request_id}")
    
    data = orchestrator.get_request_status(request_id)
    if not data:
        return JSONResponse(status_code=404, content={"error": "request_not_found", "request_id": request_id})
    return JSONResponse(data)


@app.get("/api/users/{user_id}/requests")
async def list_user_requests(user_id: str, limit: int = 20):
    """List requests for a user from in-memory orchestrator store."""
    result = orchestrator.list_user_requests(user_id=user_id, limit=limit)
    return JSONResponse(result)


@app.get("/api/health")
async def health_check():
    """
    Server health check endpoint.
    
    Used by load balancers and monitoring systems to verify service availability.
    """
    logger.info("Health check")
    
    # TODO: Check DB connection, Redis connection, Slack connectivity
    
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "0.1.0"
    }


# ============ Startup / Shutdown ============

@app.on_event("startup")
async def startup():
    """Initialize app on startup."""
    logger.info("FastAPI app starting...")
    
    # TODO: Initialize DB connection pool
    # TODO: Initialize Slack Bolt app
    # TODO: Initialize Redis connection
    # TODO: Initialize Celery worker connection


@app.on_event("shutdown")
async def shutdown():
    """Clean up resources on shutdown."""
    logger.info("FastAPI app shutting down...")
    
    # TODO: Close DB pool
    # TODO: Close Redis connection
    # TODO: Cleanup async tasks


# ============ Error handlers ============

@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions."""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"}
    )


# ============ Entry point ============

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    logger.info(f"Starting server on port {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
