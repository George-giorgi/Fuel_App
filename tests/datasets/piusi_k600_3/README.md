# PIUSI K600/3 OCR dataset

Add a meter photograph or an LCD-only crop to this directory and add one
corresponding JSON entry to `labels.json`. Prefer LCD-only crops when the full
photo contains unrelated equipment or identifying details. Do not include real
fuel transactions, employee details, or credentials.

Each label records only the bottom TOTAL row's raw digits and value. The PIUSI
K600/3 shows exactly six TOTAL digits, with three decimal places implied:
`261563` is `261.563 L`, `261798` is `261.798 L`, and `267981` is `267.981 L`.
Never reorder digits to match another reading. Keep challenging captures (blur,
glare, angle, dim light, or occlusion) and annotate them with
`expected_ocr_status: "uncertain"` when OCR methods disagree or a human must
confirm the digits. These examples are regression checks, not evidence of
general accuracy.

These examples are regression checks, not evidence of general accuracy.
