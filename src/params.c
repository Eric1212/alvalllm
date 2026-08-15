/*
 * alvalllm — params.c
 * Chargement JSON via jansson. La grille est validée au chargement :
 *   - <= 100 paliers
 *   - croissants et contigus (sans trou ni chevauchement)
 *   - dernier palier ouvert vers le haut
 * Un params.json invalide -> message clair + refus (-1).
 */

#include "params.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <jansson.h>

/* ---------- valeurs par défaut (frame minimal intégré) ---------- */

static void params_defaut(Parametres *p)
{
    int i;
    static const struct { int lo, hi, pts; } def_p[] = {
        {0, 30, 1}, {40, 50, 2}, {50, 55, 4}, {55, 60, 8}, {60, 999, 10},
    };
    static const char *profs[][4] = {
        {"default", "0.988", "0.0001", "0.0021"},
        {"normal", "0.924", "0.071",  "0.004"},
    };
    double cw[2] = {0.0095, 0.0};

    memset(p, 0, sizeof(*p));
    for (i = 0; i < (int)(sizeof(def_p) / sizeof(def_p[0])); i++) {
        p->grille.palliers[i].min_ii      = def_p[i].lo;
        p->grille.palliers[i].max_ii      = def_p[i].hi;
        p->grille.palliers[i].points_par_ii = def_p[i].pts;
    }
    p->grille.nb_palliers = (int)(sizeof(def_p) / sizeof(def_p[0]));

    for (i = 0; i < 2; i++) {
        snprintf(p->profils[i].nom, sizeof(p->profils[i].nom), "%s", profs[i][0]);
        p->profils[i].cache      = atof(profs[i][1]);
        p->profils[i].input      = atof(profs[i][2]);
        p->profils[i].output     = atof(profs[i][3]);
        p->profils[i].cache_write = cw[i];
    }
    p->nb_profils = 2;
    snprintf(p->profil_defaut, sizeof(p->profil_defaut), "default");

    /* tables : 1=general, 2=free, 3=frontier */
    strcpy(p->tables[0].nom, "1"); strcpy(p->tables[0].filtre, "");
    strcpy(p->tables[1].nom, "2"); strcpy(p->tables[1].filtre, "free");
    strcpy(p->tables[2].nom, "3"); strcpy(p->tables[2].filtre, "frontier");
    p->ffsr_onglet = 9;
}

/* ---------- chemins ---------- */

const char *chemin_donnees(const char *fichier)
{
    /* buffer rotatif : les appels successifs (params puis base) ne
     * doivent PAS partager le même buffer, sinon le 2e écrase le 1er. */
    static char buf[4][1024];
    static int idx = 0;
    const char *env = getenv("ALVALLM_DATA");
    char *b = buf[idx];

    idx = (idx + 1) % 4;
    if (env && *env) {
        snprintf(b, 1024, "%s/%s", env, fichier);
        return b;
    }
    snprintf(b, 1024, "data/%s", fichier);
    return b;
}

/* Dossier des scripts de collecte/couplage (transitoire : python).
 * ALVALLM_SCRIPTS sinon 'scripts/' relatif au cwd. */
const char *chemin_scripts(void)
{
    static char buf[1024];
    const char *env = getenv("ALVALLM_SCRIPTS");

    if (env && *env) {
        snprintf(buf, sizeof(buf), "%s", env);
        return buf;
    }
    snprintf(buf, sizeof(buf), "scripts");
    return buf;
}

/* ---------- grille ---------- */
double grille_appliquer(const Grille *g, double ii)
{
    int i, dernier = g->nb_palliers - 1;

    /* paliers semi-ouverts [min, max[ ; le dernier est ouvert vers le haut */
    for (i = 0; i < g->nb_palliers; i++) {
        const Pallier *pa = &g->palliers[i];
        int dans = (i == dernier) ? (ii >= pa->min_ii)
                                  : (ii >= pa->min_ii && ii < pa->max_ii);
        if (dans)
            return ii * pa->points_par_ii;
    }
    /* II hors grille (dans un trou) -> repli sur le palier inférieur
     * le plus proche, sinon le premier palier. */
    for (i = dernier; i >= 0; i--) {
        if (ii >= g->palliers[i].min_ii)
            return ii * g->palliers[i].points_par_ii;
    }
    return ii * g->palliers[0].points_par_ii;
}

