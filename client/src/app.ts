/**
 * Copyright (c) 2024–2025, Daily
 *
 * SPDX-License-Identifier: BSD 2-Clause License
 */

/**
 * Pipecat Client Implementation
 *
 * This client connects to an RTVI-compatible bot server using WebSocket.
 *
 * Requirements:
 * - A running RTVI bot server (defaults to http://localhost:7860)
 */

import {
  PipecatClient,
  PipecatClientOptions,
  RTVIEvent,
  TransportState,
} from '@pipecat-ai/client-js';
import { WebSocketTransport } from '@pipecat-ai/websocket-transport';

class WebsocketClientApp {
  private pcClient: PipecatClient | null = null;
  private connected: boolean = false;
  private connectBtn: HTMLButtonElement | null = null;
  private disconnectBtn: HTMLButtonElement | null = null;
  private statusSpan: HTMLElement | null = null;
  private debugLog: HTMLElement | null = null;
  private botAudio: HTMLAudioElement;
  private token: string = '';
  private metricsInterval: ReturnType<typeof setInterval> | null = null;

  constructor() {
    console.log('WebsocketClientApp');
    this.botAudio = document.createElement('audio');
    this.botAudio.autoplay = true;
    document.body.appendChild(this.botAudio);

    this.setupDOMElements();
    this.setupEventListeners();
    this.setupLoginForm();
  }

  private setupLoginForm(): void {
    const form = document.getElementById('login-form') as HTMLFormElement;
    const errorEl = document.getElementById('login-error') as HTMLElement;

    form?.addEventListener('submit', async (e) => {
      e.preventDefault();
      const username = (document.getElementById('username') as HTMLInputElement).value;
      const password = (document.getElementById('password') as HTMLInputElement).value;
      const loginBtn = document.getElementById('login-btn') as HTMLButtonElement;

      loginBtn.disabled = true;
      errorEl.textContent = '';

      try {
        const params = new URLSearchParams({ user_id: username, password });
        const resp = await fetch(`/token?${params.toString()}`, {
          method: 'POST',
        });

        if (!resp.ok) {
          const data = await resp.json();
          throw new Error(data.detail || 'Login failed');
        }

        const data = await resp.json();
        this.token = data.access_token;

        // Show session panel, hide login
        document.getElementById('login-panel')!.style.display = 'none';
        document.getElementById('session-panel')!.style.display = 'block';
        document.getElementById('logged-in-user')!.textContent = username;
        this.log(`Logged in as ${username}`);
        this.startMetricsPolling();
      } catch (err) {
        errorEl.textContent = (err as Error).message;
      } finally {
        loginBtn.disabled = false;
      }
    });
  }

  /**
   * Set up references to DOM elements and create necessary media elements
   */
  private setupDOMElements(): void {
    this.connectBtn = document.getElementById(
      'connect-btn'
    ) as HTMLButtonElement;
    this.disconnectBtn = document.getElementById(
      'disconnect-btn'
    ) as HTMLButtonElement;
    this.statusSpan = document.getElementById('connection-status');
    this.debugLog = document.getElementById('debug-log');
  }

  /**
   * Set up event listeners for connect/disconnect buttons
   */
  private setupEventListeners(): void {
    this.connectBtn?.addEventListener('click', () => this.connect());
    this.disconnectBtn?.addEventListener('click', () => this.disconnect());
  }

  /**
   * Add a timestamped message to the debug log
   */
  private log(message: string): void {
    if (!this.debugLog) return;
    const entry = document.createElement('div');
    entry.textContent = `${new Date().toISOString()} - ${message}`;
    if (message.startsWith('User: ')) {
      entry.style.color = '#2196F3';
    } else if (message.startsWith('Bot: ')) {
      entry.style.color = '#4CAF50';
    }
    this.debugLog.appendChild(entry);
    this.debugLog.scrollTop = this.debugLog.scrollHeight;
    console.log(message);
  }

  /**
   * Update the connection status display
   */
  private updateStatus(status: string): void {
    if (this.statusSpan) {
      this.statusSpan.textContent = status;
    }
    this.log(`Status: ${status}`);
  }

