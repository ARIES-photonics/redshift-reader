#!/usr/bin/env python3
# redshift_reader.py  --  turn a book file into an audiobook using the Mac's own voices.
# No installs needed for .md / .txt / .tex. PDF uses pdftotext if present; EPUB uses pandoc if present.
# Built for Liam. Records-safe: never overwrites an existing audio file (auto-versions the name).
#
# Usage examples (run in Terminal, or just use the double-click .command wrapper):
#   python3 redshift_reader.py --list-voices
#   python3 redshift_reader.py "Chapter_01.md" --voice "Daniel" --rate 190
#   python3 redshift_reader.py book.pdf --voice "Zoe (Premium)" --by-paragraph --out ~/Desktop/REDSHiFT_audio
#
# Notes:
#  - Strips dash-art dividers, markdown, HTML comments, and LaTeX so the voice reads flowing prose,
#    not line-by-line like a third grader.
#  - Produces .m4a (small, AirPods-friendly) via afconvert, or raw .aiff with --aiff.

import argparse, os, re, subprocess, sys, html, datetime, zipfile

# ---------- text extraction ----------

def extract_txt(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()

def extract_pdf(path):
    # Prefer pdftotext (poppler). Fall back to python pypdf if installed.
    if which("pdftotext"):
        out = run_capture(["pdftotext", "-layout", "-enc", "UTF-8", path, "-"])
        if out is not None:
            return out
    try:
        import pypdf  # type: ignore
        reader = pypdf.PdfReader(path)
        return "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception:
        die("This PDF needs a text extractor. Easiest fix: feed me the .md or .tex version instead, "
            "or run  brew install poppler  once and try again.")

def extract_epub(path):
    if which("pandoc"):
        out = run_capture(["pandoc", "-t", "plain", path])
        if out is not None:
            return out
    # crude built-in fallback: pull text from the html inside the epub zip
    try:
        chunks = []
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))]
            for n in sorted(names):
                raw = z.read(n).decode("utf-8", "replace")
                chunks.append(strip_html(raw))
        if chunks:
            return "\n\n".join(chunks)
    except Exception:
        pass
    die("This EPUB needs pandoc to read cleanly. Run  brew install pandoc  once, "
        "or feed me the .md / .tex version instead.")

def extract(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in (".md", ".markdown", ".txt", ".text"):
        return extract_txt(path)
    if ext == ".tex":
        return strip_latex(extract_txt(path))
    if ext == ".pdf":
        return extract_pdf(path)
    if ext == ".epub":
        return extract_epub(path)
    # unknown: just try reading it as text
    return extract_txt(path)

# ---------- cleaning for speech ----------

def strip_html(text):
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text)

def strip_latex(text):
    text = re.sub(r"(?<!\\)%.*", "", text)               # comments
    text = re.sub(r"\$[^$]*\$", " ", text)               # inline math
    text = re.sub(r"\\begin\{[^}]*\}|\\end\{[^}]*\}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?(\{[^}]*\})?", " ", text)  # commands
    text = re.sub(r"\[[^\]\n]{0,40}\]", " ", text)        # leftover option brackets, e.g. [display]
    text = text.replace("{", " ").replace("}", " ").replace("\\", " ").replace("$", " ")
    text = re.sub(r"\b\d+(\.\d+)?\s*(em|ex|pt|cm|mm|in|bp|pc|sp)\b", " ", text)  # dimensions
    return text

