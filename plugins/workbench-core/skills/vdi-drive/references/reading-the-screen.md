# Reading the screen back

Typing into the remote canvas is the easier half. Reading it back is the weak half: there is no DOM,
so verification means looking at pixels.

## Cheapest first
1. A sink outside the picture: a file on the remote machine, an API response, an audit log row.
2. A cropped screenshot and a careful look.
3. OCR, only when a step must be verified unattended or repeatedly.

## If OCR is needed: RapidOCR
```bash
python -m pip install --user rapidocr onnxruntime
```
It runs PaddleOCR's PP-OCR model weights on ONNX Runtime: sub-second on CPU, no GPU, and none of
PaddlePaddle's Windows install trouble. Check that installing it, and the model weights it
bundles, is allowed on your machine (licence: Apache-2.0; re-check the version you install). For
crisp rendered UI text at full resolution, classic OCR is usually accurate and much faster than a
local vision model. Do not choose an engine from photo or scene-text benchmarks; screen text is a
different regime.

## Do not reach for a vision-language model by default
Open GUI-grounding models score well on easy screen benchmarks but drop sharply on dense
professional software, which is what a line-of-business app in a remote desktop looks like. Use a
vision model only to disambiguate icon-only controls that carry no text.

## Icon-only controls
Detector models that return bounding boxes for icons exist; check the licence of the specific
weight file before using one (some popular detector weights are AGPL-3.0).

## Privacy
OCR output and screenshots are copies of what is on the remote desktop. Keep them only as long as
the task needs them, inside the environment the authorisation covers, and delete them afterwards.
