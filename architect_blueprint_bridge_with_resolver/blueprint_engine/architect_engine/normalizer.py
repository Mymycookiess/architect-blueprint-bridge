
from __future__ import annotations
import math
APPROVED_PLANETS = ["Sun","Moon","Mercury","Venus","Mars","Jupiter","Saturn"]
ALLOWED_ASPECTS = {"Conjunction","Sextile","Square","Trine","Opposition"}
SIGNS = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo","Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]

def sign_from_longitude(deg):
    return SIGNS[int((deg%360)//30)] if deg is not None else None
def norm_degree(deg):
    return round(deg%30,6) if deg is not None else None

def _valid_longitude(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and 0 <= value < 360

def _normalize_full_houses(raw_houses):
    houses=[]
    for h in raw_houses:
        house=h.get("house_id", h.get("house"))
        deg=h.get("start_degree", h.get("degree", h.get("start")))
        if isinstance(house, bool) or not isinstance(house, (int, float)) or int(house) != house:
            return [], False
        house=int(house)
        if not 1 <= house <= 12 or not _valid_longitude(deg):
            return [], False
        houses.append({
            "house":house,
            "sign":h.get("sign") or sign_from_longitude(deg),
            "cusp_absolute_longitude":deg,
            "cusp_degree":norm_degree(deg)
        })
    valid=len(houses)==12 and {h["house"] for h in houses}==set(range(1,13))
    return (sorted(houses,key=lambda h:h["house"]), True) if valid else ([], False)

def normalize_provider_bundle(raw: dict, intake: dict, record_id: str):
    mode = "FULL" if intake.get("birth_time_status")=="KNOWN" else "PARTIAL"
    planets = raw.get("planets", [])
    pmap = {p.get("name"):p for p in planets}
    placements={}
    for name in APPROVED_PLANETS:
        p=pmap.get(name)
        if p:
            placements[name.lower()] = {
                "name":name, "sign":p.get("sign"), "sign_id":p.get("sign_id"),
                "degree":p.get("norm_degree", p.get("normDegree")),
                "absolute_longitude":p.get("full_degree", p.get("fullDegree")),
                "house":p.get("house"),
                "retrograde":str(p.get("is_retro", p.get("isRetro"))).lower()=="true",
                "speed":p.get("speed")
            }
    houses=[]
    houses_valid=False
    if mode=="FULL":
        houses,houses_valid=_normalize_full_houses(raw.get("houses",[]))
    else:
        for h in raw.get("houses",[]):
            deg=h.get("degree", h.get("start"))
            houses.append({
                "house":h.get("house"),
                "sign":h.get("sign") or sign_from_longitude(deg),
                "cusp_absolute_longitude":deg,
                "cusp_degree":norm_degree(deg)
            })
    asc = raw.get("ascendant")
    mc = raw.get("midheaven")
    if mode=="FULL":
        asc=None
    if asc is None and houses_valid:
        h1=next((h for h in houses if h["house"]==1),None)
        if h1: asc=h1["cusp_absolute_longitude"]
    if mc is None and houses:
        h10=next((h for h in houses if h["house"]==10),None)
        if h10: mc=h10["cusp_absolute_longitude"]
    aspects=[]
    for a in raw.get("aspects",[]):
        typ=a.get("type")
        if typ in ALLOWED_ASPECTS:
            aspects.append({
                "body_a":a.get("aspecting_planet",a.get("body_a")),
                "body_b":a.get("aspected_planet",a.get("body_b")),
                "type":typ,
                "orb":a.get("orb"),
                "separation":a.get("diff",a.get("separation"))
            })
    full_chart_valid=mode!="FULL" or (houses_valid and asc is not None)
    availability = {
        "sun":"sun" in placements, "moon":"moon" in placements,
        "rising": mode=="FULL" and asc is not None,
        "houses": mode=="FULL" and houses_valid,
        "aspects": bool(aspects),
        "chart_wheel": bool(raw.get("chart_url") or raw.get("chart_wheel_reference"))
    }
    if mode=="PARTIAL":
        asc=None; mc=None; houses=[]
    lookup=[]
    if placements.get("sun",{}).get("sign"):
        lookup.append("sun_"+placements["sun"]["sign"].lower())
    if placements.get("moon",{}).get("sign"):
        lookup.append("moon_"+placements["moon"]["sign"].lower())
    if availability["rising"]:
        lookup.append("rising_"+sign_from_longitude(asc).lower())
    for p in ("mercury","venus","mars","jupiter","saturn"):
        sign=placements.get(p,{}).get("sign")
        if sign: lookup.append(f"planet_{p}_{sign.lower()}")
    for a in aspects:
        b1=(a.get("body_a") or "").lower()
        b2=(a.get("body_b") or "").lower()
        typ=(a.get("type") or "").lower()
        if b1 and b2 and typ:
            lookup.append(f"aspect_{b1}_{typ}_{b2}")
    lookup.append("mode_"+mode.lower())
    return {
        "record_schema_version":"architect_chart_record_v1",
        "record_id":record_id,
        "record_status":"VALID_FOR_TEST" if full_chart_valid else "REVIEW_REQUIRED",
        "customer":{
            "name":intake["customer_name"],"birth_date":intake["birth_date"],
            "birth_time_local":intake.get("birth_time"),
            "birth_time_status":intake["birth_time_status"],
            "birth_location_display":intake["birth_location"],
            "latitude":intake.get("latitude"),"longitude":intake.get("longitude"),
            "timezone_offset":intake.get("timezone_offset")
        },
        "calculation":{"mode":mode,"provider":"AstrologyAPI","zodiac":"tropical","house_system":"placidus","validation_status":"VALID" if full_chart_valid else "REVIEW_REQUIRED"},
        "availability":availability,
        "placements":placements,
        "angles":{
            "ascendant":{"absolute_longitude":asc,"sign":sign_from_longitude(asc),"degree":norm_degree(asc)},
            "midheaven":{"absolute_longitude":mc,"sign":sign_from_longitude(mc),"degree":norm_degree(mc)}
        },
        "houses":houses,
        "aspects":aspects,
        "chart_wheel_reference":raw.get("chart_url") or raw.get("chart_wheel_reference"),
        "lookup_keys":lookup,
        "qa":{"missing_required_fields":[] if full_chart_valid else ["houses","angles.ascendant"],"notes":["Normalized by reusable pipeline V1."]}
    }
