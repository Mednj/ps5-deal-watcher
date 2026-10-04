from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator

SOURCES = ('dealabs', 'leboncoin', 'vinted', 'easycash')
HOSTS = {'dealabs': {'www.dealabs.com', 'dealabs.com'},
         'leboncoin': {'www.leboncoin.fr', 'leboncoin.fr'},
         'vinted': {'www.vinted.fr', 'vinted.fr'},
         'easycash': {'bons-plans.easycash.fr', 'www.easycash.fr'}}
CENTRES = {'Lyon / Villeurbanne': (45.7640, 4.8357),
           'Mantes-la-Jolie / Magnanville / Mantes-la-Ville': (48.9900, 1.7160)}

def cents(value: str) -> int:
    try:
        number = Decimal(value.replace(',', '.').replace('€', '').replace(' ', '').replace('\u00a0', ''))
        if not number.is_finite() or number < 0 or number > 100000 or number.as_tuple().exponent < -2:
            raise ValueError('Use a non-negative EUR amount with at most two decimals.')
        return int(number * 100)
    except InvalidOperation as exc:
        raise ValueError('Invalid EUR amount.') from exc

def listing_url(source: str, url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in HOSTS.get(source, set()) or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError('Use an HTTPS listing URL on the selected source.')
    return url

class Watch(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    aliases: list[str] = Field(default_factory=list, max_length=20)
    edition: str = Field(default='', max_length=100)
    language: str = Field(default='', max_length=60)
    excluded: list[str] = Field(default_factory=list, max_length=30)
    max_cents: int = Field(ge=1, le=10000000)
    qualification: Literal['name-price', 'strict'] = 'name-price'
    basis: Literal['all-in', 'item'] = 'all-in'
    condition: Literal['any', 'new', 'used'] = 'any'
    sources: list[str] = Field(default_factory=lambda: list(SOURCES), min_length=1)
    delivery: bool = True
    pickup: bool = True
    centres: list[str] = Field(default_factory=lambda: list(CENTRES))
    radius_km: int = Field(default=25, ge=1, le=500)
    interval_minutes: int = Field(default=5, ge=5, le=10080)
    timezone: str = 'Europe/Paris'
    start_at: float | None = None
    end_at: float | None = None
    checking_start: str = '00:00'
    checking_end: str = '00:00'
    ps4_upgrade: bool = False
    bundles: bool = False
    notify_drops: bool = True
    active: bool = True

    @field_validator('name', 'edition', 'language')
    @classmethod
    def strip_text(cls, value):
        return value.strip()

    @field_validator('timezone')
    @classmethod
    def timezone_valid(cls, value):
        ZoneInfo(value)
        return value

    @field_validator('checking_start', 'checking_end')
    @classmethod
    def hours_valid(cls, value):
        datetime.strptime(value, '%H:%M')
        return value

    @model_validator(mode='after')
    def valid(self):
        if any(s not in SOURCES for s in self.sources):
            raise ValueError('Unknown source.')
        if not self.delivery and not self.pickup:
            raise ValueError('Choose delivery, pickup, or both.')
        if self.pickup and (not self.centres or any(c not in CENTRES for c in self.centres)):
            raise ValueError('Choose a supported pickup area.')
        if self.end_at is not None and self.start_at is not None and self.end_at <= self.start_at:
            raise ValueError('End must be after start.')
        if any(len(s) > 160 for s in self.aliases + self.excluded):
            raise ValueError('Alias or excluded term is too long.')
        return self

class Listing(BaseModel):
    source: Literal['dealabs', 'leboncoin', 'vinted', 'easycash']
    external_id: str = Field(min_length=1, max_length=250)
    url: str = Field(max_length=2000)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default='', max_length=15000)
    item_cents: int = Field(ge=0, le=10000000)
    shipping_cents: int | None = Field(default=None, ge=0, le=10000000)
    fees_cents: int | None = Field(default=None, ge=0, le=10000000)
    pickup_fees_cents: int | None = Field(default=None, ge=0, le=10000000)
    delivery: bool | None = None
    pickup: bool = False
    location: str = Field(default='', max_length=200)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    condition: Literal['new', 'used', 'unknown'] = 'unknown'
    platform: Literal['ps5', 'ps4-upgrade', 'other', 'unknown'] = 'unknown'
    physical: bool | None = None
    bundle: bool = False
    price_kind: Literal['exact', 'from', 'coupon', 'membership', 'trade-in', 'installment'] = 'exact'
    availability: Literal['confirmed', 'reported', 'unverified', 'unavailable'] = 'unverified'
    provenance: str = Field(default='manual entry', max_length=200)
    observed_at: float = 0
    image: str = ''

    @model_validator(mode='after')
    def valid(self):
        listing_url(self.source, self.url)
        if (self.lat is None) != (self.lon is None):
            raise ValueError('Provide both latitude and longitude.')
        return self
