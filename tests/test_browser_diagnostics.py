import logging

from scripts.browser_diagnostics import classify_page, emit


def test_challenge_and_consent_are_distinguished():
    assert classify_page('Please enable JS')['challenge_detected']
    assert classify_page('', frames=['https://geo.captcha-delivery.com/captcha'])['challenge_detected']
    result = classify_page('Continuer sans accepter')
    assert result['consent_detected'] and not result['challenge_detected']
    assert classify_page('Aucune annonce')['empty_search_detected']


def test_french_no_results_page_is_detected_without_being_a_challenge():
    result = classify_page('Annonces « jeu » : page 2 2 annonces. Désolés, nous n’avons pas ça sous la main ! Recherche sans résultat.')
    assert result['empty_search_detected']
    assert not result['challenge_detected']


def test_page_contents_are_not_logged(caplog):
    flags = classify_page('captcha SECRET_COOKIE_VALUE')
    with caplog.at_level(logging.WARNING):
        emit('abc', 'page_inspected', 0, **flags)
    assert 'SECRET_COOKIE_VALUE' not in caplog.text
    assert 'challenge_detected' in caplog.text and 'run_id' in caplog.text


def test_challenge_types_and_routes():
    from scripts.browser_diagnostics import classify_challenge,choose_handler
    cases=[('Slide right to secure your access',{'slider':True},'slide_to_end','slider'),
           ('Solve the puzzle',{'slider':True,'image':True},'image_slider','image_slider'),
           ('Select images',{'image':True},'image_puzzle','unsupported'),
           ('',{'audio':True},'audio','unsupported'),
           ('Checking your browser',{},'device_check','wait'),
           ('Access is temporarily restricted',{},'restriction','backoff'),
           ('',{},'unknown','unsupported')]
    for text,features,kind,handler in cases:
        result=classify_challenge(text,**features)
        assert result['challenge_kind']==kind and result['challenge_blocking']
        assert choose_handler(kind,True)==handler
    assert choose_handler('slide_to_end',False)=='disabled'
    hidden=classify_challenge('Access denied',visible=False)
    assert not hidden['challenge_blocking'] and choose_handler(hidden['challenge_kind'])=='none'


def test_french_simple_slider_is_not_an_image_puzzle():
    from scripts.browser_diagnostics import classify_challenge
    assert classify_challenge('Faites glisser vers la droite pour sécuriser votre accès',slider=True,image=False)['challenge_kind']=='slide_to_end'


def test_accented_french_restriction_is_classified():
    from scripts.browser_diagnostics import classify_challenge
    assert classify_challenge('Accès temporairement refusé')['challenge_kind'] == 'restriction'
