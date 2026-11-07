## README.md

```markdown
# shard

Splits one or more files into fixed-size shards, packages them into a ZIP (STORE) container, and renames the result to `.shard`.
It can also unpack, reassemble the original files, and verify integrity.

**Core use case**: Bypass upload size limits (e.g., Cloudflare's 100MB limit) by splitting large files into 1MB chunks for package transfer.

## Format

- Extension: `.shard`
- Container: ZIP, fixed `STORE` (no compression)
- Config: `shardsetter.ini` (one in the outer layer and one in the inner layer), ANSI(cp1252) encoding, all values wrapped in double quotes
- Container hash is stored externally at `<out>.shard.sha256`, not in the INI (to avoid self-reference)

## Run

Requires Python 3.8+.

```bat
python src\main.py pack eg.exe -s 1MB
python src\main.py unpack eg.exe.shard -o D:\out
python src\main.py verify eg.exe.shard
python src\main.py info eg.exe.shard
python src\main.py list eg.exe.shard
```

## Package as a single-file exe (usable directly from CMD)

```bat
pip install pyinstaller
pyinstaller --onefile --console --name shard src\main.py --distpath bin
```

Produces `bin\shard.exe`. Put it in PATH and you can run `shard pack ...` from CMD.

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | All passed |
| 1 | Some failures but completed |
| 2 | Terminated by user |
| 3 | Invalid arguments |
| 4 | File not found |
```