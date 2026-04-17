"""
Model Gateway: Unified LLM call interface.

Routes all LLM calls through a single gateway that:
1. Checks user's key_mode (shared vs BYOK)
2. Selects appropriate API key
3. Logs usage
4. Handles retries and errors

This ensures all LLM interactions are audited and cost-tracking compatible.
"""

import logging
import os
from enum import Enum
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class SupportedProvider(str, Enum):
    """Supported LLM providers."""
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OPENAI = "openai"


class ModelGateway:
    """Unified LLM gateway."""

    def __init__(self):
        """Initialize gateway with configuration."""
        logger.info("Initializing ModelGateway")
        
        # TODO: Load provider configs from env
        # self.providers = {}
        # self.providers[SupportedProvider.OPENAI] = {
        #     "api_key_env": "OPENAI_API_KEY",
        #     "model": "gpt-4"
        # }

    def call(
        self,
        user_id: str,
        prompt: str,
        task_type: str,
        max_tokens: Optional[int] = None
    ) -> str:
        """
        Make an LLM call on behalf of a user.
        
        Automatically selects API key based on user's key_mode.
        - If key_mode=shared: use environment variable API key
        - If key_mode=byok: look up encrypted key from secret_ref
        
        Args:
            user_id: Slack user ID (for profile lookup)
            prompt: Prompt text to send to LLM
            task_type: "meeting_parse" | "jira_draft" | "review" | "personalization"
            max_tokens: Optional token limit
        
        Returns:
            LLM response text
        
        Raises:
            KeyError: API key not found for user
            Exception: LLM API error
        """
        logger.info(f"LLM call for {user_id}, task_type={task_type}, prompt_len={len(prompt)}")
        
        # TODO: Query user_profiles table for user_id
        # TODO: Get key_mode (shared or byok)
        # TODO: Get appropriate API key via _get_shared_key or _get_byok_key
        # TODO: Select provider based on user_id or task_type or default
        # TODO: Call LLM API (OpenAI, Anthropic, or Gemini)
        # TODO: Log usage to audit_logs via audit_logger.log_event()
        # TODO: Include tokens_used, provider, task_type for cost tracking
        # TODO: Return response
        
        return "stub LLM response"

    def _get_shared_key(self, provider: SupportedProvider) -> str:
        """
        Get shared API key for provider.
        
        Reads from environment variables:
        - OPENAI_API_KEY
        - ANTHROPIC_API_KEY
        - GEMINI_API_KEY
        
        Args:
            provider: LLM provider enum
        
        Returns:
            API key string
        
        Raises:
            KeyError: If env var not set
        """
        env_map = {
            SupportedProvider.OPENAI: "OPENAI_API_KEY",
            SupportedProvider.ANTHROPIC: "ANTHROPIC_API_KEY",
            SupportedProvider.GEMINI: "GEMINI_API_KEY"
        }
        
        env_var = env_map.get(provider)
        if not env_var:
            raise ValueError(f"Unknown provider: {provider}")
        
        key = os.getenv(env_var)
        if not key:
            raise KeyError(f"Environment variable {env_var} not set")
        
        logger.info(f"Using shared key for {provider}")
        return key

    def _get_byok_key(self, user_id: str, secret_ref: str) -> str:
        """
        Decrypt and retrieve BYOK key from secret store (KMS).
        
        Args:
            user_id: For audit
            secret_ref: Reference path from user_profiles.secret_ref
        
        Returns:
            Decrypted API key
        
        Raises:
            KeyError: If key not found in KMS
        """
        logger.info(f"Retrieving BYOK key for {user_id} ({secret_ref})")
        
        # TODO: Call KMS or secret store to decrypt secret_ref
        # Example (AWS KMS):
        #   import boto3
        #   client = boto3.client('kms')
        #   response = client.decrypt(CiphertextBlob=encrypted_key)
        #   return response['Plaintext']
        
        # TODO: Cache decrypted key briefly (Redis, TTL=1h)
        
        return "stub_byok_key"

    def _log_usage(
        self,
        user_id: str,
        provider: SupportedProvider,
        tokens_used: int,
        task_type: str,
        request_id: Optional[str] = None
    ) -> None:
        """
        Log LLM usage for cost tracking and audit.
        
        Stores in audit_logs or separate usage_logs table.
        
        Args:
            user_id: User making the request
            provider: LLM provider used
            tokens_used: Tokens consumed (input + output)
            task_type: Task category
            request_id: Associated request ID (if any)
        """
        logger.info(f"Logging usage: {user_id} / {tokens_used} tokens / {task_type} / {provider}")
        
        # TODO: Insert into usage_logs table or audit_logs with special flag
        # TODO: Calculate cost estimate based on provider pricing
        # TODO: Include timestamp, provider, task_type, user_id for billing


# ============ Helper functions ============

def estimate_cost(
    provider: SupportedProvider,
    tokens_used: int,
    task_type: str = "general"
) -> Dict[str, float]:
    """
    Estimate cost for an LLM call.
    
    Args:
        provider: LLM provider
        tokens_used: Total tokens used
        task_type: Task category (for future pricing adjustment)
    
    Returns:
        {
            "input_tokens": 500,
            "output_tokens": 200,
            "total_tokens": 700,
            "cost_usd": 0.015
        }
    """
    # Pricing as of 2026-04 (estimate)
    pricing = {
        SupportedProvider.OPENAI: {
            "input": 0.00001,  # $0.01 per 1K tokens
            "output": 0.00003
        },
        SupportedProvider.ANTHROPIC: {
            "input": 0.000008,
            "output": 0.000024
        },
        SupportedProvider.GEMINI: {
            "input": 0.00001,
            "output": 0.00003
        }
    }
    
    rate = pricing.get(provider, {"input": 0.00001, "output": 0.00003})
    
    # Assume 1/4 of tokens are output (rough estimate)
    output_tokens = tokens_used // 4
    input_tokens = tokens_used - output_tokens
    
    cost = (input_tokens * rate["input"]) + (output_tokens * rate["output"])
    
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": tokens_used,
        "cost_usd": round(cost, 6)
    }


# Stub: complete implementation in next phase
logger.info("ModelGateway module loaded")
