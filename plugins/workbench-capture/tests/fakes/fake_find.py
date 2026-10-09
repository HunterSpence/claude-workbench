"""A stand-in for the find CLI (interface I4): `label FILE --json` and `convert FILE [--include-labelled] --json`.
Labels are read the way the real CLI reads them (docProps/custom.xml). Every call is logged to $WB_FAKE_FIND_LOG as
`<command> <sha1 of the file>` so a test can tell which file was converted."""
import hashlib
import json
import os
import re
import sys
import zipfile


def label_of(path):
    if path.lower().endswith(".docx"):
        try:
            with zipfile.ZipFile(path) as z:
                names = {n.lower(): n for n in z.namelist()}
                if "docprops/custom.xml" in names:
                    m = re.search(r'name="MSIP_Label_[0-9a-fA-F-]+_Name"[^>]*>\s*<vt:lpwstr>([^<]*)<', z.read(names["docprops/custom.xml"]).decode("utf-8", "replace"))
                    return m.group(1) if m else None
        except (OSError, zipfile.BadZipFile):
            return None
    return None


def text_of(path):
    if path.lower().endswith(".docx"):
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        return "\n\n".join(re.sub(r"<[^>]+>", "", p) for p in re.findall(r"<w:p>.*?</w:p>", xml, re.S))
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def main(argv):
    cmd, path = argv[0], argv[1]
    log = os.environ.get("WB_FAKE_FIND_LOG")
    if log:
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"{cmd} {hashlib.sha1(open(path, 'rb').read()).hexdigest()}\n")
    label = label_of(path)
    if cmd == "label":
        print(json.dumps({"path": path, "label": label}))
    elif cmd == "convert":
        md = "" if label and "--include-labelled" not in argv else text_of(path)
        print(json.dumps({"path": path, "label": label, "markdown": md, "hidden_content": {}, "error": None}))
    else:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
