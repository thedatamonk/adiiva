"""
Per-session usage accumulator and cost estimation.

Tracks STT seconds, LLM tokens, and TTS characters for a single session,
then estimates cost using provider rate constants.
"""
from dataclasses import dataclass, field
import time

from pipecat.metrics.metrics import LLMUsageMetricsData, TTSUsageMetricsData

# Provider rate constants
DEEPGRAM_STT_PER_SECOND = 0.0058  # ~$0.0058/min Nova-2
OPENAI_LLM_PER_PROMPT_TOKEN = 0.00000015  # gpt-4o-mini input
OPENAI_LLM_PER_COMPLETION_TOKEN = 0.00000060  # gpt-4o-mini output
CARTESIA_TTS_PER_CHAR = 0.00005  # Pro plan ~$0.00005/char


@dataclass
class UsageTracker:
    session_id: str
    # Speech-to-Text seconds: total time of how long the user spoke into the mic.
    # FYI: Deepgram (the STT provider) charges based on the duration of audio it transcribes
    stt_seconds: float = 0.0

    # TTS characters: Text-to-Speech characters. This is the number of text characters that
    # the TTS provider (Cartesia) converts into spoken audio.
    # Cartesia charges based on # of characters that need to be converted to audio
    tts_characters: int = 0

    # LLM input prompt tokens
    llm_prompt_tokens: int = 0

    # LLM completion tokens
    llm_completion_tokens: int = 0

    created_at: float = field(default_factory=time.time)

    def add_stt_usage(self, seconds: float):
        self.stt_seconds += seconds
    
    def add_llm_usage(self, prompt_tokens: int, completion_tokens: int):
        self.llm_prompt_tokens += prompt_tokens
        self.llm_completion_tokens += completion_tokens
    
    def add_tts_usage(self, characters: int):
        self.tts_characters += characters
    
    def process_metrics(self, metrics_data: list):
        for item in metrics_data:
            if isinstance(item, LLMUsageMetricsData):
                self.add_llm_usage(item.value.prompt_tokens, item.value.completion_tokens)
            elif isinstance(item, TTSUsageMetricsData):
                self.add_tts_usage(item.value)

    def estimate_cost(self) -> dict:
        stt_cost = self.stt_seconds * DEEPGRAM_STT_PER_SECOND
        llm_cost = (
            self.llm_prompt_tokens * OPENAI_LLM_PER_PROMPT_TOKEN
            + self.llm_completion_tokens * OPENAI_LLM_PER_COMPLETION_TOKEN
        )
        tts_cost = self.tts_characters * CARTESIA_TTS_PER_CHAR
        return {
            "stt": round(stt_cost, 6),
            "llm": round(llm_cost, 6),
            "tts": round(tts_cost, 6),
            "total": round(stt_cost + llm_cost + tts_cost, 6),
        }

    def summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "stt_seconds": round(self.stt_seconds, 2),
            "llm_prompt_tokens": self.llm_prompt_tokens,
            "llm_completion_tokens": self.llm_completion_tokens,
            "tts_characters": self.tts_characters,
            "duration_seconds": round(time.time() - self.created_at, 2),
            "cost": self.estimate_cost(),
        }