static int grille_valider(Grille *g)
{
    int i;
    if (g->nb_palliers < 1 || g->nb_palliers > MAX_PALLIERS) {
        fprintf(stderr, "alvalllm: grille: %d paliers hors bornes [1..%d]\n",
                g->nb_palliers, MAX_PALLIERS);
        return -1;
    }
    for (i = 0; i < g->nb_palliers; i++) {
        Pallier *pa = &g->palliers[i];
        if (pa->min_ii < 0 || pa->max_ii < pa->min_ii) {
            fprintf(stderr, "alvalllm: grille: palier %d invalide (%d-%d)\n",
                    i + 1, pa->min_ii, pa->max_ii);
            return -1;
        }
        if (i > 0) {
            const Pallier *prev = &g->palliers[i - 1];
            /* chevauchement interdit ; les trous sont tolérés */
            if (pa->min_ii < prev->max_ii) {
                fprintf(stderr, "alvalllm: grille: paliers %d et %d se "
                        "chevauchent\n", i, i + 1);
                return -1;
            }
        }
        if (pa->points_par_ii < 0) {
            fprintf(stderr, "alvalllm: grille: palier %d points_par_ii negatif\n",
                    i + 1);
            return -1;
        }
    }
    return 0;
}

/* ---------- parsing ---------- */

static int lire_int(json_t *j, const char *cle, int *out, const char *ctx)
{
    json_t *v = json_object_get(j, cle);
    if (!json_is_integer(v)) {
        fprintf(stderr, "alvalllm: %s: '%s' doit etre un entier\n", ctx, cle);
        return -1;
    }
    *out = (int)json_integer_value(v);
    return 0;
}

static int lire_double(json_t *j, const char *cle, double *out, const char *ctx)
{
    json_t *v = json_object_get(j, cle);
    if (!json_is_number(v)) {
        fprintf(stderr, "alvalllm: %s: '%s' doit etre un nombre\n", ctx, cle);
        return -1;
    }
    *out = json_number_value(v);
    return 0;
}

static int parse_grille(json_t *root, Parametres *p)
{
    json_t *jgr = json_object_get(root, "grid");
    json_t *jp  = jgr ? json_object_get(jgr, "tiers") : NULL;
    size_t i, n;

    if (!jp) return 0; /* défaut conservé */

    if (!json_is_array(jp)) {
        fprintf(stderr, "alvalllm: grille.tiers doit etre un tableau\n");
        return -1;
    }
    n = json_array_size(jp);
    if (n < 1 || n > MAX_PALLIERS) {
        fprintf(stderr, "alvalllm: grille: %zu paliers hors bornes [1..%d]\n",
                n, MAX_PALLIERS);
        return -1;
    }
    p->grille.nb_palliers = (int)n;
    for (i = 0; i < n; i++) {
        json_t *pa = json_array_get(jp, i);
        Pallier *d = &p->grille.palliers[i];
        if (lire_int(pa, "min", &d->min_ii, "grille.tiers") ||
            lire_int(pa, "max", &d->max_ii, "grille.tiers") ||
            lire_int(pa, "points_per_ii", &d->points_par_ii, "grille.tiers"))
            return -1;
    }
    return grille_valider(&p->grille);
}

static int parse_profils(json_t *root, Parametres *p)
{
    json_t *jpr = json_object_get(root, "profiles");
    const char *cle;
    json_t *val;

    if (!jpr) return 0;

    json_object_foreach(jpr, cle, val) {
        if (cle[0] == '_') continue; /* annotations */
        if (p->nb_profils >= MAX_PROFILS) {
            fprintf(stderr, "alvalllm: trop de profils (max %d)\n", MAX_PROFILS);
            return -1;
        }
        Profil *pr = &p->profils[p->nb_profils];
        snprintf(pr->nom, sizeof(pr->nom), "%s", cle);
        if (lire_double(val, "cache", &pr->cache, "profils") ||
            lire_double(val, "input", &pr->input, "profils") ||
            lire_double(val, "output", &pr->output, "profils"))
            return -1;
        json_t *cw = json_object_get(val, "cache_write");
        pr->cache_write = cw && json_is_number(cw) ? json_number_value(cw) : 0.0;
        p->nb_profils++;
    }
    return 0;
}

