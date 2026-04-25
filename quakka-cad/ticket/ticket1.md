# TICKET-001: Voice Conference MVP — Create & Join Flow with Basic Layout

## Summary
Build the foundational MVP of a voice-only conference platform aimed at engineering teams. A host creates a conference, gets a shareable link, and attendees join through that link by entering only their name (no camera, no screen share). The conference UI uses a three-column layout with placeholder content in the two left columns and an attendee list plus basic controls in the right column.

## Goal
Deliver an end-to-end happy path: create a conference → share link → attendees join with name only → everyone can talk and hear each other → attendees can mute/unmute and leave.

## Scope

### In scope
- Conference creation by a host (generates a unique conference ID and shareable join link).
- Join flow via link `/<conference-id>` — prompts only for a display name, no auth.
- Voice-only WebRTC audio between all participants (mesh or SFU; SFU recommended if expecting >4 participants).
- Three-column conference layout:
  - **Left column**: empty gray placeholder box.
  - **Middle column**: empty gray placeholder box.
  - **Right column**: attendee list (bottom area) + control bar below it (mute/unmute mic, leave meeting).
- Real-time attendee list updates (join/leave events).
- Mute/unmute mic control with visual state.
- Leave meeting control that disconnects cleanly and returns the user to a simple post-leave screen.

### Out of scope (explicitly deferred)
- Video, screen share, chat, recording.
- Authentication, accounts, persistence of past conferences.
- Permissions/roles beyond "host vs attendee" (host has no special powers in this ticket).
- Content for the two left columns — they remain gray placeholders.
- Mobile-specific layouts (desktop-first; mobile can be a follow-up).

## User Flows

### Host
1. Host visits the landing page and clicks "Create conference".
2. Backend generates a conference ID; host is redirected to `/<conference-id>`.
3. Host is prompted for their display name, grants mic permission, and enters the room.
4. Host copies the shareable link from the UI to send to attendees.

### Attendee
1. Attendee opens the shared link `/<conference-id>`.
2. Prompted for display name only.
3. Browser requests mic permission.
4. On grant, attendee joins the room and appears in the attendee list for everyone.

## UI Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐   │
│  │              │  │              │  │                          │   │
│  │   (gray      │  │   (gray      │  │    (empty / reserved)    │   │
│  │  placeholder)│  │  placeholder)│  │                          │   │
│  │              │  │              │  │                          │   │
│  │              │  │              │  ├──────────────────────────┤   │
│  │              │  │              │  │  Attendees               │   │
│  │              │  │              │  │   • Alice (host)         │   │
│  │              │  │              │  │   • Bob                  │   │
│  │              │  │              │  │   • Carol (muted)        │   │
│  │              │  │              │  ├──────────────────────────┤   │
│  │              │  │              │  │  [🎙 Mute]   [⏻ Leave]   │   │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

- Three equal-width columns on desktop.
- Right column is split vertically: top area reserved/empty, bottom area contains attendee list, and control bar sits below the list.
- Muted attendees have a clear visual indicator (e.g., mic-off icon) next to their name.

## Acceptance Criteria

1. A host can create a conference and receives a unique URL of the form `/<conference-id>`.
2. Anyone with the link can join by entering only a display name — no signup, no login.
3. Two or more participants on the same conference ID can hear each other in real time with acceptable latency (<500 ms perceived).
4. The attendee list updates within ~2 seconds when someone joins or leaves.
5. The mute button toggles the local mic; other participants stop receiving audio from a muted user immediately, and the muted user is visually marked as muted in everyone's attendee list.
6. The leave button disconnects the user, removes them from everyone's attendee list, and returns them to a simple "You left the meeting" screen.
7. The layout renders as three columns with the two left columns gray and the right column containing the attendee list and controls as specified.
8. Closing the browser tab is treated as leaving (cleaned up server-side within ~10 seconds).

## Technical Notes

- **Audio transport**: WebRTC. For ≤4 participants, mesh is fine; for larger rooms use an SFU (e.g., LiveKit, mediasoup, Janus). Recommend starting with **LiveKit** to avoid hand-rolling signaling.
- **Signaling / state**: WebSocket-based room state for attendee list and join/leave events. If using LiveKit, rely on its room events.
- **Conference ID**: short URL-safe random string (e.g., 8-char nanoid); collision-checked on creation.
- **No persistence required** — conferences exist only while at least one participant is connected; remove the room when the last participant leaves.
- **Frontend**: any modern framework (React recommended). Keep components for `JoinScreen`, `ConferenceRoom`, `AttendeeList`, `ControlBar`, and `PlaceholderColumn`.
- **Browser support**: latest Chrome, Firefox, Safari, Edge.

## Risks / Open Questions
- Confirm SFU choice (LiveKit vs mediasoup vs self-hosted Janus) before implementation — affects deploy footprint.
- Mic permission denial flow: should the user be allowed to join as a listener, or blocked? Default for this ticket: blocked, with a clear error message.
- Maximum participants per conference for MVP — suggest capping at 20 for now.

## Definition of Done
- All acceptance criteria pass in a manual test with at least 3 participants across 2 different networks.
- Code reviewed and merged to `main`.
- Deployed to a staging environment with a working shareable link.
- Short README section documenting how to run locally and how to create/join a conference.