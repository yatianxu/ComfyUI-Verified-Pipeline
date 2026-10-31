import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

app.registerExtension({
    name: "VerifiedPipeline.Progress",
    nodeCreated(node) {
        if (node.comfyClass !== "VerifiedPipelineExecute") return;
        const panel = document.createElement("div");
        Object.assign(panel.style, { padding:"10px", whiteSpace:"pre-wrap", overflow:"auto",
            color:"#ddd", background:"#171d27", font:"12px/1.6 monospace", height:"100%" });
        panel.textContent = "Run the pipeline or select status to load the project profile.\nThe scheduling node returning does not mean the adapter has finished.";
        node.addDOMWidget("verified_pipeline_progress", "VERIFIED_PIPELINE_PROGRESS", panel, {serialize:false});
        let removed = false;
        const onRemoved = node.onRemoved;
        node.onRemoved = function () { removed=true; onRemoved?.apply(this,arguments); };
        const onExecuted = node.onExecuted;
        node.onExecuted = function (message) {
            const key=message?.profile_key?.[0];
            if (key) { this.properties ??= {}; this.properties.verified_profile_key=key; }
            onExecuted?.apply(this,arguments);
        };
        async function refresh() {
            if (removed) return;
            try {
                const key=node.properties?.verified_profile_key;
                const response=await api.fetchApi("/verified-pipeline/status"+(key?"?profile_key="+encodeURIComponent(key):""));
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const s=await response.json();
                panel.textContent=`${s.state??"unknown"} · ${s.current_stage??""}\n${s.message??""}\n`
                    +(s.completed_jobs?`${s.completed_jobs}/${s.total_jobs??"?"}\n`:"")
                    +(s.stages??[]).map(x=>`✓ ${x.stage??x.label??x.index}`).join("\n")
                    +`\n${s.run_dir??""}\n`+(s.outputs??[]).join("\n");
            } catch(error) { panel.textContent=`Status connection: ${error.message}; retrying`; }
            if (!removed) setTimeout(refresh,2000);
        }
        refresh();
    }
});
