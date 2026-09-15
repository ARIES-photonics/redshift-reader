#!/usr/bin/env python3
# app.py  --  REDSHiFT NERV audiobook app (native window via pywebview).
# Loads nerv_ui.html, bridges the interface to redshift_engine_v2.
#
# Run it (dev):   pip3 install pywebview ; python3 app.py
# Or just double-click Run_REDSHiFT_NERV.command.
# Build a shippable .app:  ./build_REDSHiFT_app.command  (uses PyInstaller)

import os, sys, json, threading

try:
    import webview
except ImportError:
    sys.stderr.write(
        "\nMissing dependency 'pywebview'.\n"
        "Install it once:   pip3 install pywebview\n"
        "Then run again:    python3 app.py\n\n")
    sys.exit(1)

import redshift_engine_v2 as eng


def resource(name):
    # works both as a plain script and inside a PyInstaller .app bundle
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


class Api:
    def __init__(self):
        self.window = None
        self.last_out = ""

    # --- called from the UI ---
    def get_voices(self):
        try:
            return eng.voice_names()
        except Exception:
            return []

    def choose_file(self):
        try:
            res = self.window.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=False,
                file_types=("Book files (*.md;*.markdown;*.txt;*.tex;*.pdf;*.epub)",
                            "All files (*.*)"))
            if res:
                return res[0]
        except Exception as e:
            self._js(f"window.nervError({json.dumps('file dialog: ' + str(e))})")
        return None

    def choose_folder(self):
        # whole book: pick a folder of chapter files, stitched into one audiobook
        try:
            res = self.window.create_file_dialog(webview.FOLDER_DIALOG)
            if res:
                return res[0]
        except Exception as e:
            self._js(f"window.nervError({json.dumps('folder dialog: ' + str(e))})")
        return None

    def start_render(self, opts):
        threading.Thread(target=self._render, args=(opts,), daemon=True).start()
        return {"ok": True}

    # --- worker ---
    def _render(self, opts):
        try:
            from shutil import which
            if not which("say"):
                raise eng.EngineError("`say` not found. This app only runs on macOS.")
            if not which("afconvert"):
                raise eng.EngineError("`afconvert` not found (should be built into macOS).")
            fmt = "m4b" if opts.get("fmt") == "m4b" else "m4a"
            files = eng.render(
                opts["file"],
                voice=opts.get("voice", ""),
                speed=float(opts.get("speed", 1.0)),
                by_paragraph=bool(opts.get("bypara", False)),
                fmt=fmt,
                on_start=lambda n: self._js(f"window.nervStart({int(n)})"),
                on_progress=lambda i, n, name:
                    self._js(f"window.nervProgress({int(i)},{int(n)},{json.dumps(name)})"),
            )
            self.last_out = files[0] if files else ""
            out_dir = os.path.dirname(self.last_out) if self.last_out else ""
            self._js(f"window.nervSetOut({json.dumps(self.last_out)})")
            self._js(f"window.nervDone({json.dumps(out_dir)},{len(files)})")
            if out_dir:
                self._reveal(out_dir)
        except BaseException as e:
            # BaseException so even SystemExit/keyboard cannot leave the UI frozen mid-render
            self._js(f"window.nervError({json.dumps(str(e) or e.__class__.__name__)})")

    def _reveal(self, path):
        try:
            import subprocess
            subprocess.Popen(["open", path])
        except Exception:
            pass

    def _js(self, code):
        try:
            self.window.evaluate_js(code)
        except Exception:
            pass


def main():
    api = Api()
    win = webview.create_window(
        "REDSHiFT // Audio Synthesis System",
        resource("nerv_ui.html"),
        js_api=api, width=1180, height=780, min_size=(940, 660),
        background_color="#05070b")
    api.window = win
    webview.start()


if __name__ == "__main__":
    main()
