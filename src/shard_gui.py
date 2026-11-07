"""shard_gui.py - tkinter GUI for shard pack/unpack/verify"""
import os
import sys
import threading
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import shard_core
import shard_interact
from shard_interact import ThreeWayChoice
from shard_const import ExitCode


# ---------- stdout -> log ----------
class StdoutToText:
    def __init__(self, text_widget):
        self.widget = text_widget

    def write(self, s):
        if s and s.strip():
            self.widget.after(0, self._append, s)

    def _append(self, s):
        self.widget.configure(state="normal")
        self.widget.insert("end", s)
        self.widget.see("end")
        self.widget.configure(state="disabled")

    def flush(self):
        pass


# ---------- GUI prompter: uses dialogs instead of input() ----------
class GUIPrompter:
    def __init__(self, root):
        self.root = root

    def threeway(self, err_msg, file_path, quiet=False, force=False):
        if quiet or force:
            print(f"  [auto-continue] {err_msg}")
            return "c"
        # Show modal dialog with three buttons
        return self.root.call(
            self.root._threeway_dialog, err_msg, file_path
        )

    def unknown_chunk(self, chunk_info, dir_path, auto_yes=False, auto_no=False, quiet=False):
        if auto_yes:
            return True
        if auto_no:
            return False
        if quiet:
            return False
        return messagebox.askyesno(
            "Unexpected chunk",
            f'Unexpected chunk: "{chunk_info}"\nunder "{dir_path}"\n\nInclude it in output?',
            parent=self.root,
        )


# ---------- Drag & drop via Win32 WM_DROPFILES ----------
class DropTarget:
    """Register a tkinter widget as a file-drop target."""
    WM_DROPFILES = 0x0233
    DRAGDROP_COPY = 0x1
    msw = ctypes.windll.user32
    shell32 = ctypes.windll.shell32

    def __init__(self, widget, on_drop):
        self.widget = widget
        self.on_drop = on_drop
        self.hwnd = widget.winfo_id()
        self.msw.DragAcceptFiles(self.hwnd, True)
        self.widget.bind("<Destroy>", lambda e: self.msw.RevokeDragDrop(self.hwnd))
        # Poll the message loop
        self._poll()

    def _poll(self):
        msg = wintypes.MSG()
        while self.msw.PeekMessageW(ctypes.byref(msg), self.hwnd, 0, 0, 1):
            if msg.message == self.WM_DROPFILES:
                hdrop = msg.wParam
                count = self.shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
                files = []
                buf = ctypes.create_unicode_buffer(1024)
                for i in range(count):
                    self.shell32.DragQueryFileW(hdrop, i, buf, 1024)
                    files.append(buf.value)
                self.shell32.DragFinish(hdrop)
                self.on_drop(files)
        self.widget.after(50, self._poll)


