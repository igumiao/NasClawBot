# NasClawBot Domain

NasClawBot helps a user acquire and organize media on a self-hosted NAS while keeping automated and user-triggered behavior distinct.

## Language

**Media Organization**:
The overall capability for identifying, naming, and placing downloaded media into the library.
_Avoid_: Download Supervision

**Manual Organization**:
Media Organization explicitly initiated by the user through the conversation Agent.
_Avoid_: Fallback Organization

**Automatic Post-download Organization**:
Media Organization triggered automatically after a download reaches completion and the configured policy authorizes it.
_Avoid_: Download Supervision, Automatic Download

**Download Watch**:
Background observation of one download until it completes or fails; it may trigger a follow-up action but does not organize media itself.
_Avoid_: Download Workflow, Organization Task

**Organize WorkerAgent**:
A task-scoped Agent that applies the organization skill to one authorized media source and reports the outcome.
_Avoid_: Agent Session, Download Agent
