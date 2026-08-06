"""Typhoon AI client and per-channel conversation state, compatible with GeminiService signature."""

import random
import time
import requests
from ..config import TYPHOON_API_KEY

class TyphoonResponse:
    def __init__(self, text: str):
        self.text = text

class TyphoonChat:
    def __init__(self, service: 'GeminiService', system_instruction: str):
        self.service = service
        self.messages = [{"role": "system", "content": system_instruction}]

    def send_message(self, prompt: str) -> TyphoonResponse:
        self.messages.append({"role": "user", "content": prompt})
        
        # Limit history size to 21 items (system + 20 exchanges)
        if len(self.messages) > 21:
            self.messages = [self.messages[0]] + self.messages[-20:]
            
        try:
            reply = self.service._call_typhoon(self.messages)
            self.messages.append({"role": "assistant", "content": reply})
            return TyphoonResponse(reply)
        except Exception as e:
            # Remove last user message on failure
            self.messages.pop()
            raise e

class GeminiService:
    """Typhoon Service wrapper matching original GeminiService name and methods."""
    def __init__(self):
        self.api_key = TYPHOON_API_KEY
        if not self.api_key:
            raise ValueError("TYPHOON_API_KEY not found or is empty. Please set it in your .env file")
        # Standard high-quality model for text reasoning
        self.model_name = "typhoon-v2.5-30b-a3b-instruct"
        self.chat_sessions = {}  # channel_id -> TyphoonChat object

    def get_or_create_chat(self, channel_id: int) -> TyphoonChat:
        """Get or create an ongoing chat session for a specific channel."""
        if channel_id not in self.chat_sessions:
            system_instruction = (
                "You are Javis, a helpful, cool, and polite Discord bot assistant. "
                "Keep your answers concise and formatted nicely for Discord chats (using markdown and emojis). "
                "Respond naturally in Thai."
            )
            self.chat_sessions[channel_id] = TyphoonChat(self, system_instruction)
        return self.chat_sessions[channel_id]

    def reset_chat(self, channel_id: int):
        """Clear chat history/session for a channel."""
        if channel_id in self.chat_sessions:
            del self.chat_sessions[channel_id]

    def _call_typhoon(self, messages: list[dict[str, str]], max_retries: int = 3) -> str:
        url = "https://api.opentyphoon.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model_name,
            "messages": messages,
            "temperature": 0.6,
            "max_tokens": 1500
        }
        
        last_exception = None
        for attempt in range(max_retries):
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=30)
                if response.status_code == 200:
                    data = response.json()
                    choices = data.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "")
                        if content:
                            return content
                    raise ValueError(f"Empty response structure: {response.text}")
                else:
                    raise ValueError(f"Typhoon API error: HTTP {response.status_code} - {response.text}")
            except Exception as e:
                last_exception = e
                print(f"[Typhoon] Attempt {attempt+1} failed: {e}")
                time.sleep(random.uniform(1, 2))
        raise last_exception or ValueError("Request failed")

    def generate_response(self, prompt: str) -> str:
        messages = [{"role": "user", "content": prompt}]
        return self._call_typhoon(messages)
    
    def generate_complex_response(self, prompt: str, max_retries: int = 3) -> str:
        messages = [{"role": "user", "content": prompt}]
        try:
            return self._call_typhoon(messages, max_retries)
        except Exception:
            return "Sorry, I'm having trouble connecting to the AI right now. Please try again later."
    
    def generate_with_retry(self, prompt: str, max_retries: int = 3) -> str:
        messages = [{"role": "user", "content": prompt}]
        try:
            return self._call_typhoon(messages, max_retries)
        except Exception:
            return "Sorry, I'm having trouble connecting to the AI right now. Please try again later."
