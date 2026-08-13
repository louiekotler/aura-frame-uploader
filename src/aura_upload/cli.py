"""Command line interface."""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from . import images
from .auth import load_session, login, logout
from .client import AuraClient
from .config import load_config
from .errors import AuraError
from .backends.api import ApiBackend

log = logging.getLogger("aura_upload")

BACKENDS = {"api": ApiBackend}


def _emit(payload: dict, as_json: bool):
    if as_json:
        print(json.dumps(payload, indent=2, default=str))


def cmd_login(args, cfg):
    email = args.email or cfg.account_email
    if not email:
        raise AuraError("Pass --email, or set account.email in your config file.")
    session = login(email, args.password)
    print(f"Logged in as {session.get('name') or email} ({session['user_id']})")
    print("Token stored in the system keyring. Your password was not saved.")
    return 0


def cmd_logout(args, cfg):
    print("Stored session removed." if logout() else "No stored session to remove.")
    return 0


def cmd_frames(args, cfg):
    client = AuraClient.from_keyring()
    frames = client.frames()
    rows = [
        {
            "id": f.get("id"),
            "name": f.get("name"),
            "num_assets": f.get("num_assets"),
            "aspect": f.get("display_aspect_ratio"),
            "model": f.get("matting_color"),
            "allowed": cfg.is_allowed(f.get("id", "")),
        }
        for f in frames
    ]
    if args.json:
        _emit({"frames": rows}, True)
        return 0

    print(f"{len(rows)} frame(s) on this account:\n")
    for r in rows:
        mark = "allowed" if r["allowed"] else "NOT allowed — writes refused"
        print(f"  {r['name']}")
        print(f"    id      {r['id']}   [{mark}]")
        print(f"    panel   {r['aspect']}  {r['model']}   photos: {r['num_assets']}")
        print()
    if not cfg.allowed_frame_ids:
        print("No allowed_frame_ids configured — every write will be refused.")
        print(f"Add the id(s) you want to publish to in {cfg.path}.")
    return 0


def cmd_list(args, cfg):
    frame_id = cfg.resolve_frame(args.frame)
    client = AuraClient.from_keyring()
    assets = client.all_assets(frame_id)
    matched = [
        a for a in assets
        if not args.match or args.match in (a.get("local_identifier") or "")
    ]
    if args.json:
        _emit({"frame_id": frame_id, "count": len(assets), "assets": matched}, True)
        return 0

    print(f"{len(assets)} asset(s) listed on {frame_id}")
    if args.match:
        print(f"{len(matched)} matching {args.match!r}")
    for a in matched[: args.limit]:
        print(f"  {a.get('id')}  {a.get('local_identifier')!r}  "
              f"{a.get('width')}x{a.get('height')}  {a.get('taken_at')}")
    return 0


def cmd_upload(args, cfg):
    # Resolve the frame before anything else so a refused target fails fast,
    # independently of whether there is a usable session.
    frame_id = cfg.resolve_frame(args.frame)
    client = AuraClient.from_keyring()
    backend = BACKENDS[args.backend](client)

    target = Path(args.path).expanduser()
    paths = images.collect(target, recursive=args.recursive)
    if args.max:
        paths = paths[: args.max]
    if not paths:
        print(f"No supported images found in {target}")
        return 1

    if args.local_id and len(paths) > 1:
        raise AuraError("--local-id applies to a single file, but multiple were found.")

    # Identifier -> asset id, so a skip can still report which asset already
    # holds this photo. Callers need that id to record the photo as published.
    existing = {}
    if not args.force:
        existing = {
            a.get("local_identifier"): a.get("id") for a in client.all_assets(frame_id)
        }

    print(f"{len(paths)} image(s) -> frame {frame_id} via {backend.name}")
    if args.dry_run:
        print("(dry run — nothing will be uploaded)\n")

    results, failures, skipped = [], 0, []
    for i, path in enumerate(paths, 1):
        local_id = args.local_id or images.content_identifier(path)
        if local_id in existing and not args.force:
            skipped.append({"local_identifier": local_id, "asset_id": existing[local_id],
                            "path": str(path)})
            print(f"  [{i}/{len(paths)}] {path.name}: already on the frame, skipping")
            continue
        try:
            prepared = images.prepare(path, cfg.max_long_edge, cfg.jpeg_quality)
            label = (
                f"  [{i}/{len(paths)}] {path.name}  {prepared.width}x{prepared.height}  "
                f"{len(prepared.data)/1024:.0f}KB  taken {prepared.taken_at:%Y-%m-%d} "
                f"({prepared.taken_at_source})"
            )
            if args.dry_run:
                print(label + "  [would upload]")
                results.append({"path": str(path), "local_identifier": local_id,
                                "dry_run": True})
                continue

            ref = backend.upload(prepared, local_id, frame_id)
            print(label + f"  -> {ref.asset_id}")
            results.append(
                {
                    "path": str(path),
                    "local_identifier": ref.local_identifier,
                    "asset_id": ref.asset_id,
                    "sha256": prepared.sha256,
                    "taken_at": prepared.taken_at,
                }
            )
        except AuraError as e:
            failures += 1
            print(f"  [{i}/{len(paths)}] {path.name}: FAILED — {e}", file=sys.stderr)
            # Rate limits are unmeasured, so stop rather than hammer a failing API.
            if not args.keep_going:
                print("Stopping. Re-run with --keep-going to continue past errors.",
                      file=sys.stderr)
                break
        if args.delay and i < len(paths):
            time.sleep(args.delay)

    print(f"\nuploaded {len(results)}  skipped {len(skipped)}  failed {failures}")
    if args.json:
        _emit({"frame_id": frame_id, "uploaded": results,
               "skipped": skipped, "failed": failures}, True)
    return 1 if failures else 0


