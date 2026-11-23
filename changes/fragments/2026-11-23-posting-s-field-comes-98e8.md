---
id: 2026-11-23-posting-s-field-comes-98e8
type: changed
scope: postings
summary:
  en: "A posting's field comes from one fixed list, in your language: a field and a specialty"
  zh: "岗位的“方向”改为一份固定的分类表，按你的界面语言显示：领域加细分方向"
  fr: "Le domaine d’une offre vient d’une liste fixe, dans votre langue : un domaine et une spécialité"
highlight: true
---

The model used to write a posting's field as it liked - "backend", "全栈/后端", "other (mining engineering)" - so
the filter grew with every scan (one copy had 502 different labels for 1,200 postings), in two languages whatever
the page's. It now picks from one list of 18 fields with their specialties (Software engineering → Back end, Full
stack, ML and AI engineering ...; Electronics and hardware; Civil, construction and mining; Healthcare; Business and
finance; and more, so that it fits any line of work), the field alone when no specialty fits, and "Other". Each is
named in English, Chinese and French. The *Field* filter lists the fields with how many, their specialties under
them; choosing a field takes in its specialties. Postings labelled before are sorted into the list by the model in
the background after the update ("Sort postings into fields" in the activity); until then they show their old label
under *Not sorted yet*.
