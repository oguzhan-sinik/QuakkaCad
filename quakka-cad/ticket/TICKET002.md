# TICKET-002: Live Transcription via ElevenLabs Scribe v2 Realtime

## Summary
Add live transcription to the conference platform built in TICKET-001. Each participant's microphone audio is streamed to ElevenLabs Scribe v2 Realtime, and the resulting transcripts (attributed to the speaker by name) are surfaced in the conference UI in real time and persisted for the conference session.

## Goal
While a conference is running, every participant's spoken audio is transcribed live with sub-second latency, attributed correctly to whoever spoke it, and viewable by all participants as the conversation unfolds.

## Background
ElevenLabs Scribe v2 Realtime is a streaming STT model with ~150ms latency, 90+ language support, and a WebSocket API. Critically, **it does not currently support speaker diarization in realtime mode** — diarization only exists in the batch Scribe v2 model. To attribute lines to speakers, we run **one Scribe v2 Realtime session per participant**, feeding only that participant's mic stream into it. The participant's display name (from TICKET-001) becomes the speaker label.

## Scope

### In scope
- Per-participant WebSocket connection to Scribe v2 Realtime, established when a participant joins a conference and torn down when they leave.
- Streaming the participant's local mic audio (the same stream already captured for WebRTC) into their Scribe session as `input_audio_chunk` messages.
- Receiving `partial_transcript` and committed transcript events; broadcasting them to all conference participants, tagged with the speaker's display name.
- A transcript panel in the UI showing committed lines as a running log, plus the most recent partial line for whoever is currently speaking.
- Server-side storage of committed transcript lines for the lifetime of the conference (in-memory is acceptable for this MVP step), exposed via a simple "download transcript" action when the conference ends.
- Secure auth: API key lives only on the server. The client uses ElevenLabs' single-use token endpoint to open its WebSocket directly, OR the server proxies the WebSocket. Pick one; see Open Questions.
- Graceful handling of mute: while a participant is muted, no audio is sent to their Scribe session (saves credits and avoids spurious transcripts).

### Out of scope (deferred)
- Translation, summarization, or any LLM post-processing of the transcript.
- Speaker diarization for shared/room audio (we sidestep this by using per-participant streams).
- Long-term persistence (database storage), search, or transcript export to external systems.
- Profanity filtering, redaction, or PII handling beyond what Scribe provides natively.
- Keyterm prompting / custom vocabulary tuning — leave for a later iteration.
- Transcribing audio after a participant disconnects mid-utterance.

## UI Changes

The transcript lives in the **middle column** (previously a gray placeholder in TICKET-001). The left column remains gray for now.

```
┌──────────────┐  ┌──────────────────────────┐  ┌──────────────────────────┐
│              │  │  Live Transcript         │  │                          │
│  (gray       │  │                          │  │   (empty / reserved)     │
│  placeholder)│  │  Alice: Let's start with │  │                          │
│              │  │   the API design.        │  │                          │
│              │  │  Bob: Sounds good. I was │  ├──────────────────────────┤
│              │  │   thinking we should…    │  │  Attendees               │
│              │  │  Alice (typing…): yeah   │  │   • Alice (host)         │
│              │  │   that makes sense for   │  │   • Bob                  │
│              │  │                          │  │   • Carol (muted)        │
│              │  │                          │  ├──────────────────────────┤
│              │  │                          │  │  [🎙 Mute]   [⏻ Leave]   │
└──────────────┘  └──────────────────────────┘  └──────────────────────────┘
```

- Committed lines render in normal weight, prefixed with the speaker's name.
- The current partial line for the active speaker renders in a muted color/italic and updates as it streams.
- The panel auto-scrolls to the bottom on new lines unless the user has scrolled up (then a "Jump to latest" pill appears).

## User Flow
1. Participant joins a conference (per TICKET-001) and grants mic permission.
2. Client obtains a single-use Scribe token from our backend.
3. Client opens a WebSocket to Scribe v2 Realtime, sends a session config message, then begins streaming PCM audio chunks from their mic.
4. As Scribe returns `partial_transcript` and committed messages, the client forwards them to our conference server (via the existing room WebSocket from TICKET-001), tagged with the participant's display name.
5. Server fans the transcript events out to all other participants in the room.
6. Each client renders incoming events in the transcript panel.
7. On mute → client pauses sending audio chunks. On unmute → resumes.
8. On leave → client closes the Scribe WebSocket cleanly.

