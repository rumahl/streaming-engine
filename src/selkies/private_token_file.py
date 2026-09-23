# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Load an operator token from a private file without exposing it in argv."""

import os
import stat


def read_private_token_file(path: str) -> str:
    """Read a one-line token from a non-symlink file owned by this user.

    Args:
        path: Absolute path to the provisioned secret.

    Returns:
        The token without one optional final newline.

    Raises:
        ValueError: The path, file permissions, or contents are unsafe.
    """
    if not os.path.isabs(path):
        raise ValueError("master_token_file must be an absolute path")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise ValueError("master_token_file requires O_NOFOLLOW support")
    descriptor = os.open(path, os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0))
    try:
        details = os.fstat(descriptor)
        if not stat.S_ISREG(details.st_mode):
            raise ValueError("master_token_file must be a regular file")
        if details.st_uid != os.geteuid() or details.st_mode & 0o077:
            raise ValueError("master_token_file must be owned by the service user and private")
        with os.fdopen(descriptor, "rb", closefd=False) as secret_file:
            contents = secret_file.read(4097)
        if len(contents) > 4096:
            raise ValueError("master_token_file is too large")
        if contents.endswith(b"\n"):
            contents = contents[:-1]
        try:
            token = contents.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError("master_token_file must contain UTF-8") from error
        if not token or any(character.isspace() for character in token):
            raise ValueError("master_token_file must contain one nonempty token")
        return token
    finally:
        os.close(descriptor)
