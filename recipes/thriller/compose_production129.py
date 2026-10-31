"""Restore native 4K background and soundtrack; composite only generated complete bodies."""
from production129_common import *
from generate_production129 import inverse
from PIL import Image,ImageDraw
import hashlib
DEST=R.parents[1]/'最终交付/Thriller_万圣节名人群舞成片/129秒完整版'
ORDER=['Musk','FeiFei','Jensen','Altman','Girlfriend']

def encoder_command(master,hd,source,duration=129):
    cmd=[FF,'-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','2880x2160','-r','24','-i','pipe:0','-ss','506','-i',str(source),'-filter_complex','[0:v]split=2[master][down];[master]pad=3840:2160:480:0:black[v4k];[down]scale=1440:1080:flags=lanczos[vhd]']
    for stream,path in [('[v4k]',master),('[vhd]',hd)]:
        cmd+=['-map',stream,'-map','1:a:0','-t',str(duration),'-c:v','libx264','-preset','slow','-crf','16','-pix_fmt','yuv420p','-c:a','aac','-b:a','320k','-movflags','+faststart',str(path)]
    return cmd

def original_frames():
    src=next(R.glob('*4K*.mp4'))
    p=subprocess.Popen([FF,'-hide_banner','-loglevel','error','-threads','2','-ss','506','-i',str(src),'-an','-vf','crop=2880:2160:480:0,fps=24','-frames:v','3096','-f','rawvideo','-pix_fmt','rgb24','pipe:1'],stdout=subprocess.PIPE)
    try:
        for _ in range(3096):
            a=p.stdout.read(2880*2160*3)
            if len(a)!=2880*2160*3:raise ValueError('Source frame decode incomplete')
            yield np.frombuffer(a,np.uint8).reshape(2160,2880,3).copy()
    finally:p.stdout.close();p.wait()
    if p.returncode:raise RuntimeError('4K decode failed')

