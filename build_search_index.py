#!/usr/bin/env python3
"""
build_search_index.py  -  builds the offline full-text search index for index.html

Put this file, index.html and Update-Index.bat in the TOP folder of your library (the folder that
contains your category folders). Then run Update-Index.bat (or: python build_search_index.py).

  * Every PDF / EPUB / DOCX / TXT / MD under this folder is read, including NEW folders you add later.
  * Text is extracted page by page, so results can open the PDF at the right page.
  * Re-runs are fast: unchanged files are not re-read.
  * Output goes to a folder called _search next to index.html. Copy the whole library folder
    (index.html + _search + your category folders) to the USB drive. Nothing in it depends on a drive letter.

Options:
  --root PATH       library folder (default: the folder this script is in)
  --ocr             OCR pages that have no text (scans). Slow, but makes scanned manuals searchable.
                    Needs: pip install pymupdf pytesseract pillow   and the Tesseract program.
  --ocr-dpi N       OCR resolution (default 150; 200 is more accurate but slower)
  --rebuild         ignore the cache and re-read everything
  --faster          shorthand: skip the final summary of scanned files

Tip: pip install pymupdf makes text extraction roughly 10x faster than the default reader.
"""
import argparse
import html
import json
import math
import os
import re
import shutil
import sys
import time
import zipfile
from array import array
from collections import defaultdict
from datetime import datetime
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None
try:
    import pytesseract
    from PIL import Image
except ImportError:
    pytesseract = None
    Image = None

VERSION = 1
SEARCH_DIR = "_search"
SKIP_DIRS = {SEARCH_DIR.lower(), "_baddownloads", "_duplicates", "$recycle.bin",
             "system volume information", ".git", "__pycache__"}
EXTS = {".pdf", ".epub", ".docx", ".txt", ".md"}
MAX_PAGES = 65535          # composite id = doc*65536 + page
CHUNK_CHARS = 3000         # pseudo-pages for non-PDF text
MIN_TOKEN = 3
MAX_TOKEN = 30
COMMON_RATIO = 0.60        # terms on more than this share of pages are treated as stop words

STOP = set("""the and for with that this from are was were have has had not but you your can will any all may
which their they them been would should into than then when where what such other these those there also each
more most some only its our out who how why does did use used using via per etc one two""".split())


# --------------------------------------------------------------------------- tokenizing (MUST match index.html)
def stem(w):
    if len(w) > 4:
        if w.endswith("ies"):
            w = w[:-3] + "y"
        elif w.endswith("sses"):
            w = w[:-2]
        elif w.endswith(("xes", "ches", "shes")):
            w = w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    if len(w) > 5 and w.endswith("ing") and len(w) - 3 >= 4:
        w = w[:-3]
    elif len(w) > 5 and w.endswith("ed") and len(w) - 2 >= 4:
        w = w[:-2]
    if len(w) > 4 and w[-1] == w[-2] and w[-1] not in "aeioulsz":
        w = w[:-1]
    return w


TOKEN_RE = re.compile(r"[a-z0-9]+")


def index_terms(text):
    out = set()
    for t in TOKEN_RE.findall(text.lower()):
        if MIN_TOKEN <= len(t) <= MAX_TOKEN and t not in STOP:
            out.add(stem(t))
    return out


# --------------------------------------------------------------------------- extraction
def clean_page(t):
    t = t or ""
    t = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", t)      # join words hyphenated at line ends
    t = t.replace("\u2028", " ").replace("\u2029", " ").replace("\x00", " ")
    return re.sub(r"\s+", " ", t).strip()


def ocr_page(page, dpi):
    pix = page.get_pixmap(dpi=dpi)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return pytesseract.image_to_string(img)


def extract_pdf(path, use_ocr, dpi):
    """Return (pages, ocr_pages_count). pages is a list of strings (may be empty strings)."""
    pages = []
    if fitz is not None:
        try:
            doc = fitz.open(path)
            if doc.needs_pass:
                doc.authenticate("")
            n = min(len(doc), MAX_PAGES)
            for i in range(n):
                try:
                    txt = doc[i].get_text()
                except Exception:
                    txt = ""
                pages.append(clean_page(txt))
            ocr_count = 0
            if use_ocr and pytesseract is not None:
                for i in range(n):
                    if len(pages[i]) < 25:
                        try:
                            pages[i] = clean_page(ocr_page(doc[i], dpi))
                            ocr_count += 1
                        except Exception as e:
                            print(f"      OCR failed on page {i + 1}: {e}")
                            break
            doc.close()
            return pages, ocr_count
        except Exception as e:
            print(f"      PyMuPDF could not read it ({e}); trying the other reader")
            pages = []
    if PdfReader is not None:
        try:
            reader = PdfReader(str(path))
            if reader.is_encrypted:
                reader.decrypt("")
            n = min(len(reader.pages), MAX_PAGES)
            for i in range(n):
                try:
                    pages.append(clean_page(reader.pages[i].extract_text() or ""))
                except Exception:
                    pages.append("")
            return pages, 0
        except Exception as e:
            print(f"      unreadable: {e}")
    return pages, 0