def clean_for_speech(text):
    # HTML comments / tags first (the .md files have <!-- CANON ... --> blocks)
    text = strip_html(text)

    # Markdown code fences and inline code
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`([^`]*)`", r"\1", text)

    # Images / links: keep the words, drop the syntax
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)

    # Headings, blockquotes, list bullets, table pipes
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "", text)
    text = re.sub(r"(?m)^\s*\d+\.\s+", "", text)
    text = text.replace("|", " ")

    # Emphasis markers
    text = re.sub(r"(\*\*|__|\*|_)", "", text)

    # Dash-art dividers and rules: lines made mostly of - = _ ~ / and em dashes
    text = re.sub(r"(?m)^[\s\-\=\_\~\/—–‒―\.\*\#]{4,}$", "", text)

    # Runs of slashes / pipes / backslashes used as styling (e.g. //RED//SHiFT////) -> space,
    # so the voice reads "RED SHiFT" not "slash slash red slash". Single slash (and/or) is kept.
    text = re.sub(r"[\/|\\]{2,}", " ", text)

    # Em / en dashes anywhere -> comma pause (also Liam's hard no-em-dash rule)
    text = re.sub(r"\s*[‒–—―]+\s*", ", ", text)

    # Smart quotes / ellipsis to plain so the voice handles them well
    text = (text.replace("‘", "'").replace("’", "'")
                .replace("“", '"').replace("”", '"')
                .replace("…", "... "))

    # Collapse hard-wrapped lines into paragraphs:
    # blank line(s) = paragraph break (keep), single newline inside a paragraph = space.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    paras = re.split(r"\n[ \t]*\n+", text)
    fixed = []
    for p in paras:
        joined = re.sub(r"\s*\n\s*", " ", p).strip()
        joined = re.sub(r"[ \t]{2,}", " ", joined)
        if joined:
            fixed.append(joined)
    return "\n\n".join(fixed)

# ---------- chunking ----------

def chunk_text(text, by_paragraph=False, max_chars=120000):
    paras = [p for p in text.split("\n\n") if p.strip()]
    if by_paragraph:
        return paras
    # Otherwise pack paragraphs into big blocks (say handles long input fine;
    # blocks just give resumable files and avoid any input-size edge cases).
    blocks, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) + 2 > max_chars:
            blocks.append(cur); cur = ""
        cur = (cur + "\n\n" + p) if cur else p
    if cur:
        blocks.append(cur)
    return blocks or [text]

# ---------- mac speech ----------

def list_voices():
    out = run_capture(["say", "-v", "?"])
    if out is None:
        die("Could not run `say`. This tool only runs on macOS.")
    print(out.rstrip())
    print("\nTip: the nicest ones are the 'Premium' / 'Enhanced' voices. Download more in\n"
          "System Settings, Accessibility, Spoken Content, System Voice, Manage Voices.")

def unique_path(path):
    # Never overwrite. If it exists, append _v2, _v3, ...
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{base}_v{n}{ext}"):
        n += 1
    return f"{base}_v{n}{ext}"

def synth(block, voice, rate, out_aiff):
    cmd = ["say"]
    if voice:
        cmd += ["-v", voice]
    if rate:
        cmd += ["-r", str(rate)]
    cmd += ["-o", out_aiff, block]
    subprocess.run(cmd, check=True)

def to_m4a(aiff_path, m4a_path):
    # afconvert ships with macOS. AAC, 64 kbps mono-ish is plenty for speech.
    subprocess.run(["afconvert", aiff_path, m4a_path,
                    "-d", "aac", "-f", "m4af", "-b", "80000"], check=True)

# ---------- helpers ----------

def which(name):
    from shutil import which as _w
    return _w(name)

def run_capture(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            return None
        return r.stdout
    except FileNotFoundError:
        return None

def die(msg):
    print("\n[redshift_reader] " + msg + "\n", file=sys.stderr)
    sys.exit(1)

def safe_stem(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("_") or "audiobook"

# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description="Read a book file aloud with a Mac voice and save audio.")
    ap.add_argument("input", nargs="?", help="book file: .md .txt .tex .pdf .epub")
    ap.add_argument("--voice", default="", help='Mac voice name, e.g. "Daniel" or "Zoe (Premium)"')
    ap.add_argument("--speed", type=float, default=1.0,
                    help="podcast-style multiplier, 1.0 = natural. 0.5 to 2.5 in 0.1 steps. Pitch stays normal.")
    ap.add_argument("--rate", type=int, default=0,
                    help="absolute words per minute. Overrides --speed if given (~175 is natural).")
    ap.add_argument("--out", default="", help="output folder (default: a folder next to the input file)")
    ap.add_argument("--by-paragraph", action="store_true", help="one audio file per paragraph (max resumability)")
    ap.add_argument("--aiff", action="store_true", help="keep raw .aiff instead of converting to .m4a")
    ap.add_argument("--list-voices", action="store_true", help="list installed Mac voices and exit")
    ap.add_argument("--dump-text", action="store_true", help="just print the cleaned text, do not synthesize")
    args = ap.parse_args()

    if args.list_voices:
        list_voices(); return
    if not args.input:
        ap.error("give me a book file (or use --list-voices)")
    if not os.path.exists(args.input):
        die(f"file not found: {args.input}")

    raw = extract(args.input)
    text = clean_for_speech(raw)
    if not text.strip():
        die("nothing readable found in that file after cleaning.")

    if args.dump_text:
        print(text); return

    stem = safe_stem(args.input)
    out_dir = args.out or os.path.join(os.path.dirname(os.path.abspath(args.input)),
                                       f"{stem}_audio")
    os.makedirs(out_dir, exist_ok=True)

    # Resolve speed -> words per minute. say's natural pace sits near 175 wpm.
    BASE_WPM = 175
    if args.rate:
        eff_rate = args.rate
        speed_label = f"{args.rate} wpm"
    else:
        speed = round(min(2.5, max(0.5, args.speed)) * 10) / 10  # clamp + snap to 0.1
        eff_rate = 0 if speed == 1.0 else int(round(BASE_WPM * speed))
        speed_label = f"{speed:.1f}x"

    blocks = chunk_text(text, by_paragraph=args.by_paragraph)
    n = len(blocks)
    width = max(3, len(str(n)))
    ext = ".aiff" if args.aiff else ".m4a"
    print(f"[redshift_reader] {stem}: {n} block(s), voice={args.voice or 'default'}, "
          f"speed={speed_label} -> {out_dir}")

    made = []
    for i, block in enumerate(blocks, 1):
        idx = str(i).zfill(width)
        aiff = unique_path(os.path.join(out_dir, f"{stem}_{idx}.aiff"))
        synth(block, args.voice, eff_rate, aiff)
        if args.aiff:
            made.append(aiff)
        else:
            m4a = unique_path(os.path.join(out_dir, f"{stem}_{idx}.m4a"))
            to_m4a(aiff, m4a)
            os.remove(aiff)
            made.append(m4a)
        print(f"  [{idx}/{n}] {os.path.basename(made[-1])}")

    print(f"\n[redshift_reader] done. {len(made)} file(s) in:\n  {out_dir}")

if __name__ == "__main__":
    main()
