#!/usr/bin/env python3
"""
alvalllm — collecte des modèles opencode (Zen/Go) depuis les sources OFFICIELLES
===============================================================================
Deux sources officielles OpenCode, récupérées via ffsr :

  1. Les LISTES de modèles :
       https://opencode.ai/zen/v1/models      (62 modèles)
       https://opencode.ai/zen/go/v1/models   (26 modèles)
     via ffsr go + bidi `JSON.stringify($json.text)` (viewer JSON).

  2. Les PRIX (docs officielles) :
       https://opencode.ai/docs/zen
       https://opencode.ai/docs/go
     via ffsr get txt (le tableau « MODÈLE | INPUT | OUTPUT | CACHED
     READ | CACHED WRITE » n'est pas dans le HTML source : il est
     hydraté par JS, seul innerText l'a). Le mapping nom->slug vient
     du tableau des endpoints (nom | id) présent dans le HTML source.

Champs générés par modèle (OC_ZEN.json / OC_GO.json) :
  - id, object, created, owned_by   (tel quel de l'endpoint)
  - input, output, cache_read       (prix $ / 1M tokens ; si 2 paliers
    (≤/> 200K ou 272K) on garde TOUJOURS le plus élevé)
  - cache_write                     : DROP (pas collecté)

NI urllib (voué à disparaître) NI curl — tout passe par ffsr.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
TAB = 9
ENDPOINTS = {
    "OC_ZEN.json": "https://opencode.ai/zen/v1/models",
    "OC_GO.json": "https://opencode.ai/zen/go/v1/models",
}
DOCS = {
    "OC_ZEN.json": "https://opencode.ai/docs/zen",
    "OC_GO.json": "https://opencode.ai/docs/go",
}
LAB_PAGE = "https://opencode.ai/fr/data/google/gemini-flash-latest"
AA_MODELS_URL = "https://artificialanalysis.ai/models"


def bidi(frame: dict, timeout: int = 30) -> dict:
    """Envoie un frame BiDi à ffsr et retourne la réponse parsée."""
    out = subprocess.run(["ffsr", "bidi", json.dumps(frame)],
                         capture_output=True, text=True, timeout=timeout)
    return json.loads(out.stdout)


def go(url: str, tab: int = TAB):
    subprocess.run(["ffsr", "go", str(tab), url, "w"], check=True,
                   stdout=subprocess.DEVNULL)


def find_tab_context(url_part: str, tab: int = TAB) -> str:
    """Trouve le contexte BiDi de l'onglet TAB via browsingContext.getTree.
    Retourne le contexte dont l'URL contient url_part (ex. 'zen/v1/models')."""
    r = bidi({"id": 2, "method": "browsingContext.getTree", "params": {}})

    def walk(contexts):
        for c in contexts:
            if url_part in c.get("url", ""):
                return c["context"]
            found = walk(c.get("children", []))
            if found:
                return found
        return None

    ctx = walk(r["result"]["contexts"])
    if not ctx:
        raise RuntimeError(f"contexte '{url_part}' introuvable dans getTree")
    return ctx


def fetch_official(url: str, tab: int = TAB, retries: int = 3) -> dict:
    """Récupère un endpoint JSON officiel : go -> getTree -> $json.text.
    Retourne {} si l'appel BiDi échoue (contexte instable)."""
    import time
    for attempt in range(retries):
        go(url, tab)
        time.sleep(1)
        try:
            ctx = find_tab_context("zen/" + ("go/" if "zen/go" in url else "") + "v1/models")
            r = bidi({
                "id": 2, "method": "script.evaluate",
                "params": {
                    "expression": "JSON.stringify($json.text)",
                    "target": {"context": ctx},
                    "awaitPromise": False, "resultOwnership": "none",
                },
            })
            value = r["result"]["result"]["value"]
            return json.loads(json.loads(value))
        except (KeyError, json.JSONDecodeError) as e:
            if attempt < retries - 1:
                print(f"  Tentative {attempt+1}/{retries} échouée pour {url}, retry...")
                time.sleep(2)
            else:
                print(f"AVERTISSEMENT: échec récupération {url} après {retries} tentatives - {e}")
    return {"object": "list", "data": []}


