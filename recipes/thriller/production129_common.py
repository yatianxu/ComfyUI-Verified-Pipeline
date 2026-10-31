"""Shared disk/API utilities for the cut-aware, resumable 129-second render."""
from pathlib import Path
import json,time,subprocess,math
import requests,av,cv2,numpy as np,imageio_ffmpeg
R=Path(__file__).resolve().parent
if not (R/'production/runtime').exists():
    R=next((p/'素材/thriller' for p in R.parents if (p/'素材/thriller/production/runtime').exists()),R)
D=R/'film/span_506_635/v3_production'
P=R/'production/runtime'; INP=P/'input'; OUT=P/'output'
URL='http://127.0.0.1:8188'; FF=imageio_ffmpeg.get_ffmpeg_exe()

def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))

def approved_variant(chunk,role,default,variants):
    matches=[v['candidate'] for key,v in variants.items() if v.get('approved') and v.get('chunk',key)==chunk and v['role']==role]
    if len(matches)>1:raise ValueError('Conflicting approved variants for '+chunk+'_'+role)
    return matches[0] if matches else default
def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)
def frames(path):
    with av.open(str(path)) as c:
        for f in c.decode(video=0):yield f.to_ndarray(format='rgb24')
def write_video(path,seq,crf=0):
    it=iter(seq);first=next(it);h,w=first.shape[:2];path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    p=subprocess.Popen([FF,'-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s',f'{w}x{h}','-r','24','-i','pipe:0','-an','-c:v','libx264','-preset','fast','-crf',str(crf),'-pix_fmt','yuv420p',str(path)],stdin=subprocess.PIPE)
    try:
        p.stdin.write(first.tobytes())
        for f in it:p.stdin.write(f.tobytes())
    finally:p.stdin.close();p.wait()
    if p.returncode:raise RuntimeError('Video encoding failed '+str(path))
def submit(g,key,timeout=3600):
    hp=D/(key+'.history.json');ap=D/(key+'.api.json');jp=D/(key+'.job.json')
    if hp.exists() and read(hp)['status']['status_str']=='success':return read(hp)
    if jp.exists():
        jid=read(jp)['prompt_id'];h=requests.get(URL+'/history/'+jid,timeout=30).json().get(jid)
        if h and h['status']['status_str']=='success':save(hp,h);return h
        queue=requests.get(URL+'/queue',timeout=30).json();pending={x[1] for q in ['queue_running','queue_pending'] for x in queue[q]}
        if jid not in pending:jid=None
    else:jid=None
    if jid is None:
        save(ap,g);z=requests.post(URL+'/prompt',json={'prompt':g,'client_id':'thriller-final129'},timeout=60)
        if not z.ok:raise RuntimeError(z.text)
        save(jp,z.json());jid=z.json()['prompt_id'];print('submitted',key,jid,flush=True)
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        h=requests.get(URL+'/history/'+jid,timeout=30).json().get(jid)
        if h:
            save(hp,h)
            if h['status']['status_str']!='success':raise RuntimeError(str(h['status']))
            print('completed',key,flush=True);return h
        time.sleep(3)
    raise TimeoutError(key)
def packed_masks(path,index=0):
    with np.load(path,allow_pickle=False) as z:
        meta=json.loads(str(z['metadata']));packed=z['packed_masks']
        if packed.shape[1]<=index:return np.zeros((meta['n_frames'],*meta['orig_size']),np.uint8)
        a=packed[:,index]
    # SAM3 stores a square bit grid; discard padding bits before resizing.
    a=np.unpackbits(a,axis=-1,bitorder='little')[:,:,:a.shape[1]]
    h,w=meta['orig_size']
    return np.stack([cv2.resize(m,(w,h),interpolation=cv2.INTER_NEAREST) for m in a]).astype(np.uint8)
def support(masks,grow=8):
    n,h,w=masks.shape;k=np.ones((2*grow+1,2*grow+1),np.uint8)
    cells=np.stack([cv2.dilate(m.astype(np.uint8),k).reshape(h//16,16,w//16,16).max((1,3)) for m in masks])
    at=token=0
    while at<n:
        end=min(n,at+(1,4,4,4,4)[token%5]);cells[at:end]=cells[at:end].max(0);at=end;token+=1
    return cells.repeat(16,1).repeat(16,2)
def native_track(video,mask,prefix):
    return {'1':{'class_type':'CheckpointLoaderSimple','inputs':{'ckpt_name':'sam3.1_multiplex_fp16.safetensors'}},'2':{'class_type':'LoadVideo','inputs':{'file':video}},'3':{'class_type':'GetVideoComponents','inputs':{'video':['2',0]}},'4':{'class_type':'LoadImage','inputs':{'image':mask}},'5':{'class_type':'ImageToMask','inputs':{'image':['4',0],'channel':'red'}},'6':{'class_type':'SAM3_VideoTrack','inputs':{'images':['3',0],'model':['1',0],'initial_mask':['5',0],'detection_threshold':.5,'max_objects':1,'detect_interval':999}},'7':{'class_type':'ThrillerSaveTrackCache','inputs':{'track_data':['6',0],'filename_prefix':prefix}}}
