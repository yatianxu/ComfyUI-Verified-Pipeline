"""Generic staged adapter protocol; stages and project rules come from a JSON profile."""
from pathlib import Path
import hashlib, json, os, subprocess, sys, time, uuid

_PROFILES = {}
_LAST = None


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    path = Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temp,path)


def load_profile(path):
    global _LAST
    if not path.strip():
        config = Path(__file__).with_name('config.local.json')
        path = read(config).get('default_profile','') if config.is_file() else ''
    if not path:
        raise ValueError('Set profile_path to a local pipeline profile JSON')
    profile_path = Path(path).expanduser().resolve()
    profile = read(profile_path)
    if profile.get('schema_version') != 1:
        raise ValueError('Unsupported profile schema_version')
    root = (profile_path.parent / profile['project_root']).resolve()
    runner = (root / profile['runner']).resolve()
    if not runner.is_relative_to(root) or not runner.is_file():
        raise ValueError('Runner must be an existing Python script within project_root')
    stages = profile['stages']
    if not isinstance(stages,list) or not stages or not all(isinstance(x,str) and x.strip() for x in stages):
        raise ValueError('stages must be a nonempty ordered list of labels')
    state = (profile_path.parent / profile['state_directory']).resolve()
    key = hashlib.sha256(str(profile_path).encode()).hexdigest()[:24]
    result = {**profile,'project_root':str(root),'runner':str(runner),'state_directory':str(state),
              'profile_path':str(profile_path),'profile_key':key,'profile_sha256':hashlib.sha256(profile_path.read_bytes()).hexdigest()}
    _PROFILES[key] = result; _LAST = key
    return result


def current_status(key=None):
    profile = _PROFILES.get(key or _LAST)
    if profile is None:
        return {'state':'not_started','message':'Run Settings / Execute to select a project profile'}
    path = Path(profile['state_directory'])/'latest.json'
    if not path.is_file():return {'state':'not_started','message':'Profile loaded; no run yet'}
    status = read(path)
    if status.get('state') in ['starting','running'] and not is_running(status):
        status = {**status,'state':'interrupted','message':'Controller exited; inspect controller.log before resuming'}
    return status


def is_running(status):
    import psutil
    if status.get('state') not in ['starting','running'] or not status.get('pid'):return False
    try:
        process = psutil.Process(int(status['pid']))
        # Birth time prevents a recycled PID from blocking a later run.
        born = status.get('process_created')
        return process.is_running() and (born is None or abs(process.create_time()-born)<1)
    except (psutil.NoSuchProcess,psutil.AccessDenied):return False


class VerifiedPipelineSettings:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{
            'profile_path':('STRING',{'default':'','tooltip':'Local JSON profile; blank uses config.local.json. No project data is embedded in the node.'}),
            'start_stage':('INT',{'default':1,'min':1,'max':1024}),
            'end_stage':('INT',{'default':6,'min':1,'max':1024}),
            'rebuild_outputs':('BOOLEAN',{'default':False}),
            'full_verify':('BOOLEAN',{'default':False}),
        }}
    RETURN_TYPES=('VERIFIED_PIPELINE',)
    RETURN_NAMES=('execution_plan',)
    FUNCTION='build'
    CATEGORY='Verified Pipeline'
    @classmethod
    def IS_CHANGED(cls,**kwargs):return float('nan')
    def build(self,profile_path,start_stage,end_stage,rebuild_outputs=False,full_verify=False):
        profile = load_profile(profile_path)
        if not 1<=start_stage<=end_stage<=len(profile['stages']):raise ValueError('Invalid start/end stage range')
        return ({'profile':profile,'start':start_stage,'end':end_stage,'rebuild_outputs':rebuild_outputs,
                 'full_verify':full_verify,'chain':[]},)


