"""Command line entry point for `voice-dictation`."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Sequence

from . import __version__, launch_agent
from .config import Settings

COMMANDS = ("run", "install-launch-agent", "uninstall-launch-agent")


def _add_run_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="log debug details, including the dictated text",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="voice-dictation",
        description=(
            "Offline push-to-talk dictation: hold Right Option, speak, release to paste. "
            "With no command, 'run' is assumed."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    run = sub.add_parser("run", help="start listening for Right Option (default)")
    _add_run_options(run)
    install = sub.add_parser(
        "install-launch-agent",
        help="start voice-dictation at login (run options given here are kept)",
    )
    _add_run_options(install)
    sub.add_parser("uninstall-launch-agent", help="stop it starting at login and remove it")
    return parser


def settings_from_args(args: argparse.Namespace) -> Settings:
    return Settings(verbose=args.verbose)


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "run")
    args = build_parser().parse_args(argv)

    if args.command == "install-launch-agent":
        return _install(run_args=argv[1:])
    if args.command == "uninstall-launch-agent":
        return _uninstall()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    if not args.verbose:
        # Keep third-party chatter (HTTP requests, numba) out of the log.
        for noisy in ("httpx", "huggingface_hub", "numba", "urllib3"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    from .app import run

    return run(settings_from_args(args))


def _install(run_args: Sequence[str]) -> int:
    python = sys.executable
    try:
        paths = launch_agent.install(python, run_args)
    except RuntimeError as exc:
        print(f"Could not load the LaunchAgent: {exc}", file=sys.stderr)
        return 1
    real_python = os.path.realpath(python)
    uid = os.getuid()
    print(f"Installed {launch_agent.LABEL}: it is running now and will start at every login.")
    print(f"  plist: {paths.plist}")
    print(f"  log:   {paths.log}")
    print()
    print("The agent runs this Python binary, which needs its own permissions in")
    print("System Settings > Privacy & Security:")
    print(f"  {real_python}")
    print("  - Accessibility and Input Monitoring: click +, press Cmd+Shift+G, paste the path.")
    print("  - Microphone: macOS asks the first time you dictate.")
    print("After granting them, restart the agent:")
    print(f"  launchctl kickstart -k gui/{uid}/{launch_agent.LABEL}")
    return 0


def _uninstall() -> int:
    paths, existed = launch_agent.uninstall()
    if existed:
        print(f"Removed {launch_agent.LABEL} ({paths.plist}); it will no longer start at login.")
    else:
        print(f"{launch_agent.LABEL} was not installed; nothing to remove.")
    return 0
