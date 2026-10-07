# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Translate one OS-authorized session into a constrained Selkies process.

The supervisor supplies a private JSON document on stdin for each active
session. Apps do not invoke this entry point and cannot choose a transport,
listener, codec, or permission. One process owns one Unix socket and exits
with that session; the OS starts and stops it on demand. The browser-facing
gateway and its short-lived access grants belong to rumahl OS, not here.
"""

import json
import os
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set


CAPABILITY = "com.rumahl.streaming.v1"
MAX_SPEC_BYTES = 65536


def _object(value: Any, keys: Set[str], label: str) -> Dict[str, Any]:
    """Require an object with exactly the specified keys."""
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} must contain exactly: {', '.join(sorted(keys))}")
    return value


def _boolean(value: Any, label: str) -> bool:
    """Reject JSON numbers and strings where a policy boolean is expected."""
    if type(value) is not bool:
        raise ValueError(f"{label} must be a boolean")
    return value


def _path(value: Any, label: str) -> str:
    """Require an absolute path without traversal or control characters."""
    if (not isinstance(value, str) or not os.path.isabs(value)
            or any(part in (".", "..") for part in value.split(os.sep))
            or any(ord(character) < 32 for character in value)):
        raise ValueError(f"{label} must be a clean absolute path")
    return value


@dataclass(frozen=True)
class SessionPolicy:
    """Permissions resolved by rumahl OS, not requested by the app."""

    audio: bool
    microphone: bool
    camera: bool
    clipboard_to_app: bool
    clipboard_from_app: bool
    file_upload: bool
    file_download: bool
    printing: bool

    @classmethod
    def parse(cls, value: Any) -> "SessionPolicy":
        """Accept only explicit permission decisions and dependent capabilities."""
        keys = set(cls.__dataclass_fields__)
        data = _object(value, keys, "policy")
        policy = cls(**{key: _boolean(data[key], f"policy.{key}") for key in keys})
        if policy.microphone and not policy.audio:
            raise ValueError("microphone requires audio")
        return policy


@dataclass(frozen=True)
class SessionSpec:
    """Versioned, OS-owned configuration for one isolated stream session."""

    session_id: str
    unix_socket: str
    master_token_file: str
    transport: str
    max_frame_rate: int
    initial_frame_rate: int
    policy: SessionPolicy

    @classmethod
    def parse(cls, value: Any) -> "SessionSpec":
        """Validate the complete JSON contract without accepting extra knobs."""
        keys = {"capability", "session_id", "unix_socket", "master_token_file",
                "transport", "max_frame_rate", "initial_frame_rate", "policy"}
        data = _object(value, keys, "session")
        if data["capability"] != CAPABILITY:
            raise ValueError("unsupported streaming capability")
        session_id = data["session_id"]
        try:
            if not isinstance(session_id, str) or str(uuid.UUID(session_id)) != session_id:
                raise ValueError("noncanonical UUID")
        except (ValueError, AttributeError) as error:
            raise ValueError("session_id must be a canonical UUID") from error
        transport = data["transport"]
        if transport not in ("websockets", "webrtc"):
            raise ValueError("transport must be websockets or webrtc")
        maximum = data["max_frame_rate"]
        initial = data["initial_frame_rate"]
        if type(maximum) is not int or not 1 <= maximum <= 120:
            raise ValueError("max_frame_rate must be 1-120")
        if type(initial) is not int or not 1 <= initial <= maximum:
            raise ValueError("initial_frame_rate must be 1-max_frame_rate")
        return cls(
            session_id=session_id,
            unix_socket=_path(data["unix_socket"], "unix_socket"),
            master_token_file=_path(data["master_token_file"], "master_token_file"),
            transport=transport,
            max_frame_rate=maximum,
            initial_frame_rate=initial,
            policy=SessionPolicy.parse(data["policy"]),
        )

    def selkies_command(self) -> List[str]:
        """Build server-owned settings; never pass the token value in argv."""
        policy = self.policy
        clipboard = (
            "true" if policy.clipboard_to_app and policy.clipboard_from_app else
            "in" if policy.clipboard_to_app else
            "out" if policy.clipboard_from_app else "false"
        )
        transfers = ",".join(
            direction for allowed, direction in (
                (policy.file_upload, "upload"),
                (policy.file_download, "download"),
            ) if allowed
        ) or "none"
        return [
            "selkies",
            "--unix-socket", self.unix_socket,
            "--master-token-file", self.master_token_file,
            "--enable-basic-auth=false",
            "--mode", self.transport,
            "--enable-dual-mode=false",
            "--enable-sharing=false",
            "--command-enabled=false",
            "--gamepad-enabled=false",
            "--audio-enabled", f"{str(policy.audio).lower()}|locked",
            "--audio-on-start", str(policy.audio).lower(),
            "--microphone-enabled", f"{str(policy.microphone).lower()}|locked",
            "--microphone-on-start", "false",
            "--webcam-enabled", f"{str(policy.camera).lower()}|locked",
            "--webcam-on-start", "false",
            "--enable-clipboard", clipboard,
            "--file-transfers", transfers,
            "--printing-enabled", f"{str(policy.printing).lower()}|locked",
            "--framerate", f"{self.initial_frame_rate},1-{self.max_frame_rate}",
        ]


def main(argv: Optional[List[str]] = None) -> None:
    """Replace this adapter with the on-demand Selkies session process.

    Args:
        argv: Optional argument vector for tests; production uses sys.argv.

    Raises:
        ValueError: Stdin contains a malformed or unsupported session spec.
    """
    arguments = sys.argv if argv is None else argv
    if len(arguments) != 1:
        raise ValueError("session spec must be supplied on stdin, not argv")
    document = sys.stdin.buffer.read(MAX_SPEC_BYTES + 1)
    if len(document) > MAX_SPEC_BYTES:
        raise ValueError("session spec is too large")
    spec = SessionSpec.parse(json.loads(document))
    command = spec.selkies_command()
    os.execvpe(command[0], command, os.environ.copy())


if __name__ == "__main__":
    main()
