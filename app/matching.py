from dataclasses import dataclass
from contextvars import ContextVar

manual_check = ContextVar('manual_check', default=False)
from datetime import datetime, timezone
import math
import re
import unicodedata
from zoneinfo import ZoneInfo

from .models import Watch, Listing, CENTRES

def normalize(text):
    text = unicodedata.normalize('NFKD', text.casefold()).replace('’', "'")
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"['’]", '', text)
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()

def phrase(needle, haystack):
    return f' {normalize(needle)} ' in f' {normalize(haystack)} '

def hours_contains(start, end, local):
    if not start or not end or start == end:
        return True
    clock = local.strftime('%H:%M')
    return start <= clock < end if start < end else clock >= start or clock < end

def eligible(watch: Watch, now, allow_manual=True):
    if allow_manual and manual_check.get():
        return watch.active and (watch.end_at is None or now < watch.end_at)
    return (watch.active and (watch.start_at is None or now >= watch.start_at)
            and (watch.end_at is None or now < watch.end_at)
            and hours_contains(watch.checking_start, watch.checking_end, datetime.fromtimestamp(now, ZoneInfo(watch.timezone))))

def quiet(settings, now):
    return bool(settings.get('quiet_start') and settings.get('quiet_end')
                and settings['quiet_start'] != settings['quiet_end']
                and hours_contains(settings['quiet_start'], settings['quiet_end'], datetime.fromtimestamp(now,ZoneInfo(settings['timezone']))))

def distance(a, b):
    lat1,lon1,lat2,lon2=map(math.radians,(*a,*b))
    h=math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371*2*math.atan2(math.sqrt(h),math.sqrt(max(0,1-h)))

@dataclass
class Match:
    state: str
    reason: str
    total: int | None = None
    route: str = ''

