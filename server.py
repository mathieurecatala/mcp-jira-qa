"""Serveur MCP « jira-qa » : du backlog Jira aux critères d'acceptation Gherkin.

Le serveur ne génère rien lui-même : il donne à l'assistant (Claude Code, Claude Desktop…)
des outils déterministes pour lire un export Jira, repérer les tickets pas prêts à tester,
enregistrer des scénarios Gherkin validés par un vrai parser, et mesurer la couverture
des critères d'acceptation. L'IA rédige, le serveur contrôle.

Lancement :  python server.py [chemin/vers/export.csv|.json]
Variables :  JIRA_QA_BACKLOG (export Jira), JIRA_QA_FEATURES (dossier des .feature)
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from gherkin.errors import ParserError
from gherkin.parser import Parser
from gherkin.token_scanner import TokenScanner
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

ICI = Path(__file__).resolve().parent
BACKLOG = Path(  # l'argument n'est lu qu'au lancement direct (pas à l'import par un test)
    sys.argv[1] if __name__ == "__main__" and len(sys.argv) > 1
    else os.environ.get("JIRA_QA_BACKLOG", ICI / "exemple" / "backlog_jira.csv")
)
FEATURES = Path(os.environ.get("JIRA_QA_FEATURES", ICI / "features"))

CLE = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")
TITRE_CA = re.compile(r"^\s*(h\d\.\s*)?(crit[eè]res? d'acceptation|acceptance criteria|ac)\s*:?\s*$", re.IGNORECASE)
TITRE = re.compile(r"^\s*h\d\.\s")
PUCE = re.compile(r"^\s*[*#-]+\s+(.*)$")
TERMES_FLOUS = [
    "rapide", "intuitif", "intuitive", "simple", "facilement", "clair", "claire", "fluide",
    "correctement", "meilleur", "meilleurs", "optimisé", "si possible", "à voir", "etc",
    "user-friendly", "fast", "easy", "as needed", "tbd",
]

mcp = MCPServer(
    "jira-qa",
    instructions=(
        "Outils Product/QA sur un export Jira. Commencer par auditer_backlog pour repérer les tickets "
        "pas prêts. Pour écrire des critères d'acceptation, utiliser le prompt criteres_acceptation, "
        "puis enregistrer_feature ; corriger et renvoyer tant que le serveur signale des erreurs."
    ),
)


# --- Lecture de l'export Jira -------------------------------------------------------------

def _texte_adf(noeud: Any) -> str:
    """Aplatit une description au format Atlassian Document Format (API Jira Cloud v3)."""
    if isinstance(noeud, str):
        return noeud
    if not isinstance(noeud, dict):
        return ""
    if noeud.get("type") == "text":
        return noeud.get("text", "")
    enfants = "".join(_texte_adf(n) for n in noeud.get("content", []))
    t = noeud.get("type")
    if t == "heading":
        return f"h{noeud.get('attrs', {}).get('level', 3)}. {enfants}\n"
    if t == "listItem":
        return f"* {enfants.strip()}\n"
    if t in ("paragraph", "codeBlock"):
        return enfants + "\n"
    return enfants


def _premier(brut: dict[str, list[str]], col: str) -> str:
    """Première valeur non vide d'une colonne (Jira répète les colonnes à valeurs multiples)."""
    return next((v for v in brut.get(col, []) if v), "")


def _nom(fields: dict, champ: str) -> str:
    return (fields.get(champ) or {}).get("name", "")


def _lire_csv(chemin: Path) -> list[dict]:
    # Jira répète les colonnes à valeurs multiples (Labels, Sprint…) : on les regroupe.
    with chemin.open(encoding="utf-8-sig", newline="") as f:
        lignes = list(csv.reader(f))
    entete, tickets = lignes[0], []
    for ligne in lignes[1:]:
        brut: dict[str, list[str]] = {}
        for col, val in zip(entete, ligne):
            brut.setdefault(col.strip(), []).append(val.strip())
        points = next((_premier(brut, c) for c in brut if "story point" in c.lower() and _premier(brut, c)), "")
        tickets.append({
            "cle": _premier(brut, "Issue key"), "titre": _premier(brut, "Summary"), "type": _premier(brut, "Issue Type"),
            "statut": _premier(brut, "Status"), "priorite": _premier(brut, "Priority"),
            "labels": [v for v in brut.get("Labels", []) if v],
            "sprint": _premier(brut, "Sprint"), "points": points, "description": _premier(brut, "Description"),
        })
    return tickets