def cmd_remove(args, cfg):
    frame_id = cfg.resolve_frame(args.frame)
    client = AuraClient.from_keyring()
    failed = client.remove_asset(
        frame_id, local_identifier=args.local_id, asset_id=args.asset_id
    )
    target = args.asset_id or args.local_id
    print(f"removed {target} from {frame_id}" if not failed
          else f"failed to remove {target} (number_failed={failed})")
    return 1 if failed else 0


def cmd_show(args, cfg):
    frame_id = cfg.resolve_frame(args.frame)
    client = AuraClient.from_keyring()
    asset_id = args.asset_id
    if not asset_id:
        asset = client.asset_for_local_identifier(args.local_id)
        if not asset:
            raise AuraError(f"No live asset for local identifier {args.local_id!r}.")
        asset_id = asset["id"]
    ok = client.show_asset(frame_id, asset_id)
    print(f"frame is showing {asset_id}" if ok else "frame did not acknowledge")
    return 0 if ok else 1


def cmd_whoami(args, cfg):
    s = load_session()
    print(f"{s.get('name')} <{s.get('email')}>  user_id={s['user_id']}")
    print(f"config: {cfg.path}")
    print(f"allowed frames: {', '.join(cfg.allowed_frame_ids) or '(none — writes refused)'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    # Accepted either side of the subcommand. SUPPRESS keeps the subparser copy
    # from overwriting a value already given before the subcommand.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="machine-readable output")
    common.add_argument("-v", "--verbose", action="store_true",
                        default=argparse.SUPPRESS)

    p = argparse.ArgumentParser(
        prog="aura-upload",
        description="Publish photos to an Aura digital picture frame.",
        parents=[common],
    )
    sub = p.add_subparsers(dest="command", required=True, parser_class=lambda **kw:
                           argparse.ArgumentParser(parents=[common], **kw))

    lg = sub.add_parser("login", help="authenticate and store a token in the keyring")
    lg.add_argument("--email")
    lg.add_argument("--password", help="omit to be prompted (preferred)")
    lg.set_defaults(func=cmd_login)

    sub.add_parser("logout", help="forget the stored token").set_defaults(func=cmd_logout)
    sub.add_parser("whoami", help="show the stored session and allowlist").set_defaults(
        func=cmd_whoami
    )
    sub.add_parser("frames", help="list frames on the account").set_defaults(
        func=cmd_frames
    )

    up = sub.add_parser("upload", help="upload a file or folder (defaults to cwd)")
    up.add_argument("path", nargs="?", default=".")
    up.add_argument("--frame")
    up.add_argument("--local-id", help="identity for a single file; default is a content hash")
    up.add_argument("--backend", choices=sorted(BACKENDS), default="api")
    up.add_argument("--recursive", action="store_true")
    up.add_argument("--dry-run", action="store_true")
    up.add_argument("--force", action="store_true", help="re-upload even if already present")
    up.add_argument("--keep-going", action="store_true", help="continue past failures")
    up.add_argument("--delay", type=float, default=0.0, help="seconds between uploads")
    up.add_argument("--max", type=int, help="stop after this many files")
    up.set_defaults(func=cmd_upload)

    ls = sub.add_parser("list", help="list what is actually on a frame")
    ls.add_argument("--frame")
    ls.add_argument("--match", help="only identifiers containing this")
    ls.add_argument("--limit", type=int, default=20, help="how many to print")
    ls.set_defaults(func=cmd_list)

    rm = sub.add_parser("remove", help="remove an asset from a frame")
    rm.add_argument("--frame")
    g = rm.add_mutually_exclusive_group(required=True)
    g.add_argument("--local-id")
    g.add_argument("--asset-id")
    rm.set_defaults(func=cmd_remove)

    sh = sub.add_parser("show", help="display an asset on the frame now")
    sh.add_argument("--frame")
    g2 = sh.add_mutually_exclusive_group(required=True)
    g2.add_argument("--local-id")
    g2.add_argument("--asset-id")
    sh.set_defaults(func=cmd_show)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    args.json = getattr(args, "json", False)
    logging.basicConfig(
        level=logging.DEBUG if getattr(args, "verbose", False) else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    try:
        return args.func(args, load_config())
    except AuraError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
