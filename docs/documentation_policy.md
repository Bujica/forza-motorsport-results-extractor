# Documentation Policy

Status: current
Audience: maintainer, developer, LLM
Lifecycle: permanent
Scope: documentation ownership, naming, lifecycle, and update rules
Last verified: 2026-06-05
Supersedes: ad hoc documentation placement rules in `docs/README.md`
Related tests: none

This project treats documentation as part of the maintenance contract. The goal
is to make the current state, active contracts, historical evidence, and future
plans easy to distinguish.

## Documentation Layers

Documentation is organized into the following layers.

| Layer | Location | Purpose |
| --- | --- | --- |
| Project status | `docs/project_status.md` | Current development state, known issues, and next approved work. |
| User guides | `docs/user/` | User-facing operation guides. |
| Developer guides | `docs/developer/` | Developer setup, maintenance, and release guidance. |
| Contracts | `docs/contracts/` | Normative behavior the code must satisfy. |
| Architecture | `docs/architecture/` | Structural design and technical rationale. |
| Plans | `docs/plans/` | Approved or proposed work that is not complete yet. |
| History | `docs/history/` | Completed work, audits, run postmortems, and handoff evidence. |

Top-level documentation is limited to navigation and project-wide policy/state:

| Document | Purpose |
| --- | --- |
| `../QUICK_GUIDE.md` | Fast install, launch, common commands, and document entry points. |
| `docs/README.md` | Documentation map and navigation instructions. |
| `docs/documentation_policy.md` | Documentation naming, lifecycle, ownership, and update rules. |
| `docs/project_status.md` | Current stage, known issues, and next approved work. |

`README.md` files are indexes and local navigation aids. They must not absorb
substantial guide, contract, architecture, plan, or historical content.

## Required Header

Every permanent or plan document must begin with this header:

```text
Status: current | draft | planned | deprecated | archived
Audience: user | maintainer | developer | LLM
Lifecycle: permanent | release | temporary | historical
Scope: ...
Last verified: YYYY-MM-DD
Supersedes: ...
Related tests: ...
```

Historical records may use the same fields in prose form, but they must clearly
state that they are not the current contract.

`Last verified` means a maintainer checked that the document reflects the
current code, structure, behavior, environment, or project state appropriate to
that document type. It is not a reading timestamp. Updating the date without
checking the relevant current state makes the field meaningless.

## Naming Rules

Use lowercase file names with underscores. The only uppercase documentation
exceptions are conventional entry points outside topic directories:
`README.md`, `CHANGELOG.md`, and `QUICK_GUIDE.md`.

```text
docs/project_status.md
docs/documentation_policy.md
docs/user/advanced_tools.md
docs/developer/guide.md
docs/contracts/review.md
docs/contracts/best_laps.md
docs/architecture/database.md
docs/plans/YYYY-MM-DD_area_plan.md
docs/history/YYYY-MM-DD_area_kind.md
```

Prefer singular domain names unless the project vocabulary is plural, such as
`best_laps`.

## Source Of Truth Rules

There must be one primary place for each kind of information.

| Information | Source of truth |
| --- | --- |
| Current project state | `docs/project_status.md` |
| Current behavior contract | `docs/contracts/*.md` |
| Technical structure | `docs/architecture/*.md` |
| User workflow | `docs/user/*.md` |
| Developer setup and package conventions | `docs/developer/guide.md` |
| Advanced GUI tools operation | `docs/user/advanced_tools.md` |
| Future approved work | `docs/plans/*.md` |
| Past evidence and postmortems | `docs/history/*.md` |
| Release changes | `../CHANGELOG.md` |

Plans and history must not be cited as the current behavior contract. If a plan
or historical record changes the expected behavior, the relevant contract must
be updated in the same change.

Contracts define intended behavior. Architecture explains the current
structure. Guides explain operation. Project status records known issues and
current divergences between intended behavior and current implementation. Plans
describe approved future work. History records past evidence.

## When To Create A Document