def get_txt(url: str, tab: int = TAB) -> str:
    """get txt via ffsr après navigation."""
    go(url, tab)
    out = subprocess.run(["ffsr", "get", "txt", str(tab)],
                         capture_output=True, text=True, timeout=60)
    return out.stdout


def get_html(tab: int = TAB) -> str:
    """get (outerHTML) via ffsr (onglet déjà navigué)."""
    out = subprocess.run(["ffsr", "get", "html", str(tab)],
                         capture_output=True, text=True, timeout=60)
    return out.stdout


def parse_endpoint_ids(html: str) -> dict:
    """Tableau des endpoints du HTML source : (nom | id) -> {nom_normalisé: id}."""
    pairs = re.findall(r"<tr><td>([^<]+)</td><td>([a-z0-9.\-]+)</td>"
                       r"<td><code[^>]*>https://opencode\.ai/zen/", html)
    return {norm_name(n): i for n, i in pairs}


def norm_name(s: str) -> str:
    """Normalise un nom affiché pour le matching :
    minuscule, retrait des parenthèses de palier, espaces et points ->
    tirets (claude-opus-4.8 == claude-opus-4-8 == 'Claude Opus 4.8')."""
    s = re.sub(r"\s*[≤<>]([^()]*)\)", "", s)   # "(≤ 272K tokens)" etc.
    s = re.sub(r"[^a-z0-9]", " ", s.lower())   # tout sauf alphanum -> espace
    s = re.sub(r"\s+", "-", s.strip())
    return s


def parse_prices(txt: str) -> dict:
    """Tableau de prix du get txt : {nom_normalisé: (input, output, cache)}.
    Si 2 paliers (≤/> 200K, 272K...) pour un même modèle, on garde le
    PLUS ÉLEVÉ (règle Éric)."""
    prices = {}
    in_table = False
    for line in txt.splitlines():
        if "MODÈLE" in line and "INPUT" in line and "OUTPUT" in line:
            in_table = True
            continue
        if not in_table:
            continue
        if "Rechargement" in line or "NOTE" in line:
            break
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 4 or not parts[0]:
            continue
        name, inp, out, cache = parts[0], parts[1], parts[2], parts[3]
        key = norm_name(name)
        val = (price(inp), price(out), price(cache))
        prev = prices.get(key)
        if prev is None:
            prices[key] = val
        else:
            # palier > (plus élevé) : on garde le max de chaque champ
            prices[key] = tuple(
                max(a, b) if a is not None and b is not None
                else (a if a is not None else b)
                for a, b in zip(prev, val))
    return prices


def price(s: str):
    """'$0.30' -> 0.3 ; 'Free' -> 0 ; '-' -> None."""
    if not s or s == "-":
        return None
    s = s.strip().lstrip("$").replace(",", ".")
    if s.lower() in ("free", "gratuit"):
        return 0.0
    try:
        return float(s)
    except ValueError:
        return None


