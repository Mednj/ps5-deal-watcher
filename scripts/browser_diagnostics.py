"""Bounded browser diagnostics without cookies, tokens, URLs or page contents."""
import json
import logging
import time

logger = logging.getLogger('leboncoin.browser')


def classify_page(text, title='', frames=()):
    sample = (title + ' ' + text).lower()
    return {
        'challenge_detected': any(term in sample for term in (
            'captcha', 'verify you are human', 'vÃƒÆ’Ã‚Â©rifiez que vous',
            'enable js', 'enable javascript', 'access denied', 'accÃƒÆ’Ã‚Â¨s refusÃƒÆ’Ã‚Â©',
        )) or any('captcha-delivery.com' in frame for frame in frames),
        'consent_detected': any(term in sample for term in (
            'continuer sans accepter', 'cookies for good',
        )),
        'empty_search_detected': any(term in sample for term in (
            'aucune annonce', '0 annonce', 'aucun rÃƒÆ’Ã‚Â©sultat',
        )),
    }


def emit(run_id, event, started, **fields):
    # Callers supply bounded counts, flags, stage names and exception types only.
    logger.warning(json.dumps({'component': 'leboncoin.browser', 'run_id': run_id,
                              'event': event, 'elapsed_ms': round((time.monotonic()-started)*1000),
                              **fields}, sort_keys=True))


def classify_challenge(text='', *, visible=True, path='', slider=False, image=False, audio=False):
    sample=text.lower()
    if not visible:
        return {'challenge_kind':'hidden_frame','challenge_blocking':False,'challenge_confidence':'high'}
    if any(term in sample for term in ('access is temporarily restricted','access denied','accÃƒÂ¨s refusÃƒÂ©')):
        kind='restriction'
    elif audio:
        kind='audio'
    elif slider and any(t in sample for t in ('slide right to secure your access','faites glisser vers la droite')):
        kind='slide_to_end'
    elif slider and image:
        kind='image_slider'
    elif image and any(term in sample for term in ('select','sÃƒÂ©lection','puzzle','image','rotate')):
        kind='image_puzzle'
    elif '/interstitial' in path or '/devicecheck' in path or any(term in sample for term in ('checking your browser','verifying your browser','vÃƒÂ©rification de votre navigateur')):
        kind='device_check'
    else:
        kind='unknown'
    return {'challenge_kind':kind,'challenge_blocking':True,'challenge_confidence':'low' if kind=='unknown' else 'high'}


def choose_handler(kind, interactive_enabled=False):
    if kind=='device_check':return 'wait'
    if kind=='slide_to_end':return 'slider' if interactive_enabled else 'disabled'
    if kind=='image_slider':return 'image_slider' if interactive_enabled else 'disabled'
    if kind in ('none','hidden_frame'):return 'none'
    if kind=='restriction':return 'backoff'
    return 'unsupported'


def inspect_challenge(page):
    from urllib.parse import urlsplit
    detected=[]
    for frame in page.frames:
        parsed=urlsplit(frame.url)
        if not parsed.hostname or not (parsed.hostname=='captcha-delivery.com' or parsed.hostname.endswith('.captcha-delivery.com')):
            continue
        try:
            element=frame.frame_element()
            visible=element.is_visible() and element.evaluate("e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>8&&r.height>8&&s.opacity!=='0'&&s.visibility!=='hidden'}")
            if not visible:
                detected.append(classify_challenge(visible=False));continue
            text=frame.locator('body').inner_text(timeout=1500)[:10000]
            slider=frame.locator('.slider:visible,[role=slider]:visible').count()>0
            image=frame.locator('canvas:visible').evaluate_all('els=>els.some(e=>e.width>20&&e.height>20)') or frame.locator('[class*=puzzle] img:visible,[class*=challenge] img:visible').count()>0
            audio=frame.locator('.audio-captcha-inputs:visible').count()>0
            detected.append(classify_challenge(text,visible=True,path=parsed.path,slider=slider,image=image,audio=audio))
        except Exception:
            detected.append(classify_challenge())
    blocking=next((d for d in detected if d['challenge_blocking']),None)
    if blocking:return blocking
    if detected:return detected[0]
    try:
        text=page.locator('body').inner_text(timeout=3000)[:20000]
    except Exception:
        return {'challenge_kind':'unknown','challenge_blocking':True,'challenge_confidence':'low'}
    if any(term in text.lower() for term in ('access is temporarily restricted','access denied','accÃƒÂ¨s refusÃƒÂ©','verification required','verify you are human')):
        return classify_challenge(text)
    return {'challenge_kind':'none','challenge_blocking':False,'challenge_confidence':'high'}
