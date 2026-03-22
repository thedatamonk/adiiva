"""
Wrapper around the bot.py code (https://github.com/pipecat-ai/pipecat/blob/main/examples/quickstart/bot.py)
"""

import asyncio
import os
import wave
from pathlib import Path

from loguru import logger
from opentelemetry.exporter.otlp.proto.http.trace_exporter import \
    OTLPSpanExporter
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import \
    LocalSmartTurnAnalyzerV3
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (LLMRunFrame, OutputAudioRawFrame,
                                   TTSSpeakFrame)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair, LLMUserAggregatorParams)
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.websocket.fastapi import (FastAPIWebsocketParams,
                                                  FastAPIWebsocketTransport)
from pipecat.turns.user_start import (TranscriptionUserTurnStartStrategy,
                                      VADUserTurnStartStrategy)
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.utils.tracing.setup import setup_tracing
from pipecat.audio.vad.vad_analyzer import VADParams

from .metrics_store import MetricsStore
from .observers import LatencyBreakdownObserver

IS_TRACING_ENABLED = bool(os.getenv("ENABLE_TRACING"))

# Initialize tracing if enabled
if IS_TRACING_ENABLED:
    # Create the exporter
    otlp_exporter = OTLPSpanExporter()

    # Set up tracing with the exporter
    setup_tracing(
        service_name="pipecat-adiiva",
        exporter=otlp_exporter,
        console_export=bool(os.getenv("OTEL_CONSOLE_EXPORT")),
    )
    logger.info("OpenTelemetry tracing initialized")

SAMPLE_RATE = 16000
CHANNELS = 1
POEM_WAV_PATH = Path(__file__).resolve().parent.parent / "static" / "poem.wav"
AUDIO_CHUNK_SIZE = 16000

async def create_pipeline(websocket, session_id: str, store: MetricsStore):
    """
    Create and run a Pipecat pipeline for a single websocket session
    """
    # transport is responsible for connecting the pipeline to the actual audio I/O
    transport = FastAPIWebsocketTransport(
        websocket,
        FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            serializer=ProtobufFrameSerializer(),
            vad_analyzer = SileroVADAnalyzer(
                params=VADParams(start_secs=0.2, stop_secs=0.5)
            ),
        )
    )

    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY")) # type: ignore

    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"), # type: ignore
        settings=CartesiaTTSService.Settings(
            voice="71a7ad14-091c-4e8e-a314-022ece01c121",  # British Reading Lady
        ),
    )

    llm = OpenAILLMService(
        api_key=os.getenv("OPENAI_API_KEY"),
        settings=OpenAILLMService.Settings(
            system_instruction=(
                "You are a friendly voice AI assistant. "
                "Keep every response to 1-2 sentences maximum. Be concise and conversational. "
                "Greet the user briefly in under 10 words. "
                "Never use markdown, asterisks, bullet points, numbered lists, or special symbols. "
                "Write plain spoken English only — your output is read aloud by a text-to-speech engine. "
                "You have a tool called 'play_audio' that plays a pre-recorded poem for the user. "
                "Call it when the user asks to hear a poem, nursery rhyme, or recitation."
            ),
        )
    )

    smart_turn_params = SmartTurnParams(stop_secs=1.5, pre_speech_ms=0.0)
    turn_analyzer = LocalSmartTurnAnalyzerV3(params=smart_turn_params)

    # Play Audio tool — reads a WAV file and sends raw audio frames to client
    async def play_audio_handler(params: FunctionCallParams):
        logger.info(f"[{session_id}] play_audio tool called")

        if not POEM_WAV_PATH.exists():
            logger.error(f"[{session_id}] Poem WAV not found at {POEM_WAV_PATH}")
            await params.result_callback({"status": "error", "reason": "audio file not found"})
            return

        # Wait for TTS filler speech ("Sure, here's a poem for you") to finish
        await asyncio.sleep(2.5)

        with wave.open(str(POEM_WAV_PATH), "rb") as wf:
            audio_bytes = wf.readframes(wf.getnframes())

        # Send in chunks so we don't block the pipeline with one massive frame
        for i in range(0, len(audio_bytes), AUDIO_CHUNK_SIZE):
            chunk = audio_bytes[i : i + AUDIO_CHUNK_SIZE]
            frame = OutputAudioRawFrame(
                audio=chunk,
                sample_rate=SAMPLE_RATE,
                num_channels=CHANNELS,
            )
            await params.llm.push_frame(frame)

        logger.info(f"[{session_id}] Poem audio sent ({len(audio_bytes)} bytes)")
        await params.result_callback({"status": "poem_played"})

    llm.register_function("play_audio", play_audio_handler)

    @llm.event_handler("on_function_calls_started")
    async def on_function_calls_started(service, function_calls):
        logger.info(f"[{session_id}] Function calls started: {[fc.function_name for fc in function_calls]}")
        await tts.queue_frame(TTSSpeakFrame("Sure, here's a poem for you."))

    tools = ToolsSchema(
        standard_tools=[
            FunctionSchema(
                name="play_audio",
                description="Play a pre-recorded poem audio clip for the user. Call this when the user asks to hear a poem, recitation, or nursery rhyme.",
                properties={},
                required=[],
            )
        ]
    )

    context = LLMContext(tools=tools)

    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(
                start=[VADUserTurnStartStrategy(), TranscriptionUserTurnStartStrategy()],
                stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=turn_analyzer)],
            ),
            user_turn_stop_timeout=2.0,
            user_idle_timeout=5.0,
        ),
    )

    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            user_aggregator,
            llm,
            tts,
            transport.output(),
            assistant_aggregator,
        ]
    )

    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            enable_metrics=True,         # performance metrics
            enable_usage_metrics=True,   # usage metrics
            observers=[LatencyBreakdownObserver(session_id, store)]
        ),
        enable_tracing=IS_TRACING_ENABLED,
        conversation_id=session_id,
        additional_span_attributes={"langfuse.session_id": session_id}
    )

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, websocket):
        logger.info(f"[{session_id}] Client connected")
        # We are adding a seed user message so that we can trigger an LLM response
        # as LLM wont respond on its own
        context.add_message(
            {"role": "user", "content": "Say hello and briefly introduce yourself."}
        )
        await task.queue_frames([LLMRunFrame()])
    
    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, websocket):
        logger.info(f"[{session_id}] Client disconnected")
        await task.cancel()
    

    # We are setting `handle_sigint` = False so that
    # Pipecat doesn't handle sigint (Ctrl + C) as it will be done by FastAPI
    runner = PipelineRunner(handle_sigint=False)
    await runner.run(task)
