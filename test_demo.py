"""Vérifie le serveur de bout en bout via un vrai client MCP (en mémoire) : python test_demo.py"""

import asyncio
import json
import os
import tempfile

os.environ["JIRA_QA_FEATURES"] = tempfile.mkdtemp()

from mcp import Client

import server

BON = """# language: fr
@BOUT-101
Fonctionnalité: Ajout au panier depuis la fiche produit

  @CA1
  Scénario: Taille non choisie
    Soit la fiche du produit "Veste Oslo" disponible en tailles S, M et L
    Quand je n'ai choisi aucune taille
    Alors le bouton "Ajouter au panier" est désactivé

  @CA2
  Scénario: Le compteur augmente
    Soit un panier contenant 1 article
    Quand j'ajoute 2 "Veste Oslo" en taille M
    Alors le compteur du panier affiche 3

  @CA3 @erreur
  Scénario: Stock insuffisant
    Soit 1 "Veste Oslo" en taille M en stock
    Quand j'ajoute 2 "Veste Oslo" en taille M
    Alors le message "Il ne reste qu'1 article" s'affiche
    Et le panier est inchangé
"""


def donnees(res):
    assert not res.is_error, res.content
    if res.structured_content is None:  # dict non typé : renvoyé en texte JSON
        return json.loads(res.content[0].text)
    return res.structured_content.get("result", res.structured_content)


async def main():
    async with Client(server.mcp) as c:
        outils = {t.name for t in (await c.list_tools()).tools}
        assert outils == {"lister_tickets", "lire_ticket", "auditer_backlog", "enregistrer_feature", "couverture"}, outils
        assert {p.name for p in (await c.list_prompts()).prompts} == {"criteres_acceptation", "revue_backlog"}

        tickets = donnees(await c.call_tool("lister_tickets", {"type_ticket": "Bug"}))
        assert [t["cle"] for t in tickets] == ["BOUT-104", "BOUT-105"], tickets

        t = donnees(await c.call_tool("lire_ticket", {"cle": "bout-106"}))
        assert list(t["criteres"]) == ["CA1", "CA2", "CA3", "CA4", "CA5"] and t["labels"] == ["retours", "sav"]

        audit = donnees(await c.call_tool("auditer_backlog", {}))
        verdicts = {a["cle"]: a["verdict"] for a in audit["tickets"]}
        print("Audit :", audit["synthese"], verdicts)
        assert verdicts["BOUT-101"] == "prêt" and verdicts["BOUT-104"] == "prêt"
        assert verdicts["BOUT-103"] == verdicts["BOUT-105"] == verdicts["BOUT-110"] == "bloqué"
        assert verdicts["BOUT-102"] == verdicts["BOUT-109"] == "à affiner"

        # Refus : syntaxe cassée, puis règles métier (tag ticket, Alors manquant, CA inexistant)
        r = donnees(await c.call_tool("enregistrer_feature", {"cle": "BOUT-101", "gherkin": "# language: fr\nFonctionnalité: x\n  Soit rien\n"}))
        assert not r["enregistre"] and r["erreurs"], r
        mauvais = BON.replace("@BOUT-101\n", "").replace("    Alors le bouton", "    Et le bouton").replace("@CA2", "@CA9")
        r = donnees(await c.call_tool("enregistrer_feature", {"cle": "BOUT-101", "gherkin": mauvais}))
        print("Refus attendu :", json.dumps(r["erreurs"], ensure_ascii=False, indent=1))
        assert not r["enregistre"] and len(r["erreurs"]) == 3, r

        r = donnees(await c.call_tool("enregistrer_feature", {"cle": "BOUT-101", "gherkin": BON}))
        assert r["enregistre"] and r["scenarios"] == 3, r
        assert r["couverture"]["criteres_non_couverts"] == ["CA4"] and r["couverture"]["cas_limites_ou_erreurs"] == 1, r

        cov = donnees(await c.call_tool("couverture", {}))
        assert cov["tickets_avec_feature"] == 1 and "BOUT-101" not in cov["tickets_sans_feature"]

        err = await c.call_tool("lire_ticket", {"cle": "BOUT-999"})
        assert err.is_error and "absent de l'export" in err.content[0].text, err

        p = await c.get_prompt("criteres_acceptation", {"cle": "BOUT-106"})
        assert "BOUT-106" in p.messages[0].content.text

    # Lecture d'une réponse JSON de l'API Jira (descriptions au format ADF)
    json_tickets = server._lire_json(server.ICI / "exemple" / "backlog_jira.json")
    assert [t["cle"] for t in json_tickets] == ["BOUT-201", "BOUT-202"], json_tickets
    assert len(server.criteres(json_tickets[0]["description"])) == 3 and json_tickets[0]["points"] == "3", json_tickets[0]
    assert server.auditer(json_tickets[1])["verdict"] == "prêt", server.auditer(json_tickets[1])
    print("OK : tous les contrôles passent.")


def test_demo():  # même vérification, lancée par pytest
    asyncio.run(main())


if __name__ == "__main__":
    asyncio.run(main())
