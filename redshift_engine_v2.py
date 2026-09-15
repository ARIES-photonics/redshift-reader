#!/usr/bin/env python3
# redshift_engine_v2.py  --  REDSHiFT audiobook engine (v2).
# v1 (redshift_reader.py) is kept untouched as a record. v2 adds:
#   - single-file .m4b audiobook export (drops straight into Apple Books on iPhone)
#   - whole-folder mode (stitch every chapter file into one audiobook, natural-sorted)
#   - render() with progress callbacks, used by the NERV app (app.py)
#   - say -f (reads text from a file) so huge books do not blow the command-line limit
#
# Mac only at synthesis time (uses `say` and `afconvert`, both built into macOS).
# Text extraction/cleaning works anywhere, so --dry-run can be tested off-Mac.
#
# CLI:
#   python3 redshift_engine_v2.py --list-voices
#   python3 redshift_engine_v2.py "Chapter_01.md" --voice "Daniel" --speed 1.3
#   python3 redshift_engine_v2.py "Chapter_01.md" --m4b --voice "Zoe (Premium)"
#   python3 redshift_engine_v2.py /path/to/Scenes --m4b --voice "Daniel"   # whole folder -> one book
#   python3 redshift_engine_v2.py file.md --dry-run                        # plan only, no audio

import argparse, os, re, subprocess, sys, html, tempfile


class EngineError(Exception):
    """Raised for clean, user-facing problems (bad format, missing tool, empty text).
    The app catches this and shows the message in the MAGI console instead of dying silently."""
    pass


# ----------------------------------------------------------------- extraction

def _read(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()

def extract(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".md", ".markdown", ".txt", ".text"):
        return _read(path)
    if ext == ".tex":
        return strip_latex(_read(path))
    if ext == ".pdf":
        return extract_pdf(path)
    if ext == ".epub":
        return extract_epub(path)
    return _read(path)

def extract_pdf(path):
    if which("pdftotext"):
        out = run_capture(["pdftotext", "-layout", "-enc", "UTF-8", path, "-"])
        if out is not None:
            return out
    try:
        import pypdf  # type: ignore
        return "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(path).pages)
    except ImportError:
        raise EngineError("This PDF needs a reader. Feed the .md or .tex version instead, "
                          "or install support once with:  pip3 install pypdf")
    except Exception as e:
        raise EngineError("Could not read that PDF (" + str(e) + "). Try the .md or .tex version.")

def extract_epub(path):
    if which("pandoc"):
        out = run_capture(["pandoc", "-t", "plain", path])
        if out is not None:
            return out
    try:
        import zipfile
        parts = []
        with zipfile.ZipFile(path) as z:
            for n in sorted(x for x in z.namelist() if x.lower().endswith((".xhtml", ".html", ".htm"))):
                parts.append(strip_html(z.read(n).decode("utf-8", "replace")))
        if parts:
            return "\n\n".join(parts)
    except Exception:
        pass
    die("EPUB needs pandoc. Run  brew install pandoc, or feed the .md / .tex instead.")

# ----------------------------------------------------------------- cleaning

def strip_html(text):
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text)

def strip_latex(text):
    text = re.sub(r"(?<!\\)%.*", "", text)
    text = re.sub(r"\$[^$]*\$", " ", text)
    text = re.sub(r"\\begin\{[^}]*\}|\\end\{[^}]*\}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^}]*\})?", " ", text)
    text = re.sub(r"\[[^\]\n]{0,40}\]", " ", text)
    text = text.replace("{", " ").replace("}", " ").replace("\\", " ").replace("$", " ")
    text = re.sub(r"\b\d+(\.\d+)?\s*(em|ex|pt|cm|mm|in|bp|pc|sp)\b", " ", text)
    return text

def clean_for_speech(text):
    text = strip_html(text)
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    text = re.sub(r"(?m)^\s*\d+\.\s+", "", text)
    text = text.replace("|", " ")
    text = re.sub(r"(\*\*|__|\*|_)", "", text)
    text = re.sub(r"(?m)^[\s\-\=\_\~\/—–‒―\.\*\#]{4,}$", "", text)
    text = re.sub(r"[\/|\\]{2,}", " ", text)
    text = re.sub(r"\s*[‒–—―]+\s*", ", ", text)
    text = (text.replace("‘", "'").replace("’", "'")
                .replace("“", '"').replace("”", '"').replace("…", "... "))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for p in re.split(r"\n[ \t]*\n+", text):
        j = re.sub(r"\s*\n\s*", " ", p).strip()
        j = re.sub(r"[ \t]{2,}", " ", j)
        if j:
            out.append(j)
    return "\n\n".join(out)

