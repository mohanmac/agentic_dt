"""
Zerodha Kite Connect authentication using secure OAuth flow.
NO password automation - user must manually log in via browser.
"""
import json
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
import os

from kiteconnect import KiteConnect

from app.core.config import settings
from app.core.utils import logger, log_event


class ZerodhaAuth:
    """Handles Zerodha authentication using OAuth redirect flow."""
    
    def __init__(self):
        self.api_key = settings.KITE_API_KEY
        self.api_secret = settings.KITE_API_SECRET
        self.redirect_url = settings.KITE_REDIRECT_URL
        self.token_file = settings.get_token_file()
        
        # Initialize KiteConnect client
        self.kite = KiteConnect(api_key=self.api_key)
        
        # Load existing token if available
        self._load_token()
    
    def generate_login_url(self) -> str:
        """
        Generate Kite Connect login URL for manual user authentication.
        
        Returns:
            Login URL that user should visit in browser
        """
        login_url = self.kite.login_url()
        
        log_event("login_url_generated", {
            "url": login_url,
            "redirect_url": self.redirect_url
        })
        
        logger.info(f"Generated login URL: {login_url}")
        logger.info("User must manually log in via browser to complete authentication")
        
        return login_url
    
    def exchange_request_token(self, request_token: str) -> Dict[str, Any]:
        """
        Exchange request_token for access_token.
        
        Args:
            request_token: Token received from OAuth callback
        
        Returns:
            Session data including access_token
        
        Raises:
            Exception if token exchange fails
        """
        try:
            # Generate session
            session_data = self.kite.generate_session(
                request_token=request_token,
                api_secret=self.api_secret
            )
            
            # Save access token
            self._save_token(session_data)
            
            log_event("token_exchange_success", {
                "user_id": session_data.get('user_id'),
                "user_name": session_data.get('user_name')
            })
            
            logger.info(f"Successfully authenticated user: {session_data.get('user_name')}")
            
            return session_data
        
        except Exception as e:
            log_event("token_exchange_failed", {
                "error": str(e)
            }, level="ERROR")
            logger.error(f"Token exchange failed: {e}", exc_info=True)
            raise
    
    def _save_token(self, session_data: Dict[str, Any]):
        """
        Save access token to file with restricted permissions.
        
        Args:
            session_data: Session data from Kite
        """
        token_data = {
            "access_token": session_data.get("access_token"),
            "user_id": session_data.get("user_id"),
            "user_name": session_data.get("user_name"),
            "user_type": session_data.get("user_type"),
            "email": session_data.get("email"),
            "login_time": str(session_data.get("login_time")) if session_data.get("login_time") else None,
            "saved_at": datetime.now().isoformat()
        }
        
        # Ensure data directory exists
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Write token file
        with open(self.token_file, 'w') as f:
            json.dump(token_data, f, indent=2)
        
        # Set restrictive permissions (owner read/write only)
        # Note: On Windows, this may not work as expected
        try:
            os.chmod(self.token_file, 0o600)
        except Exception as e:
            logger.warning(f"Could not set file permissions: {e}")
        
        # Set access token in KiteConnect instance
        self.kite.set_access_token(token_data["access_token"])
        
        logger.info(f"Access token saved to {self.token_file}")
    
    def _load_token(self) -> bool:
        """
        Load access token from file.
        
        Returns:
            True if token loaded successfully
        """
        if not self.token_file.exists():
            logger.warning("No saved access token found")
            return False
        
        try:
            with open(self.token_file, 'r') as f:
                token_data = json.load(f)
            
            access_token = token_data.get("access_token")
            if access_token:
                self.kite.set_access_token(access_token)
                logger.info(f"Loaded access token for user: {token_data.get('user_name')}")
                return True
            else:
                logger.warning("Token file exists but no access_token found")
                return False
        
        except Exception as e:
            logger.error(f"Failed to load token: {e}", exc_info=True)
            return False

    def set_manual_token(self, access_token: str, user_id: str = "MANUAL_USER", user_name: str = "Manual User"):
        """
        Manually set access token (bypassing OAuth).
        
        Args:
            access_token: The access token string
            user_id: User ID to display
            user_name: User Name to display
        """
        # Create dummy session data
        session_data = {
            "access_token": access_token,
            "user_id": user_id,
            "user_name": user_name,
            "user_type": "individual",
            "email": "manual@example.com",
            "login_time": datetime.now().isoformat()
        }
        
        self._save_token(session_data)
        log_event("manual_token_set")
    
    def validate_token(self) -> tuple[bool, Optional[Dict[str, Any]]]:
        """
        Validate current access token by making a test API call.
        
        Returns:
            (is_valid, profile_data) tuple
        """
        try:
            # Try to fetch user profile
            profile = self.kite.profile()
            
            log_event("token_validation_success", {
                "user_id": profile.get('user_id'),
                "user_name": profile.get('user_name')
            })
            
            return True, profile
        
        except Exception as e:
            log_event("token_validation_failed", {
                "error": str(e)
            }, level="WARNING")
            logger.warning(f"Token validation failed: {e}")
            return False, None
    
    def get_kite_instance(self) -> KiteConnect:
        """
        Get authenticated KiteConnect instance.
        
        Returns:
            KiteConnect instance with access token set
        
        Raises:
            ValueError if not authenticated
        """
        if not self.kite.access_token:
            raise ValueError("Not authenticated. Please complete login flow first.")
        
        return self.kite
    
    def get_auth_status(self) -> Dict[str, Any]:
        """
        Get current authentication status.
        
        Returns:
            Status dictionary (NO secrets included)
        """
        is_valid, profile = self.validate_token()
        
        status = {
            "authenticated": is_valid,
            "token_file_exists": self.token_file.exists(),
            "api_key_configured": bool(self.api_key and self.api_key != "your_api_key_here")
        }
        
        if is_valid and profile:
            status.update({
                "user_id": profile.get("user_id"),
                "user_name": profile.get("user_name"),
                "user_type": profile.get("user_type"),
                "email": profile.get("email")
            })
        
        return status
    
    def logout(self):
        """
        Logout and clear access token.
        """
        try:
            # Invalidate session on Kite
            if self.kite.access_token:
                self.kite.invalidate_access_token()
        except Exception as e:
            logger.warning(f"Could not invalidate token on server: {e}")
        
        # Remove token file
        if self.token_file.exists():
            self.token_file.unlink()
            logger.info("Access token removed")
        
        # Clear from instance
        self.kite.set_access_token(None)
        
        log_event("logout_complete")


# Global auth instance
zerodha_auth = ZerodhaAuth()