def chunk(text, size=CHUNK_CHARS):
    text = clean_page(text)
    out, i = [], 0
    while i < len(text):
        j = min(len(text), i + size)
        if j < len(text):
            k = text.rfind(" ", i + size // 2, j)
            if k > 0:
                j = k
        out.append(text[i:j].strip())
        i = j
    return out


def strip_tags(s):
    s = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return html.unescape(s)


def extract_epub(path):
    try:
        with zipfile.ZipFile(path) as z:
            names = sorted(n for n in z.namelist() if n.lower().endswith((".xhtml", ".html", ".htm")))
            text = " ".join(strip_tags(z.read(n).decode("utf-8", "ignore")) for n in names)
        return chunk(text)
    except Exception as e:
        print(f"      unreadable: {e}")
        return []


def extract_docx(path):
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        return chunk(strip_tags(xml))
    except Exception as e:
        print(f"      unreadable: {e}")
        return []


def extract_txt(path):
    try:
        return chunk(Path(path).read_text(encoding="utf-8", errors="ignore"))
    except Exception as e:
        print(f"      unreadable: {e}")
        return []


# --------------------------------------------------------------------------- file helpers
def pretty_title(stem_text):
    from urllib.parse import unquote
    s = unquote(stem_text).replace("_", " ")
    s = re.sub(r"(?<=[A-Za-z])-(?=[A-Za-z0-9])", " ", s)
    s = re.sub(r"(?<=\d)-(?=[A-Za-z])", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def write_js(path, kind, key, payload_json):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f'__lib("{kind}",{json.dumps(key)},\n{payload_json}\n);\n')


def read_pages_js(path):
    raw = Path(path).read_text(encoding="utf-8")
    body = raw.split("\n", 1)[1].rsplit("\n);", 1)[0]
    return json.loads(body)


def scan_files(root):
    found = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d.lower() not in SKIP_DIRS)
        for f in sorted(files):
            if Path(f).suffix.lower() in EXTS and not f.startswith("~$"):
                found.append(Path(dirpath) / f)
    return found