def match(watch: Watch, listing: Listing):
    if listing.source not in watch.sources:
        return Match('excluded','Source not selected.')
    text = f'{listing.title} {listing.description}'
    title = normalize(listing.title)
    name = next((name for name in [watch.name,*watch.aliases] if phrase(name,listing.title)), None)
    if not name:
        return Match('excluded','Game name or explicit alias not found in title.')
    excluded_term=next((term for term in watch.excluded if term.strip() and phrase(term,text)),None)
    if excluded_term:
        return Match('excluded',f'Excluded term "{excluded_term}" matched the listing title or description.')
    if watch.qualification == 'name-price':
        if listing.availability == 'unavailable':
            return Match('excluded','Source reports unavailable.')
        if listing.item_cents > watch.max_cents:
            return Match('over-budget','Advertised item price exceeds your budget.',listing.item_cents,'item')
        return Match('qualified',f'Title matches {name}; advertised item price is within budget. Platform, disc, edition, delivery and fees are not qualification requirements.',listing.item_cents,'item')
    # Numbers and common subtitle/edition additions after the matched game need review.
    tail = title.split(normalize(name),1)[1].strip()
    if re.match(r'^(?:[0-9]+|ii|iii|iv|v|vi|vii|viii|ix|x)(?: |$)',tail):
        return Match('excluded','Title appears to be a different sequel. Add its full name as a watch.')
    forbidden = ['digital','numerique','dematerialise','code de telechargement','download code','cle cd','cd key','compte','account','boite vide','empty case','boitier seul','sans disque','manette','controller','accessoire','season pass','dlc']
    matched_forbidden=next((term for term in forbidden if phrase(term,text)),None)
    if matched_forbidden:
        return Match('excluded',f'Excluded listing type "{matched_forbidden}" detected.')
    if listing.physical is False:
        return Match('excluded','Listing is not a physical disc.')
    if listing.bundle or any(phrase(x,listing.title) for x in ['bundle','lot de','pack de']):
        if not watch.bundles:
            return Match('excluded','Bundles are disabled.')
    if listing.platform == 'other' or (listing.platform == 'ps4-upgrade' and not watch.ps4_upgrade):
        return Match('excluded','Wrong platform or PS4 upgrade not enabled.')
    if listing.availability == 'unavailable':
        return Match('excluded','Source reports unavailable.')
    if listing.price_kind in ('trade-in','installment'):
        return Match('excluded','Trade-in or installment amount is not a sale price.')
    if watch.condition != 'any' and listing.condition not in (watch.condition,'unknown'):
        return Match('excluded','Condition does not match.')
    reasons = []
    if listing.platform == 'unknown': reasons.append('PS5 platform unconfirmed')
    if listing.physical is None: reasons.append('physical disc unconfirmed')
    if watch.condition != 'any' and listing.condition == 'unknown': reasons.append('condition unconfirmed')
    if watch.edition and not phrase(watch.edition,text): reasons.append('requested edition unconfirmed')
    if watch.language and not phrase(watch.language,text): reasons.append('requested language unconfirmed')
    if listing.price_kind != 'exact': reasons.append(f'{listing.price_kind} price requires checking')
    editions = ['deluxe','ultimate','collector','gold edition','complete edition','goty','remastered','remake']
    if not watch.edition and any(phrase(e,listing.title) and not phrase(e,name) for e in editions):
        reasons.append('edition differs from the watch title')
    # Strict title matching is conservative: unrecognised trailing subtitle text stays for review.
    remainder = tail
    for token in ['sur','on','ps5','ps4','playstation','5','4','disc','disque','physical','physique','occasion','used','new','neuf','sealed','scelle','jeu','game']:
        remainder = re.sub(r'\b'+token+r'\b',' ',remainder)
    if watch.edition: remainder = remainder.replace(normalize(watch.edition),'')
    if watch.language: remainder = remainder.replace(normalize(watch.language),'')
    if remainder.strip(): reasons.append('additional title wording needs review')
    routes = []
    pickup_possible = False
    if watch.pickup and listing.pickup:
        if listing.lat is not None and listing.lon is not None:
            pickup_possible = any(distance(CENTRES[c],(listing.lat,listing.lon)) <= watch.radius_km for c in watch.centres)
            if pickup_possible:
                total = listing.item_cents + listing.pickup_fees_cents if listing.pickup_fees_cents is not None else None
                routes.append(('pickup',total))
        else:
            reasons.append('pickup location/radius unconfirmed')
            routes.append(('pickup',None))
    if watch.delivery and listing.delivery is not False:
        total = listing.item_cents + listing.shipping_cents + listing.fees_cents if listing.shipping_cents is not None and listing.fees_cents is not None and listing.delivery is True else None
        routes.append(('delivery',total))
    if not routes:
        return Match('excluded','No eligible delivery or pickup route in the selected areas.')
    if watch.basis == 'item':
        # Unknown delivery/pickup eligibility still needs review even for item-only budgets.
        route = next((r for r,t in routes if r=='pickup' and pickup_possible or r=='delivery' and listing.delivery is True), '')
        total = listing.item_cents
        if not route: reasons.append('delivery or pickup availability unconfirmed')
    else:
        known = [(route,total) for route,total in routes if total is not None]
        route,total = min(known,key=lambda pair:pair[1]) if known else (routes[0][0],None)
        if total is not None and total > watch.max_cents and any(t is None for _,t in routes) and listing.item_cents <= watch.max_cents:
            route,total = next((r,t) for r,t in routes if t is None)
        if total is None: reasons.append('shipping, fees or route not fully known')
    if total is not None and total > watch.max_cents:
        return Match('over-budget',f'Known {route} total is above your budget.',total,route)
    if total is None and listing.item_cents > watch.max_cents:
        return Match('over-budget','Item price alone exceeds your budget.',None,route)
    evidence = f'Title matches {name}; platform {listing.platform}; disc {listing.physical}; {route}.'
    if reasons:
        return Match('candidate',evidence + ' Review: ' + '; '.join(dict.fromkeys(reasons)) + '.',total,route)
    availability_note='Availability was marked confirmed during manual review.' if listing.availability=='confirmed' else 'Availability is source-reported or unverified, not independently confirmed.'
    return Match('qualified',evidence + f' Price within budget. {availability_note}',total,route)