def _lire_json(chemin: Path) -> list[dict]:
    # Réponse de l'API Jira Cloud /rest/api/3/search/jql : {"issues": [{"key", "fields": {...}}]}
    donnees = json.loads(chemin.read_text(encoding="utf-8-sig"))
    tickets = []
    for issue in donnees.get("issues", donnees if isinstance(donnees, list) else []):
        f = issue.get("fields", {})
        points = next((str(v) for k, v in f.items() if k.startswith("customfield_") and isinstance(v, (int, float))), "")
        tickets.append({
            "cle": issue.get("key", ""), "titre": f.get("summary", ""), "type": _nom(f, "issuetype"),
            "statut": _nom(f, "status"), "priorite": _nom(f, "priority"), "labels": f.get("labels", []),
            "sprint": "", "points": points, "description": _texte_adf(f.get("description") or "").strip(),
        })
    return tickets


def charger_backlog() -> dict[str, dict]:
    """Relu à chaque appel : un export remplacé pendant la démo est pris en compte."""
    tickets = _lire_json(BACKLOG) if BACKLOG.suffix.lower() == ".json" else _lire_csv(BACKLOG)
    return {t["cle"]: t for t in tickets if t["cle"]}


def criteres(description: str) -> list[str]:
    """Puces de la section « Critères d'acceptation » de la description."""
    dans_section, trouves = False, []
    for ligne in description.splitlines():
        if TITRE_CA.match(ligne):
            dans_section = True
        elif TITRE.match(ligne):
            dans_section = False
        elif dans_section and (m := PUCE.match(ligne)):
            trouves.append(m.group(1).strip())
    return trouves


def _ticket(cle: str) -> dict:
    cle = cle.strip().upper()
    backlog = charger_backlog()
    if cle not in backlog:
        raise ToolError(f"Ticket {cle} absent de l'export ({BACKLOG.name}).")
    return backlog[cle]


# --- Audit « prêt à tester » --------------------------------------------------------------

def auditer(t: dict) -> dict:
    desc, typ = t["description"], t["type"].lower()
    bas = desc.lower()
    constats: list[dict] = []

    def constat(niveau: str, regle: str, detail: str) -> None:
        constats.append({"niveau": niveau, "regle": regle, "detail": detail})

    if typ in ("bug", "bogue"):
        if not re.search(r"(étapes|etapes|steps to reproduce|reproduire)", bas):
            constat("bloquant", "bug_sans_reproduction", "Aucune étape pour reproduire le bug.")
        if not re.search(r"(résultat attendu|resultat attendu|expected)", bas):
            constat("bloquant", "bug_sans_attendu", "Le résultat attendu n'est pas écrit : impossible de dire quand c'est corrigé.")
    elif typ in ("story", "user story", "récit"):
        if not re.search(r"(en tant que|as an? )", bas):
            constat("avertissement", "format_user_story", "Pas de forme « En tant que… je veux… afin de… ».")
        if not criteres(desc):
            constat("bloquant", "sans_criteres", "Aucun critère d'acceptation : le QA ne sait pas quoi tester.")
        if not t["points"]:
            constat("info", "sans_estimation", "Pas de story points.")
    if len(desc) < 80:
        constat("avertissement", "description_courte", f"Description de {len(desc)} caractères.")
    flous = sorted({m for m in TERMES_FLOUS if re.search(rf"(?<!\w){re.escape(m)}(?!\w)", bas)})
    if flous:
        constat("avertissement", "termes_non_testables", "Termes à chiffrer ou préciser : " + ", ".join(flous) + ".")

    niveaux = {c["niveau"] for c in constats}
    verdict = "bloqué" if "bloquant" in niveaux else "à affiner" if "avertissement" in niveaux else "prêt"
    return {"cle": t["cle"], "titre": t["titre"], "type": t["type"], "verdict": verdict, "constats": constats}


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
def lister_tickets(type_ticket: str = "", statut: str = "", label: str = "") -> list[dict]:
    """Liste les tickets de l'export Jira, filtrables par type_ticket (Story, Bug, Task), statut ou label."""
    def garde(val: str, filtre: str) -> bool:
        return not filtre or filtre.lower() == val.lower()

    return [
        {k: t[k] for k in ("cle", "titre", "type", "statut", "priorite", "sprint", "points")}
        | {"nb_criteres": len(criteres(t["description"]))}
        for t in charger_backlog().values()
        if garde(t["type"], type_ticket) and garde(t["statut"], statut)
        and (not label or label.lower() in (x.lower() for x in t["labels"]))
    ]


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
def lire_ticket(cle: str) -> dict:
    """Renvoie un ticket complet et ses critères d'acceptation numérotés (CA1, CA2…)."""
    t = _ticket(cle)
    return t | {"criteres": {f"CA{i}": c for i, c in enumerate(criteres(t["description"]), 1)}}


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
def auditer_backlog(statut: str = "") -> dict:
    """Contrôle « prêt à tester » de chaque ticket : critères absents, bug sans étapes de
    reproduction, termes non testables (« rapide », « intuitif »…). Règles fixes, explicables."""
    audits = [auditer(t) for t in charger_backlog().values() if not statut or t["statut"].lower() == statut.lower()]
    synthese = {v: sum(a["verdict"] == v for a in audits) for v in ("prêt", "à affiner", "bloqué")}
    ordre = {"bloqué": 0, "à affiner": 1, "prêt": 2}
    return {"synthese": synthese, "tickets": sorted(audits, key=lambda a: ordre[a["verdict"]])}


