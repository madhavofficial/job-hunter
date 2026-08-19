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

def get_best_model(client: Groq) -> str:
    # Check if a model is explicitly specified in the environment
    env_model = os.getenv("GROQ_MODEL")
    if env_model:
        return env_model
        
    # Order of preference for Groq models
    preferred_models = [
        "openai/gpt-oss-120b",
        "llama-3.3-70b-versatile",
        "llama-3.1-70b-versatile",
        "openai/gpt-oss-20b",
        "llama3-70b-8192",
        "llama-3.1-8b-instant"
    ]
    
    try:
        available_models = [m.id for m in client.models.list().data]
        for model in preferred_models:
            if model in available_models:
                return model
        
        for model in available_models:
            if any(term in model.lower() for term in ["120b", "70b", "20b", "8b"]):
                return model
                
        if available_models:
            return available_models[0]
            
    except Exception as e:
        print(f"Warning: Failed to fetch available Groq models ({e}). Using default: openai/gpt-oss-120b", file=sys.stderr)
        
    return "openai/gpt-oss-120b"
