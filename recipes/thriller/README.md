# Project-specific video adapter source

These Python files are the first production adapter for the generic control nodes. They are **not** the node package's default behavior and do not contain production inputs, masks, celebrity images, native API records, source MV footage or model weights.

The adapter expects an already prepared project tree: `production/runtime`, approved native API templates and inputs, a cut-aware base timeline and selected insert configurations. Copy the recipe scripts into that project root. The existing prepared project can run `python integrated_pipeline.py build` to freeze its inputs and selected outputs, then use a generic profile with:

```json
{
  "schema_version": 1,
  "project_root": "/absolute/path/to/prepared/project",
  "runner": "integrated_pipeline.py",
  "state_directory": "/absolute/path/to/production/run-records",
  "stages": ["Check inputs", "Native H3", "Native SAM masks", "Base composite", "Final composite", "Verify"],
  "request_options": {"rebuild_outputs": "reencode", "full_verify": "full_decode"}
}
```

The `state_directory` must match the adapter's production directory. The published source retains that project's timeline and six-stage recipe so that its behavior is reviewable. It is not an automatic setup wizard for arbitrary videos. Its source tracking, role assignment, chosen visual corrections and SHA-bound review decisions require project preparation.

This adapter uses a Windows file lock, project-specific 129-second base / 132.208333-second final timelines, native H3/SAM APIs and existing 4K composition helpers. It additionally requires the prepared H3/SAM node environment plus numpy, av, opencv-python, imageio-ffmpeg, requests, Pillow and scipy. No upstream custom-node implementation is bundled here.

The generic Settings / Stage / Execute nodes and CPU example are independent of these video-specific assumptions. Fresh outputs that differ from approved raw or mask SHA values stop for review; an old visual approval is never automatically applied to changed generation results.