  /**
   * Check for available media tracks and set them up if present
   * This is called when the bot is ready or when the transport state changes to ready
   */
  setupMediaTracks() {
    if (!this.pcClient) return;
    const tracks = this.pcClient.tracks();
    if (tracks.bot?.audio) {
      this.setupAudioTrack(tracks.bot.audio);
    }
  }

  /**
   * Set up listeners for track events (start/stop)
   * This handles new tracks being added during the session
   */
  setupTrackListeners() {
    if (!this.pcClient) return;

    // Listen for new tracks starting
    this.pcClient.on(RTVIEvent.TrackStarted, (track, participant) => {
      // Only handle non-local (bot) tracks
      if (!participant?.local && track.kind === 'audio') {
        this.setupAudioTrack(track);
      }
    });

    // Listen for tracks stopping
    this.pcClient.on(RTVIEvent.TrackStopped, (track, participant) => {
      this.log(
        `Track stopped: ${track.kind} from ${participant?.name || 'unknown'}`
      );
    });
  }

  /**
   * Set up an audio track for playback
   * Handles both initial setup and track updates
   */
  private setupAudioTrack(track: MediaStreamTrack): void {
    this.log('Setting up audio track');
    if (
      this.botAudio.srcObject &&
      'getAudioTracks' in this.botAudio.srcObject
    ) {
      const oldTrack = this.botAudio.srcObject.getAudioTracks()[0];
      if (oldTrack?.id === track.id) return;
    }
    this.botAudio.srcObject = new MediaStream([track]);
  }

  /**
   * Initialize and connect to the bot
   * This sets up the Pipecat client, initializes devices, and establishes the connection
   */
  public async connect(): Promise<void> {
    try {
      const startTime = Date.now();

      //const transport = new DailyTransport();
      const PipecatConfig: PipecatClientOptions = {
        transport: new WebSocketTransport(),
        enableMic: true,
        enableCam: false,
        callbacks: {
          onConnected: () => {
            this.connected = true;
            this.updateStatus('Connected');
            if (this.connectBtn) this.connectBtn.disabled = true;
            if (this.disconnectBtn) this.disconnectBtn.disabled = false;
          },
          onDisconnected: () => {
            this.connected = false;
            this.updateStatus('Disconnected');
            if (this.connectBtn) this.connectBtn.disabled = false;
            if (this.disconnectBtn) this.disconnectBtn.disabled = true;
            this.log('Client disconnected');
          },
          onBotReady: (data) => {
            this.log(`Bot ready: ${JSON.stringify(data)}`);
            this.setupMediaTracks();
          },
          onUserTranscript: (data) => {
            if (data.final) {
              this.log(`User: ${data.text}`);
            }
          },
          onBotTranscript: (data) => this.log(`Bot: ${data.text}`),
          onTransportStateChanged: (state: TransportState) => {
            if (state === 'error') {
              this.log('Connection rejected — you may have exceeded the concurrency limit');
            }
          },
          onMessageError: (error) => this.log(`Message error: ${JSON.stringify(error)}`),
          onError: (error) => this.log(`Error: ${JSON.stringify(error)}`),
        },
      };
      this.pcClient = new PipecatClient(PipecatConfig);
      // @ts-ignore
      window.pcClient = this.pcClient; // Expose for debugging
      this.setupTrackListeners();

      this.log('Initializing devices...');
      await this.pcClient.initDevices();

      // Build WebSocket URL with JWT token
      const wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const wsUrl = `${wsProto}//${location.host}/ws/talk?token=${this.token}`;
      this.log('Connecting to bot...');
      await this.pcClient.connect({
        wsUrl,
      });

      const timeTaken = Date.now() - startTime;
      this.log(`Connection complete, timeTaken: ${timeTaken}`);
    } catch (error) {
      this.log(`Error connecting: ${(error as Error).message}`);
      this.updateStatus('Error');
      // Clean up if there's an error — only disconnect if we actually connected
      if (this.pcClient && this.connected) {
        try {
          await this.pcClient.disconnect();
        } catch (disconnectError) {
          this.log(`Error during disconnect: ${disconnectError}`);
        }
      }
      this.pcClient = null;
    }
  }

