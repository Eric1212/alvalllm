#!/usr/bin/env python3
"""
alvalllm — couplage opencode ↔ AA (Intelligence Index)
=======================================================
Couple la liste des modèles opencode (breadcrumb) avec les II (Intelligence
Index) d'Artificial Analysis, puis génère data/models.json.

Méthode de couplage (validée avec Éric) :
  1. lowercase + suppression tirets/points
  2. Fusion des réglages d'effort (high/low/medium/xhigh/non-reasoning/
     reasoning/thinking/adaptive) -> même modèle, on prend le plus intelligent
  3. Suffixes de VARIANTE (flash/max/plus/mini/nano/pro/lite/small/large/
     turbo/ultra/code) -> doivent matcher exactement (modèles différents)
  4. Règle de date fine : si opencode a une date, ne coupler qu'avec AA sans
     date ou de même date ; sinon DROP
  5. DROP des modèles sans équivalent exact (pas de faux match)

Entrées (dans data/) :
  - OC_ZEN.json      : modèles OpenCode Zen (id, input, output, cache_read)
  - OC_GO.json       : modèles OpenCode Go (id, input, output, cache_read)
  - AA_II.json       : liste AA [{slug, ii, ...}]
Sortie : data/models.json au format attendu par base_charger()
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

# Suffixes de RÉGLAGE d'effort : mêmes variantes d'un même modèle. Pour AA,
# chaque variante a son propre II ; la famille est désignée par sa variante
# au II maximum (en pratique : le slug sans suffixe).
FUSION = [
    "non-reasoning", "nonreasoning", "highspeed", "reasoning",
    "thinking", "high", "low", "medium", "xhigh", "adaptive",
    "instruct", "it", "preview",
]

# Suffixes de VARIANTE de modèle : modèles distincts, ne PAS fusionner.
# (absent : on n'utilise pas de liste à retirer, juste on ne les fusionne pas)


def strip_reglages(slug: str) -> str:
    """Retire les suffixes de réglage d'effort pour obtenir le nom de base
    d'une famille (ex. 'claude-opus-5-xhigh' -> 'claude-opus-5')."""
    s = slug.lower()
    changed = True
    while changed:
        changed = False
        for suf in sorted(FUSION, key=len, reverse=True):
            if s.endswith("-" + suf):
                s = s[: -(len(suf) + 1)]
                changed = True
    return s


def strip_date_full(s: str) -> str:
    """Retire une date de version en fin de slug, tous formats :
    - 4-8 chiffres en fin (ex. 'deepseek-v4-pro-0424')
    - segment -MM-YY (ex. 'grok-build-0-1-06-16')
    AA ne collecte pas les dates : on les retire pour rattacher la famille
    à sa base (ex. grok-build-0-1-06-16 -> grok-build-0-1)."""
    s = re.sub(r"[0-9]{4,8}$", "", s)
    s = re.sub(r"-\d{2}-\d{2}$", "", s)
    return s.rstrip("-")


def tokens_multiset(slug: str) -> Counter:
    """Compte des tokens (mots séparés par - . ou espaces), en gardant les
    doublons. Sert au match 'multiset égal' : mêmes tokens, ordre différent
    (ex. 'claude-4-5-sonnet' vs 'claude-sonnet-4-5')."""
    return Counter(re.sub(r"[^a-z0-9]", " ", slug.lower()).split())


def norm_oc(slug: str) -> str:
    """Normalise un nom opencode en retirant les attributs que AA ne
    collecte pas : taille (-XXb), suffixe (-instruct/-it) et dates, en fin
    de slug, jusqu'à stabilité.
    Ex. 'llama-4-maverick-17b-instruct' -> 'llama-4-maverick'."""
    s = slug.lower()
    changed = True
    while changed:
        changed = False
        for pat in (r"-\d+b$", r"-(instruct|it)$"):
            if re.search(pat, s):
                s = re.sub(pat, "", s)
                changed = True
        s2 = strip_date_full(s)
        if s2 != s:
            s = s2
            changed = True
    return s


