"""Portable, CPU-only adapter example. It does not submit another Comfy prompt."""
from pathlib import Path
import hashlib,json,os,sys,time

def save(path,value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2),encoding='utf-8');os.replace(temp,path)

def main(path):
    request=json.loads(Path(path).read_text(encoding='utf-8'));run=Path(request['run_dir'])
    state=dict(state='running',pid=os.getpid(),run_id=run.name,run_dir=str(run),stages=[],started=time.time())
    def report(**fields):
        state.update(fields,updated=time.time());save(run/'status.json',state);save(run.parent/'latest.json',state)
    artifact=run/'artifact.txt'
    # The second stage can also run alone: it verifies a constant artifact rather
    # than claiming an absent first-stage file was already processed.
    payload=b'Verified Pipeline CPU demonstration\n'
    try:
        for index in range(request['start'],request['end']+1):
            if (run/'cancel.request').exists():report(state='cancelled',message='Stopped at stage boundary');return
            report(current_stage=f'Stage {index}',message='Running')
            if index==1:artifact.write_bytes(payload)
            elif index==2:
                if not artifact.exists():artifact.write_bytes(payload)
                digest=hashlib.sha256(artifact.read_bytes()).hexdigest()
                assert digest==hashlib.sha256(payload).hexdigest()
                save(run/'verification.json',dict(passed=True,sha256=digest))
            state['stages'].append(dict(index=index,stage=f'Stage {index}',state='complete'))
        report(state='complete',message='CPU example completed',outputs=[str(artifact)])
    except Exception as e:report(state='failed',message=str(e));raise

if __name__=='__main__':
    if sys.argv[1]!='run':raise SystemExit('usage: runner.py run REQUEST.json')
    main(sys.argv[2])
