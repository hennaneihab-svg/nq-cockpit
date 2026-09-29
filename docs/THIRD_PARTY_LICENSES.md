# Licences Tierces (Third-Party Licenses)

Ce document répertorie les licences et conditions d'attribution applicables aux dépendances et au code tiers analysé ou adapté dans le cadre du projet NQ Cockpit.

---

## 1. `gex-dashboard` (Darthreign)

- **Dépôt d'origine** : `vendor/gex-dashboard` (https://github.com/Darthreign/gex-dashboard)
- **Licence** : MIT
- **Statut dans NQ Cockpit** : Composants mathématiques et logiques adaptés dans `src/nqcockpit/` (sans reprise des modules d'automatisation, backup ou courtage propriétaire).
- **Règle d'attribution** : Tout fichier de `src/nqcockpit/` adapté ou dérivé de ce dépôt portera obligatoirement en tête la mention suivante :
  ```python
  # Adapté de Darthreign/gex-dashboard (MIT), copyright conservé.
  ```

### Texte intégral de la licence MIT (`vendor/gex-dashboard/LICENSE`)

```text
MIT License

Copyright (c) 2026 Darthreign

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 2. `gammagrid` (Gammagrid)

- **Dépôt d'origine** : `vendor/gammagrid`
- **Licence** : GNU Affero General Public License v3.0 (AGPLv3)
- **Statut dans NQ Cockpit** : **Aucun code repris**. En raison du caractère viral et contraignant de la licence AGPLv3 et de l'incompatibilité architecturale (dépendances Streamlit / PostgreSQL / Docker), aucun extrait de code de ce dépôt n'est utilisé, réutilisé ou incorporé dans NQ Cockpit.

---

## 3. `gex-analytics` (pikki622)

- **Dépôt d'origine** : `vendor/gex-analytics`
- **Licence** : MIT (2024 pikki622)
- **Statut dans NQ Cockpit** : **Aucun code repris**. En raison de fragilités structurelles dans l'alignement des chaînes d'options (concaténation naïve par colonnes sans jointure sur strikes) et de l'absence de tests unitaires, aucun code de ce dépôt n'est intégré dans NQ Cockpit.
