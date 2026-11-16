---
source_id: PROC-GEN-002
title: Escalation and human-review policy
category: general
doc_type: guideline
version: 1.0
synthetic: true
---
# Escalation and human-review policy

Synthetic policy for InspectBot experiments.

## When to stop and ask a human
Pause the inspection and return Insufficient evidence with a request for human review when any of these holds:
- the object identity or category is uncertain
- no procedure applies, or the applicable procedures conflict
- observations contradict each other and the contradiction affects the outcome
- a required check cannot be completed
- tool failures repeat
- the evidence-gathering budget is exhausted
- the request falls outside the approved scope

## What the escalation must contain
- the observations collected, with identifiers
- the procedures consulted, with versions
- the failed actions and their errors
- the single unresolved question the reviewer should answer

## Reviewer options
A reviewer may clarify the task, supply approved guidance, authorize one more bounded inspection, or close the case. Every override is recorded.
