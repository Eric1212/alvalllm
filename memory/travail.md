# État du travail — alvalllm (à relire après compaction de contexte)

> La compaction d'opencode répond seulement « Contexte supprimé, bonne journée »
> (prompt minimaliste volontaire). Tout l'état utile est consigné ici.

## Projet
- **alvalllm** : CLI en C, dépend de ffsr. Grille non-linéaire II→points,
  profils de ratios, tables 1-3 dans `params.json`.
- Rôles : **c'est alvallim qui pilote ffsr**, pas l'assistant. Collecte sur
  **onglet 9** (onglets 0-9 permanents). `ffsr bidi` = injection JS.
- Commande programme : `fetch oc` → `décodage + on récupère le II`

## Objectif
Lister les LLM opencode (breadcrumb), les coupler avec les **II d'AA
(Artificial Analysis, Intelligence Index)**, **drop** ceux absents d'AA.

## Méthode de collecte (validée)
- 316 modèles opencode via breadcrumb → `data/models_oc_316.txt`
- **608 modèles AA** décodés via bidi : contexte
  `d631f55f-ac3f-4c8b-9779-7beb2926b607` (artificialanalysis.ai/models),
  `window.storefront.getState().models` expose `intelligenceIndex`, prix,
  etc. → `/tmp/opencode/aa_models.json`
- `data/aa_ii_140.json` : 140 modèles AA avec II

### ⚠️ COLLECTE OPENCODE (modèles_oc_316) — MÉTHODE DOCUMENTÉE, MAIS INUTILE
**Comment collecter le breadcrumb (si un jour nécessaire) :**
1. `ffsr go 9 "https://opencode.ai/fr/data/<n'importe quel lab>" w` — ouvrir
   une page lab (ex. alibaba) dans l'onglet 9
2. `ffsr get txt 9` — le texte visible contient le MENU DU BREADCRUM :
   - la liste des **29 labs** (Alibaba, Anthropic, Arcee Ai, Bytedance
     Seed, Cohere, Deepreinforce, DeepSeek, Google, Ibm, Meituan, Meta,
     Microsoft, MiniMax, Mistral, Moonshot, Nvidia, OpenAI, Perplexity,
     Poolside, Sakana, Sarvam, Sdaia, StepFun, Swiss Ai, Tencent,
     Thinkingmachines, xAI, Xiaomi, Zhipu)
   - la liste des **modèles du lab courant** (noms affichés, ex. anthropic :
     Claude Mythos 5, Opus 5, Sonnet 5, Fable 5, Opus 4.8...)
3. Pour chaque lab : `ffsr go 9 "https://opencode.ai/fr/data/<lab>" w` +
   `ffsr get 9` → le HTML contient les modèles avec ids/slugs/prix
4. Les URLs `/fr/data/<lab>/<modele>` → `models_all.txt` (316) →
   retirer `/fr/data/` → `models_uniq.txt` → `data/models_oc_316.txt`
**Format HTML des pages lab** : sérialisation linéaire
`$R[N]={id:"lab/modele",...,cost:$R[M]={input:X,output:Y,cacheRead:Z,
cacheWrite:W},...}` — découpable par `$R[N]={id:"` + regex cost
(~15 lignes de Python, validé sur alibaba 39/39 et deepseek 12/12)

**POURQUOI C'EST INUTILE (découverte 14/08) :**
- Les pages `/fr/data/<lab>` gardent TOUS les modèles qui sont, seront
  et ont été dans OpenCode = **ARCHIVE** (ex. deepseek : 12 modèles dont
  deepseek-v3, deepseek-r1, deepseek-chat = anciens ; seuls
  deepseek-v4-flash et deepseek-v4-pro sont réellement chez Zen/Go)
- Les **316 du breadcrumb = l'archive complète** (claude-3-5-sonnet-20241022,
  gpt-3.5-turbo, qwen-turbo... = anciens archivés)
- Les **prix des pages lab = prix NOMINAUX du lab**, PAS ce que Zen/Go
  facturent (ex. deepseek-v4-pro : 1.6/3.2 sur la page vs 0.435/0.87
  chez Go)
- **`cost: void 0`** = modèles archivés sans tarif actuel
- **La liste RÉELLE des modèles OpenCode = les ENDPOINTS OFFICIELS
  (62 Zen + 26 Go = 72 uniques)** :
  - Zen : `https://opencode.ai/zen/v1/models`
  - Go : `https://opencode.ai/zen/go/v1/models`
  - models.dev = base TIERCE (anomalyco/models.dev) avec 29 modèles
    obsolètes en trop — PAS la source de vérité.
- **✔ COLLECTE OFFICIELLE ffsr VALIDÉE (14/08) :
  `scripts/collect_models.py`** — méthode bidi :
  1. `ffsr go 9 <endpoint-json>` (le viewer JSON se charge)
  2. `ffsr bidi {"id":2,"method":"browsingContext.getTree","params":{}}`
     → trouver le contexte de l'onglet 9 (celui dont l'URL contient
     'zen/.../v1/models') — le contexte change à chaque navigation !
  3. `ffsr bidi` script.evaluate `JSON.stringify($json.text)` sur ce
     contexte → le JSON brut du viewer (double-échappé)
  → OC_ZEN.json (62) + OC_GO.json (26). NI urllib NI curl.
- **Les prix se récupèrent via le breadcrumb des pages
  opencode.ai/data/<lab>/<modele> (le cost du payload) — à implémenter**
- **316 sauvegardés dans `poubelle/models_oc_316.txt` (gitignoré)** —
  archive non utilisée actuellement

## Couplage : ÉTAT FINAL = 94 matchs (87/103 familles AA)
- `scripts/couplage.py` → génère `data/models.json` (94 modèles opencode ↔ II AA)
- **103 familles AA** (140 modèles bruts → familles par variante max II,
  après retrait des réglages ET des dates)