def canon(slug: str) -> str:
    """Normalise un slug : lowercase, retire tirets/points, fusionne les
    réglages d'effort."""
    s = slug.lower()
    changed = True
    while changed:
        changed = False
        for suf in sorted(FUSION, key=len, reverse=True):
            if s.endswith("-" + suf) or s.endswith("." + suf):
                s = s[: -(len(suf) + 1)]
                changed = True
            elif s.endswith(suf):
                s = s[: len(s) - len(suf)]
                changed = True
    return re.sub(r"[\-\. ]", "", s)


def canon_aa(slug: str, lab: str) -> str:
    """Canon d'un slug AA, en retirant le préfixe lab s'il est redondant
    avec le lab opencode (ex. AA 'nvidia-nemotron-...' vs opencode
    'nvidia/nemotron-...')."""
    s = slug.lower()
    if lab and s.startswith(lab + "-"):
        s = s[len(lab) + 1:]
    return canon(s)


def strip_date(s: str) -> str:
    """Retire une date (4 ou 6-8 chiffres) en fin de slug."""
    return re.sub(r"[0-9]{4,8}$", "", s)


def strip_ver(s: str) -> str:
    """Retire un numéro de version en fin de slug (ex. -1-0, -2-5)."""
    return re.sub(r"[-\.]\d+[-\.]\d+$", "", s)


def strip_ver_latest(s: str) -> str:
    """Retire une version en fin de slug, y compris -d simple (ex. -4, -2).
    Utilisé UNIQUEMENT pour la règle '-latest' (famille complète), car
    fusionner les générations ailleurs crée des faux matchs."""
    s = re.sub(r"[-\.]\d+[-\.]\d+$", "", s)
    s = re.sub(r"[-\.]\d+$", "", s)
    return s


def has_version(s: str) -> bool:
    """Vrai si le slug porte un numéro de version type -d-d en fin."""
    return bool(re.search(r"[-\.]\d+[-\.]\d+$", s))


def get_date(s: str):
    """Extrait la date de version en fin de slug, sinon None."""
    m = re.search(r"([0-9]{6}|[0-9]{4})$", s)
    return m.group(1) if m else None


def charger_opencode() -> list:
    """Lit OC_ZEN.json et OC_GO.json et retourne la liste des modèles
    avec leurs prix (input, output, cache_read)."""
    out = []
    for fname in ("OC_ZEN.json", "OC_GO.json"):
        path = DATA / fname
        if not path.exists():
            continue
        for m in json.loads(path.read_text()):
            out.append({
                "nom": m["id"],
                "input": m.get("input"),
                "output": m.get("output"),
                "cache_read": m.get("cache_read"),
            })
    return out


def charger_labs() -> dict:
    """Récupère le mapping modèle -> lab depuis OC_LABS.json.
    Matching case-insensitive sur le slug."""
    path = DATA / "OC_LABS.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    # Normaliser en lowercase pour matching case-insensitive
    return {k.lower(): v for k, v in data.get("par_slug", {}).items()}
    time.sleep(2)
    html = subprocess.run(["ffsr", "get", "html", "9"], 
                          capture_output=True, text=True, timeout=30).stdout
    
    # Extraire les labs du breadcrumb (select labs)
    lab_matches = re.findall(r'<option[^>]*value="([a-z0-9-]+)"[^>]*>', html)
    labs = [l for l in lab_matches if "/" not in l and len(l) > 1]
    labs = list(dict.fromkeys(labs))  # dédoublonner en gardant l'ordre
    
    print(f"  {len(labs)} labs trouvés")
    
    # 2. Pour chaque lab, récupérer ses modèles
    labs_map = {}
    for i, lab in enumerate(labs):
        url = f"https://opencode.ai/fr/data/{lab}"
        subprocess.run(["ffsr", "go", "9", url, "w"], check=True, stdout=subprocess.DEVNULL)
        time.sleep(1)
        html = subprocess.run(["ffsr", "get", "html", "9"], 
                              capture_output=True, text=True, timeout=30).stdout
        
        # Extraire les modèles du tableau lab-model-table-track
        rows = re.findall(
            r'data-component="lab-model-row" href="/fr/data/[a-z0-9-]+/([^"]+)"[^>]*role="row"[^>]*>(.*?)</a>',
            html, re.S,
        )
        for slug, body in rows:
            # Extraire le nom affiché (dans <strong>)
            m = re.search(r"<strong>(.*?)</strong>", body)
            name = m.group(1) if m else slug
            if slug not in labs_map:
                labs_map[slug] = lab
    
    # Sauvegarder pour cache
    lines = [f"{lab}/{slug}" for slug, lab in labs_map.items()]
    labs_file.write_text("\n".join(lines))
    print(f"  {len(labs_map)} modèles mappés, cache écrit")
    
    return labs_map


