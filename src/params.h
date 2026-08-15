/*
 * alvalllm — params.h
 * Chargement de params.json (paramètres utilisateur, non versionnés)
 * et de models.json (base de modèles, versionnée).
 *
 * params.json n'existe pas toujours : alvalllm fonctionne alors avec
 * des valeurs par défaut en dur (frame minimal intégré).
 */

#ifndef ALVALLM_PARAMS_H
#define ALVALLM_PARAMS_H

#include <stddef.h>

#define MAX_PALLIERS     100
#define MAX_PROFILS      8
#define MAX_MODELE_NOM   64
#define MAX_MODELE_LAB   48
#define MAX_MODELES      256
#define MAX_TABLES       3
#define NOM_TABLE_LEN    24

/* ---- grille (paliers non linéaires II -> points par II) ---- */
typedef struct {
    int min_ii;
    int max_ii;          /* inclusif; dernier palier ouvert vers le haut */
    int points_par_ii;
} Pallier;

typedef struct {
    Pallier palliers[MAX_PALLIERS];
    int     nb_palliers; /* <= MAX_PALLIERS */
} Grille;

/* ---- profil de ratios réels (cache/input/output/cache_write) ---- */
typedef struct {
    char  nom[MAX_MODELE_NOM];
    double cache;        /* cache read  (part) */
    double input;        /* input       (part) */
    double output;       /* output      (part) */
    double cache_write;  /* cache write (part) */
} Profil;

/* ---- mapping table -> filtre ---- */
typedef struct {
    char nom[4];
    char filtre[NOM_TABLE_LEN]; /* "" = tous */
} TableDef;

/* ---- paramètres globaux ---- */
typedef struct {
    Grille grille;
    Profil profils[MAX_PROFILS];
    int    nb_profils;
    char   profil_defaut[MAX_MODELE_NOM];
    TableDef tables[MAX_TABLES]; /* index 0..2 -> table 1..3 */
    int    ffsr_onglet;
} Parametres;

/* ---- un modèle de la base ---- */
typedef struct {
    char    nom[MAX_MODELE_NOM];
    char    lab[MAX_MODELE_LAB];
    int     ii;
    double  prix_in;      /* $ / 1M tokens */
    double  prix_out;
    double  prix_cache;   /* cache read */
    double  prix_cw;      /* cache write (0 si non facturé) */
    int     gratuit;      /* bool */
    int     frontier;     /* bool */
} Modele;

/* ---- base de modèles ---- */
typedef struct {
    Modele modeles[MAX_MODELES];
    int    nb_modeles;
} Base;

/* Résout le chemin de params.json / models.json :
 *  1) ./data/<fichier>
 *  2) ALVALLM_DATA/<fichier> (variable d'env)
 *  sinon "" (par défaut). */
const char *chemin_donnees(const char *fichier);

/* Résout le dossier des scripts python (transitoire) :
 *  ALVALLM_SCRIPTS sinon 'scripts/' relatif au cwd. */
const char *chemin_scripts(void);

/* Charge params.json ; échoue (retourne -1) seulement si le fichier
 * existe mais est invalide. Si absent -> valeurs par défaut. */
int params_charger(const char *chemin, Parametres *p);

/* Charge models.json ; -1 si absent ou invalide. */
int base_charger(const char *chemin, Base *b);

/* Applique la grille à un II -> capacité pondérée (II * points_par_ii). */
int grille_appliquer(const Grille *g, int ii);

#endif /* ALVALLM_PARAMS_H */