def main():
    gate=read(D/'repair_review_gate.json')
    if any(not v.get('resolved') for v in gate.values()):raise RuntimeError('Character-motion review is still pending; final compositing held')
    DEST.mkdir(parents=True,exist_ok=True);state=read(D/'generation_state.json');chunks=sorted(state['chunks'].items(),key=lambda x:x[1]['start_frame']+x[1]['keep_from'])
    alignment=read(D/'full_source_alignment_check.json')
    if not alignment.get('passed'):raise ValueError('Full source frame alignment has not passed')
    settings=read(D/'composite_settings129.json')
    state_sha=hashlib.sha256((D/'generation_state.json').read_bytes()).hexdigest()
    input_digest=hashlib.sha256((D/'generation_state.json').read_bytes()+(D/'actor_bindings.json').read_bytes());hashed=set()
    input_digest.update(b'production-composite-v2-source-safety-margin')
    input_digest.update((D/'composite_settings129.json').read_bytes())
    for key,c in chunks:
        for role,cfg in c['roles'].items():
            for item in [Path(cfg['raw']),Path(cfg['crop_masks']),D/c['shot']/(role+'_source_masks.npz'),D/(key+'_'+role+'_generated_mask.npz')]:
                if item not in hashed:input_digest.update(hashlib.file_digest(item.open('rb'),'sha256').digest());hashed.add(item)
    input_sha=input_digest.hexdigest()
    previous=D/'composition_complete.json'
    if previous.exists():
        old=read(previous)
        if old.get('composition_input_sha256')==input_sha and all((DEST/name).exists() and hashlib.file_digest((DEST/name).open('rb'),'sha256').hexdigest()==v['sha256'] for name,v in old['files'].items()):
            verified=D/'final_decode_verification.json'
            if not verified.exists() or any(read(verified)['files'].get(name,{}).get('sha256')!=v['sha256'] for name,v in old['files'].items()):
                import verify_final129
                verify_final129.main()
            print('VERIFIED FINISHED OUTPUT REUSED',flush=True);return
    assert sum(c['actual_frames']-c['keep_from'] for _,c in chunks)==3096
    cursor=0
    for key,c in chunks:
        if c['start_frame']+c['keep_from']!=cursor or c['start_frame']+c['actual_frames']!=c['end_frame']:raise ValueError('Timeline discontinuity: '+key)
        cursor=c['end_frame']
    if cursor!=3096:raise ValueError('Timeline does not end at3096')
    matte_report=read(D/'matting_complete.json')
    if matte_report.get('severe_missing') or matte_report.get('severe_low_overlap'):raise ValueError('Unresolved generated-body tracking gaps or wrong-object masks')
    q=requests.get(URL+'/queue',timeout=30).json()
    if not q['queue_running'] and not q['queue_pending']:requests.post(URL+'/free',json={'unload_models':True,'free_memory':True},timeout=30)
    target=DEST/'Thriller_万圣节名人群舞_129秒_4K.mp4';temp=target.with_suffix('.partial.mp4');src=next(R.glob('*4K*.mp4'))
    hd=DEST/'Thriller_万圣节名人群舞_129秒_1080p.mp4';temp_hd=hd.with_suffix('.partial.mp4')
    encode=subprocess.Popen(encoder_command(temp,temp_hd,src),stdin=subprocess.PIPE)
    plate_iter=original_frames();count=outside_changed=0;reports=[];contacts=[]
    review_frames=set(range(0,3096,24))
    for shot in read(D/'production_plan.json')['shots']:
        a,b=shot['start_frame'],shot['end_frame'];review_frames.update([a,min(a+3,b-1),(a+b)//2,max(a,b-4),b-1])
    try:
        for key,c in chunks:
            roles=[r for r in ORDER if r in c['roles']];raw={r:frames(c['roles'][r]['raw']) for r in roles};orig={};sup={};new={};source_masks={}
            for r in roles:
                cfg=c['roles'][r];a=np.load(cfg['crop_masks'])['masks'];orig[r]=a;sup[r]=support(a,cfg['geometry']['grow']);new[r]=np.load(D/(key+'_'+r+'_generated_mask.npz'))['masks']
                source_masks[r]=np.load(D/c['shot']/(r+'_source_masks.npz'))['masks']
            edited=0
            for i in range(c['actual_frames']):
                raws={r:next(raw[r]) for r in roles}
                if i<c['keep_from']:continue
                plate=next(plate_iter);result=plate.copy();h,w=plate.shape[:2];region_masks={};distances=[];spec={}
                for j,r in enumerate(roles):
                    cfg=c['roles'][r];box,_=inverse(orig[r][i],cfg['geometry'],(w,h),True);x,y,bw,bh=box
                    full=cv2.resize(source_masks[r][c['shot_offset']+i],(w,h),interpolation=cv2.INTER_NEAREST)
                    om=full[y:y+bh,x:x+bw]
                    parameters={**settings['default'],**settings.get('overrides',{}).get(key+'_'+r,{})}
                    # SAM's 640px source outline excludes fine hair and motion-blurred edges.
                    # Cover their old silhouette using H3's regenerated background, without
                    # smoothing the new face/body pixels or changing actor proportions.
                    if parameters['source_margin_4k_px'] and om.any():
                        om=(cv2.distanceTransform(1-om,cv2.DIST_L2,5)<=parameters['source_margin_4k_px']).astype(np.uint8)
                    gm=new[r][i]&(sup[r][i]>0)
                    # No generated ghosts when the original actor is entirely out of frame.
                    if not full.any():gm[:]=0
                    _,nm=inverse(gm.astype(np.uint8),cfg['geometry'],(w,h),True)
                    distance=cv2.distanceTransform(1-full,cv2.DIST_L2,3)
                    # Front role wins an exact distance tie, without stealing neighbouring bodies.
                    distances.append(distance+j*.001);region_masks[r]=om.astype(bool)|nm.astype(bool);spec[r]=box
                owner=np.stack(distances).argmin(0) if distances else None
                cover=np.zeros((h,w),bool)
                for j,r in enumerate(roles):
                    cfg=c['roles'][r];x,y,bw,bh=spec[r];core=region_masks[r]
                    if not source_masks[r][c['shot_offset']+i].any():continue
                    parameters={**settings['default'],**settings.get('overrides',{}).get(key+'_'+r,{})}
                    distance=cv2.distanceTransform((~core).astype(np.uint8),cv2.DIST_L2,5);alpha=np.clip(1-distance/parameters['feather_4k_px'],0,1)
                    alpha*=owner[y:y+bh,x:x+bw]==j
                    _,patch=inverse(raws[r],cfg['geometry'],(w,h));area=result[y:y+bh,x:x+bw]
                    area[:]=np.clip(np.rint(area*(1-alpha[...,None])+patch*alpha[...,None]),0,255).astype(np.uint8);cover[y:y+bh,x:x+bw]|=alpha>0
                outside_changed+=int(np.count_nonzero(result[~cover]!=plate[~cover]));edited+=int(cover.sum());encode.stdin.write(result.tobytes());count+=1
                if count-1 in review_frames:
                    thumb=cv2.resize(result,(480,360),interpolation=cv2.INTER_AREA);contacts.append((count-1,thumb))
            reports.append({'chunk':key,'frames':c['actual_frames']-c['keep_from'],'roles':roles,'edited_pixels':edited});print('COMPOSED',key,count,'/3096',flush=True)
    finally:encode.stdin.close();encode.wait()
    if encode.returncode or count!=3096 or outside_changed:raise RuntimeError((encode.returncode,count,outside_changed))
    temp.replace(target);temp_hd.replace(hd)
    preview_dir=DEST/'工作流与运行记录/编码前预览';preview_dir.mkdir(parents=True,exist_ok=True)
    for start in range(0,len(contacts),12):
        page=contacts[start:start+12];b=Image.new('RGB',(1440,390*math.ceil(len(page)/3)));dr=ImageDraw.Draw(b)
        for j,(idx,im) in enumerate(page):
            x=j%3*480;y=j//3*390;b.paste(Image.fromarray(im),(x,y+25));dr.text((x,y+4),f'{idx/24:.3f}s / source {506+idx/24:.3f}s',fill='white')
        b.save(preview_dir/f'检查图_{start//12:02d}.jpg',quality=94)
    report={'frames':count,'fps':24,'duration_seconds':count/24,'source_range_seconds':[506,635],'generation_state_sha256':state_sha,'composition_input_sha256':input_sha,'outside_changed_before_lossy_encoding':outside_changed,'4K_resolution':[3840,2160],'active_picture':[2880,2160],'HD_resolution':[1440,1080],'original_audio':True,'chunks':reports,'files':{f.name:{'bytes':f.stat().st_size,'sha256':hashlib.file_digest(f.open('rb'),'sha256').hexdigest()} for f in [target,hd]}}
    report['composite_settings']=settings
    report['review_frame_indices']=[idx for idx,_ in contacts]
    save(DEST/'成片核验.json',report);save(D/'composition_complete.json',report)
    import verify_final129
    verify_final129.main()
    import review_encoded129
    review_encoded129.main()
    print('FULL 129 SECOND FILM COMPLETE',target,flush=True)

if __name__=='__main__':main()
