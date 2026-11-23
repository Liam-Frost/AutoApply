---
id: 2026-11-23-ai-service-s-saved-8a06
type: security
scope: ai
summary:
  en: "An AI service's saved key is sent only to the address it was saved for; the address is checked"
  zh: "AI 服务已保存的密钥只发往保存时的地址；服务地址会先经过检查"
  fr: "La clé enregistrée d’un service d’IA n’est envoyée qu’à l’adresse pour laquelle elle a été enregistrée ; l’adresse est vérifiée"
---

Listing the models of an OpenAI-compatible service with an address typed in the settings sent the key saved for that
service to whatever host the address named. The saved key now goes only to the address it was saved for (or the
service's own); for another address the key is typed with it. An address must be a plain `http://` or `https://`
address with a host - no user name or password, no `?` or `#` in it. A service on your own computer or network
(Ollama, LM Studio) works as before. With nothing typed, the list is asked of the address saved.
