# CageBakeCake

An interactive, standalone Python tool for authoring and editing bake cages - the
offset envelope used to project high-poly detail onto a low-poly mesh when baking
normal maps. See `README.md` for the overview and `docs/` for the full design
(`docs/roadmap.md` is the entry point into milestones and phases).

## Working principles

### 1. Think before acting
State assumptions before changing code or docs. If a task has multiple reasonable
interpretations, record the options (in the relevant doc or your reply) instead of
silently picking one. Confusion is a signal to escalate, not to guess.

### 2. Smallest action that helps
Prefer noting an observation over a write, and a small write over a big one. Don't
restructure the docs tree, invent process, or "tidy" things nobody asked you to
touch.

### 3. Surgical changes
Touch only what the task needs and the follow-ups your own changes create. Don't
sweep the whole codebase, don't rewrite docs or milestones, don't change things that
aren't broken.

### 4. Verifiable runs
Every change ends with a clear git commit a human can diff. The success test:
someone reading the commit message and diff can reconstruct exactly what changed and
why, without re-running the tool.
