"""One bounded attempt for the observed slide-to-end challenge."""
import time
import math
import random
from urllib.parse import urlsplit


def slider_centers(handle, target):
    if not handle or not target:
        return None
    if any(b.get('width',0)<=0 or b.get('height',0)<=0 for b in (handle,target)):
        return None
    start=(handle['x']+handle['width']/2,handle['y']+handle['height']/2)
    end=(target['x']+target['width']/2,target['y']+target['height']/2)
    if not 20<=end[0]-start[0]<=600 or abs(end[1]-start[1])>10:
        return None
    return start,end


def drag_path(start, end, rng=None):
    """Three randomized speed phases: fast, medium, then slow near the target."""
    rng = rng or random.SystemRandom()
    cuts=(0, rng.uniform(.40,.55), rng.uniform(.78,.88), 1)
    speeds=(rng.uniform(.40,.60), rng.uniform(.18,.28), rng.uniform(.055,.10))
    distance=math.hypot(end[0]-start[0],end[1]-start[1])
    result=[]
    previous=0
    for phase,speed in enumerate(speeds):
        lo,hi=cuts[phase],cuts[phase+1]
        steps=max(5,round(distance*(hi-lo)/rng.uniform(3,5)))
        for i in range(1,steps+1):
            progress=lo+(hi-lo)*i/steps
            x=start[0]+(end[0]-start[0])*progress
            y=start[1]+(end[1]-start[1])*progress+math.sin(math.pi*progress)*rng.uniform(-1.2,1.2)
            delay=max(8,distance*(progress-previous)/speed*rng.uniform(.92,1.08))
            result.append((x,y,delay))
            previous=progress
    result[-1]=(*end,result[-1][2])
    return result


def challenge_state(page):
    for frame in page.frames:
        if urlsplit(frame.url).hostname == 'geo.captcha-delivery.com':
            try:
                text=frame.locator('body').inner_text(timeout=1500).lower()
                if 'access is temporarily restricted' in text:
                    return 'temporarily_restricted'
                if 'slide right to secure your access' in text:
                    return 'slider_present'
                return 'other_challenge'
            except Exception:
                return 'frame_unreadable'
    return 'no_challenge_frame'


def find_slide_controls(page):
    reason='no_visible_challenge_frame'
    for frame in page.frames:
        parsed=urlsplit(frame.url)
        if parsed.hostname!='geo.captcha-delivery.com':continue
        try:
            element=frame.frame_element()
            if not element.is_visible():continue
            reason='instruction_not_recognised'
            instruction=frame.locator('.sliderText:visible').first
            if not instruction.count():continue
            text=instruction.inner_text(timeout=1000).lower()
            if not any(t in text for t in ('slide right to secure your access','faites glisser vers la droite')):continue
            reason='controls_not_ready'
            handle=frame.locator('.slider:visible').first
            target=frame.locator('.sliderTarget:visible').first
            if not handle.count() or not target.count():continue
            points=slider_centers(handle.bounding_box(timeout=1000),target.bounding_box(timeout=1000))
            if points:return (handle,points),'ready'
            reason='invalid_control_geometry'
        except Exception:
            reason='frame_changed_during_inspection'
    return None,reason


def attempt_slide(page, emit, run_id, started):
    """Select visible controls, allowing a bounded wait for delayed rendering."""
    until=time.monotonic()+4
    while True:
        controls,reason=find_slide_controls(page)
        if controls or time.monotonic()>=until:break
        page.wait_for_timeout(250)
    if not controls:
        emit(run_id,'interactive_unavailable',started,reason=reason,state=challenge_state(page))
        return 'unsupported'
    handle,points=controls
    emit(run_id,'slider_controls_ready',started)
    emit(run_id,'interactive_attempt_started',started,kind='slide_to_end')
    start,end=points
    rng=random.SystemRandom()
    verification=[]
    def response_seen(response):
        parsed=urlsplit(response.url)
        if parsed.hostname=='geo.captcha-delivery.com' and ('check' in parsed.path or 'verify' in parsed.path):
            verification.append(response.status)
            emit(run_id,'challenge_verification_response',started,http_status=response.status)
    page.on('response',response_seen)
    delay=rng.randint(700,1400)
    emit(run_id,'pacing_pause',started,stage='before_pointer_approach',duration_ms=delay)
    page.wait_for_timeout(delay)
    origin=(start[0]-35,start[1]+15)
    page.mouse.move(*origin)
    for step in range(1,13):
        t=step/12
        page.mouse.move(origin[0]+(start[0]-origin[0])*t,origin[1]+(start[1]-origin[1])*t)
        page.wait_for_timeout(rng.randint(35,80))
    page.wait_for_timeout(rng.randint(600,1200))
    page.mouse.down()
    page.wait_for_timeout(rng.randint(120,260))
    try:
        for x,y,delay in drag_path(start,end,rng):
            page.mouse.move(x,y)
            page.wait_for_timeout(delay)
        moved=handle.bounding_box()
        emit(run_id,'slider_motion_finished',started,target_reached=bool(moved and abs(moved['x']+moved['width']/2-end[0])<8))
        page.wait_for_timeout(rng.randint(90,220))
    finally:
        page.mouse.up()
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        challenge=any(urlsplit(f.url).hostname=='geo.captcha-delivery.com' for f in page.frames)
        cards=page.locator('a[href*="/ad/jeux_video/"]:visible').count()
        if not challenge and cards:
            emit(run_id,'interactive_attempt_finished',started,kind='slide_to_end',access_confirmed=True)
            page.remove_listener('response',response_seen)
            return 'access_confirmed'
        page.wait_for_timeout(500)
    page.remove_listener('response',response_seen)
    emit(run_id,'interactive_attempt_finished',started,kind='slide_to_end',access_confirmed=False,state=challenge_state(page),verification_responses=len(verification))
    return 'not_cleared'
