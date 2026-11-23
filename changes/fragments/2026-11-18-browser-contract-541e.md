---
id: 2026-11-18-browser-contract-541e
type: added
scope: agent
summary:
  en: "A contract both browsers keep to, tested in the automated and the ordinary browser"
  zh: "两种浏览器共同遵守的契约，在自动化浏览器和普通浏览器中分别测试"
  fr: "Un contrat que les deux navigateurs respectent, testé dans le navigateur automatisé et dans l’ordinaire"
---

A contract both browsers keep to (`tests/test_browser_contract.py`): the selector shapes the program writes, the frames it looks for, boxes the page itself is in charge of, files, windows and the mouse - each written once and run in the automated and in the ordinary browser against the same expected answer. The sign-in window has the same (`tests/test_takeover.py`). The tests that are run once more in the ordinary browser are one list now (`tests/ordinary_browser.txt`), with the sign-in flows in it.
