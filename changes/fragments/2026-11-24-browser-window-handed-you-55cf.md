---
id: 2026-11-24-browser-window-handed-you-55cf
type: fixed
scope: agent
summary:
  en: "A browser window handed to you opens maximized, and its page follows the window: a site's check is never off the screen"
  zh: "交给你操作的浏览器窗口会最大化打开，页面跟随窗口大小：网站的人机验证不会再跑到屏幕外"
  fr: "Une fenêtre de navigateur qui vous est confiée s’ouvre en plein écran et sa page suit la fenêtre : une vérification n’est plus hors de l’écran"
highlight: true
---

The program's browser drew its page at a fixed size (1366 x 900) even in a window on your screen. With the screen scaled, that page did not fit, and a site's check of the browser ("click all the animal icons"), opened in the page's bottom right corner, was off the screen and out of reach - maximizing the window changed nothing, because the page did not follow it. A window on your screen now opens maximized, and its page is as large as the window and follows it when you resize it. Hidden pages, and the pictures of a page shown in the web page on a server, keep a size of their own.