def charger_aa(labs: dict = None) -> list:
    """Charge les modèles AA et les regroupe en FAMILLES.

    Une famille = même nom de base (suffixes de réglage d'effort ignorés,
    ex. claude-opus-5 / claude-opus-5-xhigh / -high / -medium / -low).
    La famille est désignée par sa variante au II maximum : son slug devient
    le slug de la famille, et le II de la famille est ce II maximum.

    labs (optionnel) : non utilisé ici — le retrait du préfixe lab superflu
    (nvidia-nemotron-...) se fait côté couplage, avec le contexte opencode.

    Retourne une liste de familles au même format qu'avant :
        [{"slug": <basename>, "ii": <max_ii>, ...}]
    pour que le couplage traite chaque famille comme un modèle AA.
    """
    familles = {}
    for a in json.loads((DATA / "AA_II.json").read_text()):
        base = strip_reglages(a["slug"])
        base = strip_date_full(base)
        # Attributs de taille : MoE (-550b-a55b) et taille simple (-27b).
        # AA route vers le plus gros modèle inféré ; le nom sans taille désigne
        # la même famille (nemotron-3-ultra-550b-a55b == nemotron-3-ultra).
        base = re.sub(r"-\d+b-a\d+b$", "", base)
        base = re.sub(r"-\d+b$", "", base)
        f = familles.setdefault(base, {"slug": base, "ii": -1})
        if a["ii"] is not None and a["ii"] > f["ii"]:
            f["slug"] = base
            f["ii"] = a["ii"]
    # Seules les familles avec un II réel (ii>0) sont candidates au match.
    # Les familles sans II (null chez AA) restent à -1 -> exclues, sinon
    # elles matcheraient des OC mais avec ii=-1 (absurde).
    return [f for f in familles.values() if f["ii"] > 0]


