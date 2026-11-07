"""
shard_core.py — 核心业务逻辑
  pack / unpack / verify / info / list
规范 v1 对齐
"""
import os
import shutil

from shard_const import (
    PACKAGE_FORMAT, PACKAGE_VERSION, PACKAGE_TOOL, PACKAGE_COMPRESSION,
    DEFAULT_TMP_DIR, DEFAULT_OUTPUT_MULTI,
    CHUNK_NUM_SUFFIX, CHUNK_LAST_NAME,
    ExitCode,
)
from shard_ini import ShardINI
from shard_utils import (
    sha256_file, sha256_bytes, parse_size, fmt_size, now_str,
    get_mtime, set_mtime, get_mode, set_mode,
)
from shard_interact import prompt_threeway, prompt_unknown_chunk, ThreeWayChoice
from shard_zip import (
    zip_store_pack, zip_list, zip_is_valid, zip_read_text, zip_extract_file,
)


def _chunk_fname(orig_name: str, idx: int) -> str:
    return f"{orig_name}{CHUNK_NUM_SUFFIX}{idx}"


def _last_fname(orig_name: str) -> str:
    return f"{orig_name}.{CHUNK_LAST_NAME}"


def _read_chunk_order(ini: ShardINI):
    out = []
    i = 1
    while True:
        f = ini.get("chunk", f"{i}.file")
        if f is None:
            break
        out.append((
            str(i),
            f,
            int(ini.get("chunk", f"{i}.size", "0")),
            ini.get("chunk", f"{i}.sha256", ""),
        ))
        i += 1
    fm = ini.get("chunk", "m.file")
    if fm:
        out.append((
            "m",
            fm,
            int(ini.get("chunk", "m.size", "0")),
            ini.get("chunk", "m.sha256", ""),
        ))
    return out


def _empty_sha256() -> str:
    return sha256_bytes(b"")


# ============================================================
# PACK
# ============================================================

