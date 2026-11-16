---
paths:
  - "backend/**/*.py"
---

# Prompt Template Maintenance

** templates ** - all prompt templates ( chain-of-thought, any other prompt type) need to be maintained in a single file called 'PromptTemplates.py' under backend/prompt, never inline in other modules.
** access ** - templates are fetched through one function that receives the template name and the variables as kwargs, e.g. `get_prompt("few-shot", question=q, context=c)`; callers must not build prompt strings themselves.
** variables ** - templates use named placeholders only; a missing or unknown variable must raise a clear error, and an unknown template name must raise an error listing the valid names.
