# ComfyUI Verified Pipeline

Generic ComfyUI nodes that turn a project's sequential processing stages into one visible workflow. Stage names, counts, execution rules and output validation come from a local adapter profile. No actor names, source videos, personal paths, credentials or model weights are built into the nodes.

## Install

```sh
cd ComfyUI/custom_nodes
git clone https://github.com/yatianxu/ComfyUI-Verified-Pipeline.git
python -m pip install -r ComfyUI-Verified-Pipeline/requirements.txt
```

Use the Python environment that runs ComfyUI. Restart the server and refresh the browser. Import an example workflow or add nodes from **Verified Pipeline**.

The standard ComfyUI V1 interface is used: `INPUT_TYPES`, `RETURN_TYPES`, `FUNCTION`, `CATEGORY`, `OUTPUT_NODE`, `NODE_CLASS_MAPPINGS`, `NODE_DISPLAY_NAME_MAPPINGS`, and `WEB_DIRECTORY`. V1 remains supported by ComfyUI. Registry metadata is provided, but GitHub publication does not mean the package has been registered on Comfy Registry.

## Nodes

| Node | Function |
|---|---|
| Verified Pipeline · Settings | Load a local JSON profile and select start/end stages, rebuild and verification options. |
| Verified Pipeline · Stage | Append one stage by index. Reuse this node for any number of stages; invalid order is rejected. |
| Verified Pipeline · Execute / Status | Start the detached adapter, inspect progress, or request a safe stop. The node panel polls actual adapter status. |

Connect Settings → Stage 1 → Stage 2 → … → Stage N → Execute. To run only a subset, keep the full chain and change the start/end indices. `run`, `status`, and `stop` are the Execute actions.

**The scheduling graph finishing means the adapter has started, not that all media has finished.** Wait for `state: complete` in the live panel. Rebuild, cache validation, cancellation boundaries and output verification are implemented by the adapter, not inferred from a green Comfy node.

## CPU demonstration

The two-stage example in `examples/demo_project` creates a text artifact and verifies its SHA-256. Set Settings `profile_path` to the absolute path of `examples/demo_project/profile.json`, and set end stage to 2. It runs without video or model dependencies. An exported example workflow is supplied.

## Adapter profile

```json
{
  "schema_version": 1,
  "project_root": "./my_project",
  "runner": "runner.py",
  "state_directory": "./runs",
  "stages": ["Prepare inputs", "Generate", "Composite", "Verify"],
  "request_options": {
    "rebuild_outputs": "rebuild_outputs",
    "full_verify": "full_verify"
  }
}
```

Paths are relative to the profile, except `runner`, which is relative to `project_root` and must stay inside it. An optional `python` field selects the adapter interpreter; otherwise the ComfyUI interpreter is used. An optional `environment` mapping adds adapter environment variables. Keep machine-specific profiles local. Blank `profile_path` can use an ignored `config.local.json` containing `{"default_profile":"/absolute/path/to/profile.json"}`.

The adapter command is an argument list, without a shell:

```text
python -u <project_root>/<runner> run <run_dir>/request.json
```

Requests contain 1-based inclusive `start`/`end`, a unique `run_dir`, `project_root`, the profile SHA and two Boolean options. `request_options` can rename those options for an existing adapter. The adapter writes `status.json` inside the run and `latest.json` in the state directory, with `state`, `pid`, `run_id`, `run_dir`, `current_stage`, `message`, and `stages`; it may include `completed_jobs`, `total_jobs` and output paths. Terminal states are `complete`, `failed`, and `cancelled`. A safe-stop request is a `cancel.request` file inside the run. The adapter must serialize competing runs and check this request at safe boundaries.

If an adapter submits native ComfyUI graphs, it must do so asynchronously from the detached process, after the scheduling graph has left the executor. Blocking an output node while waiting on another prompt in the same executor can deadlock. No shell-command node, global queue interruption or model-installation behavior is added by this package.

## Why an additional package?

Existing projects were reviewed before extracting these nodes:

- [ControlOrder-FreeMemory](https://github.com/mkim87404/ComfyUI-ControlOrder-FreeMemory) routes data between groups and manages memory within a graph.
- [Workflow Iterator](https://github.com/jason-n-tran/comfyui-workflow-iterator) creates parameter sweeps by queuing workflow variations.
- [Workflow Runner](https://github.com/hex/comfyui-workflow-runner) saves expanded API graphs and submits selected outputs.
- [Job Iterator](https://github.com/ali1234/comfyui-job-iterator) implements list/sequence iteration.

Those are useful when their scope fits. This package adds a local adapter contract for heterogeneous stages, including CPU compositing and existing verified artifacts. It does not replace native generation, segmentation or encoding nodes and does not copy the reviewed projects' implementations.

The first project adapter is a video-editing production pipeline. Its identities, masks, approved variants and compositing rules remain project-specific. Those restrictions are not requirements of these generic control nodes.

## Development

```sh
python -m unittest discover -s tests -v
```

The included example is portable; the production video adapter was tested on Windows with a local single-GPU ComfyUI instance. Package-level tests do not claim to validate every third-party adapter. Supported ComfyUI definitions: [official backend node documentation](https://docs.comfy.org/custom-nodes/backend/server_overview); packaging metadata: [official pyproject specification](https://docs.comfy.org/registry/specifications).

MIT licensed. Only source code and synthetic examples belong in this repository.
