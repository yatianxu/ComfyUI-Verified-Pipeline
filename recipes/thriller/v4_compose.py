"""Patch reviewed inserts into V3 master, extend original 4K plate to the house cut."""
from production129_common import *
from generate_production129 import inverse
from PIL import Image,ImageDraw
import hashlib,itertools,ctypes
N=D.parent/'v4_closeups'
DEST=R.parents[1]/'最终交付/Thriller_万圣节名人群舞成片/鬼屋前截止_特写增强版'
BASE=R.parents[1]/'最终交付/Thriller_万圣节名人群舞成片/129秒完整版/Thriller_万圣节名人群舞_129秒_4K.mp4'
FILMS=['Thriller_万圣节名人群舞_132.21秒_4K.mp4','Thriller_万圣节名人群舞_132.21秒_1080p.mp4']
ORDER=['Musk','FeiFei','Jensen','Altman','Satya','Hinton','Mark']

def stream_plate():
    original=next(R.glob('*4K*.mp4'))
    for path,extra,count,vf in [(BASE,[],3096,'crop=2880:2160:480:0'),(original,['-ss','630'],77,'crop=2880:2160:480:0,fps=24,trim=start_frame=120:end_frame=197,setpts=PTS-STARTPTS')]:
        p=subprocess.Popen([FF,'-hide_banner','-loglevel','error','-threads','2',*extra,'-i',str(path),'-an','-vf',vf,'-fps_mode','passthrough','-frames:v',str(count),'-pix_fmt','rgb24','-f','rawvideo','pipe:1'],stdout=subprocess.PIPE)
        try:
            for _ in range(count):
                a=p.stdout.read(2880*2160*3)
                if len(a)!=2880*2160*3:raise RuntimeError('Incomplete baseplate decode')
                yield np.frombuffer(a,np.uint8).reshape(2160,2880,3)
        finally:p.stdout.close();p.wait()
        if p.returncode:raise RuntimeError('Baseplate decoder failed')

def load_job(key,cfg,matte):
    assert hashlib.file_digest(Path(cfg['raw']).open('rb'),'sha256').hexdigest()==matte['raw_sha256']
    raw=frames(cfg['raw'])
    for _ in range(cfg['keep_from']):next(raw)
    data={'cfg':cfg,'raw':raw,'source':np.load(cfg['source_masks'])['masks'],'original':np.load(cfg['crop_masks'])['masks'],'new':np.load(matte['mask'])['masks']}
    data['support']=support(data['original'],8)
    if cfg.get('background_plate'):
        data['background']=np.array(Image.open(cfg['background_plate']).convert('RGB').resize((2880,2160),Image.Resampling.LANCZOS))
        data['background_fit']=[]
    return data

def compose_frame(plate,active,i):
    h,w=plate.shape[:2];scale=w/2880;result=plate.copy();order=sorted(active,key=lambda x:ORDER.index(active[x]['cfg']['role']));spec={};dist=[];cover=np.zeros((h,w),bool)
    for j,key in enumerate(order):
        job=active[key];cfg=job['cfg'];k=i-cfg['source_start_frame'];raw=next(job['raw']);full=cv2.resize(job['source'][k],(w,h),interpolation=cv2.INTER_NEAREST);box,patch=inverse(raw,cfg['geometry'],(w,h));x,y,bw,bh=box
        _,new=inverse((job['new'][k]&(job['support'][k]>0)).astype(np.uint8),cfg['geometry'],(w,h),True)
        if not full.any():new[:]=0
        om=full[y:y+bh,x:x+bw]
        old=cv2.distanceTransform(1-om,cv2.DIST_L2,5)<=18*scale if om.any() else np.zeros_like(om,bool)
        if 'background' in job and full.any():
            # Fill only the vacated old silhouette. Generated complete actor pixels retain
            # their original spatial geometry; no face paste or head resize occurs here.
            bg=job['background'] if job['background'].shape[:2]==(h,w) else cv2.resize(job['background'],(w,h),interpolation=cv2.INTER_LANCZOS4);safe=cv2.resize((~job['source'].any(0).astype(bool)).astype(np.uint8),(w,h),interpolation=cv2.INTER_NEAREST).astype(bool)
            if not job['background_fit']:
                sample=safe[::12,::12];aa=bg[::12,::12][sample].astype(float);bb=plate[::12,::12][sample].astype(float)
                gains=[];offset=[]
                for c in range(3):
                    fit=np.linalg.lstsq(np.column_stack([aa[:,c],np.ones(len(aa))]),bb[:,c],rcond=None)[0];gains.append(float(np.clip(fit[0],.8,1.2)));offset.append(float(np.clip(fit[1],-30,30)))
                job['background_fit'].append((gains,offset))
            gains,offset=job['background_fit'][0]
            clean=np.clip(bg[y:y+bh,x:x+bw].astype(float)*gains+offset,0,255)
            gm=cv2.GaussianBlur(new.astype(np.float32),(0,0),1.6*scale);patch=np.clip(np.rint(clean*(1-gm[...,None])+patch*gm[...,None]),0,255).astype(np.uint8)
            # These 12 portrait frames contain no other dancer. The thin flying
            # hairs lie beyond SAM's old-body support, so use the matched empty
            # scene throughout this portrait crop, then restore the whole actor.
            old[:]=True
        core=old|(new>0);spec[key]=(box,patch,core,bool(full.any()))
        dist.append(cv2.distanceTransform(1-full,cv2.DIST_L2,3)+j*.001)
    owner=np.stack(dist).argmin(0)
    for j,key in enumerate(order):
        (x,y,bw,bh),patch,core,visible=spec[key]
        if not visible:continue
        distance=cv2.distanceTransform((~core).astype(np.uint8),cv2.DIST_L2,5);alpha=np.clip(1-distance/(12*scale),0,1);alpha*=owner[y:y+bh,x:x+bw]==j
        if active[key]['cfg'].get('background_cleanup'):
            alpha*=np.clip(np.arange(bh,dtype=np.float32)[:,None]/(48*scale),0,1)
        area=result[y:y+bh,x:x+bw];area[:]=np.clip(np.rint(area*(1-alpha[...,None])+patch*alpha[...,None]),0,255).astype(np.uint8);cover[y:y+bh,x:x+bw]|=alpha>0
    changed=int(np.count_nonzero(result[~cover]!=plate[~cover]));return result,changed

