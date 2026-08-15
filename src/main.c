/*
 * alvalllm — main.c
 * CLI: help | table [1-3] | tables
 *
 *   table        -> table par défaut (générale = 1)
 *   table 1      -> générale   (tous modèles, coût pondéré par ratios réels)
 *   table 2      -> free (modèles gratuits)
 *   table 3      -> frontier
 *   tables       -> les 3 tables
 *
 * Dépend de ffsr pour la collecte (breadcrumb). Les calculs utilisent
 * la grille non-linéaire et les profils de ratios de params.json.
 */

#include "params.h"
#include <unistd.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>

static void usage(void)
{
    printf("alvalllm — Algorithme de valeur LLM (CLI, dépend de ffsr)\n"
           "\n"
           "Usage:\n"
           "  alvalllm help             cette aide\n"
           "  alvalllm table            table par défaut (= 1)\n"
           "  alvalllm table <n>        table 1-3\n"
           "  alvalllm tables           les 3 tables\n"
           "  alvalllm fetch <src>      collecte les données de la source\n"
           "  alvalllm coupling <src>   couplage II AA -> data/models.json\n"
           "  alvalllm build <src>      fetch + coupling (chaînés)\n"
           "\n"
           "Sources:\n"
           "  OC  = opencode (collecte + couplage via scripts/)\n"
           "\n"
           "Tables:\n"
           "  1 = general    (tous modèles, coût pondéré par ratios réels)\n"
           "  2 = free       (modèles gratuits)\n"
           "  3 = frontier   (modèles frontier / phares de lab)\n"
           "\n"
           "Paramètres : data/params.json (non versionné) — copier depuis "
           "data/params.json.example.\n"
           "Base de modèles : data/models.json.\n");
}

/* ---- sources (fetch/coupling/build) ---- */

typedef struct {
    const char *nom;          /* "OC" */
    const char *fetch_script; /* collecte (ex. collect_models.py) */
    const char *coup_script;  /* couplage (ex. couplage.py) */
} Source;

static const Source sources[] = {
    { "OC", "collect_models.py", "couplage.py" },
};

/* exécute un script python transitoire, retourne son code de sortie */
static int exec_script(const char *script)
{
    char cmd[2048];
    int rc;

    snprintf(cmd, sizeof(cmd), "python3 %s/%s", chemin_scripts(), script);
    printf("alvalllm: %s\n", cmd);
    rc = system(cmd);
    if (rc == -1) {
        perror("alvalllm: system");
        return 1;
    }
    if (WIFEXITED(rc))
        return WEXITSTATUS(rc);
    return 1;
}

/* fetch | coupling | build <src> */
static int cmd_pipeline(const char *cmd, const char *nom_src)
{
    const Source *src = NULL;
    size_t i;
    int rc;

    for (i = 0; i < sizeof(sources) / sizeof(sources[0]); i++) {
        if (strcmp(sources[i].nom, nom_src) == 0) {
            src = &sources[i];
            break;
        }
    }
    if (!src) {
        fprintf(stderr, "alvalllm: source inconnue '%s' — disponibles :",
                nom_src);
        for (i = 0; i < sizeof(sources) / sizeof(sources[0]); i++)
            fprintf(stderr, " %s", sources[i].nom);
        fprintf(stderr, "\n");
        return 2;
    }

    if (strcmp(cmd, "fetch") == 0)
        return exec_script(src->fetch_script);

    if (strcmp(cmd, "coupling") == 0)
        return exec_script(src->coup_script);

    /* build = fetch puis coupling */
    rc = exec_script(src->fetch_script);
    if (rc != 0) return rc;
    return exec_script(src->coup_script);
}

/* coût pondéré par 1M tokens pour un modèle et un profil de ratios */
static double cout_pondere(const Modele *m, const Profil *pr)
{
    return pr->cache * m->prix_cache +
           pr->input * m->prix_in +
           pr->output * m->prix_out +
           pr->cache_write * m->prix_cw;
}

/* sélection d'un profil par nom */
static const Profil *profil_par_nom(const Parametres *p, const char *nom)
{
    int i;
    for (i = 0; i < p->nb_profils; i++)
        if (strcmp(p->profils[i].nom, nom) == 0)
            return &p->profils[i];
    return &p->profils[0];
}

static int modele_passe(const Modele *m, const char *filtre)
{
    if (filtre[0] == '\0') return 1;
    if (strcmp(filtre, "free") == 0) return m->gratuit;
    if (strcmp(filtre, "frontier") == 0) return m->frontier;
    return 1;
}

/* format : 36628 -> "36 628" (séparateur de milliers) */
static void fmt_milliers(char *out, size_t sz, double v)
{
    char tmp[64];
    int len, i, o = 0;

    snprintf(tmp, sizeof(tmp), "%.0f", v);
    len = (int)strlen(tmp);
    for (i = 0; i < len && (size_t)o + 2 < sz; i++) {
        if (i > 0 && (len - i) % 3 == 0)
            out[o++] = ' ';
        out[o++] = tmp[i];
    }
    out[o] = '\0';
}

/* format : 51.766577 -> "51 767" (3 décimales, le point devient un espace) */
static void fmt_ii(char *out, size_t sz, double v)
{
    char tmp[64];
    size_t len, i, o = 0;

    snprintf(tmp, sizeof(tmp), "%.3f", v);
    len = strlen(tmp);
    for (i = 0; i < len && o + 1 < sz; i++) {
        if (tmp[i] == '.')
            out[o++] = ' ';
        else
            out[o++] = tmp[i];
    }
    out[o] = '\0';
}

