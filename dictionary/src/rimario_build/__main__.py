"""CLI: ``rimario-build [fetch|build|report] [--offline] [--only ID] [-v]``."""

import argparse
import logging
import sys

from . import cache, fetch, pipeline

log = logging.getLogger("rimario_build")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rimario-build",
        description="Build the Super Rimario Italiano dictionary (default: fetch, then build).",
    )
    parser.add_argument("command", nargs="?", choices=("fetch", "build", "report"),
                        help="fetch: update data/raw/ and sources.lock.json; build: build out/ "
                             "from the local files; report: rewrite out/report.md from the cache")
    parser.add_argument("--offline", action="store_true", help="skip fetching, use the files on disk")
    parser.add_argument("--only", metavar="ID", help="fetch only this source and rerun its extractor")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args(argv)

    pipeline.setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    ids = [s["id"] for s in fetch.load_sources()]
    if args.only is not None and args.only not in ids:
        parser.error(f"unknown source {args.only!r}; known: {', '.join(ids)}")
    if args.command == "fetch" and args.offline:
        parser.error("fetch can't run --offline")
    if args.command == "report" and args.only is not None:
        parser.error("report reruns no stage, so it takes no --only")

    try:
        if args.command == "fetch":
            pipeline.run_fetch(args.only)
        elif args.command == "report":
            pipeline.regenerate_report()
        else:
            pipeline.run(do_fetch=args.command is None and not args.offline, only=args.only)
    except (fetch.FetchError, cache.CacheMiss) as e:
        log.error("%s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
