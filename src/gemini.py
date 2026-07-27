import random
import time
from google import genai
from google.genai import types
from src.config import GEMINI_API_KEY

class GeminiService:
    def __init__(self):
        self.api_key = GEMINI_API_KEY
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY not found or is empty. Please set it in your .env file")
        self.client = genai.Client(api_key=self.api_key)
        self.model_name = "gemini-3.5-flash"
        self.chat_sessions = {}  # channel_id -> Chat object

    def get_or_create_chat(self, channel_id: int):
        """Get or create an ongoing chat session for a specific channel."""
        if channel_id not in self.chat_sessions:
            system_instruction = (
                "You are Javis, a helpful, cool, and polite Discord bot assistant. "
                "Keep your answers concise and formatted nicely for Discord chats (using markdown and emojis). "
                "Respond naturally in Thai."
            )
            self.chat_sessions[channel_id] = self.client.chats.create(
                model=self.model_name,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction
                )
            )
        return self.chat_sessions[channel_id]

    def reset_chat(self, channel_id: int):
        """Clear chat history/session for a channel."""
        if channel_id in self.chat_sessions:
            del self.chat_sessions[channel_id]

    
    def generate_response(self, prompt: str) -> str:
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt
        )
        return response.text
    
    def generate_complex_response(self, prompt: str, max_retries: int = 3) -> str:
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt
                )
                if response.text:
                    return response.text
                else:
                    print(f"[GeminiService] Empty response on attempt {attempt + 1}")
                    time.sleep(random.uniform(1, 3))
            except Exception as e:
                print(f"[GeminiService] Error on attempt {attempt + 1}: {e}")
                time.sleep(random.uniform(1, 3))
        return "Sorry, I'm having trouble connecting to the AI right now. Please try again later."
    
    def generate_with_retry(self, prompt: str, max_retries: int = 3) -> str:
        for attempt in range(max_retries):
            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt
                )
                return response.text
            except Exception as e:
                print(f"Error on attempt {attempt + 1}: {e}")
                time.sleep(1)
        return "Sorry, I'm having trouble connecting to the AI right now. Please try again later."
