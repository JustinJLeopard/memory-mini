from __future__ import annotations

import argparse
import json
from datetime import timedelta

from memory_mini.store import Store


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memory-mini")
    parser.add_argument("--db", default="memory-mini.db", help="SQLite database path")
    sub = parser.add_subparsers(dest="command", required=True)

    store = sub.add_parser("store", help="Store a value. Upsert is on by default and recommended.")
    store.add_argument("key")
    store.add_argument("value")
    store.add_argument("--namespace", "--ns", default=None)
    store.add_argument("--metadata", default="{}")
    store.add_argument("--upsert", action=argparse.BooleanOptionalAction, default=True)

    get = sub.add_parser("get", help="Get an active value")
    get.add_argument("key")
    get.add_argument("--namespace", "--ns", default=None)
    get.add_argument("--include-deleted", action="store_true")

    list_cmd = sub.add_parser("list", help="List values")
    list_cmd.add_argument("--namespace", "--ns", default=None)
    list_cmd.add_argument("--include-deleted", action="store_true")

    search = sub.add_parser("search", help="Search values")
    search.add_argument("text")
    search.add_argument("--namespace", "--ns", default=None)
    search.add_argument("--mode", choices=["prefix", "regex", "fts"], default="prefix")

    soft_delete = sub.add_parser("soft-delete", help="Mark a value as soft-deleted")
    soft_delete.add_argument("key")
    soft_delete.add_argument("--namespace", "--ns", default=None)

    cleanup = sub.add_parser("cleanup", help="Hard-remove soft-deleted values after retention")
    cleanup.add_argument("--retention-days", type=int, default=30)
    cleanup.add_argument("--all-deleted", action="store_true")

    sub.add_parser("stats", help="Show counts by status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    with Store(args.db) as store:
        if args.command == "store":
            stored = store.store(
                args.key,
                args.value,
                args.namespace,
                upsert=args.upsert,
                metadata=json.loads(args.metadata),
            )
            print(
                json.dumps(
                    {"key": stored.key, "namespace": stored.namespace, "status": stored.status}
                )
            )
        elif args.command == "get":
            found = store.get(args.key, args.namespace, include_deleted=args.include_deleted)
            print("" if found is None else found.value)
        elif args.command == "list":
            for entry in store.list(args.namespace, include_deleted=args.include_deleted):
                print(f"{entry.namespace}\t{entry.key}\t{entry.status}\t{entry.value}")
        elif args.command == "search":
            for entry in store.search(args.text, args.namespace, mode=args.mode):
                print(f"{entry.namespace}\t{entry.key}\t{entry.value}")
        elif args.command == "soft-delete":
            print("deleted" if store.soft_delete(args.key, args.namespace) else "missing")
        elif args.command == "cleanup":
            retention = None if args.all_deleted else timedelta(days=args.retention_days)
            print(store.cleanup(retention=retention, all_deleted=args.all_deleted))
        elif args.command == "stats":
            print(json.dumps(store.stats(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