static int parse_tables(json_t *root, Parametres *p)
{
    json_t *jt = json_object_get(root, "tables");
    int i;

    if (!jt) return 0;

    for (i = 0; i < MAX_TABLES; i++) {
        char cle[8];
        json_t *t;
        snprintf(cle, sizeof(cle), "%d", i + 1);
        t = json_object_get(jt, cle);
        if (!t || !json_is_object(t)) continue;
        json_t *jn = json_object_get(t, "name");
        json_t *jf = json_object_get(t, "filter");
        if (json_is_string(jn))
            snprintf(p->tables[i].nom, sizeof(p->tables[i].nom), "%s",
                     json_string_value(jn));
        if (json_is_string(jf))
            snprintf(p->tables[i].filtre, sizeof(p->tables[i].filtre), "%s",
                     json_string_value(jf));
    }
    return 0;
}

int params_charger(const char *chemin, Parametres *p)
{
    json_error_t err;
    json_t *root;

    root = json_load_file(chemin, 0, &err);
    if (!root) {
        if (err.line > 0) {
            fprintf(stderr, "alvalllm: params.json: ligne %d: %s\n",
                    err.line, err.text);
            return -1;
        }
        /* fichier absent : alvalllm n'utilise AUCUN défaut silencieux.
         * params.json.example n'est jamais lu — seule params.json compte. */
        fprintf(stderr, "alvalllm: %s introuvable — copie "
                        "data/params.json.example vers data/params.json "
                        "puis remplis tes valeurs\n", chemin);
        return -1;
    }

    params_defaut(p);

    if (parse_grille(root, p) || parse_profils(root, p) ||
        parse_tables(root, p)) {
        json_decref(root);
        return -1;
    }

    json_t *jf = json_object_get(root, "ffsr");
    if (jf && json_is_object(jf)) {
        json_t *jog = json_object_get(jf, "tab");
        if (json_is_integer(jog))
            p->ffsr_onglet = (int)json_integer_value(jog);
    }
    json_t *jpd = json_object_get(root, "default_profile");
    if (json_is_string(jpd))
        snprintf(p->profil_defaut, sizeof(p->profil_defaut), "%s",
                 json_string_value(jpd));

    json_decref(root);
    return 0;
}

int base_charger(const char *chemin, Base *b)
{
    json_error_t err;
    json_t *root, *arr;
    size_t i;

    memset(b, 0, sizeof(*b));

    root = json_load_file(chemin, 0, &err);
    if (!root) {
        fprintf(stderr, "alvalllm: models.json introuvable ou invalide: %s\n",
                err.text);
        return -1;
    }
    arr = json_object_get(root, "modeles");
    if (!json_is_array(arr)) {
        fprintf(stderr, "alvalllm: models.json: 'modeles' manquant\n");
        json_decref(root);
        return -1;
    }
    b->nb_modeles = (int)json_array_size(arr);
    if (b->nb_modeles > MAX_MODELES)
        b->nb_modeles = MAX_MODELES;

    for (i = 0; i < (size_t)b->nb_modeles; i++) {
        json_t *m = json_array_get(arr, i);
        Modele *d = &b->modeles[i];
        json_t *v;

        if (!json_is_object(m)) { json_decref(root); return -1; }

        v = json_object_get(m, "nom");      if (json_is_string(v)) snprintf(d->nom,  sizeof(d->nom),  "%s", json_string_value(v));
        v = json_object_get(m, "lab");      if (json_is_string(v)) snprintf(d->lab,  sizeof(d->lab),  "%s", json_string_value(v));
        v = json_object_get(m, "ii");       if (json_is_number(v)) d->ii = json_number_value(v);
        v = json_object_get(m, "prix_in");  if (json_is_number(v))  d->prix_in  = json_number_value(v);
        v = json_object_get(m, "prix_out"); if (json_is_number(v))  d->prix_out = json_number_value(v);
        v = json_object_get(m, "prix_cache"); if (json_is_number(v)) d->prix_cache = json_number_value(v);
        v = json_object_get(m, "prix_cw");  if (json_is_number(v))  d->prix_cw  = json_number_value(v);
        v = json_object_get(m, "gratuit");  d->gratuit  = json_is_true(v) || (json_is_integer(v) && json_integer_value(v) != 0);
        v = json_object_get(m, "frontier"); d->frontier = json_is_true(v) || (json_is_integer(v) && json_integer_value(v) != 0);
    }
    json_decref(root);
    return 0;
}
