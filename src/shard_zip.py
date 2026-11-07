"""
shard_zip.py — ZIP(STORE) 容器操作
固定 compression=ZIP_STORED（不压缩）
"""
import os
import zipfile


def zip_store_pack(source_dir: str, zip_path: str, include_dirs=None) -> None:
    """
    把 source_dir 下的文件打包成 zip_path，STORE 不压缩。
    include_dirs: 若给定，只打包 source_dir/shardsetter.ini + 这些子目录；
                  否则打包整个 source_dir。
    """
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
        if include_dirs is None:
            for root, dirs, files in os.walk(source_dir):
                for fn in files:
                    full = os.path.join(root, fn)
                    rel = os.path.relpath(full, source_dir)
                    arc = rel.replace(os.sep, "/")
                    zf.write(full, arc)
        else:
            outer_ini = os.path.join(source_dir, "shardsetter.ini")
            if os.path.isfile(outer_ini):
                zf.write(outer_ini, "shardsetter.ini")
            for d in include_dirs:
                d_full = os.path.join(source_dir, d)
                if not os.path.isdir(d_full):
                    continue
                for root, dirs, files in os.walk(d_full):
                    for fn in files:
                        full = os.path.join(root, fn)
                        rel = os.path.relpath(full, source_dir)
                        arc = rel.replace(os.sep, "/")
                        zf.write(full, arc)


def zip_list(zip_path: str) -> list:
    with zipfile.ZipFile(zip_path, "r") as zf:
        return zf.namelist()


def zip_is_valid(zip_path: str) -> bool:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            bad = zf.testzip()
        return bad is None
    except (zipfile.BadZipFile, OSError):
        return False


def zip_read_bytes(zip_path: str, name: str) -> bytes:
    with zipfile.ZipFile(zip_path, "r") as zf:
        return zf.read(name)


def zip_read_text(zip_path: str, name: str, encoding: str = "cp1252") -> str:
    return zip_read_bytes(zip_path, name).decode(encoding, errors="replace")


def zip_extract_file(zip_path: str, name: str, dest_path: str) -> None:
    data = zip_read_bytes(zip_path, name)
    d = os.path.dirname(dest_path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(dest_path, "wb") as f:
        f.write(data)