def pack(files: list, opts) -> int:
    existing = []
    seen_paths = set()
    for fp in files:
        real = os.path.abspath(fp)
        if real in seen_paths:
            if not getattr(opts, "quiet", False):
                print(f"skip duplicate input: {fp}")
            continue
        seen_paths.add(real)
        if not os.path.exists(fp) and not os.path.islink(fp):
            print(f"Error: file not found: {fp}")
            return ExitCode.FILE_NOT_FOUND
        if os.path.isdir(fp):
            print(f"Error: directories are not allowed (files only): {fp}")
            return ExitCode.ARG_ERR
        existing.append(fp)

    if not existing:
        print("Error: no files to pack")
        return ExitCode.ARG_ERR

    chunk_size = parse_size(opts.size or "1MB")
    tmp_dir = opts.tmp or DEFAULT_TMP_DIR
    is_multi = len(existing) > 1

    used_basenames = {}
    resolved_names = []
    for fp in existing:
        b = os.path.basename(fp)
        if b not in used_basenames:
            used_basenames[b] = 1
            resolved_names.append(b)
        else:
            used_basenames[b] += 1
            stem, dot, ext = b.rpartition(".")
            if dot:
                new = f"{stem}.{used_basenames[b]}.{ext}"
            else:
                new = f"{b}.{used_basenames[b]}"
            if not getattr(opts, "quiet", False):
                print(f"basename collision: {b} -> {new}")
            resolved_names.append(new)

    if opts.output:
        out_name = opts.output
        if not out_name.endswith(".shard"):
            out_name += ".shard"
    else:
        if is_multi:
            out_name = DEFAULT_OUTPUT_MULTI + ".shard"
        else:
            out_name = resolved_names[0] + ".shard"

    if not opts.dry_run:
        os.makedirs(tmp_dir, exist_ok=True)

    dir_entries = []
    total_chunks = 0
    total_orig_size = 0
    any_inner_fail = False

    try:
        for idx_fp, fp in enumerate(existing):
            basename = resolved_names[idx_fp]
            sub_dir = os.path.join(tmp_dir, basename)
            inner_ini_path = os.path.join(sub_dir, "shardsetter.ini")

            if not opts.quiet and not opts.dry_run:
                print(f"[{idx_fp+1}/{len(existing)}] processing: {fp}")

            is_symlink = os.path.islink(fp)
            link_target = os.readlink(fp) if is_symlink else ""
            keep_symlink = bool(getattr(opts, "no_follow", False)) and is_symlink

            if keep_symlink:
                orig_size = 0
                orig_sha = ""
                orig_mtime = get_mtime(fp)
                orig_mode = 0o777
            else:
                orig_size = os.path.getsize(fp)
                orig_sha = sha256_file(fp)
                orig_mtime = get_mtime(fp)
                orig_mode = get_mode(fp)

            reused = False
            if opts.resume and os.path.isfile(inner_ini_path):
                try:
                    old = ShardINI.load(inner_ini_path)
                    if (old.get("original", "size") == str(orig_size)
                            and old.get("original", "sha256") == orig_sha):
                        reused = True
                        if not opts.quiet:
                            print(f"[resume] reusing existing chunks: {basename}")
                except Exception:
                    reused = False

            if reused:
                inner = ShardINI.load(inner_ini_path)
                chunk_list = _read_chunk_order(inner)
            else:
                if not opts.dry_run:
                    if os.path.isdir(sub_dir):
                        shutil.rmtree(sub_dir)
                    os.makedirs(sub_dir, exist_ok=True)

                chunk_list = []
                if keep_symlink:
                    pass
                elif orig_size == 0:
                    fn = _chunk_fname(basename, 1)
                    if not opts.dry_run:
                        with open(os.path.join(sub_dir, fn), "wb") as f:
                            pass
                    chunk_list.append(("1", fn, 0, _empty_sha256()))
                else:
                    n_full = orig_size // chunk_size
                    has_remain = (orig_size % chunk_size) != 0
                    idx = 1
                    with open(fp, "rb") as fsrc:
                        for _ in range(n_full):
                            buf = fsrc.read(chunk_size)
                            fn = _chunk_fname(basename, idx)
                            if not opts.dry_run:
                                with open(os.path.join(sub_dir, fn), "wb") as fo:
                                    fo.write(buf)
                            chunk_list.append((str(idx), fn, len(buf), sha256_bytes(buf)))
                            idx += 1
                        if has_remain:
                            buf = fsrc.read()
                            fn = _last_fname(basename)
                            if not opts.dry_run:
                                with open(os.path.join(sub_dir, fn), "wb") as fo:
                                    fo.write(buf)
                            chunk_list.append(("m", fn, len(buf), sha256_bytes(buf)))

                inner = ShardINI()
                inner.set("shard", "format", PACKAGE_FORMAT)
                inner.set("shard", "version", PACKAGE_VERSION)
                inner.set("shard", "type", "symlink" if keep_symlink else "single")
                inner.set("original", "name", basename)
                inner.set("original", "size", str(orig_size))
                inner.set("original", "sha256", orig_sha)
                inner.set("original", "mtime", str(orig_mtime))
                inner.set("original", "mode", str(orig_mode))
                if keep_symlink:
                    inner.set("original", "link_target", link_target)
                inner.set("chunk", "size", str(chunk_size))
                inner.set("chunk", "count", str(len(chunk_list)))
                if chunk_list:
                    inner.set("chunk", "last", chunk_list[-1][1])
                for key, fn, csize, csha in chunk_list:
                    inner.set("chunk", f"{key}.file", fn)
                    inner.set("chunk", f"{key}.size", str(csize))
                    inner.set("chunk", f"{key}.sha256", csha)

                verify_result = "pass"
                fail_reason = ""
                chunks_verified = 0
                chunks_expected = len(chunk_list)

                if opts.no_verify or keep_symlink:
                    verify_result = "skipped" if opts.no_verify else "pass"
                else:
                    try:
                        if len(chunk_list) != int(inner.get("chunk", "count")):
                            raise RuntimeError("chunk count does not match chunk.count")
                        for key, fn, csize, csha in chunk_list:
                            p = os.path.join(sub_dir, fn)
                            if not os.path.isfile(p):
                                raise RuntimeError(f"chunk {fn} missing")
                            actual_size = os.path.getsize(p)
                            if actual_size != csize:
                                raise RuntimeError(f"chunk {fn} size mismatch: expected {csize}, got {actual_size}")
                            actual_sha = sha256_file(p)
                            if actual_sha != csha:
                                raise RuntimeError(f"chunk {fn} corrupt: sha256 mismatch")
                            chunks_verified += 1
                        tmp_concat = os.path.join(tmp_dir, f"_concat_{basename}.tmp")
                        with open(tmp_concat, "wb") as fo:
                            for key, fn, csize, csha in chunk_list:
                                with open(os.path.join(sub_dir, fn), "rb") as fi:
                                    while True:
                                        b = fi.read(1024 * 1024)
                                        if not b:
                                            break
                                        fo.write(b)
                        concat_size = os.path.getsize(tmp_concat)
                        if concat_size != orig_size:
                            raise RuntimeError(f"reassembled size mismatch: expected {orig_size}, got {concat_size}")
                        concat_sha = sha256_file(tmp_concat)
                        if concat_sha != orig_sha:
                            raise RuntimeError("reassembled sha256 mismatch")
                        os.remove(tmp_concat)
                    except Exception as e:
                        verify_result = "fail"
                        fail_reason = str(e)
                        if not opts.force:
                            ans = prompt_threeway(
                                f"self-check failed: {e}",
                                sub_dir,
                                quiet=opts.quiet,
                                force=False,
                            )
                            if ans == "t":
                                raise ThreeWayChoice(str(e))

                inner.set("verify", "checked_at", now_str())
                inner.set("verify", "result", verify_result)
                inner.set("verify", "fail_reason", fail_reason)
                inner.set("verify", "original_size", str(orig_size))
                inner.set("verify", "original_sha256", orig_sha)
                inner.set("verify", "chunks_verified", str(chunks_verified))
                inner.set("verify", "chunks_expected", str(chunks_expected))
                inner.set("verify", "decisions", "")
                inner.set("verify", "skipped", "")
                inner.set("verify", "aborted", "0")

                if not opts.dry_run:
                    inner.dump(inner_ini_path)

            dir_entries.append({
                "basename": basename,
                "path": fp if not opts.flatten else basename,
                "size": orig_size,
                "sha256": orig_sha,
                "files": len(chunk_list),
                "last": chunk_list[-1][1] if chunk_list else "",
                "mtime": orig_mtime,
                "mode": orig_mode,
                "sub_dir": sub_dir,
                "verify_result": inner.get("verify", "result", "pass"),
                "is_symlink": keep_symlink,
                "link_target": link_target,
            })
            if inner.get("verify", "result", "pass") == "fail":
                any_inner_fail = True
            total_chunks += len(chunk_list)
            total_orig_size += orig_size

        outer = ShardINI()
        outer.set("package", "format", PACKAGE_FORMAT)
        outer.set("package", "version", PACKAGE_VERSION)
        outer.set("package", "type", "multi" if is_multi else "single")
        outer.set("package", "created", now_str())
        outer.set("package", "tool", PACKAGE_TOOL)
        outer.set("package", "compression", PACKAGE_COMPRESSION)
        outer.set("chunk", "size", str(chunk_size))
        outer.set("chunk", "count", str(total_chunks))
        outer.set("verify", "checked_at", now_str())
        outer.set("verify", "result", "fail" if any_inner_fail else "pass")
        outer.set("verify", "fail_reason", "")
        outer.set("verify", "chunks_verified", str(total_chunks))
        outer.set("verify", "chunks_expected", str(total_chunks))
        outer.set("verify", "decisions", "")
        outer.set("verify", "skipped", "")
        outer.set("verify", "aborted", "0")

        for i, e in enumerate(dir_entries, start=1):
            outer.set("dir." + str(i), "dirname", e["basename"])
            outer.set("dir." + str(i), "original", e["basename"])
            outer.set("dir." + str(i), "path", e["path"])
            outer.set("dir." + str(i), "size", str(e["size"]))
            outer.set("dir." + str(i), "sha256", e["sha256"])
            outer.set("dir." + str(i), "files", str(e["files"]))
            outer.set("dir." + str(i), "last", e["last"])
            outer.set("dir." + str(i), "mtime", str(e["mtime"]))
            outer.set("dir." + str(i), "mode", str(e["mode"]))

        outer_ini_path = os.path.join(tmp_dir, "shardsetter.ini")
        if not opts.dry_run:
            outer.dump(outer_ini_path)

        if opts.dry_run:
            print()
            print(f"[dry-run] will pack {len(dir_entries)} files -> {out_name}")
            print(f"[dry-run] chunk size: {fmt_size(chunk_size)}")
            print(f"[dry-run] total chunks: {total_chunks}")
            print(f"[dry-run] original total size: {fmt_size(total_orig_size)}")
            return ExitCode.OK

        zip_tmp = out_name + ".tmp.zip"
        if os.path.exists(zip_tmp):
            os.remove(zip_tmp)
        include = [e["basename"] for e in dir_entries]
        zip_store_pack(tmp_dir, zip_tmp, include_dirs=include)
        if os.path.exists(out_name):
            os.remove(out_name)
        os.rename(zip_tmp, out_name)

        if not opts.no_hash:
            h = sha256_file(out_name)
            with open(out_name + ".sha256", "w", encoding="ascii") as f:
                f.write(f"{h}  {os.path.basename(out_name)}\n")

        if not opts.resume:
            shutil.rmtree(tmp_dir, ignore_errors=True)

        print()
        print("Status  pack done")
        print(f"Output  {out_name}")
        print(f"Files  {len(dir_entries)}")
        print(f"TotalChunks {total_chunks}")
        print(f"OrigSize  {fmt_size(total_orig_size)}")
        verify_state = "skipped" if opts.no_verify else "pass"
        print(f"SelfCheck  {verify_state}")
        return ExitCode.OK

    except ThreeWayChoice as e:
        print(f"\nAborted: {e}")
        return ExitCode.USER_TERMINATED


