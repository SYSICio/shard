#!/usr/bin/env python3
"""shard - file chunking tool"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import argparse
from shard_const import PACKAGE_TOOL, ExitCode
import shard_core


def build_parser():
    p = argparse.ArgumentParser(
        prog="shard",
        description="shard file chunking tool (.shard = ZIP STORE container)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )
    sub = p.add_subparsers(dest="command", metavar="<command>")

    sp = sub.add_parser("pack", help="pack files into .shard")
    sp.add_argument("files", nargs="+", help="files to pack (files only, no directories)")
    sp.add_argument("-s", "--size", default="1MB", help="chunk size, e.g. 1MB / 512KB / 25MB (default: 1MB)")
    sp.add_argument("-o", "--output", default=None, help="output filename (default: <orig>.shard or shards.shard)")
    sp.add_argument("--no-verify", action="store_true", help="skip self-check before packing")
    sp.add_argument("-f", "--force", action="store_true", help="continue even if self-check fails")
    sp.add_argument("--no-hash", action="store_true", help="do not write external .sha256 file")
    sp.add_argument("--flatten", action="store_true", help="flatten: do not preserve original paths")
    sp.add_argument("--no-follow", action="store_true", help="do not follow symlinks; store them as links")
    sp.add_argument("--tmp", default="tmp", help="temporary working directory (default: tmp/)")
    sp.add_argument("--resume", action="store_true", help="resume interrupted pack; reuse existing tmp/")
    sp.add_argument("--dry-run", action="store_true", help="show plan only, write nothing")
    sp.add_argument("-q", "--quiet", action="store_true", help="no interactive prompts; auto-continue")

    su = sub.add_parser("unpack", help="unpack .shard")
    su.add_argument("package", help=".shard file to unpack")
    su.add_argument("-o", "--output", default=".", help="output directory (default: current dir)")
    su.add_argument("--verify-only", action="store_true", help="verify only, do not write files")
    su.add_argument("-f", "--force", action="store_true", help="overwrite existing output files")
    su.add_argument("--flatten", action="store_true", help="flatten: put all files in one directory")
    su.add_argument("--no-mtime", action="store_true", help="do not restore original mtime")
    su.add_argument("--no-mode", action="store_true", help="do not restore permission bits")
    su.add_argument("-y", "--yes", action="store_true", help="auto-accept undeclared chunks")
    su.add_argument("-n", "--no", action="store_true", help="auto-skip undeclared chunks")
    su.add_argument("--dry-run", action="store_true", help="show plan only, write nothing")
    su.add_argument("-q", "--quiet", action="store_true", help="no interactive prompts; auto-skip")

    sv = sub.add_parser("verify", help="verify .shard only")
    sv.add_argument("package", help=".shard file to verify")
    sv.add_argument("-q", "--quiet", action="store_true", help="no interactive prompts")

    si = sub.add_parser("info", help="show package metadata")
    si.add_argument("package", help=".shard file to inspect")

    sl = sub.add_parser("list", help="list entries in package")
    sl.add_argument("package", help=".shard file to list")

    sub.add_parser("help")
    sub.add_parser("version")
    return p


HELP_TEXT = """shard - file chunking tool
Format: .shard = ZIP(STORE) + dual INI + fixed-size chunks

Usage:
  shard pack <files...> [options]
  shard unpack <package> [options]
  shard verify <package>
  shard info <package>
  shard list <package>
  shard help [command]
  shard version

Commands:
  pack       Split files into chunks and pack into .shard
  unpack     Unpack .shard and reassemble original files
  verify     Verify package integrity without extracting
  info       Show package metadata (files, sizes, chunk counts)
  list       List every entry inside the .shard
  help       Show this help, or help for a specific command
  version    Show version

Run `shard help pack` or `shard help unpack` for options.

