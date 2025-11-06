# Minimal make targets to demo the skeleton quickly

PY=python
SHELL:=/bin/bash

EXAMPLE_DIR=refactor_skeleton/examples/lithium_metal_anode

.PHONY: extract-example
extract-example:
	$(PY) refactor_skeleton/scripts/extract_marker.py \
		--params-file $(EXAMPLE_DIR)/extract/extract_params.json \
		--visualize-schema $(EXAMPLE_DIR)/extract/diagram.svg \
		--visualize-only
	@echo "Schema visualized and params validated; see $(EXAMPLE_DIR)/extract/diagram.svg"
