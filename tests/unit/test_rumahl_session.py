#!/usr/bin/env python3
"""Source-only checks for the rumahl OS session adapter and token-file path."""

import copy
import io
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rumahl_streaming.session import CAPABILITY, SessionSpec, main  # noqa: E402
from selkies.private_token_file import read_private_token_file  # noqa: E402
from selkies.settings import AppSettings, SETTING_DEFINITIONS  # noqa: E402


def session_data() -> dict:
    """Build a policy with every decision explicit and no optional privilege."""
    return {
        "capability": CAPABILITY,
        "session_id": str(uuid.uuid4()),
        "unix_socket": "/run/rumahl/streaming/session.sock",
        "master_token_file": "/run/rumahl/secrets/stream-token",
        "transport": "websockets",
        "max_frame_rate": 60,
        "initial_frame_rate": 30,
        "policy": {
            "audio": False,
            "microphone": False,
            "camera": False,
            "clipboard_to_app": False,
            "clipboard_from_app": False,
            "file_upload": False,
            "file_download": False,
            "printing": False,
        },
    }


class RumahlSessionTest(unittest.TestCase):
    """Exercise the OS-owned contract through the actual Selkies parser."""

    def test_default_policy_is_locked_down(self) -> None:
        """A minimal session cannot enable sharing or peripheral access."""
        spec = SessionSpec.parse(session_data())
        command = spec.selkies_command()
        self.assertIn("--unix-socket", command)
        self.assertIn("--master-token-file", command)
        self.assertNotIn("--master-token", command)
        self.assertIn("--enable-sharing=false", command)
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "secret"
            token_path.write_text("a" * 48, encoding="utf-8")
            token_path.chmod(0o600)
            command[command.index("--master-token-file") + 1] = str(token_path)
            with mock.patch.object(sys, "argv", command), mock.patch.dict(os.environ, {}, clear=True):
                settings = AppSettings(copy.deepcopy(SETTING_DEFINITIONS))
        self.assertEqual(settings.master_token, "a" * 48)
        self.assertEqual(settings.unix_socket, spec.unix_socket)
        self.assertEqual(settings.mode, "websockets")
        self.assertEqual(settings.framerate, (1, 60))
        self.assertEqual(settings.audio_enabled, (False, True))
        self.assertEqual(settings.microphone_enabled, (False, True))
        self.assertEqual(settings.webcam_enabled, (False, True))
        self.assertEqual(settings.enable_clipboard, "false")
        self.assertEqual(settings.file_transfers, [])
        self.assertEqual(settings.printing_enabled, (False, True))
        self.assertFalse(settings.enable_sharing[0])
        self.assertFalse(settings.enable_dual_mode[0])
        self.assertFalse(settings.enable_basic_auth[0])

    def test_permissions_map_without_enabling_other_features(self) -> None:
        """An allowed microphone or file upload needs an explicit OS decision."""
        data = session_data()
        data["transport"] = "webrtc"
        data["policy"].update(audio=True, microphone=True, camera=True,
                              clipboard_to_app=True, file_upload=True)
        command = SessionSpec.parse(data).selkies_command()
        self.assertEqual(command[command.index("--mode") + 1], "webrtc")
        self.assertEqual(command[command.index("--enable-clipboard") + 1], "in")
        self.assertEqual(command[command.index("--file-transfers") + 1], "upload")
        self.assertEqual(command[command.index("--microphone-enabled") + 1], "true|locked")
        self.assertIn("--enable-sharing=false", command)

    def test_rejects_app_infrastructure_knobs(self) -> None:
        """Unknown fields fail closed instead of reaching Selkies settings."""
        for field, value in (("codec", "h264"), ("public", True), ("master_token", "bad")):
            with self.subTest(field=field):
                data = session_data()
                data[field] = value
                with self.assertRaises(ValueError):
                    SessionSpec.parse(data)

    def test_rejects_missing_or_invalid_policy(self) -> None:
        """Permissions cannot fall back to Selkies' more permissive defaults."""
        data = session_data()
        del data["policy"]["file_download"]
        with self.assertRaises(ValueError):
            SessionSpec.parse(data)
        data = session_data()
        data["policy"]["camera"] = 1
        with self.assertRaises(ValueError):
            SessionSpec.parse(data)
        data = session_data()
        data["policy"]["microphone"] = True
        with self.assertRaises(ValueError):
            SessionSpec.parse(data)

    def test_rejects_invalid_paths_and_rates(self) -> None:
        """Version, private paths, and bounded frame rates are mandatory."""
        for field, value in (("capability", "com.rumahl.streaming.v2"),
                             ("unix_socket", "relative.sock"),
                             ("master_token_file", "/tmp/../secret"),
                             ("max_frame_rate", 121),
                             ("initial_frame_rate", 61),
                             ("transport", "other")):
            with self.subTest(field=field):
                data = session_data()
                data[field] = value
                with self.assertRaises(ValueError):
                    SessionSpec.parse(data)

    def test_token_file_rejects_symlink_and_shared_permissions(self) -> None:
        """Secrets never load from a symlink or a group-readable file."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "token"
            path.write_text("a" * 48 + "\n", encoding="utf-8")
            path.chmod(0o600)
            self.assertEqual(read_private_token_file(str(path)), "a" * 48)
            path.chmod(0o640)
            with self.assertRaises(ValueError):
                read_private_token_file(str(path))
            path.chmod(0o600)
            link = Path(directory) / "link"
            link.symlink_to(path)
            with self.assertRaises(OSError):
                read_private_token_file(str(link))

    def test_adapter_execs_without_token_in_arguments(self) -> None:
        """Production entry point reads stdin and replaces only its own process."""
        document = io.TextIOWrapper(io.BytesIO(json.dumps(session_data()).encode()))
        with mock.patch.object(sys, "stdin", document), mock.patch("os.execvpe") as execute:
            main(["rumahl-streaming-session"])
        command = execute.call_args.args[1]
        self.assertEqual(command[0], "selkies")
        self.assertNotIn("a" * 48, " ".join(command))
        self.assertEqual(command[command.index("--unix-socket") + 1],
                         "/run/rumahl/streaming/session.sock")


if __name__ == "__main__":
    unittest.main()
