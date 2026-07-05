"""Command-line entry point: ``workspace-manager <command>``.

Commands:
  janitor [--apply]   scan for large+stale items; dry-run by default
  sort    [--dry-run] classify & file new downloads
  report              write a file-system state report
"""

from __future__ import annotations

import argparse
import sys

from . import config as config_mod
from . import __version__


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="workspace-manager",
        description="Reproducible, LLM-driven macOS file organization.")
    ap.add_argument("--version", action="version",
                    version=f"workspace-manager {__version__}")
    ap.add_argument("--config", help="path to a config.yaml (overrides default)")
    sub = ap.add_subparsers(dest="command", required=True)

    p_jan = sub.add_parser("janitor", help="flag large + stale items for review")
    p_jan.add_argument("--apply", action="store_true",
                       help="move flagged items into the review folder "
                            "(default: dry-run, nothing moves)")

    p_sort = sub.add_parser("sort", help="classify & file new downloads")
    p_sort.add_argument("--dry-run", action="store_true",
                        help="show classifications without moving anything "
                             "(still calls the LLM — respects --limit)")
    p_sort.add_argument("--limit", type=int, default=None,
                        help="max items to classify this run (0 = unlimited; "
                             "default: config sort_batch_limit)")
    p_sort.add_argument("--set-baseline", action="store_true",
                        help="record now as the cutoff and exit: only downloads "
                             "created after this moment will ever be sorted "
                             "(ignores the existing backlog)")
    p_sort.add_argument("--all-existing", action="store_true",
                        help="ignore the baseline and sort pre-existing files too "
                             "(use to clear a backlog on demand)")

    sub.add_parser("report", help="write a file-system state report")

    args = ap.parse_args(argv)
    cfg = config_mod.load(
        __import__("pathlib").Path(args.config) if args.config else None)

    if args.command == "janitor":
        from . import janitor
        return janitor.run(cfg, apply=args.apply)
    if args.command == "sort":
        from . import download_sorter
        if args.set_baseline:
            return download_sorter.set_baseline(cfg)
        return download_sorter.run(cfg, dry_run=args.dry_run, limit=args.limit,
                                   all_existing=args.all_existing)
    if args.command == "report":
        from . import reporter
        return reporter.run(cfg)
    ap.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
