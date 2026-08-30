
from __future__ import annotations
import os, json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from base64 import b64encode
from collections import defaultdict

ALLOWED_ASPECTS={"Conjunction","Sextile","Square","Trine","Opposition"}
ALLOWED_BODIES={"Sun","Moon","Mercury","Venus","Mars","Jupiter","Saturn"}

def _request(url, payload, user_id, api_key, *, use_basic_auth):
    if use_basic_auth:
        credentials = b64encode(f"{user_id}:{api_key}".encode("utf-8")).decode("ascii")
        body = urlencode(payload).encode("utf-8")
        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
    else:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "x-astrologyapi-key": api_key,
        }

    req = Request(url, data=body, headers=headers, method="POST")
    with urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post_json(url, payload, user_id, api_key):
    """Use the auth/body contract that matches the configured credentials."""
    use_basic_auth = bool(user_id)
    try:
        return _request(
            url,
            payload,
            user_id,
            api_key,
            use_basic_auth=use_basic_auth,
        )
    except HTTPError as exc:
        # A stale User ID may remain configured beside a wallet access token.
        # Retry once with token auth before surfacing the provider failure.
        if use_basic_auth and exc.code in {401, 403, 405}:
            try:
                return _request(
                    url,
                    payload,
                    user_id,
                    api_key,
                    use_basic_auth=False,
                )
            except HTTPError as retry_exc:
                exc = retry_exc

        try:
            detail = exc.read().decode("utf-8", errors="replace").strip()
        except Exception:
            detail = ""
        message = f"AstrologyAPI POST failed with HTTP {exc.code}"
        if detail:
            message += f": {detail[:500]}"
        raise RuntimeError(message) from exc


def _creds(config):
    base = os.environ.get(config["provider"]["base_url_env"], "").rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]
    user_id_env = config["provider"].get("user_id_env", "")
    user_id = os.environ.get(user_id_env, "").strip() if user_id_env else ""
    key = os.environ.get(config["provider"]["api_key_env"], "")
    if not (base and key):
        raise RuntimeError("Live provider credentials not configured.")
    return base, user_id, key

def _base_payload(intake, hour, minute=0):
    year,month,day=map(int,intake["birth_date"].split("-"))
    return {
        "day":day,"month":month,"year":year,"hour":hour,"min":minute,
        "lat":intake["latitude"],"lon":intake["longitude"],"tzone":intake["timezone_offset"],
        "house_type":"placidus"
    }

def fetch_full_bundle(intake: dict, config: dict) -> dict:
    base,uid,key=_creds(config)
    hour,minute=map(int,intake["birth_time"].split(":"))
    payload=_base_payload(intake,hour,minute)
    planets=_post_json(base+"/v1/planets/tropical",payload,uid,key)
    chart = _post_json(base+"/v1/western_chart_data", payload, uid, key)
    wheel = _post_json(base+"/v1/natal_wheel_chart", payload, uid, key)
    planets_list=planets if isinstance(planets,list) else planets.get("planets",planets.get("data",[]))
    return {
        "planets":planets_list,
        "houses":chart.get("houses",[]),
        "aspects":chart.get("aspects",[]),
        "ascendant":chart.get("ascendant"),
        "midheaven":chart.get("midheaven"),
        "chart_url":wheel.get("chart_url")
    }

def fetch_partial_stability_bundle(intake: dict, config: dict) -> dict:
    """Unknown-time conservative strategy.

    Samples 00:00, 06:00, 12:00, and 18:00 local time.
    A planet is retained only if its sign is identical across every sample.
    An aspect is retained only if body pair + type exists in every sample and
    its orb range is <= configured partial max_orb_range_deg (default 1.5°).
    Rising, houses, Midheaven, and chart wheel are never returned.
    """
    base,uid,key=_creds(config)
    samples=config.get("partial_stability",{}).get("sample_hours",[0,6,12,18])
    max_orb_range=float(config.get("partial_stability",{}).get("max_orb_range_deg",1.5))
    planet_samples=[]; aspect_samples=[]
    for hr in samples:
        payload=_base_payload(intake,int(hr),0)
        planets=_post_json(base+"/v1/planets/tropical",payload,uid,key)
        chart=_post_json(base+"/western_chart_data",payload,uid,key)
        plist=planets if isinstance(planets,list) else planets.get("planets",planets.get("data",[]))
        planet_samples.append({p.get("name"):p for p in plist if p.get("name") in ALLOWED_BODIES})
        amap={}
        for a in chart.get("aspects",[]):
            b1=a.get("aspecting_planet"); b2=a.get("aspected_planet"); typ=a.get("type")
            if b1 in ALLOWED_BODIES and b2 in ALLOWED_BODIES and typ in ALLOWED_ASPECTS:
                key2=tuple(sorted([b1,b2]))+(typ,)
                amap[key2]=a
        aspect_samples.append(amap)
    stable_planets=[]
    for body in ALLOWED_BODIES:
        vals=[s.get(body) for s in planet_samples]
        if not all(vals): continue
        signs={v.get("sign") for v in vals}
        if len(signs)==1:
            rep=dict(vals[len(vals)//2])
            rep["house"]=None
            stable_planets.append(rep)
    stable_aspects=[]
    common=set.intersection(*(set(x.keys()) for x in aspect_samples)) if aspect_samples else set()
    for key2 in common:
        vals=[x[key2] for x in aspect_samples]
        orbs=[float(v.get("orb")) for v in vals if v.get("orb") is not None]
        if len(orbs)!=len(vals): continue
        if max(orbs)-min(orbs)<=max_orb_range:
            rep=dict(vals[len(vals)//2])
            rep["orb"]=round(sum(orbs)/len(orbs),2)
            stable_aspects.append(rep)
    return {
        "planets":stable_planets,
        "houses":[],
        "aspects":stable_aspects,
        "ascendant":None,
        "midheaven":None,
        "chart_url":None,
        "partial_stability":{
            "sample_hours":samples,
            "stable_planets":[p.get("name") for p in stable_planets],
            "stable_aspect_count":len(stable_aspects),
            "max_orb_range_deg":max_orb_range
        }
    }

def fetch_live_bundle(intake: dict, config: dict) -> dict:
    if intake["birth_time_status"]=="KNOWN":
        return fetch_full_bundle(intake,config)
    return fetch_partial_stability_bundle(intake,config)
