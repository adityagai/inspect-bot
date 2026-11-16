---
source_id: PUB-001
title: MVTec Anomaly Detection dataset - overview (paraphrased summary)
category: general
doc_type: reference
version: 2019
synthetic: false
url: https://www.mvtec.com/company/research/datasets/mvtec-ad
---
# MVTec AD dataset: overview (paraphrased summary)

This is a summary in our own words of the public MVTec AD dataset description (Bergmann et al., CVPR 2019).

## Contents
MVTec AD is a public benchmark for unsupervised industrial anomaly detection. It covers texture categories (such as carpet, leather, tile and wood) and object categories (such as bottle, metal nut, screw and transistor). Training sets contain only defect-free images. Test sets mix defect-free images with many defect types, such as cracks, scratches, contamination and misplaced parts, with pixel-level ground-truth masks.

## Relevance to InspectBot
MVTec images are single static views. They have no extra viewpoints or lighting changes, so they suit static analysis and abstention experiments but not active evidence gathering. Evaluation images and their labels must never be added to the reference collection.
