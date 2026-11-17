# PIUSI K600/3 OCR dataset

Add original, unmodified meter photographs to this directory and add one
corresponding JSON entry to `labels.json`. Do not include real fuel transactions,
employee details, or credentials.

Each label records the two known readings, expected raw digits, and decimal
point positions counted from the left side of each row. Both rows use three
fractional digits: `22032` is `22.032 L` and `261563` is `261.563 L`. Keep
challenging captures (blur, glare, angle, dim light, or occlusion) and annotate
them with `expected_status: "uncertain"` when a human cannot read both rows
reliably.

The reference photo is one positive example, not evidence of general accuracy.
