# Offline audiobook reader

Turns a book file into a chaptered audiobook using the speech voices already installed on macOS. No
network calls, no API keys, no subscription. Ships as a command-line tool and as a packaged .app.

```sh
python3 redshift_reader.py "Chapter_01.md" --voice "Daniel" --speed 1.4
python3 redshift_reader.py book.pdf --voice "Zoe (Premium)" --by-paragraph
python3 redshift_reader.py file.md --dump-text     # preview cleaned text, emit no audio
python3 redshift_reader.py --list-voices
```

Output is `.m4a`, one file per chapter by default, written next to the source.

## The actual problem

Feeding raw markdown or LaTeX to a speech synthesizer produces something unlistenable. The
synthesizer reads punctuation as punctuation, treats every hard-wrapped line as a sentence ending,
and pauses in the wrong places, so the result stutters line by line instead of reading as prose.

Most of this codebase is the text normalizer, not the audio call. Before synthesis it:

- welds hard-wrapped lines back into real sentences and paragraphs
- strips markdown, LaTeX commands and inline math, and HTML comment blocks
- removes rule-art dividers and decorative title bars
- converts smart quotes and em dashes into pause punctuation the synthesizer handles correctly

`--dump-text` prints exactly what will be spoken so the normalizer can be inspected before spending
time on synthesis. That flag exists because reading the cleaned text is far faster than listening to
find out what went wrong.

## Input formats

`.md`, `.txt` and `.tex` work on a stock Mac with no installation. `.pdf` and `.epub` need the
extractors in `requirements.txt`.

## Flags

| Flag | Effect |
|---|---|
| `--voice NAME` | Any installed system voice. Premium and Enhanced voices sound best. |
| `--speed 0.5..2.5` | Rate multiplier. Pitch is unchanged. |
| `--rate WPM` | Absolute words per minute, overrides `--speed`. |
| `--by-paragraph` | One audio file per paragraph instead of per chapter. |
| `--out FOLDER` | Output directory. |
| `--aiff` | Keep AIFF, skip the m4a encode. |
| `--dump-text` | Print the cleaned text and exit. |

## Building the app

```sh
bash build_REDSHiFT_app.command
```

Uses PyInstaller with the included spec file. The GUI wrapper is `app.py` with `nerv_ui.html`.

## Platform

macOS only. It drives the system speech synthesizer directly, so there is no Linux or Windows path
without swapping the synthesis backend.

## License

MIT