# --- Gherkin : validation, enregistrement, couverture -------------------------------------

def _analyser_gherkin(texte: str) -> tuple[dict | None, list[str]]:
    try:
        return Parser().parse(TokenScanner(texte)), []
    except ParserError as e:  # CompositeParserException regroupe toutes les erreurs de syntaxe
        erreurs = [str(x) for x in getattr(e, "errors", [])] or [str(e)]
        return None, erreurs


def _scenarios(doc: dict) -> list[dict]:
    enfants = list(doc["feature"].get("children", []))
    for e in list(enfants):
        if "rule" in e:
            enfants += e["rule"].get("children", [])
    return [e["scenario"] for e in enfants if "scenario" in e]


def _tags(noeud: dict) -> set[str]:
    return {t["name"].lstrip("@") for t in noeud.get("tags", [])}


@mcp.tool()
def enregistrer_feature(cle: str, gherkin: str) -> dict:
    """Valide un fichier Gherkin pour un ticket puis l'écrit dans features/<CLE>.feature.
    Refusé si : syntaxe invalide, fonctionnalité sans tag @<CLE>, scénario sans étape Alors/Then,
    scénario sans tag @CAn, ou tag @CAn qui ne correspond à aucun critère du ticket.
    En cas de refus, corriger selon les erreurs renvoyées et rappeler l'outil."""
    t = _ticket(cle)
    cle = t["cle"]
    if not CLE.match(cle):
        raise ToolError(f"Clé de ticket invalide : {cle}")
    doc, erreurs = _analyser_gherkin(gherkin)
    if doc is None:
        return {"enregistre": False, "erreurs": erreurs}
    if not doc.get("feature"):
        return {"enregistre": False, "erreurs": ["Aucune Fonctionnalité/Feature trouvée."]}

    nb_ca = len(criteres(t["description"]))
    scenarios = _scenarios(doc)
    if cle not in _tags(doc["feature"]):
        erreurs.append(f"Ajouter le tag @{cle} sur la ligne Fonctionnalité (traçabilité Jira).")
    if not scenarios:
        erreurs.append("Aucun scénario.")
    for s in scenarios:
        nom = s["name"] or f"ligne {s['location']['line']}"
        types = {p.get("keywordType") for p in s.get("steps", [])}
        if "Outcome" not in types:
            erreurs.append(f"Scénario « {nom} » : aucune étape Alors/Then, il ne vérifie rien.")
        ca = {x for x in _tags(s) if re.fullmatch(r"CA\d+", x)}
        if nb_ca and not ca:
            erreurs.append(f"Scénario « {nom} » : indiquer le ou les critères couverts (@CA1…).")
        for x in sorted(ca):
            if int(x[2:]) > nb_ca:
                erreurs.append(f"Scénario « {nom} » : @{x} n'existe pas, le ticket a {nb_ca} critère(s).")
    if erreurs:
        return {"enregistre": False, "erreurs": erreurs}

    FEATURES.mkdir(parents=True, exist_ok=True)
    chemin = FEATURES / f"{cle}.feature"
    chemin.write_text(gherkin.strip() + "\n", encoding="utf-8", newline="\n")
    return {"enregistre": True, "fichier": str(chemin), "scenarios": len(scenarios), "couverture": _couverture(t)}


