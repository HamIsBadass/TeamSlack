"""
User Profile Manager: handle profile loading, persona formatting, etc.

Manages user customization settings and provides interfaces for LLM routing.
"""

import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class UserProfile:
    """User profile with personalization settings."""

    def __init__(self, user_id: str):
        """
        Load user profile from DB.
        
        Args:
            user_id: Slack user ID
        """
        logger.info(f"Loading profile for {user_id}")
        self.user_id = user_id
        self.loaded = False
        self.profile_data = {}
        
        # TODO: Query user_profiles table for user_id
        # TODO: If not found, create default profile
        # TODO: Cache in memory with TTL=1h (Redis)

    def get_persona_style(self) -> str:
        """
        Return user's persona style.
        
        Returns:
            "pm" | "developer" | "designer" | "concise"
        """
        # TODO: Return from profile_data or DB
        return "concise"

    def get_output_format(self) -> str:
        """
        Return user's preferred output format.
        
        Returns:
            "markdown" | "bullet_list" | "json"
        """
        # TODO: Return from profile_data or DB
        return "markdown"

    def get_key_mode(self) -> str:
        """
        Return user's key mode.
        
        Returns:
            "shared" | "byok"
        """
        # TODO: Return from profile_data or DB
        return "shared"

    def get_secret_ref(self) -> Optional[str]:
        """
        Return encrypted API key reference (for BYOK).
        
        Returns:
            KMS path if byok, None otherwise
        """
        # TODO: Return from profile_data if key_mode == "byok"
        return None

    def get_job_role(self) -> Optional[str]:
        """
        Return user's job role.
        
        Returns:
            "PM" | "Engineer" | "Designer" | None
        """
        # TODO: Return from profile_data or DB
        return None

    def get_display_name(self) -> str:
        """
        Return user's display name.
        
        Returns:
            Display name string
        """
        # TODO: Return from profile_data or fall back to Slack user name
        return f"User {self.user_id}"

    def get_tenor_id(self) -> Optional[str]:
        """
        Return user's tenant ID.
        
        Returns:
            Tenant ID or "DEFAULT"
        """
        # TODO: Return from profile_data
        return "DEFAULT"

    def update_key_mode(self, key_mode: str, secret_ref: Optional[str] = None) -> bool:
        """
        Update user's key mode (shared → byok or vice versa).
        
        Args:
            key_mode: "shared" or "byok"
            secret_ref: KMS reference path (required if key_mode == "byok")
        
        Returns:
            True if successful
        """
        logger.info(f"Updating key_mode for {self.user_id} to {key_mode}")
        
        # TODO: Validate key_mode
        # TODO: If byok, validate secret_ref (should be encrypted and retrievable)
        # TODO: Update user_profiles table
        # TODO: Invalidate cache
        
        return True

    def update_persona_style(self, style: str) -> bool:
        """
        Update user's persona style.
        
        Args:
            style: "pm" | "developer" | "designer" | "concise"
        
        Returns:
            True if successful
        """
        logger.info(f"Updating persona_style for {self.user_id} to {style}")
        
        # TODO: Validate style against enum
        # TODO: Update user_profiles table
        # TODO: Invalidate cache
        
        return True

    def update_output_format(self, format_type: str) -> bool:
        """
        Update user's output format.
        
        Args:
            format_type: "markdown" | "bullet_list" | "json"
        
        Returns:
            True if successful
        """
        logger.info(f"Updating output_format for {self.user_id} to {format_type}")
        
        # TODO: Validate format
        # TODO: Update user_profiles table
        # TODO: Invalidate cache
        
        return True

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert profile to dict for API responses.
        
        Returns:
            Profile dict
        """
        return {
            "user_id": self.user_id,
            "display_name": self.get_display_name(),
            "persona_style": self.get_persona_style(),
            "output_format": self.get_output_format(),
            "job_role": self.get_job_role(),
            "key_mode": self.get_key_mode(),
            "tenant_id": self.get_tenor_id()
        }


def get_or_create_profile(user_id: str) -> UserProfile:
    """
    Get existing user profile or create default.
    
    Args:
        user_id: Slack user ID
    
    Returns:
        UserProfile instance
    """
    logger.info(f"Getting or creating profile for {user_id}")
    
    profile = UserProfile(user_id)
    
    # TODO: Check if exists in DB
    # TODO: If not, create default profile with:
    #   - persona_style = "concise"
    #   - output_format = "markdown"
    #   - key_mode = "shared"
    #   - job_role = None
    
    return profile


def list_profiles(tenant_id: str = "DEFAULT", limit: int = 100) -> list:
    """
    List all user profiles in a tenant.
    
    Args:
        tenant_id: Tenant ID
        limit: Max number of results
    
    Returns:
        List of UserProfile instances
    """
    logger.info(f"Listing profiles for tenant {tenant_id}")
    
    # TODO: Query user_profiles where tenant_id = ...
    # TODO: Return list of UserProfile instances
    
    return []


# Stub: complete implementation in next phase
logger.info("Profile manager module loaded")
