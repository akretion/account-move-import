# Configuration Payfit pour Account Move Import

Ce module inclut une configuration pré-remplie pour importer les fichiers CSV exportés depuis Payfit.

## Format du fichier Payfit (2025)

Le CSV exporté depuis Payfit contient les colonnes suivantes :

| Position | Colonne | Description | Mapping Odoo |
|----------|---------|-------------|--------------|
| A (0) | EcritureDate | Date de l'écriture | `col_date` |
| B (1) | CompteNum | Numéro de compte | `col_account` |
| C (2) | CompteLib | Libellé du compte | `col_name` |
| D (3) | EmployeLib | Nom de l'employé | *(ignoré)* |
| E (4) | Debit | Montant débit | `col_debit` |
| F (5) | Credit | Montant crédit | `col_credit` |

**Note importante** : Le format Payfit 2025 n'exporte plus le code journal. Vous devrez donc **obligatoirement sélectionner un journal** lors de l'import.

## Paramètres CSV

- **Encodage** : UTF-8
- **Délimiteur** : `;` (point-virgule)
- **Séparateur décimal** : `.` (point)
- **Format de date** : `%d/%m/%Y` (ex: 31/12/2024)
- **Ligne de départ** : 2 (ignore l'en-tête)

## Utilisation

### 1. Installer le module

```bash
# Le module doit être installé avec ses dépendances
pip install openpyxl xlrd
```

### 2. Configurer le journal par défaut

**Important** : Payfit n'exporte plus le code journal, il faut donc configurer un journal par défaut.

1. Allez dans **Comptabilité > Configuration > Comptabilité > Configurations d'import d'écritures**
2. Ouvrez la configuration **"Payfit CSV"**
3. Dans le champ **"Force Journal"**, sélectionnez le journal **"OD - Opérations diverses"** (ou le journal de votre choix)
4. Enregistrez

### 3. Importer un fichier Payfit

1. Allez dans **Comptabilité > Comptabilité > Import d'écritures**
2. Sélectionnez la configuration **"Payfit CSV"**
3. Choisissez votre fichier CSV exporté depuis Payfit
4. Cliquez sur **Importer**

Les écritures seront créées dans le journal configuré (OD par défaut si vous avez suivi l'étape 2).

### 4. Options supplémentaires

La configuration Payfit par défaut :
- Ne comptabilise **pas** automatiquement les écritures (vous pouvez modifier ce comportement)
- Ignore les lignes avec débit = crédit = 0
- Utilise la méthode de séparation des écritures "Balanced" (équilibrée)

## Personnalisation

Si le format Payfit change ou si vous avez besoin d'ajuster la configuration :

1. Dupliquez la configuration "Payfit CSV"
2. Modifiez les paramètres selon vos besoins
3. Ajustez le mapping des colonnes si nécessaire

## Différences avec la version 16.0

Dans la version 16.0, le support Payfit était codé en dur dans le code Python.
Dans la version 19.0, nous utilisons le système de configuration flexible qui permet :
- De modifier la configuration sans toucher au code
- D'avoir plusieurs configurations Payfit si besoin
- De dupliquer et personnaliser facilement

## Support

Pour toute question ou problème, contactez [Akretion France](https://akretion.com/)

---
*Configuration créée pour la migration 19.0 - Février 2026*
