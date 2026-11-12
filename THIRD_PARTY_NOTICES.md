# Mentions tierces

ChipCard embarque ou s'appuie sur les bibliothèques suivantes.

| Bibliothèque | Licence | Usage |
|---|---|---|
| [pyscard](https://github.com/LudovicRousseau/pyscard) | BSD-2-Clause | Communication PC/SC avec les lecteurs de cartes à puce |
| [pywebview](https://github.com/r0x0r/pywebview) | BSD-3-Clause | Fenêtre native macOS autour de l'interface web |
| [PyInstaller](https://pyinstaller.org/) | GPL-2.0 (avec exception pour les programmes empaquetés) | Construction de l'application autonome |
| [Pillow](https://python-pillow.org/) | HPND | Génération de l'icône de l'application (outil de build uniquement) |

Ce projet s'appuie sur le sous-système PC/SC de macOS pour dialoguer avec les lecteurs de cartes à puce (testé avec un HID OMNIKEY 3121). "OMNIKEY" et les autres marques citées appartiennent à leurs propriétaires respectifs ; ce projet n'est affilié à, ni approuvé par, aucun fabricant de lecteurs de cartes.