def build_models(fname: str, base_prices: dict = None) -> list:
    """Construit la liste finale des modèles pour un fichier :
    ids officiels + prix docs (input/output/cache_read), drop cache_write.

    base_prices (optionnel) : mapping {id -> (input, output, cache_read)}
    des prix de base valides, fusionnés sur TOUS les fichiers. Sert au
    fallback des modèles '-free' : un -free sans prix dans son doc prend
    le prix de sa base même si celle-ci vit dans un autre fichier."""
    url = ENDPOINTS[fname]
    doc = DOCS[fname]

    data = fetch_official(url)
    mods = extract_official(data)

    # mapping nom->slug (tableau des endpoints du HTML)
    html = get_html(doc)
    name2id = parse_endpoint_ids(html)

    # prix (tableau du get txt)
    txt = get_txt(doc)
    prices = parse_prices(txt)

    # Build comprehensive price map from doc (includes both free and non-free models from the doc)
    doc_price_map = {}
    for mid, p in prices.items():
        if p and p[0] not in (None, 0.0):
            # Normalize the model id using name2id if needed
            key = mid
            if key in name2id:
                key = name2id[key]
            doc_price_map[key] = p

    # Also add base model prices from official endpoint data (mods) for models not in doc
    for m in mods:
        mid = m["id"]
        if m.get("input") not in (None, 0.0):
            doc_price_map[mid] = (m.get("input"), m.get("output"), m.get("cache_read"))

    out = []
    for m in mods:
        mid = m["id"]
        # retrouver le prix : d'abord via le mapping nom->id, sinon
        # en normalisant l'id directement
        key = None
        for n, i in name2id.items():
            if i == mid:
                key = n
                break
        if key is None:
            key = norm_name(mid)
        p = prices.get(key)
        # For -free models, try base model price first
        if mid.endswith("-free") and (p is None or p[0] in (None, 0.0)):
            base_id = mid[:-5]
            if base_id in doc_price_map:
                p = doc_price_map[base_id]
            elif base_prices and base_id in base_prices:
                p = base_prices[base_id]
            elif base_prices:
                # L'id brut (mimo-v2.5) peut différer de la clé normalisée
                # (mimo-v2-5) dans base_prices -> essayer la normalisation.
                nid = norm_name(base_id)
                if nid in base_prices:
                    p = base_prices[nid]
        # Fallback prices when not found in docs
        FALLBACK = {"input": 2.0, "output": 10.0, "cache_read": 0.5}
        if p is None:
            p = (FALLBACK["input"], FALLBACK["output"], FALLBACK["cache_read"])
        row = {
            "id": mid,
            "object": m.get("object"),
            "created": m.get("created"),
            "owned_by": m.get("owned_by"),
            "input": p[0] if p[0] not in (None, 0.0) else FALLBACK["input"],
            "output": p[1] if p[1] not in (None, 0.0) else FALLBACK["output"],
            "cache_read": p[2] if p[2] not in (None, 0.0) else FALLBACK["cache_read"],
        }
        out.append(row)
    return out


def extract_official(data: dict) -> list:
    """Endpoint officiel {object:list, data:[...]} : copie `data` TEL QUEL
    (tous les champs : id, object, created, owned_by...)."""
    return data.get("data", [])


def fetch_aa_html(url: str) -> str:
    """HTML complet d'une page AA via ffsr (onglet TAB)."""
    go(url)
    return get_html()


def _decode_rsc_blobs(html: str) -> list:
    """Blobs RSC de Next.js (self.__next_f.push) décodés en texte."""
    blobs = re.findall(r'self\.__next_f\.push\(\[1,\"(.*?)\"\]\)', html, re.S)
    return [b.encode("utf-8").decode("unicode_escape", errors="replace") for b in blobs]


def extract_aa_first_slugs(html: str) -> list:
    """Slugs des modèles présents dans le RSC de la page /models.
    Chaque \"shortName\": = un modèle -> slug = dernier \"slug\":\"X\" avant."""
    blobs = _decode_rsc_blobs(html)
    slugs = []
    for b in blobs:
        for pos in [m.start() for m in re.finditer(r'"shortName":', b)]:
            avant = b[max(0, pos - 300):pos]
            found = re.findall(r'"slug":"([a-zA-Z0-9.-]+)"', avant)
            if found:
                slugs.append(found[-1])
    # Dédoublonner, garder l'ordre
    return list(dict.fromkeys(slugs))


