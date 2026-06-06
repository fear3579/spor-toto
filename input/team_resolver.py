# -*- coding: utf-8 -*-
from config import *
import sys, re, io, os, json, math, time, warnings
from datetime import datetime
from difflib import SequenceMatcher
import requests
import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
warnings.filterwarnings("ignore")


NAME_MAP = {
    # ── Türkiye (T1) ─────────────────────────────────────────────
    "fenerbahce":              "Fenerbahce",
    "galatasaray":             "Galatasaray",
    "besiktas":                "Besiktas",
    "trabzonspor":             "Trabzonspor",
    "basaksehir":              "Istanbul Basaksehir",
    "istanbul basaksehir":     "Istanbul Basaksehir",
    "basaksehir fk":           "Istanbul Basaksehir",
    "karagumruk":              "Fatih Karagumruk",
    "fatih karagumruk":        "Fatih Karagumruk",
    "eyupspor":                "Eyupspor",
    "kasimpasa":               "Kasimpasa",
    "samsunspor":              "Samsunspor",
    "alanyaspor":              "Alanyaspor",
    "antalyaspor":             "Antalyaspor",
    "konyaspor":               "Konyaspor",
    "kocaelispor":             "Kocaelispor",
    "goztepe":                 "Goztepe",
    "rizespor":                "Caykur Rizespor",
    "caykur rizespor":         "Caykur Rizespor",
    "caykur rizespor as":      "Caykur Rizespor",
    "genclerbirligi":          "Genclerbirligi",
    "gaziantep":               "Gaziantep",
    "gaziantep fk":            "Gaziantep",
    "kayserispor":             "Kayserispor",
    # ── Bundesliga (D1) ──────────────────────────────────────────
    "dortmund":                "Dortmund",
    "borussia dortmund":       "Dortmund",
    "b. dortmund":             "Dortmund",
    "hoffenheim":              "Hoffenheim",
    "tsg hoffenheim":          "Hoffenheim",
    "bayern":                  "Bayern Munich",
    "leverkusen":              "Bayer Leverkusen",
    "frankfurt":               "Ein Frankfurt",
    "leipzig":                 "RB Leipzig",
    # ── Premier League (E0) ───────────────────────────────────────
    "man united":              "Man United",
    "manchester united":       "Man United",
    "man city":                "Man City",
    "manchester city":         "Man City",
    "chelsea":                 "Chelsea",
    "arsenal":                 "Arsenal",
    "liverpool":               "Liverpool",
    "everton":                 "Everton",
    "tottenham":               "Tottenham",
    "newcastle":               "Newcastle",
    "aston villa":             "Aston Villa",
    # ── Serie A (I1) ─────────────────────────────────────────────
    "napoli":                  "Napoli",
    "lazio":                   "Lazio",
    "as roma":                 "Roma",
    "roma":                    "Roma",
    "atalanta":                "Atalanta",
    "inter":                   "Inter",
    "milan":                   "AC Milan",
    "ac milan":                "AC Milan",
    "juventus":                "Juventus",
    "como":                    "Como",
    # ── Eredivisie (N1) ──────────────────────────────────────────
    "ajax":                    "Ajax",
    "psv":                     "PSV",
    "psv eindhoven":           "PSV",
    "feyenoord":               "Feyenoord",
    "az alkmaar":              "AZ",
    "az":                      "AZ",
    "fc utrecht":              "Utrecht",
    "utrecht":                 "Utrecht",
    "fc twente":               "Twente",
    "twente":                  "Twente",
    "go ahead eagles":         "Go Ahead Eagles",
    "almere city":             "Almere City",
    "nec nijmegen":            "NEC Nijmegen",
    "fortuna sittard":         "Fortuna Sittard",
    "sc heerenveen":           "Heerenveen",
    "heerenveen":              "Heerenveen",
    "pec zwolle":              "Zwolle",
    "rkc waalwijk":            "RKC Waalwijk",
    "sparta rotterdam":        "Sparta Rotterdam",
    "heracles":                "Heracles",
    "nac breda":               "NAC Breda",
    # ── Belgian Pro League (B1) ───────────────────────────────────
    "club brugge":             "Club Brugge",
    "anderlecht":              "Anderlecht",
    "rsc anderlecht":          "Anderlecht",
    "kaa gent":                "Gent",
    "gent":                    "Gent",
    "standard liege":          "Standard",
    "standard":                "Standard",
    "genk":                    "Genk",
    "racing genk":             "Genk",
    "oud heverlee leuven":     "OH Leuven",
    "oh leuven":               "OH Leuven",
    "union saint gilloise":    "Union SG",
    "union sg":                "Union SG",
    "beerschot":               "Beerschot",
    "cercle brugge":           "Cercle Brugge",
    "westerlo":                "Westerlo",
    "mechelen":                "Mechelen",
    "kv mechelen":             "Mechelen",
    "antwerp":                 "Antwerp",
    "royal antwerp":           "Antwerp",
    "sint truiden":            "Sint-Truiden",
    "kortrijk":                "Kortrijk",
    "kv kortrijk":             "Kortrijk",
    # ── Primeira Liga (P1) ────────────────────────────────────────
    "benfica":                 "Benfica",
    "sl benfica":              "Benfica",
    "porto":                   "Porto",
    "fc porto":                "Porto",
    "sporting cp":             "Sporting CP",
    "sporting":                "Sporting CP",
    "sporting clube de portugal": "Sporting CP",
    "braga":                   "Braga",
    "sc braga":                "Braga",
    "vitoria guimaraes":       "Vitoria Guimaraes",
    "rio ave":                 "Rio Ave",
    "moreirense":              "Moreirense",
    "famalicao":               "Famalicao",
    "casa pia":                "Casa Pia",
    "estrela amadora":         "Estrela Amadora",
    "boavista":                "Boavista",
    "gil vicente":             "Gil Vicente",
    # ── Greek Super League (G1) ───────────────────────────────────
    "olympiakos":              "Olympiakos",
    "paok":                    "PAOK",
    "panathinaikos":           "Panathinaikos",
    "aek athens":              "AEK Athens",
    "aek":                     "AEK Athens",
    "aris thessaloniki":       "Aris",
    "aris":                    "Aris",
    "atromitos":               "Atromitos",
    "volos":                   "Volos",
    "ofi crete":               "OFI Crete",
    # ── Scottish Premiership (SC0) ────────────────────────────────
    "celtic":                  "Celtic",
    "rangers":                 "Rangers",
    "hearts":                  "Hearts",
    "hibs":                    "Hibernian",
    "hibernian":               "Hibernian",
    "aberdeen":                "Aberdeen",
    "dundee":                  "Dundee",
    "motherwell":              "Motherwell",
    "st mirren":               "St Mirren",
    # ── Allsvenskan (SWE) ─────────────────────────────────────────
    "malmo":                   "Malmo FF",
    "malmo ff":                "Malmo FF",
    "malmoe":                  "Malmo FF",
    "aik":                     "AIK",
    "aik solna":               "AIK",
    "djurgarden":              "Djurgarden",
    "djurgardens":             "Djurgarden",
    "hacken":                  "Hacken",
    "if hacken":               "Hacken",
    "hammarby":                "Hammarby",
    "if elfsborg":             "Elfsborg",
    "elfsborg":                "Elfsborg",
    "sirius":                  "Sirius",
    "ik sirius":               "Sirius",
    "kalmar":                  "Kalmar FF",
    "kalmar ff":               "Kalmar FF",
    "goteborg":                "IFK Goteborg",
    "ifk goteborg":            "IFK Goteborg",
    "brage":                   "Brage",
    "vasalunds if":            "Vasalund",
    "mjallby":                 "Mjallby",
    "norrkoping":              "Norrkoping",
    "ifk norrkoping":          "Norrkoping",
    "bp fc":                   "BP",
    "brommapojkarna":          "BP",
    # ── Eliteserien (NOR) ─────────────────────────────────────────
    "bodo glimt":              "Bodo/Glimt",
    "bodo/glimt":              "Bodo/Glimt",
    "rosenborg":               "Rosenborg",
    "molde":                   "Molde",
    "viking":                  "Viking",
    "valerenga":               "Valerenga",
    "fredrikstad":             "Fredrikstad",
    "lillestrom":              "Lillestrom",
    "sk":                      None,  # çok genel — skip
    "haugesund":               "Haugesund",
    "odd":                     "Odd",
    "brann":                   "Brann",
    "sk brann":                "Brann",
    "stromsgodset":            "Stromsgodset",
    "sarpsborg":               "Sarpsborg 08",
    "sarpsborg 08":            "Sarpsborg 08",
    "stabaek":                 "Stabaek",
    "tromso":                  "Tromso",
    "kristiansund":            "Kristiansund",
    "aalesund":                "Aalesund",
    "ham kam":                 "Ham-Kam",
    "sandefjord":              "Sandefjord",
    "hk":                      None,  # skip
    # ── J1 League (JPN) ───────────────────────────────────────────
    "kawasaki":                "Kawasaki F",
    "kawasaki frontale":       "Kawasaki F",
    "kawasaki f":              "Kawasaki F",
    "gamba osaka":             "Gamba Osaka",
    "urawa red diamonds":      "Urawa Reds",
    "urawa reds":              "Urawa Reds",
    "urawa":                   "Urawa Reds",
    "vissel kobe":             "Vissel Kobe",
    "kashima antlers":         "Kashima",
    "kashima":                 "Kashima",
    "cerezo osaka":            "Cerezo Osaka",
    "cerezo":                  "Cerezo Osaka",
    "fc tokyo":                "FC Tokyo",
    "yokohama f marinos":      "Yokohama FM",
    "yokohama fm":             "Yokohama FM",
    "yokohama marinos":        "Yokohama FM",
    "nagoya grampus":          "Nagoya",
    "nagoya":                  "Nagoya",
    "sanfrecce hiroshima":     "Hiroshima",
    "hiroshima":               "Hiroshima",
    "kashiwa reysol":          "Kashiwa",
    "kashiwa":                 "Kashiwa",
    "consadole sapporo":       "Sapporo",
    "sapporo":                 "Sapporo",
    "avispa fukuoka":          "Fukuoka",
    "fukuoka":                 "Fukuoka",
    "shimizu s-pulse":         "Shimizu",
    "shimizu":                 "Shimizu",
    "jubilo iwata":            "Jubilo",
    "jubilo":                  "Jubilo",
    "vegalta sendai":          "Sendai",
    "sendai":                  "Sendai",
    "tokushima vortis":        "Tokushima",
    "albirex niigata":         "Niigata",
    "niigata":                 "Niigata",
    "machida zelvia":          "Machida",
    "kyoto sanga":             "Kyoto",
    "kyoto":                   "Kyoto",
    # ── Veikkausliiga (FIN) ───────────────────────────────────────
    "hjk helsinki":            "HJK",
    "hjk":                     "HJK",
    "haka":                    "Haka",
    "fc haka":                 "Haka",
    "inter turku":             "Inter Turku",
    "fc inter":                "Inter Turku",
    "ilves":                   "Ilves",
    "fc ilves":                "Ilves",
    "ktp":                     "KTP",
    "fc ktp":                  "KTP",
    "mariehamn":               "IFK Mariehamn",
    "ifk mariehamn":           "IFK Mariehamn",
    "ac oulu":                 "AC Oulu",
    "oulu":                    "AC Oulu",
    "gnistan":                 "Gnistan",
    "fc gnistan":              "Gnistan",
    "seinajoki":               "SJK",
    "sjk":                     "SJK",
    "kuopio":                  "KuPS",
    "kups":                    "KuPS",
    "lahti":                   "FC Lahti",
    "fc lahti":                "FC Lahti",
    # ── Swiss Super League (SWI) ──────────────────────────────────
    "young boys":              "Young Boys",
    "bsc young boys":          "Young Boys",
    "bsc yb":                  "Young Boys",
    "basel":                   "Basel",
    "fc basel":                "Basel",
    "servette":                "Servette",
    "lucerne":                 "Luzern",
    "fc luzern":               "Luzern",
    "zurich":                  "FC Zurich",
    "fc zurich":               "FC Zurich",
    "grasshopper":             "Grasshopper",
    "gc zurich":               "Grasshopper",
    "sion":                    "Sion",
    "fc sion":                 "Sion",
    "winterthur":              "Winterthur",
    "lugano":                  "Lugano",
    "fc lugano":               "Lugano",
    "lausanne sport":          "Lausanne",
    "lausanne":                "Lausanne",
    "st gallen":               "St Gallen",
    "fc st gallen":            "St Gallen",
    # ── Danish Superliga (DNK) ────────────────────────────────────
    "fc copenhagen":           "FC Copenhagen",
    "kobenhavn":               "FC Copenhagen",
    "fc midtjylland":          "Midtjylland",
    "midtjylland":             "Midtjylland",
    "brondby":                 "Brondby",
    "aab":                     "AAB",
    "aalborg bk":              "AAB",
    "odense bk":               "OB",
    "ob":                      "OB",
    "fc nordsjaelland":        "Nordsjaelland",
    "randers":                 "Randers FC",
    "silkeborg":               "Silkeborg",
    "viborg":                  "Viborg",
    "agf":                     "AGF",
    "horsens":                 "AC Horsens",
    # ── Russian Premier League (RUS) ──────────────────────────────
    "zenit":                   "Zenit",
    "cska moscow":             "CSKA Moscow",
    "cska":                    "CSKA Moscow",
    "spartak moscow":          "Spartak Moscow",
    "spartak":                 "Spartak Moscow",
    "lokomotiv moscow":        "Lokomotiv Moscow",
    "lokomotiv":               "Lokomotiv Moscow",
    "dinamo moscow":           "Dinamo Moscow",
    "krasnodar":               "Krasnodar",
    "fc krasnodar":            "Krasnodar",
    "rubin kazan":             "Rubin Kazan",
    "rubin":                   "Rubin Kazan",
    "ural":                    "Ural",
    "rostov":                  "Rostov",
    "fc rostov":               "Rostov",
    # ── Chinese Super League (CHN) ────────────────────────────────
    "shandong taishan":        "Shandong Taishan",
    "shandong":                "Shandong Taishan",
    "guangzhou city":          "Guangzhou City",
    "guangzhou":               "Guangzhou City",
    "wuhan three towns":       "Wuhan Three Towns",
    "wuhan":                   "Wuhan Three Towns",
    "shanghai port":           "Shanghai Port",
    "shanghai sipg":           "Shanghai Port",
    "beijing guoan":           "Beijing Guoan",
    "beijing":                 "Beijing Guoan",
    "shenzhen":                "Shenzhen",
    "tianjin teda":            "Tianjin Teda",
    "dalian pro":              "Dalian Pro",
    "dalian":                  "Dalian Pro",
    "chengdu rongcheng":       "Chengdu Rongcheng",
    "chengdu":                 "Chengdu Rongcheng",
    # ── Polish Ekstraklasa (POL) ──────────────────────────────────
    "legia warsaw":            "Legia",
    "legia":                   "Legia",
    "lech poznan":             "Lech Poznan",
    "lech":                    "Lech Poznan",
    "raków czestochowa":       "Rakow",
    "rakow":                   "Rakow",
    "wisla krakow":            "Wisla",
    "wisla":                   "Wisla",
    "jagiellonia":             "Jagiellonia",
    "slask wroclaw":           "Slask Wroclaw",
    "pogon szczecin":          "Pogon Szczecin",
    # ── Austrian Bundesliga (AUT) ─────────────────────────────────
    "salzburg":                "Red Bull Salzburg",
    "red bull salzburg":       "Red Bull Salzburg",
    "rb salzburg":             "Red Bull Salzburg",
    "rapid wien":              "Rapid Wien",
    "rapid vienna":            "Rapid Wien",
    "austria wien":            "Austria Wien",
    "austria vienna":          "Austria Wien",
    "lask":                    "LASK",
    "wolfsberg":               "Wolfsberg",
    "rheindorf altach":        "Altach",
    "altach":                  "Altach",
    "hartberg":                "Hartberg",
    "sturm graz":              "Sturm Graz",
    "sturm":                   "Sturm Graz",
}



