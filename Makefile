# Single entry point for the RolloutFrontier artifact.
# Run from this directory.  Every target writes into a NEW directory under
# $(OUT); remove it (or choose another OUT) before re-running.
#
#   make install     install the hash-locked application dependency (protobuf)
#   make env         report interpreter / protobuf / SQLite versions
#   make test        focused planning, schema and runtime regression tests
#   make verify      read-only check of every saved result (32 tasks x 2 modes;
#                    the 'publication' task is skipped when ../paper is absent)
#   make reproduce   fresh bounded semantic acceptance, compared with the
#                    retained reference results/reproduction-baseline-2026-11-21
#   make paper       regenerate paper tables/figures and compile ../paper
#                    (only in the full submission package)
#   make all         env + test + verify + reproduce

PYTHON ?= python3
OUT ?= /tmp/rolloutfrontier

export PYTHONDONTWRITEBYTECODE = 1

.PHONY: all install env test verify reproduce paper

all: env test verify reproduce

install:
	$(PYTHON) -m pip install --require-hashes -r requirements-application.lock

env:
	$(PYTHON) -B check_environment.py

test:
	$(PYTHON) -B -m tests.factored_planning_regression
	$(PYTHON) -B -m unittest -v tests.goal_planner_regression tests.test_schema_contracts \
	    tests.test_smoke tests.test_sqlite_paths tests.test_application_rollout \
	    tests.test_factored_runtime tests.test_verify_interruption

# The 'publication' task checks the paper's generated tables/macros against
# results/ and needs the sibling ../paper tree.  In a standalone checkout it is
# left out; verify.py then reports PARTIAL (exit 3), which is accepted here.
verify:
	@if [ -f ../paper/main.tex ]; then \
	  $(PYTHON) -B verify.py --mode both --out $(OUT)/verify; \
	else \
	  echo "../paper not found: skipping the 'publication' check"; \
	  checks=$$($(PYTHON) -B verify.py --list | $(PYTHON) -c \
	    'import json,sys; print(",".join(t["name"] for t in json.load(sys.stdin) if t["name"] != "publication"))'); \
	  $(PYTHON) -B verify.py --mode both --out $(OUT)/verify --checks "$$checks"; rc=$$?; \
	  if [ $$rc -eq 3 ]; then rc=0; fi; exit $$rc; \
	fi

reproduce:
	$(PYTHON) -B reproduce.py --out $(OUT)/semantic \
	    --check-reference results/reproduction-baseline-2026-11-21

paper:
	@if [ -f ../paper/build.sh ]; then cd ../paper && sh build.sh --named; \
	else echo "../paper not found: the manuscript sources are not part of this repository"; fi
