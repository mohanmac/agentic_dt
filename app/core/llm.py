"""
Unified LLM Client for DayTradingPaperBot.
Supports multiple providers: OpenAI, Google Gemini, Ollama.
"""
import requests
import json
from typing import Optional, Dict, Any, List
from abc import ABC, abstractmethod

# NOTE: google.generativeai is imported lazily inside GeminiProvider so it never
# loads on the hot/cold-start path when LLM_PROVIDER is openai/ollama (e.g. on
# Streamlit Cloud). The package is large and deprecated; eager import slowed boot.

from app.core.config import settings
from app.core.utils import logger, log_event

try:
    from openai import OpenAI  # SDK v1.x
except ImportError:
    OpenAI = None  # provider stays unavailable until `pip install openai`


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    def __init__(self):
        self.total_tokens_used = 0

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
        super().__init__()
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
            
            # Extract tokens
            prompt_tokens = result.get("prompt_eval_count", 0)
            completion_tokens = result.get("eval_count", 0)
            self.total_tokens_used += (prompt_tokens + completion_tokens)
            
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
        super().__init__()
        self.api_key = settings.GOOGLE_API_KEY
        self.model_name = settings.GOOGLE_MODEL

        import google.generativeai as genai  # lazy: only when Gemini is selected
        self._genai = genai

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
                
            generation_config = self._genai.types.GenerationConfig(
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
            
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                self.total_tokens_used += getattr(response.usage_metadata, "total_token_count", 0)
            
            return response.text.strip()
            
        except Exception as e:
            logger.error(f"Gemini generation failed: {e}")
            raise e

    def check_health(self) -> bool:
        try:
            if not self.api_key:
                return False
            # Simple check: list models
            for m in self._genai.list_models():
                if "generateContent" in m.supported_generation_methods:
                    return True
            return False
        except Exception as e:
            logger.error(f"Gemini health check failed: {e}")
            return False


class OpenAIProvider(LLMProvider):
    """Client for OpenAI Chat Completions (single shared API key)."""

    def __init__(self):
        super().__init__()
        self.api_key = settings.OPENAI_API_KEY
        self.model_name = settings.OPENAI_MODEL
        if self.api_key and OpenAI is not None:
            self.client = OpenAI(api_key=self.api_key)
        else:
            self.client = None
            if not self.api_key:
                logger.warning("OPENAI_API_KEY not set — OpenAIProvider disabled")
            if OpenAI is None:
                logger.warning("openai SDK not installed — run `pip install openai`")

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
    ) -> str:
        if not self.client:
            raise ValueError("OpenAI not configured (missing api key or SDK)")
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        resp = self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if getattr(resp, "usage", None):
            self.total_tokens_used += getattr(resp.usage, "total_tokens", 0) or 0
        return (resp.choices[0].message.content or "").strip()

    def check_health(self) -> bool:
        if not self.client:
            return False
        try:
            self.client.models.list()
            return True
        except Exception as exc:
            logger.error(f"OpenAI health check failed: {exc}")
            return False


class LLMClient:
    """Unified client that delegates to the configured provider."""

    def __init__(self):
        self.provider_type = settings.LLM_PROVIDER
        self.provider: LLMProvider = None
        self._initialize_provider()

    def _initialize_provider(self):
        if self.provider_type == "openai":
            self.provider = OpenAIProvider()
        elif self.provider_type == "google":
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
            
    @property
    def total_tokens_used(self) -> int:
        if self.provider:
            return self.provider.total_tokens_used
        return 0

    def check_health(self) -> bool:
        if not self.provider:
            self._initialize_provider()
        return self.provider.check_health()


# Global instance
llm_client = LLMClient()
