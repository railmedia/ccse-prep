# ADR 0002 — Stratified sampling, not a random 25

**Status:** accepted · 2026-11-15

## Context

The exam is 25 questions with a fixed per-task distribution (10/3/2/3/7). The
manual's bank contains 120/36/24/36/84 questions per task — exactly 12× each
quota.

## Decision

Sample per task with the exam's exact quotas. Because every pool is a multiple
of its quota, campaign mode partitions the bank into 12 disjoint exams.

## Consequences

- A mock exam has the same shape as the real one; a uniform sample would often
  over- or under-represent a task.
- Twelve non-overlapping exams double as a two-week study plan.
- Adding questions to the bank breaks the 12× property; the sampler raises
  rather than silently producing uneven exams.
