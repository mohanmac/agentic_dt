"""
Ollama LLM integration for strategy reasoning and explanations.
"""
import requests
from typing import Optional, Dict, Any
import json

from app.core.config import settings
from app.core.utils import logger, log_event


class OllamaClient:
    """Client for interacting with local Ollama LLM."""
    
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL
        self.model = settings.OLLAMA_MODEL
    
    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 500
    ) -> str:
        """
        Generate text completion from Ollama.
        
        Args:
            prompt: User prompt
            system_prompt: Optional system prompt
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens to generate
        
        Returns:
            Generated text
        """
        try:
            url = f"{self.base_url}/api/generate"
            
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            }
            
            if system_prompt:
                payload["system"] = system_prompt
            
            response = requests.post(url, json=payload, timeout=30)
            response.raise_for_status()
            
            result = response.json()
            generated_text = result.get("response", "")
            
            log_event("ollama_generation_success", {
                "model": self.model,
                "prompt_length": len(prompt),
                "response_length": len(generated_text)
            })
            
            return generated_text.strip()
        
        except requests.exceptions.RequestException as e:
            log_event("ollama_generation_failed", {
                "error": str(e),
                "model": self.model
            }, level="ERROR")
            logger.error(f"Ollama generation failed: {e}")
            
            # Return fallback message
            return "LLM unavailable - using rule-based reasoning."
        
        except Exception as e:
            logger.error(f"Unexpected error in Ollama generation: {e}", exc_info=True)
            return "Error generating explanation."
    
    def check_health(self) -> bool:
        """
        Check if Ollama server is running and model is available.
        
        Returns:
            True if healthy
        """
        try:
            # Check if server is running
            url = f"{self.base_url}/api/tags"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            
            # Check if our model is available
            models = response.json().get("models", [])
            model_names = [m.get("name") for m in models]
            
            if self.model in model_names:
                logger.info(f"Ollama health check passed - model '{self.model}' available")
                return True
            else:
                logger.warning(f"Model '{self.model}' not found. Available models: {model_names}")
                logger.warning(f"Please run: ollama pull {self.model}")
                return False
        
        except Exception as e:
            logger.error(f"Ollama health check failed: {e}")
            logger.error(f"Please ensure Ollama is running: ollama serve")
            return False


# Global Ollama client
ollama_client = OllamaClient()