# ----------------------------------------------------------------- folder mode

BOOK_EXTS = (".md", ".markdown", ".txt", ".text", ".tex")

def natural_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]

def gather_folder(folder):
    files = [os.path.join(folder, f) for f in os.listdir(folder)
             if os.path.splitext(f)[1].lower() in BOOK_EXTS and not f.startswith(".")]
    files.sort(key=lambda p: natural_key(os.path.basename(p)))
    return files

def collect_text(input_path):
    """Return (list_of_(label, cleaned_text), book_stem). Folder -> one entry per file."""
    if os.path.isdir(input_path):
        chapters = []
        for fp in gather_folder(input_path):
            t = clean_for_speech(extract(fp))
            if t.strip():
                chapters.append((safe_stem(fp), t))
        return chapters, safe_stem(input_path.rstrip("/"))
    return [(safe_stem(input_path), clean_for_speech(extract(input_path)))], safe_stem(input_path)

# ----------------------------------------------------------------- speech

def voice_names():
    out = run_capture(["say", "-v", "?"])
    if not out:
        return []
    names = []
    for line in out.splitlines():
        m = re.match(r"^(.*?)\s{2,}[a-z]{2,3}[-_][A-Z]{2,3}", line)
        if m:
            names.append(m.group(1).strip())
    return names

def speed_to_rate(speed=1.0, rate=0, base_wpm=175):
    if rate:
        return rate
    s = round(min(2.5, max(0.5, speed)) * 10) / 10
    return 0 if s == 1.0 else int(round(base_wpm * s))

def say_to_aiff(text, voice, rate, aiff):
    tf = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    tf.write(text); tf.close()
    try:
        cmd = ["say"]
        if voice: cmd += ["-v", voice]
        if rate:  cmd += ["-r", str(rate)]
        cmd += ["-f", tf.name, "-o", aiff]
        subprocess.run(cmd, check=True)
    finally:
        try: os.unlink(tf.name)
        except OSError: pass

def to_m4a(aiff, m4a):
    subprocess.run(["afconvert", aiff, m4a, "-d", "aac", "-f", "m4af"], check=True)

def to_m4b(aiff, m4b):
    # m4af container + .m4b extension = Apple Books audiobook (resume, speed, sleep timer)
    subprocess.run(["afconvert", aiff, m4b, "-d", "aac", "-f", "m4af"], check=True)

# ----------------------------------------------------------------- render

def chunk(text, by_paragraph=False, max_chars=120000):
    paras = [p for p in text.split("\n\n") if p.strip()]
    if by_paragraph:
        return paras
    blocks, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) + 2 > max_chars:
            blocks.append(cur); cur = ""
        cur = (cur + "\n\n" + p) if cur else p
    if cur:
        blocks.append(cur)
    return blocks or [text]

