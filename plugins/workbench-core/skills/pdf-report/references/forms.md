# Filling a PDF form

## Two kinds of form
- **Fillable (AcroForm):** the file has named fields. `pdf_tools.py fields <form.pdf>` lists each one with its type (text, checkbox, radio,
  choice, signature), its current value and, for a checkbox or radio button, its on-state.
- **Flat:** the boxes are only drawing. There are no fields, so `fill` stops with a message. Nothing here fills a flat form by coordinates.
  Offer the user the options: type into it in Edge or a PDF reader, or, when the source document is theirs, rebuild it as HTML
  (guide 57) with real input lines.

## Steps for a fillable form
1. `fields form.pdf` and read the names exactly (they are case-sensitive).
2. `fill form.pdf --out filled.pdf --set full_name="Pat Example" --set agree=yes [--values more.json] [--png <folder>]`
   - Text fields take the text. A checkbox takes `yes`/`no` (or its on-state, such as `/Yes`). A name that does not exist stops the run and
     lists the real names.
   - The values go into a **copy**. The input is never edited and `--out` must be another file.
   - `NeedAppearances` is set, so a reader redraws the fields. `--png` renders the copy with form support switched on
     (office-render's `render.py` draws no form fields, so use this for the picture).
3. Read every PNG. Look for text that does not fit its box, a box left empty, a checkbox in the wrong state and a long value that runs off.
4. Hand the copy to the user. They check it, then sign.

## Rails (not options)
- **Encrypted file:** refused. Ask the owner for an unprotected copy. The tool never guesses a password and never asks for one.
- **Signed file:** refused by every command that writes. Any change breaks a digital signature, so work on an unsigned copy.
- **Signature fields** are never filled, and no signature image is ever drawn, stamped or pasted. The person who signs does it themselves.
- **Legal, financial, tax and government forms:** fill the copy, show it, stop. Do not sign, submit or send it. Answers that
  are statements about the user's facts come from the user, not from a guess.
- A form with embedded scripts or attachments is listed by `info` and `scrub`; they are never run and never silently removed.

## Common failures
- The value shows in some readers and not in others: the form has no appearance for that field. Open the copy in Edge and print it to PDF
  to flatten what the reader shows, then check the result.
- A choice field refuses a value: use one of the `options` that `fields` prints.
- A radio group: set the group name to the on-state of the button that should be chosen.
