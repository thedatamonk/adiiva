"""
Wrapper around the bot.py code (https://github.com/pipecat-ai/pipecat/blob/main/examples/quickstart/bot.py)
"""

import asyncio
import os
import struct
import wave
from pathlib import Path

from loguru import logger
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from pipecat.utils.tracing.setup import setup_tracing
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame, OutputAudioRawFrame, MetricsFrame, InputAudioRawFrame, TTSSpeakFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from pipecat.services.cartesia.tts import CartesiaTTSService
from pipecat.services.deepgram.stt import DeepgramSTTService
from pipecat.services.llm_service import FunctionCallParams
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from .metrics import LatencyTracker, MetricsCollector
from .usage_tracker import UsageTracker
from dotenv import load_dotenv


load_dotenv(override=True)

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
BYTES_PER_SAMPLE = 2  # 16-bit PCM
POEM_WAV_PATH = Path(__file__).resolve().parent.parent / "static" / "poem.wav"
AUDIO_CHUNK_SIZE = 16000  # ~0.5s of audio per frame at 16kHz mono 16-bit

async def create_pipeline(websocket, session_id: str, usage: UsageTracker, metrics: MetricsCollector):
    """
    Create and run a Pipecat pipeline for a single websocket session
    """
    # transport is responsible for connecting the pipeline to the actual audio I/O
    transport = FastAPIWebsocketTransport(
        websocket,
        FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            serializer=ProtobufFrameSerializer()
        )
    )

    stt = DeepgramSTTService(api_key=os.getenv("DEEPGRAM_API_KEY")) # type: ignore

    tts = CartesiaTTSService(
        api_key=os.getenv("CARTESIA_API_KEY"), # type: ignore
        settings=CartesiaTTSService.Settings(
            voice="71a7ad14-091c-4e8e-a314-022ece01c121",  # British Reading Lady
        ),
    )

    # TODO: We need to tell when the LLM should call this tool
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
        user_params=LLMUserAggregatorParams(vad_analyzer=SileroVADAnalyzer()),
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
        ),
        enable_tracing=IS_TRACING_ENABLED,
        conversation_id=session_id,
        additional_span_attributes={"langfuse.session_id": session_id}
    )

    task.add_reached_downstream_filter((MetricsFrame, InputAudioRawFrame))

    latency = LatencyTracker(session_id, metrics)
    task.add_observer(latency.observer)

    # Usage tracking
    @task.event_handler("on_frame_reached_downstream")
    async def on_frame_downstream(task, frame):
        if isinstance(frame, MetricsFrame):
            usage.process_metrics(frame.data)
        elif isinstance(frame, InputAudioRawFrame):
            # Calculate STT seconds from raw audio
            num_bytes = len(frame.audio)
            seconds = num_bytes / (SAMPLE_RATE * CHANNELS * BYTES_PER_SAMPLE)
            usage.add_stt_usage(seconds)
    
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

    return usage
