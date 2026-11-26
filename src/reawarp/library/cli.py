"""Command-line interface for the local Reawarp sample/stem library."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from reawarp.library.store import SampleLibrary, default_database_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reawarp-library",
        description="Index, search, collect, and trace Reawarp audio assets.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=default_database_path(),
        help="SQLite library database (default: ~/.reawarp/library.sqlite3)",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    index = commands.add_parser(
        "index", help="index a file, directory, or exported project"
    )
    index.add_argument("path", type=Path)

    search = commands.add_parser(
        "search", help="search by name, role, tags, or audio similarity"
    )
    search.add_argument(
        "--query", help="substring in file name, path, tags, or metadata"
    )
    search.add_argument(
        "--type", dest="asset_type", choices=("sample", "stem", "master")
    )
    search.add_argument("--role", help="asset role, e.g. kick, snare, melody, ambience")
    search.add_argument(
        "--tag", action="append", default=[], help="required tag (repeatable)"
    )
    search.add_argument(
        "--similar-to", help="asset ID or indexed file path to compare against"
    )
    search.add_argument("--limit", type=int, default=20)

    collections = commands.add_parser(
        "collections", help="manage named asset collections"
    )
    collection_commands = collections.add_subparsers(
        dest="collection_command", required=True
    )
    create = collection_commands.add_parser(
        "create", help="create or update a collection"
    )
    create.add_argument("name")
    create.add_argument("--description", default="")
    collection_commands.add_parser("list", help="list collections")
    add = collection_commands.add_parser("add", help="add assets to a collection")
    add.add_argument("name")
    add.add_argument("asset_ids", nargs="+")
    show = collection_commands.add_parser("show", help="show assets in a collection")
    show.add_argument("name")
    remove = collection_commands.add_parser(
        "remove", help="remove assets from a collection"
    )
    remove.add_argument("name")
    remove.add_argument("asset_ids", nargs="+")

    genealogy = commands.add_parser(
        "genealogy", help="show all variants in a project family"
    )
    genealogy.add_argument(
        "family_id", help="family ID returned when indexing project.json"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    with SampleLibrary(args.db) as library:
        if args.command == "index":
            path = args.path.expanduser()
            if path.is_file() and path.name == "project.json":
                result = library.index_project(path.parent)
            elif path.is_file():
                asset = library.index_file(path)
                result = {"assets_indexed": 1, "asset_id": asset.asset_id}
            elif path.is_dir() and (path / "project.json").is_file():
                result = library.index_project(path)
            elif path.is_dir():
                result = library.index_directory(path)
            else:
                parser.error(f"path does not exist: {path}")
                return
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return

        if args.command == "search":
            if (
                not args.query
                and not args.similar_to
                and not args.role
                and not args.tag
            ):
                parser.error(
                    "provide --query, --similar-to, --role, or at least one --tag"
                )
            results = library.search(
                query=args.query,
                asset_type=args.asset_type,
                role=args.role,
                tags=args.tag,
                similar_to=args.similar_to,
                limit=args.limit,
            )
            for asset in results:
                similarity = (
                    f" similarity={asset.similarity:.3f}"
                    if asset.similarity is not None
                    else ""
                )
                role = f" role={asset.role}" if asset.role else ""
                print(
                    f"{asset.asset_id}  {asset.asset_type}{role}{similarity}  "
                    f"{asset.duration_seconds:.2f}s  {asset.file_name}"
                )
            print(f"{len(results)} result(s)")
            return

        if args.command == "collections":
            if args.collection_command == "create":
                collection_id = library.create_collection(args.name, args.description)
                print(f"{args.name}: {collection_id}")
            elif args.collection_command == "list":
                print(json.dumps(library.collections(), indent=2, ensure_ascii=False))
            elif args.collection_command == "add":
                added = library.add_to_collection(args.name, args.asset_ids)
                print(f"Added {added} asset(s) to {args.name}")
            elif args.collection_command == "show":
                assets = library.collection_assets(args.name)
                for asset in assets:
                    print(f"{asset.asset_id}  {asset.asset_type}  {asset.file_name}")
                print(f"{len(assets)} asset(s)")
            elif args.collection_command == "remove":
                removed = library.remove_from_collection(args.name, args.asset_ids)
                print(f"Removed {removed} asset(s) from {args.name}")
            return

        if args.command == "genealogy":
            print(
                json.dumps(
                    library.genealogy(args.family_id), indent=2, ensure_ascii=False
                )
            )


if __name__ == "__main__":
    main()