class ShardGUI:
    def __init__(self, root):
        self.root = root
        root.title("shard - file chunker")
        root.geometry("820x660")
        root.minsize(720, 600)

        self.pack_files = []
        self._build_ui()
        self._redirect_stdout()
        self._install_prompter()
        self._install_drop()

    # ----- prompter bridge -----
    def _install_prompter(self):
        prompter = GUIPrompter(self.root)
        self.root._threeway_dialog = self._threeway_dialog
        shard_interact.set_prompter(prompter)

    def _threeway_dialog(self, err_msg, file_path):
        """Run a modal dialog, block until user picks t/c/g. Called from worker thread."""
        result = {"v": None}
        done = threading.Event()

        def popup():
            top = tk.Toplevel(self.root)
            top.title("Error")
            top.transient(self.root)
            top.grab_set()
            top.geometry("560x240")
            ttk.Label(top, text=err_msg, wraplength=520, justify="left").pack(
                fill="both", expand=True, padx=12, pady=12)
            bf = ttk.Frame(top)
            bf.pack(pady=8)

            def pick(v):
                result["v"] = v
                top.destroy()
                done.set()

            ttk.Button(bf, text="Abort (t)", command=lambda: pick("t")).pack(side="left", padx=8)
            ttk.Button(bf, text="Continue (c)", command=lambda: pick("c")).pack(side="left", padx=8)
            ttk.Button(bf, text="Open folder (g)", command=lambda: self._goto(file_path)).pack(side="left", padx=8)
            top.protocol("WM_DELETE_WINDOW", lambda: pick("t"))

        self.root.after(0, popup)
        done.wait()
        return result["v"]

    def _goto(self, path):
        try:
            os.startfile(os.path.dirname(path) if os.path.isfile(path) else path)
        except Exception:
            pass

    # ----- drop -----
    def _install_drop(self):
        try:
            DropTarget(self.pack_list, self._on_drop)
        except Exception:
            pass

    def _on_drop(self, files):
        for f in files:
            if os.path.isfile(f) and f not in self.pack_files:
                self.pack_files.append(f)
                self.pack_list.insert("end", f)

    # ----- UI -----
    def _build_ui(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=False, padx=8, pady=8)

        pack_tab = ttk.Frame(nb)
        nb.add(pack_tab, text="Pack")

        row = 0
        ttk.Label(pack_tab, text="Files (drag & drop here):").grid(row=row, column=0, sticky="nw", padx=4, pady=4)
        self.pack_list = tk.Listbox(pack_tab, height=7, width=80, selectmode="extended")
        self.pack_list.grid(row=row, column=1, columnspan=3, sticky="ew", padx=4, pady=4)
        btns = ttk.Frame(pack_tab)
        btns.grid(row=row, column=4, sticky="nw", padx=4)
        ttk.Button(btns, text="Add...", command=self.add_files).pack(fill="x", pady=2)
        ttk.Button(btns, text="Remove", command=self.remove_selected).pack(fill="x", pady=2)
        ttk.Button(btns, text="Clear", command=self.clear_files).pack(fill="x", pady=2)

        row += 1
        ttk.Label(pack_tab, text="Chunk size:").grid(row=row, column=0, padx=4, pady=4, sticky="w")
        self.size_var = tk.StringVar(value="1MB")
        ttk.Entry(pack_tab, textvariable=self.size_var, width=12).grid(row=row, column=1, sticky="w", padx=4)

        ttk.Label(pack_tab, text="Output:").grid(row=row, column=2, padx=4, pady=4, sticky="e")
        self.out_var = tk.StringVar(value="")
        ttk.Entry(pack_tab, textvariable=self.out_var, width=30).grid(row=row, column=3, sticky="ew", padx=4)

        row += 1
        opts = ttk.Frame(pack_tab)
        opts.grid(row=row, column=0, columnspan=5, sticky="w", padx=4)
        self.opt_noverify = tk.BooleanVar()
        self.opt_force = tk.BooleanVar()
        self.opt_nohash = tk.BooleanVar()
        self.opt_flatten = tk.BooleanVar()
        self.opt_resume = tk.BooleanVar()
        for i, (txt, var) in enumerate([
            ("Skip self-check", self.opt_noverify),
            ("Force on fail", self.opt_force),
            ("No .sha256", self.opt_nohash),
            ("Flatten paths", self.opt_flatten),
            ("Resume", self.opt_resume),
        ]):
            ttk.Checkbutton(opts, text=txt, variable=var).grid(row=0, column=i, padx=6)

        row += 1
        ttk.Button(pack_tab, text="PACK", command=self.do_pack).grid(
            row=row, column=0, columnspan=5, pady=10, ipadx=40, ipady=4)

        for c in range(5):
            pack_tab.columnconfigure(c, weight=1)

        up_tab = ttk.Frame(nb)
        nb.add(up_tab, text="Unpack / Verify")

        r = 0
        ttk.Label(up_tab, text=".shard file:").grid(row=r, column=0, padx=4, pady=4, sticky="w")
        self.shard_var = tk.StringVar()
        ttk.Entry(up_tab, textvariable=self.shard_var, width=70).grid(row=r, column=1, sticky="ew", padx=4)
        ttk.Button(up_tab, text="Browse...", command=self.pick_shard).grid(row=r, column=2, padx=4)

        r += 1
        ttk.Label(up_tab, text="Output dir:").grid(row=r, column=0, padx=4, pady=4, sticky="w")
        self.outdir_var = tk.StringVar(value=".")
        ttk.Entry(up_tab, textvariable=self.outdir_var, width=70).grid(row=r, column=1, sticky="ew", padx=4)
        ttk.Button(up_tab, text="Browse...", command=self.pick_outdir).grid(row=r, column=2, padx=4)

        r += 1
        uopts = ttk.Frame(up_tab)
        uopts.grid(row=r, column=0, columnspan=3, sticky="w", padx=4)
        self.opt_flatten_u = tk.BooleanVar()
        self.opt_force_u = tk.BooleanVar()
        self.opt_yes = tk.BooleanVar()
        for i, (txt, var) in enumerate([
            ("Flatten", self.opt_flatten_u),
            ("Force overwrite", self.opt_force_u),
            ("Auto-yes chunks", self.opt_yes),
        ]):
            ttk.Checkbutton(uopts, text=txt, variable=var).grid(row=0, column=i, padx=6)

        r += 1
        btns2 = ttk.Frame(up_tab)
        btns2.grid(row=r, column=0, columnspan=3, pady=10)
        ttk.Button(btns2, text="UNPACK", command=self.do_unpack).pack(side="left", padx=20, ipadx=30, ipady=4)
        ttk.Button(btns2, text="VERIFY ONLY", command=self.do_verify).pack(side="left", padx=20, ipadx=20, ipady=4)

        up_tab.columnconfigure(1, weight=1)

        log_frame = ttk.LabelFrame(self.root, text="Log")
        log_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.log = scrolledtext.ScrolledText(log_frame, height=12, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=4, pady=4)

    def _redirect_stdout(self):
        self._old_stdout = sys.stdout
        sys.stdout = StdoutToText(self.log)

    def _log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def add_files(self):
        files = filedialog.askopenfilenames(title="Select files to pack")
        for f in files:
            if f not in self.pack_files:
                self.pack_files.append(f)
                self.pack_list.insert("end", f)

    def remove_selected(self):
        for i in reversed(self.pack_list.curselection()):
            self.pack_list.delete(i)
            del self.pack_files[i]

    def clear_files(self):
        self.pack_list.delete(0, "end")
        self.pack_files.clear()

    def pick_shard(self):
        p = filedialog.askopenfilename(title="Select .shard file",
                                       filetypes=[("shard packages", "*.shard"), ("All", "*.*")])
        if p:
            self.shard_var.set(p)

    def pick_outdir(self):
        d = filedialog.askdirectory(title="Select output directory")
        if d:
            self.outdir_var.set(d)

    def _run(self, fn, *args):
        def worker():
            try:
                rc = fn(*args)
                self.root.after(0, self._done, rc)
            except ThreeWayChoice as e:
                self.root.after(0, self._done, 2)
            except Exception as e:
                self.root.after(0, self._error, e)
        threading.Thread(target=worker, daemon=True).start()

    def _done(self, rc):
        self._log(f"--- exit code: {rc} ---")
        if rc == 0:
            messagebox.showinfo("Done", "Operation completed successfully.")
        elif rc == 1:
            messagebox.showwarning("Done with warnings", "Completed, but some checks failed. See log.")
        elif rc == 2:
            messagebox.showinfo("Aborted", "Aborted by user.")

    def _error(self, e):
        self._log(f"!! exception: {e}")
        messagebox.showerror("Error", str(e))

    class _Opts:
        pass

    def _mk(self, **kw):
        o = self._Opts()
        for k, v in kw.items():
            setattr(o, k, v)
        return o

    def do_pack(self):
        if not self.pack_files:
            messagebox.showwarning("Pack", "No files selected.")
            return
        o = self._mk(
            files=list(self.pack_files),
            size=self.size_var.get() or "1MB",
            output=self.out_var.get() or None,
            no_verify=self.opt_noverify.get(),
            force=self.opt_force.get(),
            no_hash=self.opt_nohash.get(),
            flatten=self.opt_flatten.get(),
            no_follow=False,
            tmp="tmp",
            resume=self.opt_resume.get(),
            dry_run=False,
            quiet=False,
        )
        self._log("=== pack ===")
        self._run(shard_core.pack, self.pack_files, o)

    def do_unpack(self):
        sp = self.shard_var.get()
        if not sp:
            messagebox.showwarning("Unpack", "Select a .shard file first.")
            return
        o = self._mk(
            output=self.outdir_var.get() or ".",
            verify_only=False,
            force=self.opt_force_u.get(),
            flatten=self.opt_flatten_u.get(),
            no_mtime=False,
            no_mode=False,
            yes=self.opt_yes.get(),
            no=False,
            dry_run=False,
            quiet=False,
            tmp="_shard_tmp",
        )
        self._log("=== unpack ===")
        self._run(shard_core.unpack, sp, o)

    def do_verify(self):
        sp = self.shard_var.get()
        if not sp:
            messagebox.showwarning("Verify", "Select a .shard file first.")
            return
        o = self._mk(
            output=None, verify_only=True, force=False, flatten=False,
            no_mtime=False, no_mode=False, yes=False, no=True,
            dry_run=False, quiet=False, tmp="_shard_tmp",
        )
        self._log("=== verify ===")
        self._run(shard_core.unpack, sp, o)


def main():
    root = tk.Tk()
    ShardGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
