import glob, os, numpy as np
from PIL import Image, ImageDraw
from collections import deque

def felt_ref(a):
    ring=np.concatenate([a[0:2,:,:3].reshape(-1,3),a[-2:,:,:3].reshape(-1,3),
                         a[:,0:2,:3].reshape(-1,3),a[:,-2:,:3].reshape(-1,3)])
    return np.median(ring,0)

def felt_flood(a,ref,tol=12.0):
    H,W=a.shape[:2]; rgb=a[:,:,:3].astype(np.float32)
    d=np.sqrt(((rgb-ref)**2).sum(2)); cand=d<tol
    seen=np.zeros((H,W),bool); q=deque()
    for cy,cx in((0,0),(0,W-1),(H-1,0),(H-1,W-1)):
        if cand[cy,cx] and not seen[cy,cx]: seen[cy,cx]=True; q.append((cy,cx))
    while q:
        y,x=q.popleft()
        for dy,dx in((1,0),(-1,0),(0,1),(0,-1)):
            ny,nx=y+dy,x+dx
            if 0<=ny<H and 0<=nx<W and cand[ny,nx] and not seen[ny,nx]:
                seen[ny,nx]=True; q.append((ny,nx))
    return seen

def largest_cc(mask):
    H,W=mask.shape; seen=np.zeros_like(mask); best=None; bestn=0
    for sy in range(H):
        for sx in range(W):
            if mask[sy,sx] and not seen[sy,sx]:
                q=deque([(sy,sx)]); seen[sy,sx]=True; comp=[]
                while q:
                    y,x=q.popleft(); comp.append((y,x))
                    for dy,dx in((1,0),(-1,0),(0,1),(0,-1)):
                        ny,nx=y+dy,x+dx
                        if 0<=ny<H and 0<=nx<W and mask[ny,nx] and not seen[ny,nx]:
                            seen[ny,nx]=True; q.append((ny,nx))
                if len(comp)>bestn: bestn=len(comp); best=comp
    out=np.zeros_like(mask)
    for y,x in(best or []): out[y,x]=True
    return out

def fill_holes(mask):
    H,W=mask.shape; bg=np.zeros_like(mask); q=deque()
    for x in range(W):
        for y in(0,H-1):
            if not mask[y,x] and not bg[y,x]: bg[y,x]=True; q.append((y,x))
    for y in range(H):
        for x in(0,W-1):
            if not mask[y,x] and not bg[y,x]: bg[y,x]=True; q.append((y,x))
    while q:
        y,x=q.popleft()
        for dy,dx in((1,0),(-1,0),(0,1),(0,-1)):
            ny,nx=y+dy,x+dx
            if 0<=ny<H and 0<=nx<W and not mask[ny,nx] and not bg[ny,nx]:
                bg[ny,nx]=True; q.append((ny,nx))
    return mask|(~bg)

def erode(mask,k=1):
    m=mask.copy()
    for _ in range(k):
        e=m.copy(); e[1:,:]&=m[:-1,:]; e[:-1,:]&=m[1:,:]; e[:,1:]&=m[:,:-1]; e[:,:-1]&=m[:,1:]; m=e
    return m

def bleed(color,known,iters=10):
    # nearest-ish color fill: each iter, unknown pixels adjacent to known take mean of known neighbors
    col=color.astype(np.float32).copy(); kn=known.copy(); H,W=kn.shape
    for _ in range(iters):
        if kn.all(): break
        nb_sum=np.zeros_like(col); nb_cnt=np.zeros((H,W),np.float32)
        for dy,dx in((1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)):
            sh=np.zeros_like(col); shk=np.zeros((H,W),bool)
            ys0,ys1=max(0,dy),H+min(0,dy); xs0,xs1=max(0,dx),W+min(0,dx)
            yd0,yd1=max(0,-dy),H+min(0,-dy); xd0,xd1=max(0,-dx),W+min(0,-dx)
            sh[yd0:yd1,xd0:xd1]=col[ys0:ys1,xs0:xs1]; shk[yd0:yd1,xd0:xd1]=kn[ys0:ys1,xs0:xs1]
            nb_sum+=sh*shk[:,:,None]; nb_cnt+=shk
        ring=(~kn)&(nb_cnt>0)
        col[ring]=(nb_sum[ring]/nb_cnt[ring,None])
        kn|=ring
    return col

def rrect_alpha(w,h,r,ss=4):
    big=Image.new('L',(w*ss,h*ss),0); ImageDraw.Draw(big).rounded_rectangle([0,0,w*ss-1,h*ss-1],radius=r*ss,fill=255)
    return big.resize((w,h),Image.LANCZOS)

CANVAS=(134,186)
def felt_bright(ref): return float(np.mean(ref))
def process(fp, rratio=0.095, trim=2):
    im=Image.open(fp).convert('RGBA'); a=np.array(im).astype(np.int16); rgb0=np.array(im)[:,:,:3]
    ref=felt_ref(a); fb=felt_bright(ref); felt=felt_flood(a,ref,12.0)
    fg=fill_holes(largest_cc(~felt))
    R=a[:,:,0].astype(np.float32); G=a[:,:,1].astype(np.float32); B=a[:,:,2].astype(np.float32)
    bright=(R+G+B)/3.0; greenish=(G>R+6)&(G>B+6); is_shadow=greenish&(bright<0.78*fb)
    card=fill_holes(largest_cc(fg&(~is_shadow)))
    light=erode(card,trim)            # drop outer 2px ring (residue/shadow/AA)
    if not light.any(): light=card
    seed=erode(light,1);  seed=seed if seed.any() else light
    colf=bleed(rgb0,seed,iters=16)
    ys,xs=np.where(light); y0,y1,x0,x1=ys.min(),ys.max(),xs.min(),xs.max()
    w,h=x1-x0+1,y1-y0+1; r=max(6,round(rratio*w))
    crop=np.clip(colf[y0:y1+1,x0:x1+1],0,255).astype(np.uint8)
    cardimg=Image.merge("RGBA",(*Image.fromarray(crop).split(),rrect_alpha(w,h,r)))
    cw,ch=CANVAS; s=min(cw/w,ch/h); nw,nh=max(1,round(w*s)),max(1,round(h*s))
    cardimg=cardimg.resize((nw,nh),Image.LANCZOS)
    canvas=Image.new("RGBA",CANVAS,(0,0,0,0)); canvas.alpha_composite(cardimg,((cw-nw)//2,(ch-nh)//2))
    return canvas,(w,h,r)
