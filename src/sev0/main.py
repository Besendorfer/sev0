from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from sev0.config import load_config
from sev0.engine import Engine
from sev0.scheduler import create_scheduler

logger = logging.getLogger("sev0")


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def _cmd_run(args: argparse.Namespace) -> None:
    """Run the scheduler and listeners (both flows)."""
    config = load_config(args.config)
    engine = Engine(config)
    await engine.initialize()

    scheduler = create_scheduler(config, engine)
    scheduler.start()
    logger.info("Scheduler started. Press Ctrl+C to stop.")

    try:
        if config.channels:
            await engine.start_listeners()
        else:
            # No listeners — just keep the scheduler running
            while True:
                await asyncio.sleep(3600)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Shutting down...")
    finally:
        scheduler.shutdown()
        await engine.shutdown()


async def _cmd_sweep(args: argparse.Namespace) -> None:
    """Run a single sweep (one-shot)."""
    config = load_config(args.config)
    engine = Engine(config)
    await engine.initialize()

    try:
        results = await engine.sweep()
        for r in results:
            status = "TICKET" if r.action_results else "TRIAGED"
            urls = ", ".join(ar.url for ar in r.action_results if ar.url)
            print(f"[{status}] [{r.severity.value.upper()}] {r.summary}")
            if urls:
                print(f"         -> {urls}")
    finally:
        await engine.shutdown()


async def _cmd_check(args: argparse.Namespace) -> None:
    """Validate config and test connectivity."""
    try:
        config = load_config(args.config)
        print(f"Config loaded: {args.config}")
        print(f"  Sources:  {', '.join(s.type for s in config.sources) or '(none)'}")
        print(f"  Channels: {', '.join(c.type for c in config.channels) or '(none)'}")
        print(f"  Actions:  {', '.join(a.type for a in config.actions) or '(none)'}")
        print(f"  Schedule: {', '.join(s.cron for s in config.schedule) or '(none)'}")
        print(f"  Model:    {config.triage.model}")
        print(f"  Dedup:    {config.dedup.db_path} (TTL: {config.dedup.ttl_hours}h)")

        engine = Engine(config)
        await engine.initialize()
        await engine.shutdown()
        print("\nAll adapters initialized successfully.")
    except Exception as e:
        print(f"\nConfig check failed: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sev0",
        description="AI-powered on-call triage agent",
    )
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="Path to config file (default: config.yaml)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run", help="Start scheduler and listeners")
    subparsers.add_parser("sweep", help="Run a single sweep (one-shot)")
    subparsers.add_parser("check", help="Validate config and test connectivity")

    args = parser.parse_args()
    _setup_logging(args.verbose)

    commands = {
        "run": _cmd_run,
        "sweep": _cmd_sweep,
        "check": _cmd_check,
    }

    asyncio.run(commands[args.command](args))


if __name__ == "__main__":
    main()
