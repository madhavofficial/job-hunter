import os
import sys
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

class KeyManager:
    def __init__(self):
        self.keys = []
        self.current_idx = 0
        self.load_keys()
        
    def load_keys(self):
        candidate_keys = []
        
        # Check standard key
        primary = os.getenv("GROQ_API_KEY")
        if primary:
            candidate_keys.append(primary)
            
        # Check numbered keys up to 20
        for i in range(1, 21):
            k = os.getenv(f"GROQ_API_KEY_{i}")
            if k:
                candidate_keys.append(k)
                
        # Deduplicate keys while maintaining order
        seen = set()
        self.keys = []
        for k in candidate_keys:
            if k not in seen:
                seen.add(k)
                self.keys.append(k)
                
        if not self.keys:
            print("Warning: No Groq API keys found in .env file.", file=sys.stderr)
            
    def get_current_key(self):
        if not self.keys:
            return None
        return self.keys[self.current_idx]
        
    def cycle_key(self):
        if not self.keys:
            return None
        self.current_idx = (self.current_idx + 1) % len(self.keys)
        print(f"[{self.current_idx}/{len(self.keys)}] Cycled to next Groq API key.", flush=True)
        return self.keys[self.current_idx]
        
    def get_num_keys(self):
        return len(self.keys)

# Global key manager instance
key_manager = KeyManager()

def get_groq_client() -> Groq:
    key = key_manager.get_current_key()
    if not key:
        raise ValueError("No GROQ_API_KEY found.")
    return Groq(api_key=key)

def cycle_groq_client() -> Groq:
    key_manager.cycle_key()
    return get_groq_client()

def get_fallback_models(client: Groq = None) -> list[str]:
    """Dynamically discover and rank all available active chat models on the user's Groq account."""
    if client is None:
        try:
            client = get_groq_client()
        except Exception:
            return ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b", "groq/compound-mini"]

    try:
        available = [m.id for m in client.models.list().data]
    except Exception:
        available = []

    # Exclude audio and guardrail-only models from general reasoning
    excluded = {"whisper", "guard", "orpheus", "prompt-guard"}
    chat_models = [m for m in available if not any(x in m.lower() for x in excluded)]

    # Scoring heuristic: prefer larger reasoning models first, then fast models
    def model_rank(m_name: str) -> int:
        name = m_name.lower()
        if "120b" in name or "r1" in name:
            return 100
        if "70b" in name or "nemotron" in name or "kimi" in name or "moonshot" in name:
            return 90
        if "27b" in name or "qwen" in name:
            return 80
        if "20b" in name or "compound" in name:
            return 70
        if "8b" in name or "7b" in name or "mini" in name:
            return 60
        return 50

    ranked = sorted(chat_models, key=model_rank, reverse=True)
    return ranked if ranked else ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.6-27b", "groq/compound-mini"]


def get_best_model(client: Groq) -> str:
    env_model = os.getenv("GROQ_MODEL")
    if env_model:
        return env_model

    fallback_list = get_fallback_models(client)
    return fallback_list[0] if fallback_list else "openai/gpt-oss-120b"
