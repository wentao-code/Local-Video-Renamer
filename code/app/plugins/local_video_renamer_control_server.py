"""Standalone process entry point for the Local Video Renamer adapter."""

from __future__ import annotations

import argparse
import os
import threading

from .local_video_renamer_adapter import LocalVideoRenamerAdapter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local Video Renamer Feishu plugin control adapter"
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("LOCAL_VIDEO_RENAMER_CONTROL_HOST", "127.0.0.1"),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("LOCAL_VIDEO_RENAMER_CONTROL_PORT", "8763")),
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("FEISHU_CONTROL_TOKEN", ""),
        help="Bearer token; defaults to FEISHU_CONTROL_TOKEN",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(
            os.environ.get("LOCAL_VIDEO_RENAMER_CONTROL_TIMEOUT", "2")
        ),
    )
    return parser


def run_service(
    *,
    host: str,
    port: int,
    token: str,
    command_timeout: float = 2.0,
    stop_event: threading.Event | None = None,
) -> None:
    if not str(token).strip():
        raise ValueError("FEISHU_CONTROL_TOKEN is required")

    adapter = LocalVideoRenamerAdapter()
    control = adapter.create_control_server(
        token=token,
        host=host,
        port=port,
        command_timeout=command_timeout,
    )
    control.start_in_thread()
    print(f"Local Video Renamer control adapter listening on {control.base_url}")
    waiter = stop_event or threading.Event()
    try:
        while not waiter.wait(0.1):
            control.drain()
    finally:
        control.stop()


def main() -> None:
    args = build_parser().parse_args()
    run_service(
        host=args.host,
        port=args.port,
        token=args.token,
        command_timeout=args.timeout,
    )


if __name__ == "__main__":
    main()
