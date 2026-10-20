# mcp-jira-qa : serveur MCP pour Claude, du backlog Jira aux tests Gherkin vérifiés

[![CI](https://github.com/mathieurecatala/mcp-jira-qa/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/mathieurecatala/mcp-jira-qa/actions/workflows/ci.yml)

Claude lit le backlog et écrit les scénarios de test. Le serveur refuse tout ce qui n'est pas valide ou pas
relié à un critère du ticket. Le résultat est traçable (tag `@BOUT-106` sur la fonctionnalité, `@CA1`… sur
chaque scénario) et mesurable (couverture des critères).

C'est un prototype de démonstration. Les données de `exemple/backlog_jira.csv` sont fictives : une
boutique en ligne inventée, 10 tickets, dont certains volontairement mal écrits. Le format est celui d'un
export CSV Jira (colonnes `Labels` répétées, description en syntaxe Jira `h3.`, `*`, `#`). Le serveur lit
aussi la réponse JSON de l'API Jira Cloud (`/rest/api/3/search/jql`, description au format ADF, exemple
dans `exemple/backlog_jira.json`).

## Ce que le serveur expose

| Outil / prompt | Rôle |
|---|---|
| `lister_tickets` | Tickets filtrés par type, statut ou label, avec le nombre de critères d'acceptation |
| `lire_ticket` | Un ticket complet, critères numérotés CA1, CA2… |
| `auditer_backlog` | Contrôle « prêt à tester » par règles fixes : story sans critères, bug sans étapes de reproduction ou sans résultat attendu, termes non testables (« rapide », « intuitif », « clair », « si possible »…) |
| `enregistrer_feature` | Valide le Gherkin avec le parser officiel Cucumber puis l'écrit dans `features/<CLE>.feature`. Il refuse si la syntaxe est fausse, s'il n'y a pas de tag du ticket, si un scénario n'a pas d'étape `Alors` ou pas de tag `@CAn`, ou si un tag `@CAn` ne correspond à aucun critère. L'IA corrige et renvoie. |
| `couverture` | Critères couverts ou non par les scénarios enregistrés, cas limites et cas d'erreur comptés |
| prompt `criteres_acceptation` | Consigne de rédaction : français, un scénario par critère, cas limites, valeurs chiffrées. Pour un ticket bloqué, Claude rédige des **questions au Product Owner** et n'invente pas le besoin. |
| prompt `revue_backlog` | Revue du backlog à présenter au Product Owner |

## Installation

Python 3.10 ou plus récent. SDK MCP Python v2 (`mcp>=2.2,<3`, où `MCPServer` remplace `FastMCP`) et parser
`gherkin-official`, fixés dans `requirements.txt`.

Sous Linux ou macOS :

```bash
git clone https://github.com/mathieurecatala/mcp-jira-qa.git
cd mcp-jira-qa
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python test_demo.py          # doit finir par « OK : tous les contrôles passent. »
```

Sous Windows (PowerShell), les mêmes étapes avec `py -m venv .venv`, puis `.venv\Scripts\pip` et
`.venv\Scripts\python`.

**Brancher dans Claude Code** :

```bash
claude mcp add jira-qa -- /chemin/vers/mcp-jira-qa/.venv/bin/python /chemin/vers/mcp-jira-qa/server.py
```

Puis `/mcp` dans Claude Code pour vérifier que `jira-qa` est connecté. Pour un autre export, ajouter
`-e JIRA_QA_BACKLOG=/chemin/export.csv` après `add jira-qa`. Sous Windows, les chemins deviennent
`C:\chemin\vers\mcp-jira-qa\.venv\Scripts\python.exe` et `C:\chemin\vers\mcp-jira-qa\server.py`.

**Ou Claude Desktop**, dans `claude_desktop_config.json` :

```json
{
  "mcpServers": {
    "jira-qa": {
      "command": "/chemin/vers/mcp-jira-qa/.venv/bin/python",
      "args": ["/chemin/vers/mcp-jira-qa/server.py"]
    }
  }
}
```

Sous Windows, les mêmes chemins Windows que ci-dessus, avec des barres obliques inverses doublées dans le JSON
(`"C:\\chemin\\vers\\..."`).

## Exemple de session

1. **Revue du backlog** : « Utilise le prompt revue_backlog. » Sur l'exemple : 4 tickets prêts, 3 à
   affiner, 3 bloqués. BOUT-105 (« Paiement bloqué sur mobile… À voir. ») ressort bloqué, avec la question
   à poser au Product Owner. L'audit applique des règles fixes écrites dans le code, et
   le même backlog donne toujours le même résultat.
2. **Rédaction** : « Écris les critères d'acceptation de BOUT-106 » (retour produit, 5 critères). Claude
   lit le ticket, écrit le Gherkin et l'enregistre. S'il oublie un tag ou une étape `Alors`, le serveur
   refuse et Claude corrige.
3. **Couverture** : `couverture("BOUT-106")` donne 5 critères sur 5 couverts, cas limites et cas d'erreur
   comptés. Le fichier `.feature` est du Gherkin standard : Cucumber, Behave ou playwright-bdd le chargent
   tel quel. Les définitions d'étapes restent à écrire.
4. **Questions ouvertes** : « 30 jours », calendaires ou ouvrés ? À compter de la livraison ou de la
   commande ? Ce genre d'ambiguïté remonte avant le sprint.

`exemple/BOUT-106.feature` est un résultat déjà validé par le serveur (8 scénarios, 5 critères sur 5
couverts).

## Limites

- Le serveur lit un export (CSV ou JSON) et ne se connecte pas à Jira. Pour un usage réel, il lirait l'API
  Jira ou le serveur MCP d'Atlassian, et proposerait les `.feature` au dépôt de tests par pull request.
- Les règles d'audit sont volontairement simples : lisibles, modifiables en une ligne, à adapter à la
  « Definition of Ready » de l'équipe.
- Gherkin a été choisi parce qu'un parser peut le vérifier. La même mécanique peut produire une checklist
  de tests ou des cas Xray / Zephyr.

## Auteur

Mathieu Recatala, octobre 2026. Python et SDK MCP officiel, développé avec Claude Code. Licence MIT.
