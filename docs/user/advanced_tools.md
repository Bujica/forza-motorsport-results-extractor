# Advanced Tools

Advanced tools are available in the GUI under `Diagnostics`.

Related tests: GUI static contracts, DB Doctor tests, and GUI read/database-state tests.

## Current surface

Diagnostics keeps product-adjacent diagnostics and maintenance surfaces only:

```text
GUI
  -> Diagnostics
       -> Overview
       -> Image Debug
       -> DB Doctor
       -> Logs
```

Former lab and bench surfaces are removed from the public GUI/CLI surface
as part of the 2026-06 clean-break removal. They are not preserved under
`tools/dev_lab`.

## Overview

Use `Overview` to inspect runtime health, model/backend status, configured paths,
and database readiness before running screenshots.

## Image Debug

Use `Image Debug` to inspect screenshot metadata, extraction results, attempts,
model response evidence, parsed data, laps, review cases, artifacts, runtime
snapshots, and timeline evidence for a selected image or result. This
image-centric surface is the supported diagnostics path for model-output review.

## DB Doctor

Use `DB Doctor` for read-only relational checks before reruns, releases, or
maintenance changes.

## Logs

Use `Logs` for application logs, error logs, and runtime event traces.

## Generated artifacts

Generated artifacts are handled through explicit product actions such as PDF/CSV
exports and DB Doctor integrity checks. There is no standalone cleanup command
or hidden raw-response artifact directory in the product surface.