# ============================================================
# UNPACK / VERIFY
# ============================================================

def _load_package(shard_path: str, opts):
    """
    Returns (outer, entries, warnings).
    Recoverable errors are surfaced as warnings after asking the user.
    Fatal errors raise RuntimeError.
    """
    from shard_interact import prompt_threeway, ThreeWayChoice

    if not os.path.isfile(shard_path):
        raise RuntimeError(f"package file not found: {shard_path}")

    quiet = getattr(opts, "quiet", False)
    force = getattr(opts, "force", False)
    warnings = []

    # External .sha256 check
    sha_path = shard_path + ".sha256"
    if os.path.isfile(sha_path):
        try:
            with open(sha_path, "r", encoding="ascii") as f:
                expected = f.read().strip().split()[0]
            actual = sha256_file(shard_path)
            if expected.lower() != actual.lower():
                msg = (f"package sha256 mismatch:\n  expected {expected}\n  got {actual}\n"
                       "The file may be corrupted or tampered. Continue anyway?")
                ans = prompt_threeway(msg, shard_path, quiet=quiet, force=force)
                if ans == "t":
                    raise ThreeWayChoice(msg)
                warnings.append("external .sha256 mismatch, ignored")
        except ThreeWayChoice:
            raise
        except Exception as e:
            msg = f"failed to read .sha256: {e}"
            ans = prompt_threeway(msg, sha_path, quiet=quiet, force=force)
            if ans == "t":
                raise ThreeWayChoice(msg)
            warnings.append(msg)

    # zip structure
    if not zip_is_valid(shard_path):
        msg = "package corrupt: invalid zip structure. Some entries may be unreadable. Continue?"
        ans = prompt_threeway(msg, shard_path, quiet=quiet, force=force)
        if ans == "t":
            raise ThreeWayChoice(msg)
        warnings.append("zip structure invalid, trying to read anyway")

    try:
        names = zip_list(shard_path)
    except Exception as e:
        raise RuntimeError(f"cannot list zip contents: {e}")

    if "shardsetter.ini" not in names:
        raise RuntimeError("structural error: missing outer shardsetter.ini (not a shard package?)")

    outer_text = zip_read_text(shard_path, "shardsetter.ini")
    tmp_work = getattr(opts, "tmp", "_shard_tmp")
    os.makedirs(tmp_work, exist_ok=True)
    outer_path_tmp = os.path.join(tmp_work, "_outer.ini")
    with open(outer_path_tmp, "w", encoding="cp1252") as f:
        f.write(outer_text)
    outer = ShardINI.load(outer_path_tmp)

    ver = outer.get("package", "version", "1")
    if ver and int(ver) > int(PACKAGE_VERSION):
        msg = f"package version {ver} is newer than tool version {PACKAGE_VERSION}. Continue at your own risk?"
        ans = prompt_threeway(msg, shard_path, quiet=quiet, force=force)
        if ans == "t":
            raise ThreeWayChoice(msg)
        warnings.append(f"version {ver} newer than tool")

    entries = []
    i = 1
    while True:
        sec = f"dir.{i}"
        dn = outer.get(sec, "dirname")
        if dn is None:
            break
        inner_name = f"{dn}/shardsetter.ini"
        if inner_name not in names:
            msg = f"missing inner INI for dir '{dn}' ({inner_name}). Skip this file?"
            ans = prompt_threeway(msg, shard_path, quiet=quiet, force=force)
            if ans == "t":
                raise ThreeWayChoice(msg)
            warnings.append(f"skipped {dn}: missing inner INI")
            i += 1
            continue
        inner_text = zip_read_text(shard_path, inner_name)
        inner_path_tmp = os.path.join(tmp_work, f"_inner_{i}.ini")
        with open(inner_path_tmp, "w", encoding="cp1252") as f:
            f.write(inner_text)
        inner = ShardINI.load(inner_path_tmp)
        chunks = _read_chunk_order(inner)
        entries.append({
            "dirname": dn,
            "outer": outer.items(sec),
            "inner": inner,
            "chunks": chunks,
        })
        i += 1

    return outer, entries, warnings


