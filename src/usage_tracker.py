"""
All user tracking metrics are defined here. These are used for:
- rate-limiting
- LLM costs, tokens and other performance metrics
"""
from dataclasses import dataclass, field
import time

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
        """
        """
        from pipecat.metrics.metrics import LLMUsageMetricsData, TTSUsageMetricsData
        
        for item in metrics_data:
            if isinstance(item, LLMUsageMetricsData):
                self.add_llm_usage(item.value.prompt_tokens, item.value.completion_tokens)
            elif isinstance(item, TTSUsageMetricsData):
                self.add_tts_usage(item.value)
            else:
                # STT metrics are not present in Pipecat as Deepgram doesnt emit duration metrics
                # TODO: We will have to calculate it from audio input frames later in the pipeline
                raise NotImplementedError

    def summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "stt_seconds": round(self.stt_seconds, 2),
            "llm_prompt_tokens": self.llm_prompt_tokens,
            "llm_completion_tokens": self.llm_completion_tokens,
            "tts_characters": self.tts_characters,
            "duration_seconds": round(time.time() - self.created_at, 2)
        }