"""interactive prompts - injectable: CLI uses input(), GUI uses dialogs."""
import os
import platform
import subprocess


def open_file_manager(path):
    try:
        target = path if os.path.isdir(path) else (os.path.dirname(path) or ".")
        system = platform.system()
        if system == "Windows":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif system == "Darwin":
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])
    except Exception:
        print(f"  (cannot open file manager, please locate manually: {path})")


class ThreeWayChoice(Exception):
    pass


class CLIPrompter:
    """Default: read from stdin."""
    def threeway(self, err_msg, file_path, quiet=False, force=False):
        if quiet or force:
            print(f"  [auto-continue] {err_msg}")
            return "c"
        print()
        print(f"ERROR: {err_msg}")
        print("Choose:")
        print("  [t] terminate  - abort, keep temp files")
        print("  [c] continue   - skip this error, record and continue")
        print("  [g] goto       - open file explorer here")
        while True:
            try:
                inp = input("t/c/g: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return "t"
            if inp == "t":
                return "t"
            if inp == "c":
                return "c"
            if inp == "g":
                open_file_manager(file_path)
            else:
                print("  enter t / c / g")

    def unknown_chunk(self, chunk_info, dir_path, auto_yes=False, auto_no=False, quiet=False):
        if auto_yes:
            return True
        if auto_no:
            return False
        if quiet:
            return False
        print()
        print(f'Unexpected chunk: "{chunk_info}" under "{dir_path}"')
        while True:
            try:
                inp = input("Include it in output? (y/n): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return False
            if inp == "y":
                return True
            if inp == "n":
                return False
            print("  enter y or n")


# Global active prompter. shard_core calls into this.
_prompter = CLIPrompter()


def set_prompter(p):
    global _prompter
    _prompter = p


def get_prompter():
    return _prompter


def prompt_threeway(err_msg, file_path, quiet=False, force=False):
    return _prompter.threeway(err_msg, file_path, quiet=quiet, force=force)


def prompt_unknown_chunk(chunk_info, dir_path, auto_yes=False, auto_no=False, quiet=False):
    return _prompter.unknown_chunk(chunk_info, dir_path,
                                   auto_yes=auto_yes, auto_no=auto_no, quiet=quiet)
