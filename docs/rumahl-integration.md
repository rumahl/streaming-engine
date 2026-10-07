# rumahl OS integration

The rumahl Streaming Engine is an optional, shared installation. It provides
`com.rumahl.streaming.v1`; rumahl OS decides when to start and stop an isolated
session. A session runs one Selkies process with its own Unix socket. No worker
needs to stay active when no streamed app is open. Selkies remains the media
engine; the rumahl Shell owns windows, focus, layout, and permissions.

`rumahl-streaming-session` reads one JSON document from private standard input
and replaces itself with `selkies`. Only the trusted OS supervisor may provide
this document. The manifest of a streamed app may request a preferred size and
frame rate, but cannot directly supply this session document or override its
transport, listener, permissions, or codec. The OS validates app preferences
and resolves them against system policy before starting the session.

```json
{
  "capability": "com.rumahl.streaming.v1",
  "session_id": "4485f47e-a1cd-4b7b-a7c2-203086be13f5",
  "unix_socket": "/run/rumahl/streaming/4485f47e-a1cd-4b7b-a7c2-203086be13f5.sock",
  "master_token_file": "/run/rumahl/secrets/4485f47e-a1cd-4b7b-a7c2-203086be13f5.token",
  "transport": "websockets",
  "max_frame_rate": 60,
  "initial_frame_rate": 30,
  "policy": {
    "audio": false,
    "microphone": false,
    "camera": false,
    "clipboard_to_app": false,
    "clipboard_from_app": false,
    "file_upload": false,
    "file_download": false,
    "printing": false
  }
}
```

All fields are required; unknown fields and unknown capability versions are
rejected. Session IDs must be canonical UUIDs, paths must be absolute and free
of traversal components, and frame rates must be in the versioned contract's
1–120 range. The adapter disables Selkies' sharing, mode switching, raw
commands, gamepads, and Basic authentication. It locks the media capabilities
to the OS policy and passes the selected token *file path*, never its value, to
Selkies. The token file must be a private regular file owned by the service
user; symlinks are refused. The OS must mount its parent directory privately,
outside the streamed app's filesystem view.

The OS gateway must authenticate each browser connection, translate it to a
session-scoped Selkies credential, and proxy the Unix socket without exposing
the master token or the socket. The stock Selkies client still puts its access
token in a URL; it is not yet a production rumahl Shell renderer. The gateway,
short-lived browser grants, Shell renderer, and per-app container lifecycle
remain separate integration work. Until these are implemented, this adapter
is a backend contract and secure launch path, not an end-to-end app feature.
