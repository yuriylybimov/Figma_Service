# add_variables.md

Read docs/superpowers/specs/variables_architecture.md before execution.
This file is the control layer for variables automation.

## Execution model

- work block by block
- wait for "start block N"
- do not continue automatically
- one command at a time
- stop after each command
- do not continue to next command without explicit approval
- confirm before executing each command

---

## Blocks

0 - rules
(create naming + mapping rules)

1 - primitives
- sync_primitive_colors
- sync_primitive_spacing
- sync_primitive_radius

2 - validation
- validate_runtime_context
- validate_sandbox_target
- validate_variable_inventory

3 - semantics
- read_tokens_summary
- sync_semantic_tokens
- validate_alias_integrity

4 - styles
- read_style_detail
- sync_text_styles
- sync_paint_styles_from_tokens

5 - UX
- validate_idempotent_rerun
- dry_run
- cmd_seed_primitives
- cmd_sync_semantics
- cmd_sync_typography
- plan_execution

---

## Rules

- always run validate_runtime_context before any sync
- stop if validation fails
- all sync must be idempotent
- all write supports dry-run
- log: created / updated / skipped