def unpack(shard_path: str, opts) -> int:
    try:
        outer, entries, load_warnings = _load_package(shard_path, opts)
    except ThreeWayChoice as e:
        print(f"\nAborted: {e}")
        return ExitCode.USER_TERMINATED
    except RuntimeError as e:
        print(f"Error: {e}")
        return ExitCode.FILE_NOT_FOUND if "not found" in str(e) or "missing" in str(e) else ExitCode.HAS_FAIL

    out_dir = opts.output or "."
    if not opts.dry_run:
        os.makedirs(out_dir, exist_ok=True)

    for w in load_warnings:
        print(f"  [warn] {w}")

    fail_list = []
    skipped_list = []
    decisions_list = []
    restored = []
    has_fail = False

    try:
        for ent in entries:
            dn = ent["dirname"]
            inner = ent["inner"]
            chunks = ent["chunks"]

            orig_name = inner.get("original", "name")
            orig_size = int(inner.get("original", "size", "0"))
            orig_sha = inner.get("original", "sha256", "")
            orig_mtime = float(inner.get("original", "mtime", "0"))
            orig_mode = int(inner.get("original", "mode", "0"))

            if dn != orig_name and not opts.quiet:
                print(f"Note: dirname {dn!r} differs from original name {orig_name!r} ; output name follows original.name")

            tmp_work = os.path.join(getattr(opts, "tmp", "_shard_tmp"), dn)
            os.makedirs(tmp_work, exist_ok=True)

            chunk_files_in_zip = set(
                n for n in zip_list(shard_path)
                if n.startswith(dn + "/") and n != f"{dn}/shardsetter.ini"
            )
            declared = set(f"{dn}/{c[1]}" for c in chunks)

            undeclared = chunk_files_in_zip - declared
            for u in undeclared:
                ok = prompt_unknown_chunk(
                    os.path.basename(u), dn,
                    auto_yes=opts.yes, auto_no=opts.no, quiet=opts.quiet,
                )
                if ok:
                    decisions_list.append(u)
                else:
                    skipped_list.append(u)

            chunks_ok = 0
            for key, fn, csize, csha in chunks:
                arc = f"{dn}/{fn}"
                local = os.path.join(tmp_work, fn)
                if arc not in chunk_files_in_zip:
                    msg = f"chunk {key} ({fn}) missing"
                    fail_list.append(msg)
                    has_fail = True
                    ans = prompt_threeway(msg, tmp_work, quiet=opts.quiet, force=opts.force)
                    if ans == "t":
                        raise ThreeWayChoice(msg)
                    continue
                if opts.dry_run:
                    chunks_ok += 1
                    continue
                zip_extract_file(shard_path, arc, local)
                actual_size = os.path.getsize(local)
                if actual_size != csize:
                    msg = f"chunk {key} ({fn}) size mismatch: expected {csize}, got {actual_size}"
                    fail_list.append(msg)
                    has_fail = True
                    ans = prompt_threeway(msg, local, quiet=opts.quiet, force=opts.force)
                    if ans == "t":
                        raise ThreeWayChoice(msg)
                    continue
                actual_sha = sha256_file(local)
                if actual_sha != csha:
                    msg = f"chunk {key} ({fn}) corrupt: sha256 mismatch"
                    fail_list.append(msg)
                    has_fail = True
                    ans = prompt_threeway(msg, local, quiet=opts.quiet, force=opts.force)
                    if ans == "t":
                        raise ThreeWayChoice(msg)
                    continue
                chunks_ok += 1

            expected_count = int(inner.get("chunk", "count", "0"))
            if chunks_ok != expected_count:
                msg = f"{orig_name}: chunk count mismatch: expected {expected_count}, passed {chunks_ok}"
                fail_list.append(msg)
                has_fail = True

            if opts.verify_only or opts.dry_run:
                continue

            outer_d = ent["outer"]
            rel_path = outer_d.get("path", orig_name)
            if opts.flatten:
                rel_path = orig_name
            final_path = os.path.join(out_dir, rel_path)
            d = os.path.dirname(final_path)
            if d:
                os.makedirs(d, exist_ok=True)

            if os.path.lexists(final_path) and not opts.force:
                msg = f"target already exists: {final_path} (use --force to overwrite)"
                fail_list.append(msg)
                has_fail = True
                ans = prompt_threeway(msg, final_path, quiet=opts.quiet, force=opts.force)
                if ans == "t":
                    raise ThreeWayChoice(msg)
                continue

            shard_type = inner.get("shard", "type", "single")
            if shard_type == "symlink":
                target = inner.get("original", "link_target", "")
                if not opts.dry_run:
                    if os.path.lexists(final_path):
                        os.remove(final_path)
                    try:
                        os.symlink(target, final_path)
                    except (OSError, NotImplementedError):
                        # Windows 无权限建符号链接时，退化为复制目标
                        if os.path.lexists(target):
                            shutil.copy2(target, final_path)
                restored.append(f"{orig_name} -> {target}")
                continue

            if not opts.dry_run:
                with open(final_path, "wb") as fo:
                    for key, fn, csize, csha in chunks:
                        local = os.path.join(tmp_work, fn)
                        if not os.path.isfile(local):
                            continue
                        with open(local, "rb") as fi:
                            while True:
                                b = fi.read(1024 * 1024)
                                if not b:
                                    break
                                fo.write(b)

                fsize = os.path.getsize(final_path)
                if fsize != orig_size:
                    msg = f"{orig_name}: reassembled size mismatch: expected {orig_size}, got {fsize}"
                    fail_list.append(msg)
                    has_fail = True
                else:
                    fsha = sha256_file(final_path)
                    if fsha != orig_sha:
                        msg = f"{orig_name}: reassembled sha256 mismatch"
                        fail_list.append(msg)
                        has_fail = True
                    else:
                        restored.append(orig_name)
                        if not opts.no_mtime:
                            set_mtime(final_path, orig_mtime)
                        if not opts.no_mode:
                            set_mode(final_path, orig_mode)

        shutil.rmtree(getattr(opts, "tmp", "_shard_tmp"), ignore_errors=True)

        print()
        if opts.verify_only:
            print("Status  verify done")
        else:
            print("Status  unpack done")
            if restored:
                print(f"Restored {', '.join(restored)}")
        if fail_list:
            print(f"Failed {len(fail_list)} items:")
            for m in fail_list:
                print(f"  - {m}")
        else:
            print("verify: all passed")
        if skipped_list:
            print(f"Skipped {len(skipped_list)} items")
        else:
            print("Skipped none")
        if decisions_list:
            print(f"undeclared chunks added to output {len(decisions_list)} items")

        return ExitCode.HAS_FAIL if has_fail else ExitCode.OK

    except ThreeWayChoice as e:
        print(f"\nAborted: {e}")
        return ExitCode.USER_TERMINATED


