# PIUSI K600/3 OCR dataset

Add a meter photograph or an LCD-only crop to this directory and add one
corresponding JSON entry to `labels.json`. Prefer LCD-only crops when the full
photo contains unrelated equipment or identifying details. Do not include real
fuel transactions, employee details, or credentials.

Each label records the two known readings, expected raw digits, and decimal
point positions counted from the left side of each row. Both rows use three
fractional digits: `22032` is `22.032 L` and `261563` is `261.563 L`. Keep
challenging captures (blur, glare, angle, dim light, or occlusion) and annotate
them with `expected_ocr_status: "uncertain"` when a human cannot read both rows
reliably or the recognizer requires manual review. The added 60313/261798 sample
is a dim-light crop and remains manual-review-only; the close-up sample is read
without a warning.

These examples are regression checks, not evidence of general accuracy.
