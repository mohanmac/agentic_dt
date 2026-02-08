"""
FastAPI server for Zerodha authentication and status endpoints.
"""
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from typing import Dict, Any

from app.core.zerodha_auth import zerodha_auth
from app.core.utils import logger, log_event
from app.core.config import settings


# Create FastAPI app
app = FastAPI(
    title="DayTradingPaperBot Auth Server",
    description="Authentication server for Zerodha Kite Connect",
    version="1.0.0"
)

# Add CORS middleware for Streamlit integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "app": "DayTradingPaperBot",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "login_url": "/auth/login_url",
            "callback": "/callback",
            "status": "/status",
            "logout": "/auth/logout"
        }
    }


@app.get("/auth/login_url")
async def get_login_url():
    """
    Generate Kite Connect login URL for manual user authentication.
    
    Returns:
        JSON with login URL
    """
    try:
        login_url = zerodha_auth.generate_login_url()
        
        return {
            "success": True,
            "login_url": login_url,
            "message": "Please visit this URL in your browser to log in to Zerodha",
            "instructions": [
                "1. Click the login URL",
                "2. Log in with your Zerodha credentials",
                "3. Authorize the application",
                "4. You will be redirected back to this server"
            ]
        }
    
    except Exception as e:
        logger.error(f"Error generating login URL: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/callback")
async def auth_callback(request: Request, request_token: str = None, status: str = None):
    """
    OAuth callback endpoint - receives request_token from Zerodha.
    
    Args:
        request_token: Token from Zerodha OAuth
        status: Status from Zerodha (success/error)
    
    Returns:
        JSON with authentication result
    """
    # Check if authentication was successful
    if status != "success" or not request_token:
        log_event("auth_callback_failed", {
            "status": status,
            "has_token": bool(request_token)
        }, level="ERROR")
        
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "message": "Authentication failed or was cancelled",
                "status": status
            }
        )
    
    try:
        # Exchange request_token for access_token
        session_data = zerodha_auth.exchange_request_token(request_token)
        
        return {
            "success": True,
            "message": "Authentication successful!",
            "user": {
                "user_id": session_data.get("user_id"),
                "user_name": session_data.get("user_name"),
                "email": session_data.get("email"),
                "user_type": session_data.get("user_type")
            },
            "note": "Access token has been saved securely. You can now start trading."
        }
    
    except Exception as e:
        logger.error(f"Error in auth callback: {e}", exc_info=True)
        
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Failed to complete authentication: {str(e)}"
            }
        )


@app.get("/status")
async def get_status():
    """
    Get current authentication and system status.
    
    Returns:
        JSON with status information (NO secrets)
    """
    try:
        auth_status = zerodha_auth.get_auth_status()
        
        return {
            "success": True,
            "auth": auth_status,
            "trading_mode": "LIVE" if settings.ENABLE_LIVE_TRADING else "PAPER",
            "config": {
                "daily_capital": settings.DAILY_CAPITAL,
                "max_daily_loss": settings.MAX_DAILY_LOSS,
                "max_trades_per_day": settings.MAX_TRADES_PER_DAY,
                "ollama_model": settings.OLLAMA_MODEL
            }
        }
    
    except Exception as e:
        logger.error(f"Error getting status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/auth/logout")
async def logout():
    """
    Logout and clear access token.
    
    Returns:
        JSON with logout confirmation
    """
    try:
        zerodha_auth.logout()
        
        return {
            "success": True,
            "message": "Logged out successfully. Access token has been cleared."
        }
    
    except Exception as e:
        logger.error(f"Error during logout: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/shutdown")
async def shutdown():
    """
    Graceful server shutdown endpoint.
    
    Returns:
        JSON with shutdown confirmation
    """
    log_event("server_shutdown_requested")
    
    return {
        "success": True,
        "message": "Server shutting down..."
    }


@app.on_event("startup")
async def startup_event():
    """Server startup event."""
    logger.info("FastAPI auth server starting up")
    log_event("server_startup", {
        "trading_mode": "LIVE" if settings.ENABLE_LIVE_TRADING else "PAPER"
    })
    
    # Validate LLM connection
    from app.core.llm import llm_client
    llm_healthy = llm_client.check_health()
    
    if not llm_healthy:
        logger.warning(f"LLM health check failed ({settings.LLM_PROVIDER}) - AI features may not work")


@app.on_event("shutdown")
async def shutdown_event():
    """Server shutdown event."""
    logger.info("FastAPI auth server shutting down")
    log_event("server_shutdown")


def run_auth_server(host: str = "127.0.0.1", port: int = 8000):
    """
    Run the FastAPI auth server.
    
    Args:
        host: Host to bind to
        port: Port to bind to
    """
    logger.info(f"Starting auth server on {host}:{port}")
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info"
    )


if __name__ == "__main__":
    run_auth_server()
