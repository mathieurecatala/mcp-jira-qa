# language: fr
@BOUT-106
Fonctionnalité: Retour d'un produit en ligne sous 30 jours
  En tant que client connecté
  Je veux déclarer le retour d'un produit depuis mon compte
  Afin d'être remboursé sans contacter le service client

  Contexte:
    Soit je suis connecté avec le compte "lea.dupont@example.com"

  @CA1
  Plan du Scénario: Bouton de retour selon l'ancienneté de la livraison
    Soit une commande livrée il y a <jours> jours
    Quand j'ouvre le détail de cette commande
    Alors le bouton "Retourner un article" est <etat>

    Exemples:
      | jours | etat      |
      | 0     | affiché   |
      | 30    | affiché   |
      | 31    | masqué    |

  @CA1 @limite
  Scénario: Commande pas encore livrée
    Soit une commande au statut "Expédiée"
    Quand j'ouvre le détail de cette commande
    Alors le bouton "Retourner un article" est masqué

  @CA2
  Scénario: Choix des articles et du motif
    Soit une commande livrée il y a 10 jours contenant 3 articles
    Quand je sélectionne 2 articles et le motif "Taille trop petite"
    Alors le récapitulatif du retour liste ces 2 articles avec ce motif

  @CA2 @erreur
  Scénario: Motif obligatoire
    Soit une commande livrée il y a 10 jours
    Quand je sélectionne 1 article sans choisir de motif
    Alors le bouton "Valider le retour" reste désactivé

  @CA3
  Scénario: Étiquette prépayée envoyée par e-mail
    Soit un retour validé pour 1 article
    Quand la demande est enregistrée
    Alors une étiquette de retour au format PDF est téléchargeable depuis mon compte
    Et un e-mail contenant cette étiquette est envoyé à "lea.dupont@example.com"

  @CA4 @erreur
  Scénario: Produit personnalisé non retournable
    Soit une commande livrée il y a 5 jours contenant 1 article personnalisé
    Quand j'essaie de sélectionner cet article pour un retour
    Alors l'article n'est pas sélectionnable
    Et le message "Les produits personnalisés ne peuvent pas être retournés" est affiché

  @CA5
  Scénario: Remboursement à la réception de l'article
    Soit un retour validé pour 1 article payé 49,90 € par carte bancaire
    Quand l'entrepôt enregistre la réception de l'article
    Alors un remboursement de 49,90 € est déclenché sur la carte bancaire d'origine

  @CA5 @limite
  Scénario: Pas de remboursement avant réception
    Soit un retour validé dont l'article n'a pas encore été reçu
    Quand 7 jours se sont écoulés depuis la validation
    Alors aucun remboursement n'a été déclenché