def main():
    approval=read(N/'visual_approval.json');assert approval['approved'] is True
    jobs=read(N/'selected_jobs.json')['jobs'];matte=read(N/'matte_state.json');assert set(jobs)==set(matte)
    if read(N/'matte_complete.json')['severe']:raise RuntimeError('Unresolved generated mask gaps')
    expected=read(N/'end_decision.json');assert expected['frames']==3173
    assert read(N/'tail_plate_alignment_passthrough.json')['passed'],'Tail source/mask frame alignment has not passed'
    fingerprints={}
    for key,cfg in jobs.items():
        for p in [Path(cfg['raw']),Path(cfg['source_masks']),Path(cfg['crop_masks']),Path(matte[key]['mask'])]+([Path(cfg['background_plate'])] if cfg.get('background_plate') else []):
            if str(p) not in fingerprints:fingerprints[str(p)]=hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
    starts={};ends={}
    for key,cfg in jobs.items():
        starts.setdefault(cfg['source_start_frame']+cfg['keep_from'],[]).append(key);ends.setdefault(cfg['source_start_frame']+cfg['actual_frames'],[]).append(key)
    for i in range(3096,3173):
        assert len([1 for c in jobs.values() if c['source_start_frame']+c['keep_from']<=i<c['source_start_frame']+c['actual_frames']])==3,'Incomplete ending coverage'
    DEST.mkdir(parents=True,exist_ok=True);paths=[DEST/f for f in FILMS];temp=[p.with_suffix('.partial.mp4') for p in paths];src=next(R.glob('*4K*.mp4'))
    import compose_production129 as old
    cmd=old.encoder_command(temp[0],temp[1],src,duration=3173/24);cmd[cmd.index('-crf')+1]='15'
    enc=subprocess.Popen(cmd,stdin=subprocess.PIPE);active={};count=outside=0;review=[]
    want=set(range(0,3173,24))|set(range(3090,3173))
    for c in jobs.values():want.update(range(c['source_start_frame']+c['keep_from'],c['source_start_frame']+c['actual_frames']))
    try:
        for i,plate in enumerate(stream_plate()):
            for key in ends.get(i,[]):
                active[key]['raw'].close();del active[key]
            for key in starts.get(i,[]):active[key]=load_job(key,jobs[key],matte[key])
            if active:result,bad=compose_frame(plate,active,i);outside+=bad
            else:result=plate
            enc.stdin.write(result.tobytes());count+=1
            if i in want:review.append((i,cv2.resize(result,(480,360),interpolation=cv2.INTER_AREA)))
            if i%240==0:print('V4 COMPOSE',i,'/3173',flush=True)
    finally:enc.stdin.close();enc.wait()
    if enc.returncode or count!=3173 or outside:raise RuntimeError((enc.returncode,count,outside))
    for a,b in zip(temp,paths):a.replace(b)
    pre=N/'composite_previews';pre.mkdir(exist_ok=True)
    for start in range(0,len(review),12):
        page=review[start:start+12];board=Image.new('RGB',(1440,390*math.ceil(len(page)/3)));draw=ImageDraw.Draw(board)
        for j,(idx,rgb) in enumerate(page):
            x=j%3*480;y=j//3*390;board.paste(Image.fromarray(rgb),(x,y+25));draw.text((x,y),f'frame{idx} original{506+idx/24:.3f}s',fill='white')
        board.save(pre/f'page_{start//12:02d}.jpg',quality=94)
    report={'frames':count,'fps':24,'duration':count/24,'source_start':506,'source_end_exclusive':506+count/24,'house_frames_included':0,'outside_changed_before_lossy_encoding':outside,'new_jobs':len(jobs),'review_frame_indices':[i for i,_ in review],'files':{p.name:{'bytes':p.stat().st_size,'sha256':hashlib.file_digest(p.open('rb'),'sha256').hexdigest()} for p in paths},'base_master_sha256':hashlib.file_digest(BASE.open('rb'),'sha256').hexdigest(),'selected_jobs_sha256':hashlib.sha256((N/'selected_jobs.json').read_bytes()).hexdigest()}
    report.update(input_files_sha256=fingerprints,matte_state_sha256=hashlib.sha256((N/'matte_state.json').read_bytes()).hexdigest(),composition_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),background_reconstruction={'solo20a':'12-frame portrait crop background rebuilt from image_gen empty plate to erase flyaway original hair; native whole-character RGB retained at original geometry'})
    save(N/'composition_complete.json',report);save(DEST/'成片合成记录.json',report);print('V4 COMPOSITION COMPLETE',flush=True)

if __name__=='__main__':
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    try:main()
    finally:ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