Create a new permanent document only when the topic has a distinct maintenance
role. A module or subsystem deserves its own contract or architecture document
when at least one condition is true:

- It defines persistent data or derived state.
- It crosses multiple packages or layers.
- It affects database integrity, rebuild, review, or output correctness.
- It has user-facing workflow semantics.
- It has states that are not obvious from the code.
- It is risky enough that future changes need explicit invariants.

Do not create a permanent document for small widgets, simple adapters, or
helpers whose behavior is already covered by a broader contract and tests.

## When To Update Documentation

Documentation must be updated in the same change as code when the change:

- alters a database table, status value, invariant, or derived-state rule;
- changes review, rebuild, best-lap, file-management, or lab behavior;
- changes GUI workflow or operator-facing terminology;
- adds, removes, or renames a CLI command or document;
- changes validation gates or expected troubleshooting flow.

`docs/project_status.md` must be updated after major milestones, after a failed
or successful full reconstruction, and before handing a complex task to another
session.

`Known Issues` sections must be updated whenever a maintainer discovers,
confirms, fixes, intentionally defers, or invalidates a current problem that
affects a contract, user workflow, rebuild/review correctness, database
integrity, GUI behavior, validation confidence, or next-work prioritization.
Add an issue when current behavior is known to be wrong or misleading, even if
the fix is already planned. Update an issue when its scope, risk, owner plan, or
evidence changes. Remove it only when the implementation and tests satisfy the
contract, or when investigation proves the issue is not real; in both cases,
record the completed work in the relevant plan, history entry, or changelog when
the change is maintenance-visible.

`../CHANGELOG.md` must be updated for every change that affects users,
contracts, architecture, CLI behavior, GUI behavior, database schema, migration
policy, validation gates, or maintenance workflow. Purely internal changes may
skip changelog only when they do not alter observable behavior, contracts, or
maintenance expectations.

`../CHANGELOG.md` must keep an `Unreleased` section at the top. During release,
move `Unreleased` entries into the dated version section and create a new empty
`Unreleased` section.

## Known Issues

Project status and contracts may include a `Known Issues` section when the
intended behavior is approved but the current implementation does not yet
satisfy it, or when an unresolved problem affects maintenance decisions.

Use this section only for unresolved current issues. Each issue must state:

- the intended behavior;
- the current behavior that fails the contract;
- the condition for removing the issue.

Remove the section when the implementation satisfies the contract. Do not use
known-issue sections to normalize indefinite technical debt or to hide
uncertainty about what the contract should be. If the intended behavior is not
yet decided, write a plan or decision note instead of disguising the uncertainty
as a known issue.

## When To Archive Or Remove

Archive a document into `docs/history/` when it has lasting evidence value but
is no longer the current contract.

Remove a document when all are true:

- it duplicates another current document;
- it is not needed for traceability;
- links have been updated;
- the removal is mentioned in `CHANGELOG.md` when it affects users or
  maintainers.

Do not leave obsolete documents in permanent locations with only a note at the
top. That makes stale information look authoritative.

## LLM Orientation Rule

A new LLM maintenance session should read documents in this order:

1. `docs/project_status.md`
2. The relevant file under `docs/contracts/`
3. The relevant file under `docs/architecture/`
4. `docs/developer/guide.md` for package and validation conventions
5. `docs/history/` only when past evidence is needed

If these documents disagree, contracts override guides, project status explains
current known issues, architecture explains structure, and history never overrides
current contracts. The authority order is:

```text
contracts -> architecture -> guides
project_status explains current known issues
plans describe approved future work
history records past evidence only
```

## Completion Checklist

Before a documentation-sensitive task is complete, verify:

- the relevant contract was updated when intended behavior changed;
- the relevant user or developer guide was updated when workflow changed;
- `docs/project_status.md` was updated when stage, known issues, or next work changed;
- `../CHANGELOG.md` was updated when the change is user-visible or
  maintenance-visible;
- active document links resolve;
- obsolete permanent documents were moved, merged, archived, or removed.
