"""Full-character H3 production. One hot sampler, cut-safe chunks, five-frame context."""
from production129_common import *
import copy,gc,re
from PIL import Image,ImageDraw
ROLES=['Musk','Jensen','FeiFei','Altman','Girlfriend']

def hd_frames(start,end):
    for ci in range(start//90,(end-1)//90+1):
        for j,f in enumerate(frames(D.parent/'high'/f'c{ci:02d}.mp4')):
            at=ci*90+j
            if start<=at<end:yield f

def geometry(m):
    yy,xx=np.where(m.any(0));x0,x1=int(xx.min()),int(xx.max()+1);y0,y1=int(yy.min()),int(yy.max()+1)
    mx=max(12,round((x1-x0)*.09));my=max(10,round((y1-y0)*.055))
    x0=max(0,x0-mx);x1=min(640,x1+mx);y0=max(0,y0-my);y1=min(480,y1+my)
    bw,bh=x1-x0,y1-y0;ratio=max(.5,min(2.,bw/bh))
    h=round(math.sqrt(555000/ratio)/32)*32;w=round(h*ratio/32)*32
    if w*h>590000:
        if w>h:w-=32
        else:h-=32
    scale=min(w/bw,h/bh);rw=min(w,round(bw*scale));rh=min(h,round(bh*scale));px=(w-rw)//2;py=(h-rh)//2
    return {'box':[x0,y0,bw,bh],'canvas':[w,h],'inner':[px,py,rw,rh],'grow':8}

def crop_frame(rgb,geo,mask=False):
    x,y,bw,bh=geo['box'];w,h=geo['canvas'];px,py,rw,rh=geo['inner']
    sx,sy=rgb.shape[1]/640,rgb.shape[0]/480
    x0,y0,x1,y1=[round(a) for a in (x*sx,y*sy,(x+bw)*sx,(y+bh)*sy)]
    patch=cv2.resize(rgb[y0:y1,x0:x1],(rw,rh),interpolation=cv2.INTER_NEAREST if mask else cv2.INTER_LANCZOS4)
    if mask:
        out=np.zeros((h,w),np.uint8);out[py:py+rh,px:px+rw]=patch;return out
    return cv2.copyMakeBorder(patch,py,h-rh-py,px,w-rw-px,cv2.BORDER_REFLECT_101)

def inverse(raw,geo,size=(1440,1080),nearest=False):
    px,py,rw,rh=geo['inner'];x,y,bw,bh=geo['box'];sw,sh=size
    x0,y0,x1,y1=[round(a) for a in (x*sw/640,y*sh/480,(x+bw)*sw/640,(y+bh)*sh/480)]
    return (x0,y0,x1-x0,y1-y0),cv2.resize(raw[py:py+rh,px:px+rw],(x1-x0,y1-y0),interpolation=cv2.INTER_NEAREST if nearest else cv2.INTER_LANCZOS4)

def context_frames(previous,source):
    raw=list(frames(previous['raw']));m=np.load(previous['crop_masks'])['masks'];sup=support(m,previous['geometry']['grow'])
    # Only the overlap is reused; none of these repeated frames enter the final timeline twice.
    actual=previous['actual_frames'];result=[]
    for j in range(5):
        idx=actual-5+j;plate=source[j].copy();(x,y,w,h),patch=inverse(raw[idx],previous['geometry'])
        _,mask=inverse(sup[idx],previous['geometry'],nearest=True)
        region=plate[y:y+h,x:x+w];region[mask>0]=patch[mask>0];result.append(plate)
    return result

def graph_for(role,cfg,key):
    base=read(R/'production'/f'GrayMotion_{role if role!="Girlfriend" else "Musk"}.api.json')
    jobs=read(R/'production/unified_jobs.json')['jobs'];template=jobs['s001_Girlfriend' if role=='Girlfriend' else 'HD_A_'+role]
    base['137']['inputs']['image']=template['costume']
    for node,field in [('152','source'),('300','mask'),('322','size')]:base[node]['inputs']['file']=cfg[field]
    q=base['136']['inputs'];q.update(prompt=template['prompt'].replace('3.750-second',f"{cfg['frames']/24:.3f}-second"),width=cfg['geometry']['canvas'][0],height=cfg['geometry']['canvas'][1],length=cfg['frames'])
    base['129']['inputs']['noise_seed']=template['seed'];base['303']['inputs']['grow']=8
    base['307']['inputs']['filename_prefix']='Prod129/raw/'+key
    # Traverse only the raw video output. Debug composites and grey previews do not consume RAM.
    keep=set()
    def visit(node):
        if node in keep:return
        keep.add(node)
        for v in base[node]['inputs'].values():
            if isinstance(v,list) and len(v)==2 and isinstance(v[0],str) and v[0] in base:visit(v[0])
    visit('307');return {k:v for k,v in base.items() if k in keep}

def raw_path(history):
    found=history['outputs']['307']['images'] if 'images' in history['outputs']['307'] else history['outputs']['307'].get('videos',[])
    if not found:
        found=[x for v in history['outputs']['307'].values() if isinstance(v,list) for x in v if isinstance(x,dict) and str(x.get('filename','')).endswith('.mp4')]
    if len(found)!=1:raise ValueError(history['outputs']['307'])
    return str(OUT/found[0].get('subfolder','')/found[0]['filename'])

def main(limit=None):
    plan=read(D/'production_plan.json');bindings=read(D/'actor_bindings.json');statefile=D/'generation_state.json';state=read(statefile) if statefile.exists() else {'chunks':{}}
    for s in plan['shots']:
        name=s['id'];n=s['frame_count'];masks={r:np.load(D/name/(r+'_source_masks.npz'))['masks'] for r in bindings[name]}
        previous={};at=chunk_index=0
        while at<n:
            stop=min(n,at+90);actual=stop-at;pad=max(5,math.ceil((actual-5)/17)*17+5);key=f'{name}_c{chunk_index:02d}';chunk=state['chunks'].get(key)
            if chunk is None:
                chunk={'shot':name,'start_frame':s['start_frame']+at,'end_frame':s['start_frame']+stop,'shot_offset':at,'actual_frames':actual,'keep_from':5 if at else 0,'frames':pad,'roles':{}}
            needed=[r for r in ROLES if r in masks and masks[r][at+chunk['keep_from']:stop].sum()>0]
            source=None
            for role in needed:
                old=chunk['roles'].get(role)
                if old and old.get('status')=='success' and Path(old['raw']).exists():previous[role]=old;continue
                if source is None:source=list(hd_frames(s['start_frame']+at,s['start_frame']+stop))
                if len(source)!=actual:raise ValueError((key,len(source),actual))
                mm=masks[role][at:stop];geo=geometry(mm);prefix='Prod129_'+key+'_'+role
                role_source=source
                context=bool(at and role in previous and previous[role]['actual_frames']>=5)
                if context:role_source=context_frames(previous[role],source[:5])+source[5:]
                cm=np.stack([crop_frame(f,geo,True) for f in mm]);edit=cm.copy()
                if context:edit[:5]=0
                # H3 accepts 17k+5 frames; pad only inside a cut and trim every padded frame later.
                if pad>actual:
                    cm=np.concatenate([cm,np.repeat(cm[-1:],pad-actual,0)]);edit=np.concatenate([edit,np.repeat(edit[-1:],pad-actual,0)])
                size=[]
                for m in cm:
                    ys=np.where(m>0)[0];v=0 if not len(ys) else min(255,max(1,round((ys.max()-ys.min()+1)/m.shape[0]*255)))
                    size.append(v)
                cfg={'source':prefix+'_source.mp4','mask':prefix+'_mask.mp4','size':prefix+'_size.mp4','geometry':geo,'frames':pad,'actual_frames':actual,'context_frames':5 if context else 0,'crop_masks':str(D/(prefix+'_masks.npz'))}
                def source_crops():
                    last=None
                    for f in role_source:
                        last=crop_frame(f,geo);yield last
                    for _ in range(pad-actual):yield last
                write_video(INP/cfg['source'],source_crops())
                write_video(INP/cfg['mask'],(np.repeat(m[...,None]*255,3,2) for m in edit))
                w,h=geo['canvas'];write_video(INP/cfg['size'],(np.full((h,w,3),v,np.uint8) for v in size))
                np.savez_compressed(cfg['crop_masks'],masks=cm,edit_masks=edit)
                del cm,edit,size,role_source,mm;source=None;gc.collect()
                g=graph_for(role,cfg,key+'_'+role);h=submit(g,key+'_'+role+'_h3')
                cfg.update(raw=raw_path(h),status='success',role=role)
                with av.open(cfg['raw']) as c:
                    st=c.streams.video[0]
                    if st.frames!=pad:raise ValueError('Incomplete generated video '+str(st.frames))
                chunk['roles'][role]=cfg;previous[role]=cfg;state['chunks'][key]=chunk;save(statefile,state)
                print('H3 ROLE READY',key,role,flush=True)
                if limit is not None:
                    limit-=1
                    if limit<=0:return
            state['chunks'][key]=chunk;save(statefile,state)
            previous=dict(chunk['roles'])
            if stop==n:break
            at=stop-5;chunk_index+=1
    assert sum(c['actual_frames']-c['keep_from'] for c in state['chunks'].values())==3096
    save(D/'generation_complete.json',{'frames':3096,'chunks':len(state['chunks']),'roles':sum(len(c['roles']) for c in state['chunks'].values())})

if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--limit',type=int);args=ap.parse_args();main(args.limit)
