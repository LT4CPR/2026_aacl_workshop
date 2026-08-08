# Taxonomy guide

The crisis taxonomy (`taxonomy.yaml`, version 1.2) defines the event and entity
categories underlying the situation reports. Understanding it is not required
to produce a report, but it explains why content is organized the way it is,
and it makes section placement predictable rather than a matter of judgment.

The taxonomy has four parts: **entity types**, **event types** grouped into
superclasses, **argument roles** connecting them, and **relations** between
events or between entities.

---

## 1. Entity types

Seven types. Each has a hierarchy of subtypes, which the file records in full;
the top level is what matters for reading reports.

| Type | Covers | Examples from the corpus |
| --- | --- | --- |
| `person` | Individuals and groups of people | residents, patients, crew, volunteers |
| `organization` | Agencies, NGOs, companies, emergency services | a volcano observatory, a relief foundation, a rail operator |
| `hazard` | The threat itself | a cyclone, a pathogen, a toxic gas, volcanic ash |
| `infrastructure` | Physical facilities and systems | a hospital, a substation, a rail yard, a ferry |
| `resource` | Materials and services in demand | oral rehydration salts, purification kits, bedding |
| `loc` | Places | towns, provinces, rivers, venue areas |
| `time` | Temporal expressions | dates, durations |

Two distinctions cause most confusion:

**`hazard` versus `infrastructure`.** A named storm or fire is a `hazard`; the
building it damages is `infrastructure`. A named disaster such as a cyclone is
a `hazard` even though it has a proper name.

**`organization` versus `person`.** An agency issuing a statement is an
`organization`. A named official speaking for it is a `person`. Reports
generally attribute to the organization.

---

## 2. Event types

Twenty-nine event types in thirteen superclasses. The superclass determines
which report section the content belongs to, which is the practical reason to
know them.

| Superclass | Event types | Report section |
| --- | --- | --- |
| `person_state_change` | INJURE, KILL, MISSING, RESCUE, TRAP, FOUND | 3 Casualties and human impact |
| `object_infra_change` | DAMAGE, DESTROY, DISRUPT_SERVICE, RESTORE | 4 Infrastructure and service impact |
| `movement_displacement` | EVACUATE, DISPLACE, RETURN | 5 Displacement and movement |
| `situational_state` | SITUATION_STATE, HAZARDOUS_CONDITION | 6 Hazard assessment |
| `response` | DEPLOY, COORDINATE | 7 Response actions |
| `communication` | WARN, REQUEST, INFORM | 8 Communication and information |
| `provide_help` | PROVIDE_HELP | 9 Aid and relief |
| `receive_help` | RECEIVE_HELP | 9 Aid and relief |
| `transaction` | TRANSFER | 9 if aid-directed, otherwise 10 |
| `org_admin` | MEETING | 10 Organizational and administrative activity |
| `socio_political` | POLICY_CHANGE, PROTEST, FUNDING | 10 for POLICY_CHANGE and FUNDING, 11 for PROTEST |
| `social` | SOCIAL_SUPPORT | 11 Social and community response |
| `cognitive` | ATTITUDE | 11 Social and community response |

Three boundaries are worth stating explicitly, because they are the ones the
taxonomy defines against intuition:

**`response` excludes aid.** The superclass is defined as *non-aid* operational
response. Deploying a search team is `response` and belongs in section 7.
Distributing water is `provide_help` and belongs in section 9. This is why
sections 7 and 9 are separate.

**`transaction` splits by recipient.** A transfer whose recipient is affected
people or a relief actor is aid, and belongs in section 9. Other economic
transfers belong in section 10.

**`provide_help` and `receive_help` are the same event from two sides.** An
agency delivering supplies is `provide_help`; a community receiving them, or
reporting that they did not arrive, is `receive_help`. Unmet needs are recorded
on the receiving side.

The mapping in the table is a guide, not an absolute. `receive_help` appears in
section 3 where the receipt is medical treatment, since the content is about
human impact rather than aid logistics. Where a superclass could plausibly
serve two sections, the section's own subject matter takes precedence.

