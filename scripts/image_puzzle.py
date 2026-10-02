"""Bounded CPU-only silhouette matching for transparent-piece canvas sliders."""
import time
from urllib.parse import urlsplit
from .interactive_challenge import drag_path


def locate_gap(width,height,background,piece):
    if not 40<=width<=600 or not 20<=height<=400 or len(background)!=width*height*4 or len(piece)!=len(background):
        return None
    mask={(x,y) for y in range(height) for x in range(width) if piece[(y*width+x)*4+3]>200}
    if not 30<=len(mask)<=width*height*.25:return None
    xmin=min(x for x,y in mask);xmax=max(x for x,y in mask)
    edges=[(x,y,dx,dy) for x,y in mask for dx,dy in ((-2,0),(2,0),(0,-2),(0,2))
           if (x+dx,y+dy) not in mask and 0<=y+dy<height]
    if len(edges)<20:return None
    # Sample the silhouette boundary; a dark cutout should contrast with its surroundings.
    edges=edges[::max(1,len(edges)//400)]
    def gray(x,y):
        i=(y*width+x)*4
        return sum(background[i:i+3])/3
    scores=[]
    for shift in range(max(15,xmax-xmin),width-xmax-2):
        valid=[(x,y,dx,dy) for x,y,dx,dy in edges if 0<=x+shift+dx<width]
        if not valid:continue
        score=sum(gray(x+shift+dx,y+dy)-gray(x+shift,y) for x,y,dx,dy in valid)/len(valid)
        scores.append((score,shift))
    if not scores:return None
    best=max(scores)
    other=max((score for score,shift in scores if abs(shift-best[1])>5),default=0)
    if best[0]<12 or best[0]-other<3:return None
    return {'shift':best[1],'score':round(best[0],2),'margin':round(best[0]-other,2)}


def attempt_image_slider(page,emit,run_id,started):
    frame=next((f for f in page.frames if urlsplit(f.url).hostname=='geo.captcha-delivery.com'),None)
    if not frame:return 'unsupported'
    try:
        data=frame.locator('canvas').evaluate_all("""els=>{
            const cs=els.filter(e=>e.width>20&&e.height>20&&e.getBoundingClientRect().height>20);
            const p=cs.find(e=>e.classList.contains('block')), b=cs.find(e=>e!==p);
            if(!p||!b||p.width!==b.width||p.height!==b.height||b.width>600||b.height>400)return null;
            return {width:b.width,height:b.height,background:Array.from(b.getContext('2d').getImageData(0,0,b.width,b.height).data),piece:Array.from(p.getContext('2d').getImageData(0,0,p.width,p.height).data),css_width:b.getBoundingClientRect().width};
        }""")
    except Exception:
        emit(run_id,'image_solver_unavailable',started,reason='unreadable_canvas')
        return 'unsupported'
    if not data:return 'unsupported'
    match=locate_gap(data['width'],data['height'],data['background'],data['piece'])
    if not match:
        emit(run_id,'image_solver_unavailable',started,reason='low_confidence')
        return 'low_confidence'
    handle=frame.locator('.slider:visible').first
    box=handle.bounding_box()
    if not box:return 'unsupported'
    start=(box['x']+box['width']/2,box['y']+box['height']/2)
    end=(start[0]+match['shift']*data['css_width']/data['width'],start[1])
    emit(run_id,'image_solver_match',started,**match)
    page.mouse.move(*start);page.mouse.down()
    try:
        for x,y,delay in drag_path(start,end):
            page.mouse.move(x,y);page.wait_for_timeout(delay)
    finally:page.mouse.up()
    until=time.monotonic()+8
    while time.monotonic()<until:
        challenge=any(urlsplit(f.url).hostname=='geo.captcha-delivery.com' for f in page.frames)
        if not challenge and page.locator('a[href*="/ad/jeux_video/"]:visible').count():return 'access_confirmed'
        page.wait_for_timeout(500)
    return 'not_cleared'