## Acceptance Criteria

1. When two or more participants are in a conference and speaking, each participant's speech appears in the transcript panel attributed to their display name, on every participant's screen.
2. Partial transcripts appear within ~1 second of speech and update live; committed lines replace partials in place.
3. Muting a participant stops new transcript lines from appearing for that participant until they unmute.
4. Leaving a conference closes that participant's Scribe WebSocket — no orphaned sessions left running.
5. The ElevenLabs API key is never present in client-side code or network requests reachable by the browser.
6. If Scribe disconnects mid-conference, the client attempts to reconnect (with backoff) and resumes transcription without disrupting the audio call itself.
7. After the conference ends, a participant can download a plain-text transcript of all committed lines, in chronological order, with speaker names and timestamps.
8. Transcript rendering does not block or jank the audio call — UI updates are throttled appropriately.

## Technical Notes

### ElevenLabs Scribe v2 Realtime
- Endpoint: WebSocket. Auth via `xi-api-key` header (server-side) or `token` query param using the single-use token endpoint (client-side).
- Model ID: `scribe_v2_realtime`.
- Audio format: PCM 16-bit, 16 kHz mono is a good default. Browser mic capture is typically 48 kHz — resample with an `AudioWorklet` or downsample server-side.
- Send audio as `input_audio_chunk` messages with base64-encoded audio.
- Receive `partial_transcript` (interim) and committed transcript messages. Use VAD-based auto-commit (default) for MVP.
- Pricing (current): ~$0.39/hour of audio. With per-participant streams, a 4-person 1-hour conference = ~$1.56 in STT costs. Worth flagging to product.

### Architecture decisions
- **Per-participant streams** are required because realtime diarization isn't available. This means concurrency cost scales linearly with participants — confirm we're under ElevenLabs' concurrency limit for our plan.
- **Client-side vs server-side WebSocket to Scribe**: client-side is simpler and lower-latency but requires the single-use token flow. Server-side gives us a chokepoint for logging/billing/abuse control. **Recommend client-side for MVP** unless the team has a reason to centralize.
- **Transcript fan-out**: reuse the existing conference room WebSocket from TICKET-001 — don't open a second channel. Wrap transcript events in a typed message so the client can route them.
- **Throttling**: partial transcripts can fire many times per second. Coalesce updates to ~10 fps in the UI.

### Data model (in-memory per conference)
```
TranscriptLine {
  id: string
  conferenceId: string
  speakerId: string         // attendee id from TICKET-001
  speakerName: string       // snapshot at time of speaking
  text: string
  startedAt: timestamp
  committedAt: timestamp
  isPartial: boolean        // false for the persisted log
}
```

## Risks / Open Questions
- **Cost at scale**: per-participant streams mean a 20-person all-hands burns ~$7.80/hour. Need product sign-off on whether to cap participant transcription or make it opt-in per-room.
- **Concurrency limits**: ElevenLabs caps concurrent Scribe v2 Realtime sessions per account. Confirm our tier supports the expected peak (e.g., 5 conferences × 10 participants = 50 concurrent streams).
- **Browser audio resampling**: 48 kHz → 16 kHz in an AudioWorklet adds complexity. Alternative: stream 48 kHz PCM if Scribe accepts it (it does — 8-48 kHz supported), at higher bandwidth cost.
- **Cross-talk attribution edge case**: if two people talk simultaneously, both transcripts will arrive nearly at once. Order them by `startedAt`, not `committedAt`, in the UI.
- **Should the transcript be visible to attendees, or host-only?** Default to visible-to-all for MVP.
- **Privacy / consent**: participants should be informed before joining that the conference is transcribed. Add a notice on the join screen.

## Definition of Done
- All acceptance criteria pass in a manual test with at least 3 participants speaking in turn and overlapping.
- One participant joining/leaving mid-conference does not disrupt others' transcripts.
- Cost telemetry captured for the test session and recorded in the PR description.
- Code reviewed and merged to `main`; deployed to staging.
- Privacy notice added to the join screen.
- README updated with how to set the `ELEVENLABS_API_KEY` env var and (if used) the token-issuing endpoint.