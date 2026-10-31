# Existing open-source options reviewed

Reviewed on 2026-10-31. These are alternatives and references, not dependencies or bundled source.

| Project | Source examined | Fit and remaining gap |
|---|---|---|
| [ControlOrder-FreeMemory](https://github.com/mkim87404/ComfyUI-ControlOrder-FreeMemory) | README and Python registration | Good for ordering connected native groups and model memory management. Does not itself define a heterogeneous disk-backed project adapter and verified artifact recovery. |
| [Workflow Iterator](https://github.com/jason-n-tran/comfyui-workflow-iterator) | README and `nodes/workflow_iterator.py`, blob `694debf048ccaac574d8173f7354eb77c3087bd3` | Parameter matrix/linear sweeps and iteration metadata, rather than ordered stages with different generation, tracking, CPU compositing and verification behavior. |
| [Workflow Runner](https://github.com/hex/comfyui-workflow-runner) | README and `__init__.py` | Exports expanded API graphs, injects inputs, prunes outputs and queues a prompt. Useful API transport; not an adapter lifecycle with stage boundaries, artifact validation and recovery. |
| [Job Iterator](https://github.com/ali1234/comfyui-job-iterator) | README and registration module | Useful sequence/list iteration inside a native workflow. Does not implement this project adapter contract. |

The comparison does not claim that no similar package exists anywhere. It records why these examined implementations did not directly replace the required adapter bridge. Existing H3, SAM and ComfyUI API mechanisms continue to do the actual native work; only the bridge is new.

Official interfaces checked: [V1 node properties, still supported](https://docs.comfy.org/custom-nodes/backend/server_overview), [node expansion](https://docs.comfy.org/custom-nodes/backend/expansion), and [packaging metadata](https://docs.comfy.org/registry/specifications). The package does not change ComfyUI's execution engine.
