"""Test helpers: a throwaway workbench, generated transcripts (a fictional, neutral domain), the fake find CLI and the
fake `claude` on PATH. Nothing here names a real person, tenant or meeting."""
import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parents[1] / "skills" / "ingest" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import common  # noqa: E402
import ingest  # noqa: E402

MEETING = "Quarterly Planning Sync"
CUES = [("00:00:05", "Alice Example", "Welcome everyone, let us start with the roadmap."),
        ("00:00:12", "Bob Sample", "The launch checklist is ready for review."),
        ("00:00:20", "Alice Example", "Decision: we ship the draft on Friday.")]


class Env:
    """A throwaway workbench home and data folder; `run()` calls ingest.main in-process and returns (exit code, stdout)."""

    def __init__(self, extra_env=None):
        self.tmp = tempfile.TemporaryDirectory(prefix="wb-ingest-test-")
        t = Path(self.tmp.name)
        self.wb, self.data, self.bin = t / "wb", t / "data", t / "bin"
        self.wb.mkdir()
        self.bin.mkdir()
        (self.wb / "config.json").write_text(json.dumps({"data_root": str(self.data).replace("\\", "/"), "kb_root": str(self.data / "kb").replace("\\", "/")}), "utf-8")
        self.find_log, self.claude_log = t / "find.log", t / "claude.log"
        self.env = {**os.environ, "WORKBENCH_HOME": str(self.wb), "WORKBENCH_FIND_CLI": str(HERE / "fake_find.py"),
                    "WB_FAKE_FIND_LOG": str(self.find_log), "WB_FAKE_CLAUDE_LOG": str(self.claude_log), "PYTHONUTF8": "1",
                    "PATH": str(self.bin) + os.pathsep + os.environ.get("PATH", ""), **(extra_env or {})}
        self.P = common.Paths(self.env)
        self.install_fake_claude()

    def close(self):
        self.tmp.cleanup()

    def settings(self, **kw):
        s = common.load_settings(self.P)
        s.update(kw)
        common.save_settings(self.P, s)

    def install_fake_claude(self):
        py, fake = sys.executable, HERE / "fake_claude.py"
        if os.name == "nt":
            (self.bin / "claude.cmd").write_text(f'@echo off\r\n"{py}" "{fake}" %*\r\n', "utf-8")
        else:
            f = self.bin / "claude"
            f.write_text(f'#!/bin/sh\nexec "{py}" "{fake}" "$@"\n', "utf-8")
            f.chmod(f.stat().st_mode | stat.S_IEXEC)

    def run(self, *argv, hooks=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ingest.main(list(argv), env=self.env, hooks={"pacer": common.Pacer(sleep=lambda s: None), **(hooks or {})})
        return code, out.getvalue() + err.getvalue()

    def reports(self):
        return [json.loads(f.read_text("utf-8")) for f in sorted(self.P.runs.glob("*-ingest.json"))] if self.P.runs.is_dir() else []

    def claude_calls(self):
        return [json.loads(x) for x in self.claude_log.read_text("utf-8").splitlines()] if self.claude_log.exists() else []

    def find_calls(self):
        return self.find_log.read_text("utf-8").splitlines() if self.find_log.exists() else []


def vtt(cues=CUES, extra=""):
    body = "".join(f"{i}\n00:00:{c[0][-2:]}.000 --> 00:00:{int(c[0][-2:]) + 3:02d}.000\n<v {c[1]}>{c[2]}</v>\n\n" for i, c in enumerate(cues, 1))
    return f"WEBVTT\n\nNOTE generated for tests\n\n{body}{extra}"


def docx(path, title=MEETING, cues=CUES, label=None):
    """A transcript .docx in the layout parse_docx expects: a title paragraph, then a speaker line (name, tab, offset) and the
    spoken text in the next paragraph. `label` adds a sensitivity label the way Office stores it."""
    W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    paras = [f"<w:p><w:r><w:t>{title}</w:t></w:r></w:p>"]
    for ts, who, text in cues:
        h, m, s = (int(x) for x in ts.split(":"))
        paras.append(f'<w:p><w:r><w:t>{who}</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t>{h}:{m:02d}:{s:02d}</w:t></w:r></w:p>')
        paras.append(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document {W}><w:body>{"".join(paras)}</w:body></w:document>')
        if label:
            z.writestr("docProps/custom.xml", '<?xml version="1.0"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/custom-properties" '
                       'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><property fmtid="{D5CDD505-2E9C-101B-9397-08002B2CF9AE}" pid="2" '
                       f'name="MSIP_Label_00000000-0000-4000-8000-000000000001_Name"><vt:lpwstr>{label}</vt:lpwstr></property></Properties>')