def _normalize(name: str) -> str:
    """Kucuk harf + Turkce karakter temizligi. Android uyumlu."""
    s = name
    s = s.replace("\u0130", "I")
    s = s.replace("\u0131", "i")
    s = s.replace("\u011e", "G")
    s = s.replace("\u011f", "g")
    s = s.replace("\u015e", "S")
    s = s.replace("\u015f", "s")
    s = s.replace("\u00dc", "U")
    s = s.replace("\u00fc", "u")
    s = s.replace("\u00d6", "O")
    s = s.replace("\u00f6", "o")
    s = s.replace("\u00c7", "C")
    s = s.replace("\u00e7", "c")
    s = s.lower()
    s = s.replace("a.s.", "").replace("a.s", "").replace("f.k.", "")
    s = s.replace("f.k", "").replace(" fk", "").replace(".", " ")
    import re as _re
    s = _re.sub(r'\s+', ' ', s).strip()
    return s


def _fuzzy_match(query: str, candidates: list) -> str | None:
    """En yüksek benzerlik skoru olan aday döner."""
    q = _normalize(query)
    best, best_score = None, 0.0
    for c in candidates:
        score = SequenceMatcher(None, q, _normalize(c)).ratio()
        if score > best_score:
            best_score, best = score, c
    if best_score >= CFG["fuzzy_cutoff"]:
        return best
    return None