def coupler(oc: list, aa: list, labs: dict) -> list:
    # Index AA par canon (sans date)
    aa_idx = {}
    for a in aa:
        c = strip_date(canon(a["slug"]))
        aa_idx.setdefault(c, []).append(a)

    # Index AA par canon simple (pour la règle norm_oc)
    aa_idx_norm = {}
    for a in aa:
        aa_idx_norm.setdefault(canon(a["slug"]), []).append(a)

    # Index AA des modèles NON versionnés, uniques par famille.
    # Sert à l'"indulgence version" : si AA n'a qu'un seul modèle sans
    # numéro de version pour une famille, on accepte un opencode versionné.
    from collections import defaultdict
    bybase = defaultdict(list)
    for a in aa:
        if not has_version(a["slug"]):
            bybase[canon(strip_ver(a["slug"]))].append(a)
    base_only = {c: lst[0] for c, lst in bybase.items() if len(lst) == 1}

    rows = []

    # 2 passes : d'abord tous les matchs directs, ensuite les fallbacks
    # (le min lab n'est stable qu'une fois tous les directs couplés).
    pendings = []
    for modele in oc:
        c = strip_date(canon(modele["nom"]))
        if c in aa_idx:
            cands = aa_idx[c]
            oc_date = get_date(modele["nom"])
            if oc_date:
                ok = [a for a in cands
                      if not get_date(a["slug"]) or get_date(a["slug"]) == oc_date]
                if not ok:
                    continue  # date différente -> DROP
                cands = ok
            best = max(cands, key=lambda a: a["ii"])
            rows.append({
                "nom": modele["nom"],
                "ii": best["ii"],
                "aa_slug": best["slug"],
                "input": modele.get("input"),
                "output": modele.get("output"),
                "cache_read": modele.get("cache_read"),
            })
            continue

        # Handle -free suffix: try matching base model (without -free) in AA
        if modele["nom"].endswith("-free"):
            c_base = strip_date(canon(modele["nom"][:-5]))
            if c_base in aa_idx:
                cands = aa_idx[c_base]
                oc_date = get_date(modele["nom"])
                if oc_date:
                    ok = [a for a in cands
                          if not get_date(a["slug"]) or get_date(a["slug"]) == oc_date]
                    if not ok:
                        continue
                    cands = ok
                best = max(cands, key=lambda a: a["ii"])
                rows.append({
                    "nom": modele["nom"],
                    "ii": best["ii"],
                    "aa_slug": best["slug"],
                    "input": modele.get("input"),
                    "output": modele.get("output"),
                    "cache_read": modele.get("cache_read"),
                })
                continue

        # Indulgence version : AA a un seul modèle non-versionné pour la

        # Multiset égal : mêmes tokens dans un ordre différent (ex. AA
        # 'claude-4-5-sonnet' vs opencode 'claude-sonnet-4-5').
        # Sûr car le Counter garde les doublons (gpt-5 != gpt-5-5).
        # La date est retirée avant (claude-haiku-4-5-20251001 ==
        # claude-4-5-haiku).
        mt = tokens_multiset(strip_date(modele["nom"]))
        cands = [a for a in aa if tokens_multiset(strip_date(a["slug"])) == mt]
        if cands:
            best = max(cands, key=lambda a: a["ii"])
            rows.append({
                "nom": modele["nom"],
                "ii": best["ii"],
                "aa_slug": best["slug"],
                "input": modele.get("input"),
                "output": modele.get("output"),
                "cache_read": modele.get("cache_read"),
            })
            continue

        # Attributs retirés (norm_oc) : opencode ajoute taille (-XXb),
        # suffixe (-instruct/-it) et dates que AA ne collecte pas.
        c = canon(norm_oc(modele["nom"]))
        if c in aa_idx_norm:
            best = max(aa_idx_norm[c], key=lambda a: a["ii"])
            rows.append({
                "nom": modele["nom"],
                "ii": best["ii"],
                "aa_slug": best["slug"],
                "input": modele.get("input"),
                "output": modele.get("output"),
                "cache_read": modele.get("cache_read"),
            })
            continue

        # Préfixe lab AA superflu : opencode 'nemotron-3-ultra-free' (lab
        # nvidia, nom sans lab) vs AA 'nvidia-nemotron-3-ultra-550b-a55b'
        # (nom avec préfixe lab). On retire le préfixe lab AA pour tenter
        # un match, sur tous les labs connus du mapping OC_LABS.
        # NB: le suffixe -free est retiré ici (routage gratuit) pour que
        # 'nemotron-3-ultra-free' se couple à 'nvidia-nemotron-3-ultra'.
        nom_base = re.sub(r"-free$", "", modele["nom"])
        matched_lab = False
        for lab in set(labs.values()):
            if nom_base.lower().startswith(lab + "-"):
                continue  # le modèle porte déjà le lab dans son nom
            c_nolab = canon(norm_oc(nom_base))
            cands = [a for a in aa
                     if canon(norm_oc(a["slug"].replace(lab + "-", ""))) == c_nolab]
            if cands:
                best = max(cands, key=lambda a: a["ii"])
                rows.append({
                    "nom": modele["nom"],
                    "ii": best["ii"],
                    "aa_slug": best["slug"],
                    "input": modele.get("input"),
                    "output": modele.get("output"),
                    "cache_read": modele.get("cache_read"),
                })
                matched_lab = True
                break
        if matched_lab:
            continue

        # -latest : opencode 'X-latest' = la meilleure version dispo de la
        # famille X -> on prend le max II de la famille chez AA. Le strip
        # de version élargi (-d simple) est utilisé ICI uniquement, c'est
        # sûr car 'latest' désigne explicitement la famille complète.
        if modele["nom"].endswith("-latest"):
            base = canon(strip_ver_latest(norm_oc(modele["nom"][:-7])))
            cands = [a for a in aa if canon(strip_ver_latest(norm_oc(a["slug"]))) == base]
            if cands:
                best = max(cands, key=lambda a: a["ii"])
                rows.append({
                    "nom": modele["nom"],
                    "ii": best["ii"],
                    "aa_slug": best["slug"],
                    "input": modele.get("input"),
                    "output": modele.get("output"),
                    "cache_read": modele.get("cache_read"),
                })
            continue

        # -pro (openai uniquement) : 'gpt-5.5-pro' = gpt-5.5 avec plus de
        # compute ("think harder"), même modèle -> on trime -pro et on
        # couple avec la famille AA (ex. gpt-5-5 II 56.31).
        # Conditionnel au lab openai : ne PAS trimmer les -pro d'autres
        # labs (gemini-3.1-pro-preview, mimo-v2.5-pro, deepseek-v4-pro...).
        if modele["nom"].endswith("-pro"):
            # Check lab case-insensitive
            lab = labs.get(modele["nom"].lower(), "")
            if lab == "openai":
                c = canon(modele["nom"][:-4])
                if c in aa_idx_norm:
                    best = max(aa_idx_norm[c], key=lambda a: a["ii"])
                    rows.append({
                        "nom": modele["nom"],
                        "ii": best["ii"],
                        "aa_slug": best["slug"],
                        "input": modele.get("input"),
                        "output": modele.get("output"),
                        "cache_read": modele.get("cache_read"),
                    })
            continue

        # Pas de match direct -> on le garde pour la passe fallback
        pendings.append(modele)

    # Passe 2 : fallback (min du lab, sinon min global) — appliqué sur
    # tous les pendings une fois les directs couplés, min stable.
    for modele in pendings:
        fb = fallback_ii(rows, modele, labs)
        rows.append({
            "nom": modele["nom"],
            "ii": fb,
            "aa_slug": "",
            "input": modele.get("input"),
            "output": modele.get("output"),
            "cache_read": modele.get("cache_read"),
        })
    return rows