---

## 3. Argument roles

Roles follow PropBank conventions. They record who did what to whom, where, and
why.

| Role | Meaning |
| --- | --- |
| `ARG0` | Agent, causer, or doer |
| `ARG1` | Affected entity or theme |
| `ARG2` | Secondary core participant, often a beneficiary |
| `ARGM-LOC` | Where the event occurs |
| `ARGM-TMP` | When it occurs |
| `ARGM-CAU` | The hazard or reason causing it |
| `ARGM-SRC` | Origin of movement or transfer |
| `ARGM-DIR` | Destination of movement or transfer |
| `ARGM-MNR` | Manner or means |
| `ARGM-PRP` | Purpose |

Each event type declares which roles it takes, what each means for that type,
and which entity types can fill it. For example, `KILL` declares:

```yaml
KILL:
  description: One or more people die.
  arg_roles:
    ARG0:      cause of death           (person, hazard, infrastructure, organization)
    ARG1:      person(s) who died       (person)
    ARGM-LOC:  location of the deaths   (loc)
    ARGM-TMP:  time of the deaths       (time)
  required_roles:
    any_of:    [ARG0, ARG1, ARGM-LOC]
    preferred: [ARG1]
```

`required_roles` states that the event must name at least one entity in one of
the `any_of` roles. This is why report bullets consistently name a place, an
actor, or an affected group rather than describing an event in the abstract.

Some event types also declare `event_fields` for type-specific attributes:
`WARN` records a warning channel and urgency, `PROVIDE_HELP` records a delivery
mode, `MEETING` records purpose and outcome.

---

## 4. Event metadata

Two attributes apply to every event.

**`realis`** — whether the event actually occurred: `actual`, `generic`,
`possible`, `conditional`, `planned`, `pledged`, `forecasted`,
`counterfactual`.

This is closely related to the `confidence` label on report bullets, but not
identical. `realis` is about the event's status in the world; `confidence` is
about how well the available tweets support the claim. A pledged aid fund that
several sources report is `pledged` in realis and `confirmed` in confidence.

**`negated`** — whether the event is asserted not to have occurred. Negated
events are reportable and appear in the corpus: a report stating that no
fatalities occurred, or that officials denied a rumour, records a negated
event. A system that treats negation as absence will lose this content.

---

## 5. Relations

**Between events:**

| Group | Relations |
| --- | --- |
| causal | CAUSES, ENABLES, PREVENTS, MITIGATES, AGGRAVATES |
| temporal | BEFORE, AFTER, DURING, OVERLAPS |
| structural | SUBEVENT_OF, PART_OF_PROCESS |
| coreference | COREFERS |

**Between entities:**

| Group | Relations |
| --- | --- |
| spatial | LOCATED_IN, NEAR |
| affiliation | MEMBER_OF, AFFILIATED_WITH |
| structural | SUBSET_OF, PART_OF |
| coreference | COREFERS |

Relations are part of the underlying representation rather than the report
format: released reports do not contain a relations section. They matter
indirectly. Temporal relations determine the ordering of events in section 2,
and coreference underlies the treatment of entity aliases, where the same
entity appears under several surface forms across tweets and reports use a
single canonical name.

---

## 6. Using the taxonomy

The taxonomy is released as `taxonomy.yaml`. It is not required input to a
system, and there is no requirement to output taxonomy labels. It is useful in
three ways:

**Section placement.** The superclass-to-section mapping in part 2 above is the
rule the reports follow. When it is unclear whether content belongs in section
7 or section 9, the aid boundary settles it.

**Argument expectations.** `required_roles` explains why bullets name entities.
A bullet that reports an event without naming any participant, location or
cause does not match the pattern of the reference reports.

**Negation and modality.** The `realis` and `negated` attributes explain why
reports contain statements about things that did not happen, and why announced
future actions are labeled differently from completed ones.

---

## 7. Version note

This corpus uses taxonomy version 1.2, which added `required_roles` to every
event type and aligned the entity vocabulary so that `loc` is the location
type. Earlier material may use `location`.
