import sys
from pathlib import Path
import os

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import settings
from app.core.llm import llm_client

def verify():
    print(f"LLM Provider: {settings.LLM_PROVIDER}")
    print(f"Google Model: {settings.GOOGLE_MODEL}")
    
    if settings.LLM_PROVIDER == "google":
        if not settings.GOOGLE_API_KEY:
            print("❌ GOOGLE_API_KEY is not set.")
            return
        else:
            print("✅ GOOGLE_API_KEY is set (length: " + str(len(settings.GOOGLE_API_KEY)) + ")")
    
    print("\nChecking health...")
    if llm_client.check_health():
        print("✅ Health check passed")
    else:
        print("❌ Health check failed")
        return

    print("\nGenerating text...")
    try:
        response = llm_client.generate("Explain day trading in one sentence.")
        print(f"Response: {response}")
        print("✅ Generation successful")
    except Exception as e:
        print(f"❌ Generation failed: {e}")

if __name__ == "__main__":
    verify()