def extract_aa_models(html: str) -> list:
    """Extrait les modèles AA (slug + intelligenceIndex) d'une page de détail.
    Repère le blob RSC qui contient la base complète (>100 modèles) :
    chaque \"shortName\": = un modèle -> slug = dernier slug avant,
    ii = premier \"intelligenceIndex\":N après. Retourne [{slug, ii, url}]."""
    blobs = _decode_rsc_blobs(html)
    # Le blob avec le plus de modèles = la base complète
    best = max(blobs, key=lambda b: len(re.findall(r'"shortName":', b)))
    if len(re.findall(r'"shortName":', best)) < 100:
        raise RuntimeError(
            f"Page AA sans base complète ({len(re.findall(chr(34)+'shortName'+chr(34)+':', best))} modèles)")

    modeles = {}
    for pos in [m.start() for m in re.finditer(r'"shortName":', best)]:
        avant = best[max(0, pos - 300):pos]
        found = re.findall(r'"slug":"([a-zA-Z0-9.-]+)"', avant)
        if not found:
            continue
        slug = found[-1]
        apres = best[pos:pos + 2500]
        ii_m = re.search(r'"intelligenceIndex":([0-9.]+|null)', apres)
        ii = float(ii_m.group(1)) if ii_m and ii_m.group(1) != "null" else None
        if slug not in modeles:
            modeles[slug] = ii

    return [{"slug": s, "ii": ii, "url": f"/models/{s}"}
            for s, ii in sorted(modeles.items(),
                                key=lambda x: (-x[1] if x[1] is not None else 0.0))]


def collect_aa() -> None:
    """Récupère les II d'Artificial Analysis via ffsr et écrit data/AA_II.json.
    Stratégie auto-adaptative : on lit /models pour obtenir des slugs récents,
    puis on ouvre la page de détail du 1er slug (toute page de détail contient
    la base complète des 608 modèles dans son RSC)."""
    import time

    print("Collecte des II AA via ffsr (HTML)...")

    # 1. Page /models -> 28 slugs récents
    html = fetch_aa_html(AA_MODELS_URL)
    time.sleep(2)
    slugs = extract_aa_first_slugs(html)
    if not slugs:
        print("  AVERTISSEMENT: aucun slug trouvé sur /models, abandon.")
        return
    print(f"  {len(slugs)} modèles sur /models, premier: {slugs[0]}")

    # 2. Page de détail du premier slug -> base complète (608)
    detail_url = f"https://artificialanalysis.ai/models/{slugs[0]}"
    html_detail = fetch_aa_html(detail_url)
    time.sleep(2)
    modeles = extract_aa_models(html_detail)

    (DATA / "AA_II.json").write_text(
        json.dumps(modeles, ensure_ascii=False, indent=1))
    n_ii = sum(1 for m in modeles if m["ii"] is not None)
    n_null = len(modeles) - n_ii
    print(f"Écrit data/AA_II.json ({len(modeles)} modèles, {n_ii} avec II, {n_null} null)")


def collect_labs() -> None:
    """Récupère le mapping modèle -> lab via ffsr (breadcrumb + pages lab)
    et écrit data/OC_LABS.json.
    Format : {"labs": [...], "par_slug": {"slug": "lab"}, "noms": {"slug": "nom"}}
    """
    import time

    print("Collecte des labs via ffsr (HTML)...")

    # 1. Page modèle pour obtenir la liste des labs via le breadcrumb (HTML)
    go(LAB_PAGE)
    time.sleep(3)
    html = get_html()
    # Debug
    with open("/tmp/lab_page.html", "w") as f:
        f.write(html)
    print(f"  HTML récupéré: {len(html)} chars")

