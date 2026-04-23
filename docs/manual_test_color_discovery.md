# Manual Test Checklist — Color Discovery

**Scope:**  
read color-usage-summary + plan primitive-colors-from-project

**Goal:**  
Verify that color discovery and proposal pipeline works end-to-end.

---

## 1. CLI Smoke Tests

Run:

```bash
python run.py read --help
python run.py plan --help
python run.py plan primitive-colors-from-project --help

Expected
color-usage-summary appears under read
primitive-colors-from-project appears under plan
No crashes

---

## 2. CLI Smoke Tests

Run:

```bash
python -m pytest tests/test_plan_handlers.py -v

Expected
All tests PASS

---

## 3. End-to-End Test

### Step 1 — Scan Figma

Run:

```bash
python run.py read color-usage-summary --out /tmp/usage.json

Expected
- Command completes successfully
- /tmp/usage.json is created

### Step 2 — Plan from usage

Run:

```bash
python run.py plan primitive-colors-from-project --usage /tmp/usage.json

Expected
- Console summary is printed

File created:
- tokens/primitives.proposed.json

## 4. Validate usage.json

Run:

```bash
python -m json.tool /tmp/usage.json | head -80

Check:
- scanned_pages exists
- scanned_nodes exists
- totals exists
- node_colors array present
- paint_styles array present
- primitive_variables array present

Node color checks:
- hex is lowercase (e.g. #3b82f6)
- fill_count and stroke_count exist
- examples length ≤ 3

## 5. Validate proposal file

Run:

```bash
python -m json.tool tokens/primitives.proposed.json | head -120

Check:
- generated_at exists (UTC)
- source_usage_file exists
- summary exists
- colors array exists

Summary correctness:
- unique_node_colors matches actual count
- matched_to_primitives correct
- from_paint_styles correct
- new_candidates correct


## 6. Sorting Rules

Check first items in colors:

Order must be:
- matched
- paint_style
- new_candidate

Within group:
- Higher usage first
- If equal → hex ASC

## 7. Field Validation

matched:
- primitive_name NOT null
- paint_style_name = null

paint_style:
- paint_style_name NOT null
- primitive_name = null

new_candidate:
- both = null

## 8. Negative Tests

### Missing usage

Run:

```bash
python run.py plan primitive-colors-from-project

Expected:
- Error about missing --usage

Invalid path

### Invalid path

Run:

```bash
python run.py plan primitive-colors-from-project --usage /tmp/nope.json

Expected:
- Clear error message

### Overwrite behavior

Run twice:

```bash
python run.py plan primitive-colors-from-project --usage /tmp/usage.json
python run.py plan primitive-colors-from-project --usage /tmp/usage.json

Expected:
- Warning about overwrite
- File updated

## 9. Real-world Validation Insight

If output shows:
- Matched to primitives: 0
- From paint styles: 0

Interpretation:
- No primitives exist in Figma
- Paint styles are not applied or mismatched
- System is using raw colors

This is expected for early-stage design systems.

## 10. Done Criteria

All conditions must be true:

CLI works
- Tests pass
- usage.json generated
- proposal.json generated
- Sorting correct
- No crashes
- Output matches expectations