class VerifiedPipelineStage:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'plan':('VERIFIED_PIPELINE',),'stage_index':('INT',{'default':1,'min':1,'max':1024})}}
    RETURN_TYPES=('VERIFIED_PIPELINE',)
    RETURN_NAMES=('next_stage',)
    FUNCTION='append'
    CATEGORY='Verified Pipeline'
    def append(self,plan,stage_index):
        if stage_index>len(plan['profile']['stages']) or plan['chain']!=list(range(1,stage_index)):
            raise ValueError('Connect all stages once, in profile order: 1 -> 2 -> ... -> N')
        return ({**plan,'chain':plan['chain']+[stage_index]},)


class VerifiedPipelineExecute:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required':{'plan':('VERIFIED_PIPELINE',),'action':(['run','status','stop'],{'default':'run'})}}
    RETURN_TYPES=('STRING',)
    RETURN_NAMES=('run_status',)
    FUNCTION='execute'
    OUTPUT_NODE=True
    CATEGORY='Verified Pipeline'
    @classmethod
    def IS_CHANGED(cls,**kwargs):return float('nan')
    def execute(self,plan,action):
        profile = plan['profile']; key = profile['profile_key']
        if plan['chain']!=list(range(1,len(profile['stages'])+1)):raise ValueError('Incomplete stage chain')
        # Re-read rather than executing an edited profile under an old cached plan.
        now = load_profile(profile['profile_path'])
        if now['profile_sha256']!=profile['profile_sha256']:raise ValueError('Profile changed; run Settings again')
        state = Path(profile['state_directory']); state.mkdir(parents=True,exist_ok=True)
        status = current_status(key)
        if action=='stop' and is_running(status):
            directory = Path(status['run_dir']).resolve()
            if not directory.is_relative_to(state):raise ValueError('Invalid run directory in status')
            (directory/'cancel.request').touch()
            status={**status,'message':'Stop requested; adapter will stop at its next safe boundary'}
        elif action=='run':
            if is_running(status):raise RuntimeError('A controller is already running for this profile')
            run_id = time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]
            directory=state/run_id;directory.mkdir()
            request={'start':plan['start'],'end':plan['end'],'run_dir':str(directory),
                     'project_root':profile['project_root'],'profile_sha256':profile['profile_sha256']}
            for option in ['rebuild_outputs','full_verify']:
                request[profile.get('request_options',{}).get(option,option)]=plan[option]
            path=directory/'request.json';save(path,request)
            starting=dict(state='starting',run_id=run_id,run_dir=str(directory),stages=[],
                          message='Controller starting; completion is reported by the live status panel')
            save(state/'latest.json',starting)
            env=os.environ.copy();env.update(profile.get('environment',{}))
            env['VERIFIED_PIPELINE_PROJECT']=profile['project_root']
            try:
                with (directory/'controller.log').open('w',encoding='utf-8') as stream:
                    proc=subprocess.Popen([profile.get('python',sys.executable),'-u',profile['runner'],'run',str(path)],
                        cwd=profile['project_root'],stdout=stream,stderr=subprocess.STDOUT,env=env,
                        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                import psutil
                starting['pid']=proc.pid
                try:starting['process_created']=psutil.Process(proc.pid).create_time()
                except psutil.NoSuchProcess:pass  # A very small adapter may already be complete.
                latest=read(state/'latest.json')
                if latest.get('run_id')==run_id and latest.get('state')=='starting':
                    if proc.poll() is not None:
                        starting.update(state='failed',message='Adapter exited without writing terminal status')
                    save(state/'latest.json',starting)
            except Exception:
                save(state/'latest.json',{**starting,'state':'failed','message':'Controller could not be started'})
                raise
            status=current_status(key)
        message=json.dumps(status,ensure_ascii=False,indent=2)
        return {'ui':{'text':[message],'profile_key':[key]},'result':(message,)}


def register_routes():
    # Can be imported and unit-tested without ComfyUI installed.
    try:
        from aiohttp import web
        from server import PromptServer
    except ImportError:return
    @PromptServer.instance.routes.get('/verified-pipeline/status')
    async def status_route(request):
        return web.json_response(current_status(request.query.get('profile_key')))
