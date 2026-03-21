"""
Wrapper around the bot.py code (https://github.com/pipecat-ai/pipecat/blob/main/examples/quickstart/bot.py)
"""

import os
import struct

from loguru import logger
from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import LLMRunFrame, OutputAudioRawFrame, MetricsFrame, InputAudioRawFrame
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

SAMPLE_RATE = 16000                                                                                                                                                   
CHANNELS = 1                                                                                                                                                        
BYTES_PER_SAMPLE = 2  # 16-bit PCM

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
            system_instruction="You are a friendly AI assistant." \
            "Respond naturally and keep your answers conversational." \
            "You have a took called 'play_audio' that can play a short notification sound to the user",
        )
    )

    # Play Audio tool
    async def play_audio_handler(params: FunctionCallParams):
        logger.info(f"[{session_id}] play_audio tool called")
        import math
        duration = 0.2
        num_samples = int(SAMPLE_RATE * duration)
        samples = []
        for i in range(num_samples):
            t = i / SAMPLE_RATE
            sample = int(16000 * math.sin(2 * math.pi * 440 * t))
            samples.append(struct.pack("<h", sample))
        audio_bytes = b"".join(samples)

        frame = OutputAudioRawFrame(
            audio=audio_bytes,
            sample_rate=SAMPLE_RATE,
            num_channels=CHANNELS,
        )
        await params.llm.push_frame(frame)
        await params.result_callback({"status": "audio_played"})

    llm.register_function("play_audio", play_audio_handler)

    tools = ToolsSchema(
        standard_tools=[
            FunctionSchema(
                name="play_audio",
                description="Play a short notification sound to the user",
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
            enable_usage_metrics=True    # usage metrics
        )
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
