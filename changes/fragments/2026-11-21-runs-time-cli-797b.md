---
id: 2026-11-21-runs-time-cli-797b
type: fixed
scope: agent
summary:
  en: "A run where the model never worked costs no time; a long brief no longer looks like Claude is missing"
  zh: "模型没有工作的运行不再消耗时间；过长的任务说明不再被误报为未安装 Claude"
  fr: "Une exécution où le modèle n’a pas travaillé ne coûte rien ; un long brief ne passe plus pour Claude absent"
---

- **A run in which the model never worked no longer uses up the application's time.** A run that ended at once because the AI service could not be reached, or its allowance was used up, was charged the minutes it took to start a browser and wait: nine of them took twenty of an application's forty-five. Such runs are on the record and cost nothing; time taken this way before is given back.
- **"Claude Code CLI not found" for an application with a long brief (Windows).** The agent's manual and the brief of the run are given to the Claude command line as its system text, on the command line itself; Windows takes 32,767 characters there and answers "file not found" to more. An application with a long posting, a full profile and a journal of a few runs went over it, could not be started at all, and was reported as Claude not being installed. A long system text is now given in a file; and when the command line is there but cannot be started, the message says that.