# Extraire les labs du select labs dans le breadcrumb (HTML)
    # Le select du lab a aria-label="Choose a lab" et size="30"
    # On extrait le select spécifique au lab (size="30"), puis ses options
    select_match = re.search(r'<select[^>]*size="30"[^>]*>(.*?)</select>', html, re.S)
    if select_match:
        select_html = select_match.group(1)
        labs = re.findall(r'<option[^>]*value="([a-z0-9-]+)"[^>]*>', select_html)
    else:
        # Fallback: chercher le select avec aria-label="Choose a lab"
        lab_select_match = re.search(r'aria-label="Choose a lab"[^<]*<select[^>]*>(.*?)</select>', html, re.S)
        if lab_select_match:
            labs = re.findall(r'<option[^>]*value="([a-z0-9-]+)"[^>]*>', lab_select_match.group(1))
        else:
            # Fallback final
            labs = re.findall(r'<option[^>]*value="([a-z0-9-]+)"[^>]*>', html)

    labs = [l for l in labs if "/" not in l]
    labs = list(dict.fromkeys(labs))  # dédoublonner, garder l'ordre

    print(f"  {len(labs)} labs trouvés: {', '.join(labs)}")

    # Mapping nom affiché -> slug (via le tableau des endpoints dans docs/zen)
    go("https://opencode.ai/docs/zen")
    time.sleep(1)
    html_doc = get_html()
    name2id = parse_endpoint_ids(html_doc)

    par_slug = {}
    noms = {}

    for i, lab in enumerate(labs):
        print(f"  [{i+1}/{len(labs)}] {lab}...", flush=True)
        go(f"https://opencode.ai/fr/data/{lab}")
        time.sleep(1)
        html = get_html()

        # Parser le tableau lab-model-table-track
        # data-component="lab-model-row" href="/fr/data/lab/slug" ... <strong>Nom</strong>
        rows = re.findall(
            r'data-component="lab-model-row" href="/fr/data/[a-z0-9-]+/([^"]+)"[^>]*role="row"[^>]*>(.*?)</a>',
            html, re.S,
        )

        for slug, body in rows:
            m = re.search(r"<strong>(.*?)</strong>", body)
            name = m.group(1) if m else slug
            if slug not in par_slug:
                par_slug[slug] = lab
                noms[slug] = name

# Construire OC_LABS.json
    oc_labs = {
        "par_slug": {k.lower(): v for k, v in par_slug.items()},
    }

    (DATA / "OC_LABS.json").write_text(json.dumps(oc_labs, ensure_ascii=False, indent=1))
    total = len(par_slug)
    print(f"Écrit data/OC_LABS.json ({len(par_slug)} modèles)")


def main() -> int:
    # Prix de base globaux (fusionnés sur tous les fichiers) pour le
    # fallback des modèles '-free' : un -free dans ZEN peut prendre le
    # prix de sa base qui vit dans GO (ex. mimo-v2.5-free -> mimo-v2.5).
    base_prices = {}
    for fname in ENDPOINTS:
        url = ENDPOINTS[fname]
        doc = DOCS[fname]
        data = fetch_official(url)
        mods = extract_official(data)
        html = get_html(doc)
        name2id = parse_endpoint_ids(html)
        txt = get_txt(doc)
        prices = parse_prices(txt)
        # Prix du doc (via mapping nom->slug)
        for mid, p in prices.items():
            if p and p[0] not in (None, 0.0):
                key = mid
                if key in name2id:
                    key = name2id[key]
                base_prices[key] = p
        # Prix des endpoints officiels
        for m in mods:
            mid = m["id"]
            if m.get("input") not in (None, 0.0):
                base_prices[mid] = (m.get("input"), m.get("output"), m.get("cache_read"))

    for fname in ENDPOINTS:
        mods = build_models(fname, base_prices)
        (DATA / fname).write_text(json.dumps(mods, ensure_ascii=False, indent=1))
        n_prix = sum(1 for m in mods if m["input"] is not None)
        print(f"Écrit data/{fname} ({len(mods)} modèles, {n_prix} avec prix)")

    # Collecte des labs -> OC_LABS.json
    collect_labs()

    # Collecte des II AA -> AA_II.json
    collect_aa()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
