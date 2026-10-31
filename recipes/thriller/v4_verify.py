"""Decode actual final films, prove duration/audio/end-frame and render encoded reviews."""
from production129_common import *
from v4_compose import N,DEST,FILMS,BASE
from PIL import Image,ImageDraw
import hashlib
from scipy.signal import correlate,correlation_lags

def pcm(path,start=0):
    a=subprocess.run([FF,'-hide_banner','-loglevel','error','-ss',str(start),'-i',str(path),'-t',str(3173/24),'-vn','-ac','1','-ar','16000','-f','f32le','pipe:1'],stdout=subprocess.PIPE,check=True).stdout
    return np.frombuffer(a,np.float32)

def audio_check(a,b):
    out=[]
    for at in [0,56,112]:
        aa=a[at*16000:min(len(a),(at+20)*16000)].astype(float);bb=b[at*16000:min(len(b),(at+20)*16000)].astype(float);n=min(len(aa),len(bb));aa=aa[:n]-aa[:n].mean();bb=bb[:n]-bb[:n].mean()
        c=correlate(bb,aa,method='fft');lags=correlation_lags(n,n);allowed=np.where(abs(lags)<=640)[0];lag=int(lags[allowed[c[allowed].argmax()]])
        x=aa[:n-lag] if lag>=0 else aa[-lag:];y=bb[lag:] if lag>=0 else bb[:n+lag];r=float(np.dot(x,y)/(np.linalg.norm(x)*np.linalg.norm(y)))
        assert abs(lag)<=16 and r>.99,(at,lag,r);out.append({'start':at,'offset_ms':lag/16,'correlation':r})
    assert abs(len(a)-len(b))<=1600,(len(a),len(b));return out

def last_original():
    src=next(R.glob('*4K*.mp4'))
    data=subprocess.run([FF,'-hide_banner','-loglevel','error','-ss','630','-i',str(src),'-vf','crop=2880:2160:480:0,fps=24,select=eq(n\\,196)','-fps_mode','passthrough','-frames:v','1','-pix_fmt','rgb24','-f','rawvideo','pipe:1'],stdout=subprocess.PIPE,check=True).stdout
    return np.frombuffer(data,np.uint8).reshape(2160,2880,3)

def main():
    comp=read(N/'composition_complete.json');report={'frames_required':3173,'duration_required':3173/24,'files':{}};original=pcm(next(R.glob('*4K*.mp4')),506);wanted=set(comp['review_frame_indices']);reference_end=last_original()
    for name,wh in zip(FILMS,[(3840,2160),(1440,1080)]):
        path=DEST/name;count=bad=0;maxerr=0;end=None;page=[];pages=[];seen=[];folder=DEST/'实际成片检查';folder.mkdir(exist_ok=True)
        def flush():
            board=Image.new('RGB',(1440,390*math.ceil(len(page)/3)));d=ImageDraw.Draw(board)
            for j,(i,rgb) in enumerate(page):
                x=j%3*480;y=j//3*390;board.paste(Image.fromarray(rgb),(x,y+25));d.text((x,y),f'ENCODED frame{i} original{506+i/24:.3f}s',fill='white')
            fname='HD_'+str(len(pages)).zfill(2)+'.jpg';board.save(folder/fname,quality=95);pages.append(fname);page.clear()
        with av.open(str(path)) as c:
            s=c.streams.video[0];au=c.streams.audio[0];assert(s.width,s.height)==wh and float(s.average_rate)==24;asec=float(au.duration*au.time_base);assert abs(asec-3173/24)<.05
            for f in c.decode(video=0):
                bad+=int(f.is_corrupt);t=float(f.pts*f.time_base);maxerr=max(maxerr,abs(t-count/24));rgb=None
                if count in wanted and wh[0]==1440:
                    rgb=f.to_ndarray(format='rgb24');page.append((count,cv2.resize(rgb,(480,360),interpolation=cv2.INTER_AREA)));seen.append(count)
                    if len(page)==12:flush()
                if count==3172:end=f.to_ndarray(format='rgb24')
                count+=1
        assert count==3173 and bad==0 and maxerr<1e-4
        if page:flush()
        if wh[0]==1440:assert set(seen)==wanted
        active=end[:,480:3360] if wh[0]==3840 else end
        ref=reference_end if wh[0]==3840 else cv2.resize(reference_end,(1440,1080),interpolation=cv2.INTER_LANCZOS4)
        # Last-frame top band is outside every original and generated actor silhouette.
        band=350 if wh[0]==3840 else 170;err=float(np.abs(active[:band].astype(float)-ref[:band]).mean());assert err<4,('Wrong ending frame',name,err)
        sound=pcm(path);alignment=audio_check(original,sound);digest=hashlib.file_digest(path.open('rb'),'sha256').hexdigest();assert digest==comp['files'][name]['sha256']
        report['files'][name]={'frames':count,'fps':24,'resolution':list(wh),'duration':count/24,'corrupt_frames':bad,'max_pts_error':maxerr,'audio_duration':asec,'audio_sync':alignment,'last_frame_background_mae_vs_expected_original':err,'sha256':digest,'encoded_review_pages':pages,'encoded_review_frames':seen}
        Image.fromarray(end).save(folder/('4K_最后舞蹈帧.png' if wh[0]==3840 else 'HD_最后舞蹈帧.png'))
        print('VERIFIED V4',name,count,'last-frame MAE',err,flush=True)
    save(N/'final_verification.json',report);save(DEST/'完整解码与音画核验.json',report)

if __name__=='__main__':main()
