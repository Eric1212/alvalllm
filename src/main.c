/*
 * alvalllm — main.c
 * CLI: help | table [1-3] | tables
 *
 *   table        -> table par défaut (générale = 1)
 *   table 1      -> générale   (tous modèles, coût pondéré par ratios réels)
 *   table 2      -> gratuite
 *   table 3      -> frontier
 *   tables       -> les 3 tables
 *
 * Dépend de ffsr pour la collecte (breadcrumb). Les calculs utilisent
 * la grille non-linéaire et les profils de ratios de params.json.
 */

#include "params.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void usage(void)
{
    printf("alvalllm — Algorithme de valeur LLM (CLI, dépend de ffsr)\n"
           "\n"
           "Usage:\n"
           "  alvalllm help             cette aide\n"
           "  alvalllm table            table par défaut (= 1)\n"
           "  alvalllm table <n>        table 1-3\n"
           "  alvalllm tables           les 3 tables\n"
           "\n"
           "Tables:\n"
           "  1 = generale   (tous modèles, coût pondéré par ratios réels)\n"
           "  2 = gratuite   (modèles gratuits)\n"
           "  3 = frontier   (modèles frontier / phares de lab)\n"
           "\n"
           "Paramètres : data/params.json (non versionné) — copier depuis "
           "data/params.json.example.\n"
           "Base de modèles : data/models.json.\n");
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
    if (strcmp(filtre, "gratuit") == 0) return m->gratuit;
    if (strcmp(filtre, "frontier") == 0) return m->frontier;
    return 1;
}

/* affiche une table */
static int afficher_table(const Parametres *p, const Base *b,
                          const Profil *pr, const char *filtre)
{
    int i;
    printf("%-32s %5s %6s %10s %12s\n",
           "Modèle", "II", "Cap.", "$/1M pond", "Valeur");
    printf("%s\n", "------------------------------------------------------------------");
    for (i = 0; i < b->nb_modeles; i++) {
        const Modele *m = &b->modeles[i];
        double cp, val;
        int cap;

        if (!modele_passe(m, filtre)) continue;

        cp  = cout_pondere(m, pr);
        cap = grille_appliquer(&p->grille, m->ii);
        val = cap / (cp > 0 ? cp : 1.0);

        printf("%-32s %5d %6d %10.4f %12.0f\n",
               m->nom, m->ii, cap, cp, val);
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

    if (params_charger(chemin_params, &params) != 0)
        return 1;

    if (argc < 2) { usage(); return 0; }

    cmd = argv[1];

    /* help et commandes inconnues ne nécessitent pas la base */
    if (strcmp(cmd, "help") == 0) { usage(); return 0; }
    if (strcmp(cmd, "table") != 0 && strcmp(cmd, "tables") != 0) {
        fprintf(stderr, "alvalllm: commande inconnue '%s' (voir: alvalllm help)\n",
                cmd);
        return 2;
    }

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