# --------------------------------------------------------------------------- main
def build(args):
    root = Path(args.root).resolve()
    sdir = root / SEARCH_DIR
    tdir, idir = sdir / "text", sdir / "idx"
    sdir.mkdir(exist_ok=True)
    tdir.mkdir(exist_ok=True)

    if fitz is None and PdfReader is None:
        sys.exit("Install a PDF reader first:   pip install pymupdf   (or: pip install pypdf)")
    if fitz is None:
        print("Tip: 'pip install pymupdf' makes this about 10x faster.\n")
    if args.ocr and (fitz is None or pytesseract is None):
        print("OCR needs:  pip install pymupdf pytesseract pillow   plus the Tesseract program. Continuing without OCR.\n")
        args.ocr = False
    if args.ocr and os.environ.get("TESSERACT_CMD"):
        pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]

    state_path = sdir / "state.json"
    state = {"next_id": 1, "files": {}}
    if state_path.exists() and not args.rebuild:
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    files = scan_files(root)
    rels = {}
    for p in files:
        rels[p.relative_to(root).as_posix()] = p
    print(f"Library: {root}\nFound {len(files)} files. Reading text (unchanged files are skipped)...\n")

    # drop files that disappeared
    for rel in list(state["files"]):
        if rel not in rels:
            info = state["files"].pop(rel)
            (tdir / f"{info['id']}.js").unlink(missing_ok=True)
            print(f"  removed from index: {rel}")

    started = time.time()
    done_new = 0
    for n, (rel, p) in enumerate(rels.items(), 1):
        st = p.stat()
        sig = {"size": st.st_size, "mtime": int(st.st_mtime)}
        info = state["files"].get(rel)
        tfile = tdir / f"{info['id']}.js" if info else None
        if (info and tfile.exists() and info.get("size") == sig["size"] and info.get("mtime") == sig["mtime"]
                and not (args.ocr and info.get("scan") and not info.get("ocr"))):
            continue
        if not info:
            info = {"id": state["next_id"]}
            state["next_id"] += 1
        ext = p.suffix.lower()
        print(f"  [{n}/{len(rels)}] {rel}")
        ocr_count = 0
        if ext == ".pdf":
            pages, ocr_count = extract_pdf(p, args.ocr, args.ocr_dpi)
        elif ext == ".epub":
            pages = extract_epub(p)
        elif ext == ".docx":
            pages = extract_docx(p)
        else:
            pages = extract_txt(p)
        chars = sum(len(x) for x in pages)
        info.update(sig)
        info["pages"] = len(pages)
        info["chars"] = chars
        info["scan"] = bool(pages) and chars < 40 * max(1, len(pages)) if ext == ".pdf" else (chars == 0)
        info["ocr"] = ocr_count > 0
        state["files"][rel] = info
        write_js(tdir / f"{info['id']}.js", "t", info["id"], json.dumps(pages, ensure_ascii=False, separators=(",", ":")))
        done_new += 1
        if done_new % 25 == 0:
            state_path.write_text(json.dumps(state), encoding="utf-8")   # safe to Ctrl+C and resume
    state_path.write_text(json.dumps(state), encoding="utf-8")
    print(f"\nRead {done_new} new/changed files in {time.time() - started:.0f}s.")

    # ---- inverted index
    print("Building the search index...")
    ids = sorted(state["files"].items(), key=lambda kv: kv[1]["id"])
    postings = defaultdict(lambda: array("q"))
    total_pages = 0
    for rel, info in ids:
        tfile = tdir / f"{info['id']}.js"
        if not tfile.exists():
            continue
        pages = read_pages_js(tfile)
        base = info["id"] * 65536
        for pno, text in enumerate(pages, 1):
            if not text:
                continue
            total_pages += 1
            for term in index_terms(text):
                postings[term].append(base + pno)

    common = [t for t, a in postings.items() if len(a) > COMMON_RATIO * max(total_pages, 1) and total_pages > 200]
    for t in common:
        del postings[t]

    if idir.exists():
        shutil.rmtree(idir)
    shards = defaultdict(dict)
    for term, arr in postings.items():
        vals = list(arr)
        deltas = [vals[0]] + [vals[i] - vals[i - 1] for i in range(1, len(vals))]
        shards[term[:2]][term] = deltas
    for key, terms in shards.items():
        write_js(idir / f"{key}.js", "i", key, json.dumps(terms, separators=(",", ":")))

    # ---- manifest
    docs = []
    for rel, info in ids:
        parts = rel.split("/")
        docs.append({
            "id": info["id"], "p": rel, "t": pretty_title(Path(rel).stem),
            "c": parts[0] if len(parts) > 1 else "Root",
            "s": "/".join(parts[1:-1]), "n": info.get("pages", 0), "b": info["size"],
            "x": 0 if info.get("scan") else 1, "o": 1 if info.get("ocr") else 0,
            "e": Path(rel).suffix.lower().lstrip("."),
        })
    manifest = {"v": VERSION, "built": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "pages": total_pages, "docs": docs, "common": sorted(common)}
    (sdir / "manifest.js").write_text(
        "window.LIB_MANIFEST=" + json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8")

    size = sum(f.stat().st_size for f in sdir.rglob("*") if f.is_file())
    scans = [d for d in docs if not d["x"]]
    print(f"\nDone. {len(docs)} documents, {total_pages:,} searchable pages, "
          f"{len(postings):,} distinct terms, index folder {size / 1048576:.1f} MB.")
    if scans and not args.faster:
        print(f"\n{len(scans)} documents have no readable text (scans). They can be found by title only.")
        print("Run Update-Index-OCR.bat (needs Tesseract) to make them searchable:")
        for d in scans[:15]:
            print(f"   - {d['p']}")
        if len(scans) > 15:
            print(f"   ... and {len(scans) - 15} more")
    print("\nOpen index.html in your browser.")


def main():
    ap = argparse.ArgumentParser(description="Build the offline search index for index.html")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent))
    ap.add_argument("--ocr", action="store_true")
    ap.add_argument("--ocr-dpi", type=int, default=150)
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--faster", action="store_true")
    build(ap.parse_args())


if __name__ == "__main__":
    main()