/* affiche une table. Les valeurs brutes restent la vérité ; les couleurs
 * (vert/cyan/jaune) sont un bonus de repérage sur les meilleurs. Les
 * mauvais ne sont pas colorés : inutile de leur donner de l'attention. */
static int afficher_table(const Parametres *p, const Base *b,
                          const Profil *pr, const char *filtre)
{
    static const char *C_VERT  = "\033[32m";
    static const char *C_CYAN  = "\033[36m";
    static const char *C_JAUNE = "\033[33m";
    static const char *C_RESET = "\033[0m";
    static const char *C_BLANC = "";
    static int couleur_ok = -1; /* -1 : pas encore déterminé */

    if (couleur_ok < 0)
        couleur_ok = isatty(STDOUT_FILENO) ? 1 : 0;
    if (!couleur_ok) {
        C_VERT = C_CYAN = C_JAUNE = C_RESET = C_BLANC;
    }

    double vmin = 0, vmax = 0;
    int n = 0, i;

    /* pré-calcul : min/max des valeurs pour l'échelle de couleur */
    for (i = 0; i < b->nb_modeles; i++) {
        const Modele *m = &b->modeles[i];
        double cp, cap, v;

        if (!modele_passe(m, filtre)) continue;
        cp  = cout_pondere(m, pr);
        cap = grille_appliquer(&p->grille, m->ii);
        v = cap / (cp > 0 ? cp : 1.0);
        if (n == 0 || v < vmin) vmin = v;
        if (n == 0 || v > vmax) vmax = v;
        n++;
    }

    printf("%-32s %6s %7s %8s %8s\n",
           "Modèle", "II ", "CAP", "$/1M", "VAL");
    printf("%s\n", "------------------------------------------------------------------");
    for (i = 0; i < b->nb_modeles; i++) {
        const Modele *m = &b->modeles[i];
        double cp, cap, val;
        const char *col = "";
        char buf[32], buf2[32], buf3[32], buf4[32];

        if (!modele_passe(m, filtre)) continue;

        cp  = cout_pondere(m, pr);
        cap = grille_appliquer(&p->grille, m->ii);
        val = cap / (cp > 0 ? cp : 1.0);

        /* couleur par quartile sur l'échelle [0..1] (min/max de la table) */
        if (vmax > vmin) {
            double q = (val - vmin) / (vmax - vmin);
            if (q >= 0.75)      col = C_VERT;
            else if (q >= 0.50) col = C_CYAN;
            else if (q >= 0.25) col = C_JAUNE;
        }

        fmt_ii(buf3, sizeof(buf3), m->ii);
        fmt_milliers(buf2, sizeof(buf2), cap);
        fmt_milliers(buf, sizeof(buf), val);
        snprintf(buf4, sizeof(buf4), "%.4f", cp);
        printf("%s%-32s %6s %7s %8s %8s%s\n",
               col, m->nom, buf3, buf2, buf4, buf, C_RESET);
    }
    return 0;
}

int main(int argc, char **argv)
{
    Parametres params;
    Base base;
    const Profil *profil;
    const char *chemin_params, *chemin_base;
    const char *cmd;
    int table = 0;

chemin_params = chemin_donnees("params.json");
    chemin_base   = chemin_donnees("models.json");

    if (argc < 2) { usage(); return 0; }

    cmd = argv[1];

    /* help et commandes inconnues ne nécessitent pas la base */
    if (strcmp(cmd, "help") == 0) { usage(); return 0; }

    /* fetch/coupling/build : pipeline de données — n'exigent ni
     * params.json ni models.json (ils les produisent). */
    if (strcmp(cmd, "fetch") == 0 || strcmp(cmd, "coupling") == 0 ||
        strcmp(cmd, "build") == 0) {
        if (argc < 3) {
            fprintf(stderr, "alvalllm: '%s' requiert une source "
                            "(ex: alvalllm %s OC)\n", cmd, cmd);
            return 2;
        }
        return cmd_pipeline(cmd, argv[2]);
    }

    if (strcmp(cmd, "table") != 0 && strcmp(cmd, "tables") != 0) {
        fprintf(stderr, "alvalllm: commande inconnue '%s' (voir: alvalllm help)\n",
                cmd);
        return 2;
    }

    if (params_charger(chemin_params, &params) != 0)
        return 1;

    if (base_charger(chemin_base, &base) != 0) {
        fprintf(stderr, "alvalllm: base introuvable — lance la collecte "
                        "via ffsr (fetch) ou fournis data/models.json\n");
        return 1;
    }
    profil = profil_par_nom(&params, params.profil_defaut);

    if (strcmp(cmd, "table") == 0) {
        if (argc >= 3)
            table = atoi(argv[2]);
        if (table < 1 || table > MAX_TABLES)
            table = 1; /* par défaut : générale */
        afficher_table(&params, &base, profil, params.tables[table - 1].filtre);
        return 0;
    }

    if (strcmp(cmd, "tables") == 0) {
        int i;
        for (i = 0; i < MAX_TABLES; i++) {
            printf("== table %d (%s) ==\n",
                   i + 1, params.tables[i].nom);
            afficher_table(&params, &base, profil, params.tables[i].filtre);
            printf("\n");
        }
        return 0;
    }

    fprintf(stderr, "alvalllm: commande inconnue '%s' (voir: alvalllm help)\n",
            cmd);
    return 2;
}