  private startMetricsPolling(): void {
    this.fetchMetrics();
    this.metricsInterval = setInterval(() => this.fetchMetrics(), 3000);
  }

  private stopMetricsPolling(): void {
    if (this.metricsInterval) {
      clearInterval(this.metricsInterval);
      this.metricsInterval = null;
    }
  }

  private async fetchMetrics(): Promise<void> {
    try {
      const res = await fetch('/metrics');
      const m = await res.json();
      this.renderMetrics(m);
    } catch (_) {
      // silently ignore fetch errors
    }
  }

  private renderMetrics(m: any): void {
    const activeEl = document.getElementById('metric-active');
    const completedEl = document.getElementById('metric-completed');
    const ageEl = document.getElementById('metrics-age');
    const detailEl = document.getElementById('metrics-detail');

    if (activeEl) activeEl.textContent = m.active_session_count || 0;
    if (completedEl) completedEl.textContent = (m.completed_sessions || []).length;
    if (ageEl) ageEl.textContent = `updated ${new Date().toLocaleTimeString()}`;

    let html = '';

    const sessionRow = (s: any) => {
      const c = s.cost || {};
      return `<tr>
        <td>${s.session_id.substring(0, 8)}...</td>
        <td>${s.stt_seconds}</td>
        <td>${s.llm_prompt_tokens + s.llm_completion_tokens}</td>
        <td>${s.tts_characters}</td>
        <td>$${c.stt?.toFixed(6) ?? '\u2014'}</td>
        <td>$${c.llm?.toFixed(6) ?? '\u2014'}</td>
        <td>$${c.tts?.toFixed(6) ?? '\u2014'}</td>
        <td>$${c.total?.toFixed(6) ?? '\u2014'}</td>
        <td>${s.duration_seconds}s</td>
      </tr>`;
    };

    const tableHeader = '<table class="metrics-table"><tr><th>Session</th><th>STT (s)</th><th>LLM Tokens</th><th>TTS Chars</th><th>STT Cost</th><th>LLM Cost</th><th>TTS Cost</th><th>Total Cost</th><th>Duration</th></tr>';

    // Active sessions
    if (m.active_sessions && m.active_sessions.length > 0) {
      html += '<div class="metrics-section-title">Active Sessions</div>';
      html += tableHeader;
      for (const s of m.active_sessions) html += sessionRow(s);
      html += '</table>';
    }

    // Completed sessions
    if (m.completed_sessions && m.completed_sessions.length > 0) {
      html += '<div class="metrics-section-title">Completed Sessions</div>';
      html += tableHeader;
      for (const s of m.completed_sessions.slice(-5)) html += sessionRow(s);
      html += '</table>';
    }

    // Latency histogram
    const h = m.latency_histogram;
    if (h && h.count > 0) {
      html += '<div class="metrics-section-title">Latency Histogram</div>';
      html += '<table class="metrics-table"><tr><th>Count</th><th>Min</th><th>Max</th><th>Mean</th><th>p50</th><th>p95</th><th>p99</th></tr>';
      html += `<tr><td>${h.count}</td><td>${h.min}s</td><td>${h.max}s</td><td>${h.mean}s</td><td>${h.p50}s</td><td>${h.p95}s</td><td>${h.p99}s</td></tr>`;
      html += '</table>';
    }

    if (detailEl) detailEl.innerHTML = html;
  }

  /**
   * Disconnect from the bot and clean up media resources
   */
  public async disconnect(): Promise<void> {
    if (this.pcClient) {
      try {
        await this.pcClient.disconnect();
        this.pcClient = null;
        if (
          this.botAudio.srcObject &&
          'getAudioTracks' in this.botAudio.srcObject
        ) {
          this.botAudio.srcObject
            .getAudioTracks()
            .forEach((track) => track.stop());
          this.botAudio.srcObject = null;
        }
      } catch (error) {
        this.log(`Error disconnecting: ${(error as Error).message}`);
      }
    }
  }
}

declare global {
  interface Window {
    WebsocketClientApp: typeof WebsocketClientApp;
  }
}

window.addEventListener('DOMContentLoaded', () => {
  window.WebsocketClientApp = WebsocketClientApp;
  new WebsocketClientApp();
});