def verify(shard_path: str, opts) -> int:
    opts.verify_only = True
    opts.output = None
    opts.dry_run = False
    return unpack(shard_path, opts)


# ============================================================
# INFO / LIST
# ============================================================

def info(shard_path: str) -> int:
    if not os.path.isfile(shard_path):
        print(f"Error: file not found: {shard_path}")
        return ExitCode.FILE_NOT_FOUND
    try:
        if not zip_is_valid(shard_path):
            print("Error: package corrupt")
            return ExitCode.HAS_FAIL
        text = zip_read_text(shard_path, "shardsetter.ini")
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".ini", delete=False, encoding="cp1252") as f:
            f.write(text)
            tmp = f.name
        outer = ShardINI.load(tmp)
        os.unlink(tmp)

        print(f"Format   {outer.get('package','format')}")
        print(f"Version  {outer.get('package','version')}")
        print(f"Type     {outer.get('package','type')}")
        print(f"Created  {outer.get('package','created')}")
        print(f"Tool     {outer.get('package','tool')}")
        print(f"Compress {outer.get('package','compression')}")
        print(f"ChunkSize{fmt_size(int(outer.get('chunk','size','0')))}")
        print(f"TotalChunks {outer.get('chunk','count')}")
        print()
        print("Files:")
        i = 1
        while True:
            sec = f"dir.{i}"
            dn = outer.get(sec, "dirname")
            if dn is None:
                break
            print(f"  [{i}] {dn}")
            print(f"        path    {outer.get(sec,'path')}")
            print(f"        size    {fmt_size(int(outer.get(sec,'size','0')))}")
            print(f"        chunks  {outer.get(sec,'files')}  (last={outer.get(sec,'last')})")
            print(f"      sha256   {outer.get(sec,'sha256')}")
            i += 1
        return ExitCode.OK
    except Exception as e:
        print(f"Error: {e}")
        return ExitCode.HAS_FAIL


def list_pieces(shard_path: str) -> int:
    if not os.path.isfile(shard_path):
        print(f"Error: file not found: {shard_path}")
        return ExitCode.FILE_NOT_FOUND
    try:
        names = zip_list(shard_path)
        for n in sorted(names):
            print(n)
        return ExitCode.OK
    except Exception as e:
        print(f"Error: {e}")
        return ExitCode.HAS_FAIL