def resolve_team(name: str, fd_teams: list) -> str:
    """Spor Toto ismini → football-data ismine çevir."""
    key = _normalize(name)
    if key in NAME_MAP:
        mapped = NAME_MAP[key]
        return mapped if mapped is not None else name
    for k, v in NAME_MAP.items():
        if v is None:
            continue
        if k in key or key in k:
            return v
    match = _fuzzy_match(name, fd_teams)
    if match:
        return match
    return name


def guess_league(home: str, away: str) -> str:
    """
    Takım adından lig kodu tahmin et.
    Mevcut + yeni ligler: N1, B1, P1, G1, SC0,
    SWE, NOR, JPN, FIN, SWI, DNK, RUS, CHN, POL, AUT
    """
    turkish = {
        "fenerbahce", "galatasaray", "besiktas", "trabzonspor",
        "basaksehir", "karagumruk", "eyupspor", "samsunspor",
        "kocaelispor", "antalyaspor", "konyaspor", "kasimpasa",
        "alanyaspor", "gaziantep", "kayserispor", "goztepe",
        "rizespor", "genclerbirligi", "adana", "sivasspor",
        "ankaragucu", "umraniyespor", "istanbulspor",
    }
    german = {
        "dortmund", "hoffenheim", "leverkusen", "frankfurt",
        "leipzig", "stuttgart", "freiburg", "wolfsburg", "mainz",
        "hamburg", "union berlin", "st pauli", "monchengladbach",
        "augsburg", "werder", "heidenheim", "koln", "bochum",
    }
    italian = {
        "napoli", "lazio", "roma", "atalanta", "inter", "milan",
        "juventus", "fiorentina", "bologna", "torino", "como",
        "monza", "udinese", "genoa", "empoli", "lecce", "cagliari",
        "parma", "verona", "sassuolo", "cremonese", "pisa",
    }
    spanish = {
        "barcelona", "real madrid", "atletico", "sevilla", "valencia",
        "villarreal", "real sociedad", "athletic bilbao", "betis",
        "osasuna", "girona", "getafe", "alaves", "mallorca",
        "celta", "rayo", "espanol", "las palmas", "valladolid",
        "leganes", "real zaragoza",
    }
    french = {
        "paris sg", "psg", "marseille", "lyon", "monaco",
        "lille", "rennes", "nice", "lens", "strasbourg",
        "montpellier", "nantes", "toulouse", "reims", "brest",
        "saint etienne", "lorient", "metz", "clermont",
    }
    english = {
        "arsenal", "chelsea", "liverpool", "man city", "man united",
        "tottenham", "newcastle", "west ham", "aston villa",
        "everton", "brighton", "fulham", "brentford", "wolves",
        "crystal palace", "bournemouth", "nottingham", "burnley",
        "sheffield", "luton", "leeds", "leicester", "ipswich",
        "sunderland", "southampton", "watford", "middlesbrough",
    }
    dutch = {
        "ajax", "psv", "feyenoord", "az alkmaar", "utrecht",
        "twente", "vitesse", "heerenveen", "groningen",
        "go ahead eagles", "almere city", "nec nijmegen",
        "fortuna sittard", "sparta rotterdam", "heracles",
        "zwolle", "waalwijk", "nac breda",
    }
    belgian = {
        "club brugge", "anderlecht", "gent", "standard liege",
        "genk", "racing genk", "oh leuven", "union saint gilloise",
        "union sg", "beerschot", "cercle brugge", "westerlo",
        "mechelen", "antwerp", "sint truiden", "kortrijk",
    }
    portuguese = {
        "benfica", "porto", "sporting", "braga",
        "vitoria guimaraes", "boavista", "rio ave",
        "moreirense", "famalicao", "casa pia", "gil vicente",
        "estrela amadora",
    }
    greek = {
        "olympiakos", "paok", "panathinaikos", "aek",
        "aris", "atromitos", "volos", "ofi",
    }
    scottish = {
        "celtic", "rangers", "hearts", "hibernian", "hibs",
        "aberdeen", "dundee", "motherwell", "st mirren",
        "ross county", "livingston", "kilmarnock", "inverness",
    }
    swedish = {
        "malmo", "aik", "djurgarden", "hacken", "hammarby",
        "elfsborg", "sirius", "kalmar", "goteborg", "brage",
        "mjallby", "norrkoping", "bp", "brommapojkarna",
        "vasalund", "halmstad",
    }
    norwegian = {
        "bodo glimt", "bodo/glimt", "rosenborg", "molde",
        "viking", "valerenga", "fredrikstad", "lillestrom",
        "haugesund", "odd", "brann", "stromsgodset",
        "sarpsborg", "stabaek", "tromso", "kristiansund",
        "aalesund", "ham-kam", "sandefjord",
    }
    japanese = {
        "kawasaki", "gamba osaka", "urawa", "vissel kobe",
        "kashima", "cerezo", "fc tokyo", "yokohama",
        "nagoya", "hiroshima", "kashiwa", "sapporo",
        "fukuoka", "shimizu", "jubilo", "sendai",
        "niigata", "machida", "kyoto",
    }
    finnish = {
        "hjk", "haka", "inter turku", "ilves", "ktp",
        "mariehamn", "oulu", "gnistan", "sjk",
        "kups", "lahti",
    }
    swiss = {
        "young boys", "basel", "servette", "luzern",
        "fc zurich", "zurich", "grasshopper", "sion",
        "winterthur", "lugano", "lausanne", "st gallen",
    }
    danish = {
        "copenhagen", "kobenhavn", "midtjylland", "brondby",
        "aab", "aalborg", "odense", "ob",
        "nordsjaelland", "randers", "silkeborg", "viborg",
        "agf", "horsens",
    }
    russian = {
        "zenit", "cska", "spartak", "lokomotiv",
        "dinamo moscow", "krasnodar", "rubin", "ural",
        "rostov",
    }
    chinese = {
        "shandong", "guangzhou", "wuhan", "shanghai port",
        "beijing guoan", "shenzhen", "tianjin", "dalian",
        "chengdu",
    }
    polish = {
        "legia", "lech poznan", "rakow", "wisla",
        "jagiellonia", "slask", "pogon szczecin",
    }
    austrian = {
        "salzburg", "rapid wien", "austria wien", "lask",
        "wolfsberg", "altach", "hartberg", "sturm graz",
    }

    combo = _normalize(home + " " + away)

    # Öncelik sırası: spesifik → genel
    if any(t in combo for t in turkish):   return "T1"
    if any(t in combo for t in norwegian): return "NOR"
    if any(t in combo for t in japanese):  return "JPN"
    if any(t in combo for t in swedish):   return "SWE"
    if any(t in combo for t in finnish):   return "FIN"
    if any(t in combo for t in chinese):   return "CHN"
    if any(t in combo for t in russian):   return "RUS"
    if any(t in combo for t in danish):    return "DNK"
    if any(t in combo for t in swiss):     return "SWI"
    if any(t in combo for t in austrian):  return "AUT"
    if any(t in combo for t in polish):    return "POL"
    if any(t in combo for t in scottish):  return "SC0"
    if any(t in combo for t in greek):     return "G1"
    if any(t in combo for t in portuguese):return "P1"
    if any(t in combo for t in belgian):   return "B1"
    if any(t in combo for t in dutch):     return "N1"
    if any(t in combo for t in german):    return "D1"
    if any(t in combo for t in italian):   return "I1"
    if any(t in combo for t in spanish):   return "SP1"
    if any(t in combo for t in french):    return "F1"
    if any(t in combo for t in english):   return "E0"
    return "E0"  # fallback
