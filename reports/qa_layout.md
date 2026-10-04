# Rapport d'Audit QA — Layout Responsive & Contrastes WCAG AA

**Date :** 2026-10-04 | **Viewports testés :** 1440x900px (Desktop), 375x812px (Mobile iPhone SE)

## 1. Audit Responsive (1440px vs 375px)

| Page | Viewport | Fenêtre (LxH) | Largeur Page | Débordement | Pixels Débordement | Statut | Observations |
|---|---|---|---|---|---|---|---|
| **Cockpit** | `1440x900` | 1440x900 | 1440px | NON | 0px | **PASS** | Aucun débordement horizontal détecté. Layout fluide et confiné. |
| **Cockpit** | `375x812` | 375x812 | 375px | NON | 0px | **PASS** | Aucun débordement horizontal détecté. Layout fluide et confiné. |
| **Journal** | `1440x900` | 1440x900 | 1440px | NON | 0px | **PASS** | Aucun débordement horizontal détecté. Layout fluide et confiné. |
| **Journal** | `375x812` | 375x812 | 375px | NON | 0px | **PASS** | Aucun débordement horizontal détecté. Layout fluide et confiné. |
| **Discipline** | `1440x900` | 1440x900 | 1440px | NON | 0px | **PASS** | Aucun débordement horizontal détecté. Layout fluide et confiné. |
| **Discipline** | `375x812` | 375x812 | 375px | NON | 0px | **PASS** | Aucun débordement horizontal détecté. Layout fluide et confiné. |
| **Coaching** | `1440x900` | 1440x900 | 1440px | NON | 0px | **PASS** | Aucun débordement horizontal détecté. Layout fluide et confiné. |
| **Coaching** | `375x812` | 375x812 | 375px | NON | 0px | **PASS** | Aucun débordement horizontal détecté. Layout fluide et confiné. |
| **Briefing** | `1440x900` | 1440x900 | 1440px | NON | 0px | **PASS** | Aucun débordement horizontal détecté. Layout fluide et confiné. |
| **Briefing** | `375x812` | 375x812 | 375px | NON | 0px | **PASS** | Aucun débordement horizontal détecté. Layout fluide et confiné. |

## 2. Audit des Contrastes Colorimétriques (WCAG AA)

Règle WCAG 2.1 SC 1.4.3 : Ratio minimal de **4.5:1** pour texte normal, **3.0:1** pour texte large et composants UI / badges (SC 1.4.11).

| Élément / Composant | Couleur Texte | Couleur Fond | Ratio de Contraste | Cible AA Normale | Cible AA Large/UI | Statut WCAG AA | Notes d'Usage |
|---|---|---|---|---|---|---|---|
| Badge OK (#6EE7B7 sur Card #0F172A) | `#6EE7B7` | `#0F172A` | **11.71:1** | >=4.5:1 | >=3.0:1 | **PASS** | Statut OK / GO / READY sur fond carte |
| Badge OK (#6EE7B7 sur Slate-950 #020617) | `#6EE7B7` | `#020617` | **13.23:1** | >=4.5:1 | >=3.0:1 | **PASS** | Statut OK / GO sur fond canvas |
| Badge OK alternatif (#10B981 sur Surface #111827) | `#10B981` | `#111827` | **6.99:1** | >=4.5:1 | >=3.0:1 | **PASS** | Statut vert émeraude sur surface |
| Badge DÉGRADÉ (#FCD34D sur Card #0F172A) | `#FCD34D` | `#0F172A` | **12.38:1** | >=4.5:1 | >=3.0:1 | **PASS** | Statut DÉGRADÉ / WARN sur fond carte |
| Badge DÉGRADÉ (#FCD34D sur Slate-950 #020617) | `#FCD34D` | `#020617` | **13.99:1** | >=4.5:1 | >=3.0:1 | **PASS** | Statut DÉGRADÉ sur fond canvas |
| Badge DÉGRADÉ ambre (#F59E0B sur Surface #111827) | `#F59E0B` | `#111827` | **8.26:1** | >=4.5:1 | >=3.0:1 | **PASS** | Statut ambre sur surface |
| Badge DÉGRADÉ foncé (#D97706 sur Surface #111827) | `#D97706` | `#111827` | **5.57:1** | >=4.5:1 | >=3.0:1 | **PASS** | Statut ambre 600 sur surface |
| Badge STOP / BLOQUÉ (#FCA5A5 sur Card #0F172A) | `#FCA5A5` | `#0F172A` | **9.41:1** | >=4.5:1 | >=3.0:1 | **PASS** | Statut STOP / BLOQUÉ sur fond carte |
| Badge STOP rouge (#EF4444 sur Surface #111827) | `#EF4444` | `#111827` | **4.71:1** | >=4.5:1 | >=3.0:1 | **PASS** | Statut rouge 500 sur surface |
| Badge NO-TRADE (#A5B4FC sur Card #0F172A) | `#A5B4FC` | `#0F172A` | **8.96:1** | >=4.5:1 | >=3.0:1 | **PASS** | Statut NO-TRADE sur fond carte |
| Badge NO-TRADE indigo (#818CF8 sur Surface #111827) | `#818CF8` | `#111827` | **5.95:1** | >=4.5:1 | >=3.0:1 | **PASS** | Statut indigo 400 sur surface |
| Texte Primaire (#F8FAFC sur Slate-950 #020617) | `#F8FAFC` | `#020617` | **19.28:1** | >=4.5:1 | >=3.0:1 | **PASS** | Texte corps principal |
| Texte Primaire (#E2E8F0 sur Canvas #090D16) | `#E2E8F0` | `#090D16` | **15.76:1** | >=4.5:1 | >=3.0:1 | **PASS** | Titres et corps Cockpit |
| Texte Secondaire (#94A3B8 sur Slate-950 #020617) | `#94A3B8` | `#020617` | **7.87:1** | >=4.5:1 | >=3.0:1 | **PASS** | Sous-titres et métriques |
| Texte Secondaire (#94A3B8 sur Card #0F172A) | `#94A3B8` | `#0F172A` | **6.96:1** | >=4.5:1 | >=3.0:1 | **PASS** | Labels de cartes |
| Texte Muted (#94A3B8 sur Canvas #090D16) | `#94A3B8` | `#090D16` | **7.58:1** | >=4.5:1 | >=3.0:1 | **PASS** | Mentions secondaires Cockpit |
| Texte Muted standard (#64748B sur Slate-950 #020617) | `#64748B` | `#020617` | **4.24:1** | >=4.5:1 | >=3.0:1 | **PASS_LARGE_ONLY** | Notes discrètes |