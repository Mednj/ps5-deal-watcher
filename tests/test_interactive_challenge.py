from scripts.interactive_challenge import slider_centers


def test_slider_requires_visible_aligned_rightward_target():
    handle=dict(x=10,y=20,width=60,height=40)
    assert slider_centers(handle,dict(x=230,y=20,width=60,height=40)) == ((40,40),(260,40))
    for target in (None,dict(x=230,y=20,width=0,height=40),dict(x=0,y=20,width=60,height=40),dict(x=230,y=70,width=60,height=40)):
        assert slider_centers(handle,target) is None


def test_drag_stays_in_track_and_finishes_on_target():
    import random
    from scripts.interactive_challenge import drag_path
    for seed in range(10):
        points=drag_path((40,40),(260,40),random.Random(seed))
        assert points[-1][:2] == (260,40)
        assert all(40<=x<=260 and abs(y-40)<=1.2 and delay>=8 for x,y,delay in points)
        assert all(a[0]<=b[0] for a,b in zip(points,points[1:]))


def test_hidden_frame_does_not_hide_ready_visible_controls():
    from types import SimpleNamespace
    from scripts.interactive_challenge import find_slide_controls
    def frame(visible):
        def locate(selector):
            text='Faites glisser vers la droite'
            box=dict(x=10 if '.slider:' in selector else 230,y=20,width=60,height=40)
            loc=SimpleNamespace(count=lambda:1,inner_text=lambda **kw:text,bounding_box=lambda **kw:box)
            loc.first=loc
            return loc
        return SimpleNamespace(url='https://geo.captcha-delivery.com/captcha/',frame_element=lambda:SimpleNamespace(is_visible=lambda:visible),locator=locate)
    page=SimpleNamespace(frames=[frame(False),frame(True)])
    controls,reason=find_slide_controls(page)
    assert reason=='ready' and controls[1]==((40,40),(260,40))


def test_three_speed_drag_slows_toward_target_and_varies_between_runs():
    import random
    from scripts.interactive_challenge import drag_path
    paths=[]
    for seed in range(20):
        points=drag_path((40,40),(260,40),random.Random(seed))
        previous=40;speed_groups=[[],[],[]]
        for x,y,delay in points:
            progress=(x-40)/220
            group=0 if progress<=.35 else 2 if progress>=.90 else 1
            speed_groups[group].append((x-previous)/delay)
            previous=x
        fast=sum(speed_groups[0])/len(speed_groups[0])
        slow=sum(speed_groups[2])/len(speed_groups[2])
        assert fast>slow*2
        paths.append(points)
    assert paths[0]!=paths[1]
