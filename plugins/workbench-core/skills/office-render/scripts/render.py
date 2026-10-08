#!/usr/bin/env python3
"""render.py: render .pptx / .docx / .xlsx / .pdf to one PNG per slide or page, for visual QA.

  python render.py <file> --out <dir> [--engine auto|office|libreoffice] [--dpi 110] [--first N]

Step 1, document -> PDF:
  office       Windows only: PowerPoint / Word / Excel through COM (PowerShell), read-only, no window.
               The most faithful render, because it is the app your readers use.
  libreoffice  soffice --headless --convert-to pdf, with a throwaway profile. Fonts may differ.
  auto         office on Windows if it works, else libreoffice.
Step 2, PDF -> PNG: pypdfium2 (Apache-2.0 / BSD-3-Clause). Prints the PNG paths, one per line.
"""
import argparse, os, pathlib, shutil, subprocess, sys, tempfile

APP = {".pptx": "powerpoint", ".docx": "word", ".xlsx": "excel"}
# Macro-enabled and legacy binary formats are refused outright: they can carry code, and the legacy
# formats are where most Office parser exploits live. Convert a trusted copy to the x-format first.
REFUSED = {".xlsm", ".xltm", ".docm", ".dotm", ".pptm", ".potm", ".doc", ".xls", ".ppt", ".rtf"}
# COM: paths travel in environment variables, never inside the script text. Macros are force-disabled
# (AutomationSecurity = 3, msoAutomationSecurityForceDisable) BEFORE anything opens, and files open
# read-only. If the user already has the app open, COM attaches to THEIR instance: we restore its
# AutomationSecurity, touch only our own document, and never hide or quit the app.
_COM = ("$a = New-Object -ComObject {prog}; $own = $a.{coll}.Count -eq 0; $prev = $a.AutomationSecurity; "
        "$a.AutomationSecurity = 3; {hide}try {{ {body} }} "
        "finally {{ $a.AutomationSecurity = $prev; if ($own) {{ $a.Quit() }}; "
        "[void][Runtime.InteropServices.Marshal]::ReleaseComObject($a) }}")
PS = {
    "powerpoint": _COM.format(prog="PowerPoint.Application", coll="Presentations", hide="",
                              body="$d = $a.Presentations.Open($env:RENDER_IN, -1, 0, 0); $d.SaveAs($env:RENDER_PDF, 32); $d.Close()"),
    "word": _COM.format(prog="Word.Application", coll="Documents", hide="if ($own) { $a.Visible = $false; $a.DisplayAlerts = 0 }; ",
                        body="$d = $a.Documents.Open($env:RENDER_IN, $false, $true, $false); "
                             "$d.ExportAsFixedFormat($env:RENDER_PDF, 17); $d.Close(0)"),
    "excel": _COM.format(prog="Excel.Application", coll="Workbooks", hide="if ($own) { $a.Visible = $false; $a.DisplayAlerts = $false }; ",
                         body="$d = $a.Workbooks.Open($env:RENDER_IN, 0, $true); $d.ExportAsFixedFormat(0, $env:RENDER_PDF); $d.Close($false)"),
}


def refuse_risky(path):
    ext = pathlib.Path(path).suffix.lower()
    if ext in REFUSED:
        raise ValueError(f"refusing {ext}: macro-enabled or legacy Office format. Open a trusted copy in Office, "
                         f"save it as .pptx/.docx/.xlsx (macros are dropped), and render that.")


def via_office(src, pdf, timeout=240):
    app = APP.get(pathlib.Path(src).suffix.lower())
    if os.name != "nt" or not app:
        raise RuntimeError("Office COM needs Windows and a pptx/docx/xlsx file")
    env = dict(os.environ, RENDER_IN=os.path.abspath(src), RENDER_PDF=os.path.abspath(pdf))
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS[app]], env=env,
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0 or not os.path.exists(pdf):
        raise RuntimeError(f"{app} COM export failed: {(r.stderr or r.stdout).strip()[:300]}")


def find_soffice():
    for name in ("soffice", "libreoffice"):
        if shutil.which(name):
            return shutil.which(name)
    for p in (r"C:\Program Files\LibreOffice\program\soffice.exe", "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if os.path.exists(p):
            return p
    return None


def via_libreoffice(src, pdf, timeout=240):
    exe = find_soffice()
    if not exe:
        raise RuntimeError("LibreOffice (soffice) not found")
    with tempfile.TemporaryDirectory() as profile, tempfile.TemporaryDirectory() as outdir:
        r = subprocess.run([exe, "-env:UserInstallation=" + pathlib.Path(profile).as_uri(), "--headless",
                            "--convert-to", "pdf", "--outdir", outdir, os.path.abspath(src)],
                           capture_output=True, text=True, timeout=timeout)
        made = os.path.join(outdir, pathlib.Path(src).stem + ".pdf")
        if not os.path.exists(made):
            raise RuntimeError(f"LibreOffice conversion failed: {(r.stderr or r.stdout).strip()[:300]}")
        shutil.move(made, pdf)


def to_pdf(src, pdf, engine="auto"):
    if engine == "office":
        return via_office(src, pdf), "office"
    if engine == "libreoffice":
        return via_libreoffice(src, pdf), "libreoffice"
    errors = []
    for name, fn in (("office", via_office), ("libreoffice", via_libreoffice)):
        try:
            fn(src, pdf)
            return None, name
        except Exception as e:
            errors.append(f"{name}: {e}")
    raise RuntimeError("no renderer worked:\n  " + "\n  ".join(errors))


def pdf_to_png(pdf, out_dir, stem, dpi=110, first=None):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(pdf)
    try:
        n = len(doc) if not first else min(first, len(doc))
        width = max(2, len(str(n)))
        paths = []
        for i in range(n):
            page = doc[i]
            path = os.path.join(out_dir, f"{stem}-{i + 1:0{width}d}.png")
            page.render(scale=dpi / 72).to_pil().save(path)
            page.close()
            paths.append(path)
        return paths
    finally:
        doc.close()


def render(src, out_dir, engine="auto", dpi=110, first=None):
    refuse_risky(src)
    os.makedirs(out_dir, exist_ok=True)
    stem = pathlib.Path(src).stem
    for old in pathlib.Path(out_dir).glob(f"{stem}-*.png"):   # stale renders mislead the next review
        old.unlink()
    if pathlib.Path(src).suffix.lower() == ".pdf":
        return pdf_to_png(src, out_dir, stem, dpi, first), "pdf"
    pdf = os.path.join(out_dir, stem + ".pdf")
    _, used = to_pdf(src, pdf, engine)
    return pdf_to_png(pdf, out_dir, stem, dpi, first), used


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--out", required=True)
    ap.add_argument("--engine", choices=("auto", "office", "libreoffice"), default="auto")
    ap.add_argument("--dpi", type=int, default=110)
    ap.add_argument("--first", type=int, help="only the first N pages")
    a = ap.parse_args(argv)
    try:
        paths, used = render(a.file, a.out, a.engine, a.dpi, a.first)
    except Exception as e:
        print(f"RENDER FAILED: {e}", file=sys.stderr)
        return 1
    print(f"# {len(paths)} page(s) rendered via {used}; look at every one")
    print("\n".join(paths))
    return 0


if __name__ == "__main__":
    sys.exit(main())
