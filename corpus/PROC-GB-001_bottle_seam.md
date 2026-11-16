---
source_id: PROC-GB-001
title: Glass bottle body - mold seam identification
category: glass_bottle
doc_type: procedure
version: 3.0
synthetic: true
---
# Glass bottle body: mold seam identification

Synthetic procedure for InspectBot experiments. It is not an industry standard.

## Expected feature: mold seam
Two-part molds leave a vertical mold seam on the bottle body. In this cell the seam is on the centre line of the face: normalized x between 0.48 and 0.52, running the full height. The seam is straight, of even width, and present on the approved reference image.

## Criterion GB-1: seam
A vertical line that meets all of these is the expected mold seam:
- it is straight, even in width, and full height
- it lies within the centre-line band
- it also appears on the reference image at the same place

Record no defect for that line. Recommended check: get_reference for glass_bottle and compare.

## Criterion GB-2: check (crack)
A line off the centre line, irregular, or absent from the reference must be treated under PROC-GB-002.