Examples:
  shard pack eg.exe -s 1MB
  shard pack a.txt b.txt -s 512KB -o shards
  shard unpack eg.exe.shard -o D:\\out
  shard unpack eg.exe.shard --verify-only
  shard verify eg.exe.shard
  shard info eg.exe.shard
"""

PACK_HELP = """shard pack - pack files into .shard

Usage:
  shard pack <files...> [options]

Options:
  -s, --size SIZE     Chunk size, e.g. 1MB / 512KB / 25MB (default: 1MB)
  -o, --output NAME   Output filename. Default: <original>.shard (single)
                      or shards.shard (multi). Auto-appends .shard if missing.
      --no-verify     Skip self-check before packing
  -f, --force         Continue even if self-check fails
      --no-hash       Do not write the external .sha256 file
      --flatten       Flatten: do not preserve original directory paths
      --no-follow     Do not follow symlinks; store them as links
      --tmp DIR       Temporary working directory (default: tmp/)
      --resume        Resume interrupted pack; reuse existing tmp/
      --dry-run       Show plan only, write nothing
  -q, --quiet         No interactive prompts; auto-continue

Examples:
  shard pack big.iso -s 25MB
  shard pack a.txt b.txt c.txt -s 512KB -o bundle
  shard pack huge.file --resume
"""

UNPACK_HELP = """shard unpack - unpack .shard

Usage:
  shard unpack <package> [options]

Options:
  -o, --output DIR    Output directory (default: current directory).
                      Original subdirectory structure is preserved unless
                      --flatten is given.
      --verify-only   Verify only, do not write extracted files
  -f, --force         Overwrite existing output files
      --flatten       Flatten: put every restored file in one directory
      --no-mtime      Do not restore original mtime
      --no-mode       Do not restore original permission bits
  -y, --yes           Auto-accept undeclared chunks
  -n, --no            Auto-skip undeclared chunks
      --dry-run       Show plan only, write nothing
  -q, --quiet         No interactive prompts; auto-skip

Examples:
  shard unpack eg.exe.shard
  shard unpack eg.exe.shard -o D:\\restored
  shard unpack eg.exe.shard --verify-only
  shard unpack shards.shard -o D:\\out --flatten
"""

OTHER_HELP = """shard verify <package>
  Verify package, chunks and reassembled hashes. Do not extract.

shard info <package>
  Show package metadata: format, version, chunk size, file list.

shard list <package>
  List every entry (file and inner INI) inside the .shard.

shard version
  Print version string.
"""


def main(argv=None):
    parser = build_parser()
    argv = list(sys.argv[1:] if argv is None else argv)

    # help [command]
    if argv and argv[0] == "help":
        sub = argv[1] if len(argv) > 1 else None
        if sub == "pack":
            print(PACK_HELP)
        elif sub == "unpack":
            print(UNPACK_HELP)
        elif sub in ("verify", "info", "list", "version"):
            print(OTHER_HELP)
        else:
            print(HELP_TEXT)
        return 0

    args = parser.parse_args(argv)

    if args.command is None:
        print(HELP_TEXT)
        return 0

    if args.command == "version":
        print(PACKAGE_TOOL)
        return 0

    if args.command == "pack":
        return shard_core.pack(args.files, args)

    if args.command == "unpack":
        return shard_core.unpack(args.package, args)

    if args.command == "verify":
        class _Opts: pass
        o = _Opts()
        o.tmp = "_shard_tmp"
        o.quiet = getattr(args, "quiet", False)
        o.verify_only = True
        o.output = None
        o.force = False
        o.flatten = False
        o.no_mtime = False
        o.no_mode = False
        o.yes = False
        o.no = True
        o.dry_run = False
        return shard_core.unpack(args.package, o)

    if args.command == "info":
        return shard_core.info(args.package)

    if args.command == "list":
        return shard_core.list_pieces(args.package)

    print(f"Unknown command: {args.command}")
    return ExitCode.ARG_ERR


if __name__ == "__main__":
    sys.exit(main())