def fallback_ii(rows: list, modele: dict, labs: dict) -> float:
    """II de repli pour un modèle non couplé : le plus petit II des modèles
    déjà couplés du MÊME lab (anti-contamination : on ne met jamais un II
    plus élevé que le minimum du lab). Si le lab est inconnu ou n'a aucun
    couplé, fallback sur le minimum GLOBAL des couplés.
    Retourne -1 si aucun couplé valide (ii>0)."""
    nom = modele["nom"]
    lab = labs.get(nom.lower(), "") or (
        labs.get(nom.lower()[:-5], "") if nom.lower().endswith("-free") else "")
    valides = [r["ii"] for r in rows if r["ii"] > 0]
    if lab:
        lab_iis = [r["ii"] for r in rows
                   if r["ii"] > 0 and (labs.get(r["nom"].lower(), "") == lab)]
        if lab_iis:
            return min(lab_iis)
    return min(valides) if valides else -1


def main():
    oc = charger_opencode()
    labs = charger_labs()
    aa = charger_aa(labs)
    rows = coupler(oc, aa, labs)
    rows.sort(key=lambda r: -r["ii"])

    # Deduplicate: keep only the highest II match for each unique model name
    seen = set()
    modeles = []
    for r in rows:
        nom_lower = r["nom"].lower()
        if nom_lower in seen:
            continue
        seen.add(nom_lower)
        
        lab = ""
        # Direct match
        lab = labs.get(nom_lower, "")
        # If model ends with -free, try without -free suffix
        if not lab and nom_lower.endswith("-free"):
            lab = labs.get(nom_lower[:-5], "")
        modeles.append({
            "nom": r["nom"],
            "lab": lab,
            "ii": r["ii"],
            "prix_in": r.get("input", 0),
            "prix_out": r.get("output", 0),
            "prix_cache": r.get("cache_read", 0),
            # Gratuit si le prix est 0 OU si le slug contient "free"
            # (les -free opencode : gratuit même en gardant le prix de base)
            "gratuit": 1 if r.get("input", 0) == 0 or "free" in r["nom"].lower() else 0,
            "frontier": 0,
        })

    out = {"modeles": modeles, "_source": "opencode+AA", "ii_from": "aa"}
    (DATA / "models.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"Couplage: {len(rows)} modèles opencode ↔ II AA")
    print(f"Écrit data/models.json ({len(modeles)} modèles)")
    return 0


if __name__ == "__main__":
    sys.exit(main())