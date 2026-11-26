# ADR 0001 — Questions are structured data, not retrieval

**Status:** accepted · 2026-11-15

## Context

The app needs to present exam questions and score them. A retrieval pipeline
over the manual is being built anyway for explanations, so retrieving questions
too would be "consistent".

## Decision

Questions are parsed once into a relational table with the official key. The
exam engine reads them with plain SQL. Only explanations use retrieval.

## Consequences

- Question text and answers are exact, versioned and testable.
- Scoring is deterministic and happens server-side.
- The answer key can be compared against the manuscript during ingestion.
- Two data planes to maintain, which is the cost we accept.
