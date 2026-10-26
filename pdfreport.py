"""Dependency-free PDF writer for the setup report, with the raw probe JSON appended so an AI can read it back.

The content streams are uncompressed, so read_raw_json() can recover the JSON from a PDF this module wrote.
Lines wrapped to fit the page are marked with a PDF comment ("%c") that text extractors ignore and the
reader uses to rejoin them.
"""
import json
import re

PAGE_W, PAGE_H, MARGIN = 595, 842, 40  # A4 in points
STYLES = {  # font resource, size, leading
    "title": ("F2", 15, 22),
    "heading": ("F2", 11, 17),
    "body": ("F1", 8.5, 11),
    "json": ("F1", 7, 8.6),
}
RAW_BEGIN, RAW_END = "BEGIN RAW JSON", "END RAW JSON"
REPLACE = {"→": "->", "—": "-", "–": "-", "…": "...", "’": "'", "“": '"', "”": '"', "█": "#", "░": "."}


def _latin1(text):
    for a, b in REPLACE.items():
        text = text.replace(a, b)
    return text.encode("latin-1", "replace").decode("latin-1")


def _escape(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _chars(style):
    # Courier is 0.6 em wide; Helvetica-Bold averages about 0.6 em too, close enough for headings.
    return max(int((PAGE_W - 2 * MARGIN) / (STYLES[style][1] * 0.6)), 20)


def _wrap(text, style):
    chars = _chars(style)
    # Break after a space when one is near the limit; the segments always join back to the exact text.
    segs = []
    while len(text) > chars:
        cut = text.rfind(" ", chars // 2, chars) + 1 or chars
        segs.append(text[:cut])
        text = text[cut:]
    return segs + [text]


def markdown_blocks(md):
    """The report's Markdown as (style, text) lines: headings bold, everything else monospace."""
    blocks, table = [], []
    for line in md.splitlines() + [""]:
        clean = line.replace("**", "")
        if clean.startswith("|"):
            if not set(clean) <= set("|-: "):
                table.append([c.strip() for c in clean.strip("|").split("|")])
            continue
        if table:
            widths = [max(len(r[i]) for r in table if i < len(r)) for i in range(len(table[0]))]
            if sum(widths) + 2 * len(widths) <= _chars("body"):
                for n, row in enumerate(table):
                    blocks.append(("body", "  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip()))
                    if n == 0:
                        blocks.append(("body", "  ".join("-" * w for w in widths)))
            else:  # too wide for the page: one block per row, titled by its first two cells
                header = table[0]
                for row in table[1:]:
                    label = f"{row[0]} ({header[1].lower()} {row[1]})" if len(row) > 1 and row[1] else row[0]
                    blocks.append(("heading", label))
                    blocks += [("body", f"{h}: {c}") for h, c in zip(header[2:], row[2:]) if c]
            table = []
        if line.startswith("# "):
            blocks.append(("title", clean[2:]))
        elif line.startswith(("## ", "### ")):
            blocks.append(("heading", clean.lstrip("#").strip()))
        else:
            blocks.append(("body", clean))
    return blocks


def write_pdf(path, md, raw_docs, appendix=""):
    blocks = markdown_blocks(md) + markdown_blocks(appendix) + [
        ("heading", "Raw probe data"),
        ("body", "Machine-readable copy of every probe result in this report. Judge it against the goals above.")]
    for doc in raw_docs:
        blocks.append(("json", RAW_BEGIN))
        blocks += [("json", line) for line in json.dumps(doc, indent=1, ensure_ascii=True).splitlines()]
        blocks.append(("json", RAW_END))

    pages, ops, y = [], [], PAGE_H - MARGIN
    for style, text in blocks:
        font, size, lead = STYLES[style]
        for i, seg in enumerate(_wrap(_latin1(text), style)):
            if y - lead < MARGIN:
                pages.append(ops)
                ops, y = [], PAGE_H - MARGIN
            y -= lead
            if i:
                ops.append("%c")
            ops.append(f"BT /{font} {size} Tf {MARGIN} {y:.1f} Td ({_escape(seg)}) Tj ET")
    pages.append(ops)

    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"]
    kids = []
    for ops in pages:
        stream = "\n".join(ops).encode("latin-1")
        objs.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                    f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {len(objs)} 0 R >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"

    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for n, obj in enumerate(objs, 1):
        offsets.append(len(out))
        body = obj if isinstance(obj, bytes) else obj.encode("latin-1")
        out += b"%d 0 obj\n" % n + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    with open(path, "wb") as f:
        f.write(out)


def read_raw_json(path):
    """Every probe result embedded in a PDF written by write_pdf()."""
    with open(path, "rb") as f:
        data = f.read().decode("latin-1")
    lines, cont = [], False
    for m in re.finditer(r"^%c$|\((?:[^\\)]|\\.)*\) Tj", data, re.M):
        tok = m.group(0)
        if tok == "%c":
            cont = True
            continue
        text = re.sub(r"\\(.)", r"\1", tok[1:-4])
        if cont and lines:
            lines[-1] += text
        else:
            lines.append(text)
        cont = False
    docs, buf = [], None
    for line in lines:
        if line == RAW_BEGIN:
            buf = []
        elif line == RAW_END and buf is not None:
            docs.append(json.loads("\n".join(buf)))
            buf = None
        elif buf is not None:
            buf.append(line)
    return docs