def _couverture(t: dict) -> dict:
    nb_ca = len(criteres(t["description"]))
    chemin = FEATURES / f"{t['cle']}.feature"
    base = {"cle": t["cle"], "titre": t["titre"], "nb_criteres": nb_ca}
    if not chemin.exists():
        return base | {"feature": False, "scenarios": 0, "criteres_non_couverts": [f"CA{i}" for i in range(1, nb_ca + 1)]}
    doc, erreurs = _analyser_gherkin(chemin.read_text(encoding="utf-8"))
    if doc is None:
        return base | {"feature": True, "erreurs": erreurs}
    scenarios = _scenarios(doc)
    couverts = {x for s in scenarios for x in _tags(s) if re.fullmatch(r"CA\d+", x)}
    return base | {
        "feature": True,
        "scenarios": len(scenarios),
        "criteres_non_couverts": [f"CA{i}" for i in range(1, nb_ca + 1) if f"CA{i}" not in couverts],
        "cas_limites_ou_erreurs": sum(bool(_tags(s) & {"limite", "erreur"}) for s in scenarios),
    }


@mcp.tool(annotations=ToolAnnotations(read_only_hint=True))
def couverture(cle: str = "") -> dict:
    """Couverture des critères d'acceptation par les scénarios enregistrés, pour un ticket ou
    pour toutes les stories et bugs du backlog."""
    if cle:
        return _couverture(_ticket(cle))
    lignes = [_couverture(t) for t in charger_backlog().values() if t["type"].lower() in ("story", "bug")]
    return {
        "tickets_avec_feature": sum(x["feature"] for x in lignes),
        "tickets_sans_feature": [x["cle"] for x in lignes if not x["feature"]],
        "detail": lignes,
    }


# --- Prompts --------------------------------------------------------------------------------

@mcp.prompt()
def criteres_acceptation(cle: str) -> str:
    """Rédiger les scénarios Gherkin (français) d'un ticket, puis les enregistrer."""
    return f"""Rédige les critères d'acceptation du ticket Jira {cle} en Gherkin, en français.

1. Lis le ticket avec lire_ticket("{cle}") et son audit avec auditer_backlog.
2. Si le ticket est « bloqué » (pas de critères, bug sans reproduction), n'invente pas le besoin :
   liste les questions précises à poser au Product Owner, et propose au plus des scénarios marqués
   @hypothese pour montrer la direction.
3. Sinon écris un fichier qui commence par « # language: fr », avec :
   - la ligne « @{cle} » puis « Fonctionnalité: … » et la user story en description ;
   - au moins un scénario par critère, tagué @CA1, @CA2… selon le critère couvert ;
   - les cas limites et les erreurs en plus, tagués @limite ou @erreur ;
   - des étapes Soit / Quand / Alors / Et concrètes, avec des valeurs chiffrées plutôt que des
     adjectifs (« en moins de 2 secondes », pas « rapidement ») ;
   - « Plan du Scénario » + « Exemples » quand seules les données changent.
4. Enregistre avec enregistrer_feature("{cle}", <texte>). Si des erreurs reviennent, corrige et
   renvoie jusqu'à ce que ce soit enregistré.
5. Termine par couverture("{cle}") et signale les critères que tu juges ambigus ou non testables."""


@mcp.prompt()
def revue_backlog() -> str:
    """Revue « prêt à tester » du backlog, à présenter au Product Owner."""
    return """Fais la revue du backlog avec auditer_backlog.
Présente d'abord la synthèse (prêt / à affiner / bloqué), puis pour chaque ticket bloqué ou à affiner :
le problème en une ligne et la question exacte à poser au Product Owner pour le débloquer.
Propose ensuite, pour les tickets bloqués, une reformulation des critères d'acceptation à faire valider
(marquée comme proposition, jamais présentée comme le besoin réel)."""


if __name__ == "__main__":
    mcp.run()
