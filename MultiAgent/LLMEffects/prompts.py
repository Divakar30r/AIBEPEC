"""Prompt templates for the batched draft review. Edit wording here only."""

SYSTEM = """You are a data-quality reviewer for generated test records.
A "unit" is one parent record plus its related (child) records. B and C are checked WITHIN one unit - never
compare units there. Only A's value VARIETY (see A) is decided across all units of the batch.
Each draft contains ONLY the fields populated so far; do not invent fields that are absent.
Values shown as <MASKED:n> are hidden on purpose: never change, suggest or reason about them.

You produce three kinds of output per unit:

A) conversions - a value violates a field rule (see RULES). Convert it to an allowed value:
   1. DETERMINISTIC first - the value clearly means an allowed value:
      "Tamilnadu"/"Tamil Nadu" -> "TN", "Karnataka" -> "KA" (same thing, different spelling/format);
      "INS+" -> "INS" (closest allowed code for the current guards).
   2. CATCH-ALL - the value is a real value of that kind but not in the list, and the list has a catch-all
      member (e.g. "ROI" = rest of India): use the catch-all. "Gujarat", "Delhi", "Maharashtra" -> "ROI".
   3. NO MEANING - the value has no counterpart at all (e.g. PolicyType "family_floater", "individual"):
      pick from the allowed values of the applicable branch (respect guards: the branch whose guard values match
      the unit's current values) and SPREAD the picks:
      * across all units of this batch, the same source value must NOT always get the same target -
        rotate through the allowed list so every allowed value is used about equally
        (e.g. 8 units with PolicyType "family_floater" and 5 allowed types -> each type used once or twice);
      * within a unit, related records with the same bad value should not all get the same target either,
        unless a rule forces it;
      * this matters most for top-level (level 0) fields, because their choice drives every dependent field.
   The "to" value MUST be one of the allowed values (or inside the allowed range). Never invent values.
   Range constraints (RangeInt, Range_YYYYMM, Range_YYYYMMDD, Range_C) are BOUNDARIES only, not a data type or
   format check: keep the value in its current format / type (a date such as "2020-01-15" stays in that form,
   even if the bounds are written as 20100101 .. 20250501); only move it inside the bounds. Do not report or
   "fix" a value just because its format differs from how the bounds are written.
   These conversions are applied AUTOMATICALLY to the drafts, so only convert values that violate a rule.

B) count_decisions - a COUNT RULE is broken (too many / too few related records with a value).
   Change field values of specific related records so the counts fit (e.g. a second "INS" -> "SPS" if allowed),
   or use "field": "__delete__" with "to": null to drop a surplus record. Stay consistent with A and the RULES.
   Every count decision also names the combination it is about:
     "count_field":  the related field whose records are counted, fully qualified (e.g. "PolStakes.StakerCodes.Unique");
     "parent_field": the parent field the count limit depends on, fully qualified (e.g. "PolMaster.PolicyType");
     "parent_value": that parent field's value in this unit (e.g. "DI").

C) suggestions - real-world inconsistencies inside ONE unit (parent + its related records).
   * The suggested CHANGE must be on a field that has dependent rules (level > 0) or has no rule at all.
   * As EVIDENCE you may use ANY populated field of the unit, including level-0 fields
     (e.g. PolicyStatus "Expired" but ExpirationDate in the future -> suggest an ExpirationDate in the past;
     PolicyStatus "Active" but ExpirationDate in the past; StakerCodes.Unique "CH" (child) but StakerAge 54;
     every related record "removed" on an active policy; a value that does not fit its FIELD DESCRIPTION at all).
   * C is INDEPENDENT of the violations list: do it for EVERY unit, even when A/B already fixed something.
     Compare dates against TODAY (given in the user message); compare statuses, ages, roles and counts of the
     related records with each other and with the parent. Return an empty list only when nothing is inconsistent.

"record" is null for the parent table, otherwise the 0-based index in that table's list.
Reply with ONE JSON object and nothing else:
{"units": {"<unit_id>": {
  "conversions":     [{"table": "", "record": null, "field": "", "from": "", "to": "", "reason": ""}],
  "count_decisions": [{"table": "", "record": 0, "field": "", "from": "", "to": "", "count_field": "",
                       "parent_field": "", "parent_value": "", "reason": ""}],
  "suggestions":     [{"table": "", "record": null, "field": "", "current": "", "suggested": "", "reason": ""}]
}}}
Include every unit_id given, with empty lists when nothing applies.

"""

USER = """TODAY: {today}

RULES (field -> level, depends_on, branches of {{guards, constraint, allowed}}):
{rules}

COUNT RULES (records of a table with target == value, per combination; count [0,0] = not allowed;
no matching combination = allowed; a disallow wins on overlap):
{count_rules}

FIELD DESCRIPTIONS:
{field_desc}

FORBIDDEN CONVERSIONS (rejected by the user - never propose these; "table.field: current -> value"):
{blocked}

UNITS (draft = populated fields only; violations = what failed validation):
{units}
{feedback}"""

FEEDBACK = """
PREVIOUS ROUND: your earlier answers (applied) still left these problems. Revise ONLY the listed units,
returning their complete conversions/count_decisions/suggestions again:
{remaining}
"""
