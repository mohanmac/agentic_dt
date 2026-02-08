"""
Unified LLM Client for DayTradingPaperBot.
Supports multiple providers: Ollama, Google Gemini.
"""
import requests
import json
from typing import Optional, Dict, Any, List
from abc import ABC, abstractmethod
import google.generativeai as genai

from app.core.config import settings
from app.core.utils import logger, log_event


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        """Generate text from prompt."""
        pass
    
    @abstractmethod
    def check_health(self) -> bool:
        """Check if provider is available."""
        pass


class OllamaProvider(LLMProvider):
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
            return result.get("response", "").strip()
        
        except Exception as e:
            logger.error(f"Ollama generation failed: {e}")
            raise e

    def check_health(self) -> bool:
        try:
            url = f"{self.base_url}/api/tags"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            
            models = response.json().get("models", [])
            model_names = [m.get("name") for m in models]
            
            if self.model in model_names:
                return True
            return False
        except Exception:
            return False


class GeminiProvider(LLMProvider):
    """Client for interacting with Google Gemini."""
    
    def __init__(self):
        self.api_key = settings.GOOGLE_API_KEY
        self.model_name = settings.GOOGLE_MODEL
        
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.model = genai.GenerativeModel(self.model_name)
        else:
            self.model = None
            logger.warning("Google API Key not provided for GeminiProvider")

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 500
    ) -> str:
        try:
            if not self.model:
                raise ValueError("Gemini not configured (missing API Key)")
                
            generation_config = genai.types.GenerationConfig(
                temperature=temperature,
                max_output_tokens=max_tokens
            )
            
            # Combine system prompt with user prompt since Gemini generic API 
            # handles system instructions differently depending on version, 
            # but prepending is safe.
            full_prompt = prompt
            if system_prompt:
                # For models that support system_instruction, we could set it, 
                # but valid strategy is to prepend.
                # Let's try to use system_instruction if initializing model allow it,
                # but since we initialized in __init__, we pass it here if we re-instantiate or just prepend.
                # Simple approach: Prepend.
                full_prompt = f"System: {system_prompt}\n\nUser: {prompt}"
            
            response = self.model.generate_content(
                full_prompt,
                generation_config=generation_config
            )
            
            return response.text.strip()
            
        except Exception as e:
            logger.error(f"Gemini generation failed: {e}")
            raise e

    def check_health(self) -> bool:
        try:
            if not self.api_key:
                return False
            # Simple check: list models
            for m in genai.list_models():
                if "generateContent" in m.supported_generation_methods:
                    return True
            return False
        except Exception as e:
            logger.error(f"Gemini health check failed: {e}")
            return False


class LLMClient:
    """Unified client that delegates to the configured provider."""
    
    def __init__(self):
        self.provider_type = settings.LLM_PROVIDER
        self.provider: LLMProvider = None
        self._initialize_provider()
        
    def _initialize_provider(self):
        if self.provider_type == "google":
            self.provider = GeminiProvider()
        else:
            self.provider = OllamaProvider()
            
    def generate(self, prompt: str, system_prompt: Optional[str] = None, **kwargs) -> str:
        """Generate text using the active provider."""
        try:
            if not self.provider:
                self._initialize_provider()
                
            response = self.provider.generate(prompt, system_prompt, **kwargs)
            
            log_event("llm_generation_success", {
                "provider": self.provider_type,
                "response_length": len(response)
            })
            
            return response
            
        except Exception as e:
            log_event("llm_generation_failed", {
                "provider": self.provider_type,
                "error": str(e)
            }, level="ERROR")
            
            # Failover logic could go here, but for now just return error message
            return "Analysis unavailable due to LLM error."
            
    def check_health(self) -> bool:
        if not self.provider:
            self._initialize_provider()
        return self.provider.check_health()


# Global instance
llm_client = LLMClient()