### Règles du couplage (dans l'ordre, validées avec Éric)
1. **charger_aa()** : regroupe AA en FAMILLES — mêmes tokens de base,
   suffixes de réglage ignorés (`non-reasoning`, `reasoning`, `thinking`,
   `high`, `low`, `medium`, `xhigh`, `adaptive`, `instruct`, `it`...).
   La famille est désignée par sa variante au II MAX (ex. claude-opus-5
   regroupe -xhigh/-high/-medium/-low, max 63.05).
   **Les DATES sont retirées des familles AA** (AA ne collecte pas les
   dates) : deepseek-v4-pro-0424 → deepseek-v4-pro, grok-build-0-1-06-16
   → grok-build-0-1, etc.
2. **charger_opencode()** : liste des noms de modèles SANS le lab (tout ce
   qui précède '/' est trimmé). Le lab est chargé SÉPARÉMENT par
   **charger_labs()** ({modele: lab}), appelé APRÈS le couplage pour
   remplir le champ `lab` de models.json.
3. **canon** : lowercase + retirer tirets/points + fusionner les suffixes
   de réglage → prendre le plus intelligent.
   ⚠️ IMPORTANT : les suffixes sont testés du PLUS LONG au PLUS COURT
   (`xhigh` avant `high`) sinon `claudeopus5x` (bug corrigé).
4. **canon_aa** : préfixe lab AA retiré quand redondant avec le lab
   opencode (ex. AA `nvidia-nemotron-3-ultra-550b-a55b` → opencode
   `nvidia/nemotron-3-ultra-550b-a55b`) → +3 nemotron
5. **dates** : si opencode a une date, coupler uniquement avec AA sans
   date ou même date, sinon DROP (ex. magistral-small-2506 ≠ 2509)
6. **indulgence version** : si AA n'a qu'UN seul modèle non-versionné
   pour une famille, accepter le n° de version opencode
   (ex. `north-mini-code-1-0` → `north-mini-code` II 20.17)
7. **multiset égal (Counter)** : mêmes tokens dans un ordre différent
   (ex. AA `claude-4-5-sonnet` vs opencode `claude-sonnet-4-5`).
   Sûr car le Counter garde les doublons (gpt-5 ≠ gpt-5-5)
8. **norm_oc** : retire les attributs opencode que AA ne collecte pas :
   taille (`-XXb`), suffixe (`-instruct`/`-it`), dates — en fin de slug,
   jusqu'à stabilité (ex. `llama-4-maverick-17b-instruct` →
   `llama-4-maverick`, `muse-glimmer-30b` → `muse-glimmer`)
9. **-latest** : opencode `X-latest` = la meilleure version dispo → max II
   de la famille AA. Utilise `strip_ver_latest` (retire -d-d ET -d simple)
   LOCALEMENT SEULEMENT — jamais globalement (fusionnerait les générations
   → 25 faux matchs : gpt-4 → gpt-5.6-sol, etc.)

### REJETÉS par l'utilisateur
- Les alias manuels (table ALIAS) — « pas d'alias ! »
- La fusion globale `-d-d` / strip_ver élargi (fusionnait les générations)
- Le sous-ensemble (AA ⊆ OC) : trop permissif (qwen3-30b-a3b ≠
  qwen3-coder-30b-a3b)

## Progression
- 72 → 75 (+3 nemotron, préfixe lab) → 78 (+3 gemma-4-31b-it,
  gemma-4-26b-a4b-it, qwen3-next-80b-a3b-instruct via -it/-instruct)
- 81 (retrait dates familles AA : +grok-build-0.1, mimo-v2.5,
  gpt-5.5-instant, deepseek-r1, magistral-small-2506, qwen3-235b)
- 83 (multiset : +claude-sonnet-4-5, claude-haiku-4-5)
- 89 (norm_oc : +muse-glimmer-30b, mistral-small-3-1-24b-instruct-2503,
  llama-4-maverick-17b-instruct, llama-4-scout-17b-instruct)
- **94** (-latest : +mistral-medium-latest 30.39, mistral-small-latest
  19.71, devstral-medium-latest 19.24, magistral-medium-latest 18.05,
  mistral-large-latest 15.92)

## 16 familles AA restantes NON couplées (drops assumés)
- **Absents d'opencode** : qwen3-8-2-4t-a95b (57.7 !), solar-pro4 (41.64),
  ling-3-0-flash (37.82), ling-3-0-tiny, mercury-2, solar-pro-3,
  celeris-1, ministral-3-14b/8b/3b, gemma-3-27b/12b
- **Irréconciliables (Mistral Labs, nommage erratique)** : devstral-small-2,
  mistral-medium-3-1, mistral-small-3-2
- **Sous-ensemble rejeté** : qwen3-30b-a3b
- Note : qwen3-8-2-4t-a95b (57.7) est une variante MoE (2.4T/95B) sans
  équivalent opencode ; opencode qwen3.8-max a déjà le meilleur II (58.08)

## Décisions utilisateur (importantes)
- Drop des non-couplables = normal (pas de faux match)
- Pas d'alias manuels ; les règles générales seulement
- AA ne collecte pas les dates → retirées des familles
- Le lab se charge séparément (charger_labs) après le couplage
- Compaction volontairement trivialisée ; préfère perdre le résumé que le
  travail → d'où ce fichier.

## TODO / prochaines étapes (NON validées par l'utilisateur)
- Automatiser la collecte dans `breadcrumb.c` (collecte opencode + bidi AA +
  couplage → régénère `data/models.json`)
- Compléter les prix (in/out/cache) depuis opencode data pour le tableau
