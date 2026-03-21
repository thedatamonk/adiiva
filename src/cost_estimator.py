DEEPGRAM_STT_PER_SECOND = 0.0058  # ~$0.0058/min Nova-2
OPENAI_LLM_PER_PROMPT_TOKEN = 0.00000015  # gpt-4o-mini input
OPENAI_LLM_PER_COMPLETION_TOKEN = 0.00000060  # gpt-4o-mini output

# Pro monthly plan costs $5/month and 1 credit = 1 character that need to be processed.
# So that brings per character pricing to be $0.00005
CARTESIA_TTS_PER_CHAR = 0.00005  

def estimate_cost(usage: dict) -> dict:
    """Takes a UsageTracker.summary() dict and adds cost estimates."""
    stt_cost = usage["stt_seconds"] * DEEPGRAM_STT_PER_SECOND
    llm_cost = (
        usage["llm_prompt_tokens"] * OPENAI_LLM_PER_PROMPT_TOKEN
        + usage["llm_completion_tokens"] * OPENAI_LLM_PER_COMPLETION_TOKEN
    )
    tts_cost = usage["tts_characters"] * CARTESIA_TTS_PER_CHAR
    total = stt_cost + llm_cost + tts_cost

    return {
        **usage,
        "cost": {
            "stt": round(stt_cost, 6),
            "llm": round(llm_cost, 6),
            "tts": round(tts_cost, 6),
            "total": round(total, 6),
        },
    }
