"""pdfgen.py: tiny hand-made PDFs for the negative and safety fixtures (standard library only). Not a PDF library."""


def make_pdf(objs, root=1, trailer=b"", header=b"%PDF-1.7\n"):
    """objs {number: body bytes}; numbers must be 1..n. Returns the file bytes with a correct xref table."""
    out, offs = bytearray(header + b"%\xe2\xe3\xcf\xd3\n"), {}
    for n in sorted(objs):
        offs[n] = len(out)
        out += b"%d 0 obj\n" % n + objs[n] + b"\nendobj\n"
    size, start = max(objs) + 1, len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size + b"".join(b"%010d 00000 n \n" % offs[n] for n in range(1, size))
    out += b"trailer\n<< /Size %d /Root %d 0 R %s >>\nstartxref\n%d\n%%%%EOF\n" % (size, root, trailer, start)
    return bytes(out)


def stream(body, extra=b""):
    return b"<< /Length %d %s >>\nstream\n%s\nendstream" % (len(body), extra, body)


def page_objs(content=b"BT /F1 18 Tf 72 720 Td (Sample line) Tj ET", annots=b"", font=b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"):
    """Objects 2 (Pages), 3 (Page), 4 (Font), 5 (content) of a one-page file."""
    return {2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R /Helv 4 0 R >> >> /Contents 5 0 R " + annots + b" >>",
            4: font, 5: stream(content)}


def plain_pdf(info=b"", content=None):
    """One page, Helvetica NOT embedded. content=None gives one line of text; pass drawing operators only for a page with no text."""
    objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>", **(page_objs(content=content) if content is not None else page_objs())}
    if info:
        objs[6] = info
        return make_pdf(objs, trailer=b"/Info 6 0 R")
    return make_pdf(objs)


def link_pdf(dest=b"(nowhere)"):
    """One page with one internal link whose destination is not defined anywhere."""
    objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>", **page_objs(annots=b"/Annots [6 0 R]"),
            6: b"<< /Type /Annot /Subtype /Link /Rect [72 700 200 720] /Border [0 0 0] /Dest " + dest + b" >>"}
    return make_pdf(objs)


def form_pdf(signature=None):
    """One page with a text field (full_name), a checkbox (agree, on-state /Yes) and an empty signature field (sign_here).
    signature=True fills the signature field with a /V, which makes the file a signed document."""
    sigv = b" /V 11 0 R" if signature else b""
    objs = {
        1: b"<< /Type /Catalog /Pages 2 0 R /AcroForm << /Fields [6 0 R 7 0 R 8 0 R] /DA (/Helv 0 Tf 0 g) /DR << /Font << /Helv 4 0 R >> >> "
           + (b"/SigFlags 3 " if signature else b"") + b">> >>",
        **page_objs(annots=b"/Annots [6 0 R 7 0 R 8 0 R]"),
        6: b"<< /Type /Annot /Subtype /Widget /FT /Tx /T (full_name) /Rect [72 650 300 672] /F 4 /P 3 0 R /DA (/Helv 12 Tf 0 g) >>",
        7: b"<< /Type /Annot /Subtype /Widget /FT /Btn /T (agree) /Rect [72 600 92 620] /F 4 /P 3 0 R /V /Off /AS /Off "
           b"/AP << /N << /Yes 9 0 R /Off 10 0 R >> >> >>",
        8: b"<< /Type /Annot /Subtype /Widget /FT /Sig /T (sign_here) /Rect [72 540 300 580] /F 4 /P 3 0 R" + sigv + b" >>",
        9: stream(b"0 0 20 20 re S", b"/Type /XObject /Subtype /Form /BBox [0 0 20 20]"),
        10: stream(b"", b"/Type /XObject /Subtype /Form /BBox [0 0 20 20]"),
    }
    if signature:
        objs[11] = (b"<< /Type /Sig /Filter /Adobe.PPKLite /SubFilter /adbe.pkcs7.detached /ByteRange [0 10 20 10] "
                    b"/Contents <00112233> /M (D:20200101000000Z) >>")
    return make_pdf(objs)


def encrypted_pdf():
    """A file whose trailer names an /Encrypt dictionary: enough for a reader to call it encrypted (never decrypted here)."""
    objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>", **page_objs(),
            6: b"<< /Filter /Standard /V 1 /R 2 /O <" + b"00" * 32 + b"> /U <" + b"00" * 32 + b"> /P -4 >>"}
    return make_pdf(objs, trailer=b"/Encrypt 6 0 R /ID [<00000000000000000000000000000000> <00000000000000000000000000000000>]")