def render(input_path, voice="", speed=1.0, rate=0, by_paragraph=False,
           fmt="m4a", out_dir="", on_start=None, on_progress=None, dry_run=False):
    """Synthesize audio. fmt in {m4a, aiff, m4b}. Returns list of output file paths.
       m4b: one audiobook file (whole file, or whole folder stitched). m4a/aiff: per block."""
    eff_rate = speed_to_rate(speed, rate)
    chapters, book_stem = collect_text(input_path)
    if not chapters:
        raise RuntimeError("nothing readable found after cleaning.")

    src_root = input_path if os.path.isdir(input_path) else os.path.dirname(os.path.abspath(input_path))
    out_dir = out_dir or os.path.join(src_root, f"{book_stem}_audio")
    if not dry_run:
        os.makedirs(out_dir, exist_ok=True)
    made = []

    if fmt == "m4b":
        full = "\n\n".join(t for _, t in chapters)
        if on_start: on_start(1)
        target = unique_path(os.path.join(out_dir, f"{book_stem}.m4b"))
        if dry_run:
            if on_progress: on_progress(1, 1, os.path.basename(target))
            return [target]
        aiff = unique_path(os.path.join(out_dir, f".{book_stem}.tmp.aiff"))
        say_to_aiff(full, voice, eff_rate, aiff)
        to_m4b(aiff, target)
        try: os.remove(aiff)
        except OSError: pass
        made.append(target)
        if on_progress: on_progress(1, 1, os.path.basename(target))
        return made

    # m4a / aiff : per block, across all chapters
    blocks = []
    for label, text in chapters:
        for b in chunk(text, by_paragraph=by_paragraph):
            blocks.append((label, b))
    n = len(blocks)
    if on_start: on_start(n)
    width = max(3, len(str(n)))
    use_aiff = (fmt == "aiff")
    for i, (label, block) in enumerate(blocks, 1):
        idx = str(i).zfill(width)
        stem = label if len(chapters) > 1 else book_stem
        if dry_run:
            made.append(os.path.join(out_dir, f"{stem}_{idx}.{ 'aiff' if use_aiff else 'm4a'}"))
            if on_progress: on_progress(i, n, os.path.basename(made[-1]))
            continue
        aiff = unique_path(os.path.join(out_dir, f"{stem}_{idx}.aiff"))
        say_to_aiff(block, voice, eff_rate, aiff)
        if use_aiff:
            made.append(aiff)
        else:
            m4a = unique_path(os.path.join(out_dir, f"{stem}_{idx}.m4a"))
            to_m4a(aiff, m4a)
            try: os.remove(aiff)
            except OSError: pass
            made.append(m4a)
        if on_progress: on_progress(i, n, os.path.basename(made[-1]))
    return made

# ----------------------------------------------------------------- helpers

def which(name):
    from shutil import which as _w
    return _w(name)

def run_capture(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.stdout if r.returncode == 0 else None
    except FileNotFoundError:
        return None

def unique_path(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{base}_v{n}{ext}"):
        n += 1
    return f"{base}_v{n}{ext}"

def safe_stem(path):
    stem = os.path.splitext(os.path.basename(path.rstrip("/")))[0]
    return re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_") or "audiobook"

def die(msg):
    print("\n[redshift_engine] " + msg + "\n", file=sys.stderr)
    sys.exit(1)

# ----------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description="REDSHiFT audiobook engine v2.")
    ap.add_argument("input", nargs="?", help="book file or folder (.md .txt .tex .pdf .epub)")
    ap.add_argument("--voice", default="")
    ap.add_argument("--speed", type=float, default=1.0, help="0.5 to 2.5, 1.0 natural (pitch locked)")
    ap.add_argument("--rate", type=int, default=0, help="absolute wpm, overrides --speed")
    ap.add_argument("--m4b", action="store_true", help="single Apple Books audiobook (.m4b)")
    ap.add_argument("--aiff", action="store_true", help="raw .aiff instead of .m4a")
    ap.add_argument("--by-paragraph", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--list-voices", action="store_true")
    ap.add_argument("--dump-text", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="plan blocks/files, no audio (works off-Mac)")
    a = ap.parse_args()

    if a.list_voices:
        vs = voice_names()
        print("\n".join(vs) if vs else "(no voices; `say` only runs on macOS)")
        return
    if not a.input:
        ap.error("give a book file or folder (or --list-voices)")
    if not os.path.exists(a.input):
        die(f"not found: {a.input}")

    if a.dump_text:
        chapters, _ = collect_text(a.input)
        print("\n\n".join(t for _, t in chapters)); return

    fmt = "m4b" if a.m4b else ("aiff" if a.aiff else "m4a")
    def start(n): print(f"[redshift_engine] {n} block(s), voice={a.voice or 'default'}, "
                        f"speed={a.speed:.1f}x, fmt={fmt}")
    def prog(i, n, name): print(f"  [{str(i).zfill(3)}/{n}] {name}")
    made = render(a.input, voice=a.voice, speed=a.speed, rate=a.rate,
                  by_paragraph=a.by_paragraph, fmt=fmt, out_dir=a.out,
                  on_start=start, on_progress=prog, dry_run=a.dry_run)
    print(f"\n[redshift_engine] {'planned' if a.dry_run else 'done'}: {len(made)} file(s)")
    if made:
        print("  -> " + os.path.dirname(made[0]))

if __name__ == "__main__":
    main()
