SHELL := /usr/bin/env bash

.PHONY: dashboard lab desktop desktop-clean clean

dashboard:
	bash ./scripts/run_web_dashboard.sh

lab:
	bash ./scripts/run_web_dashboard.sh -- --lab

desktop:
	bash ./scripts/run_desktop_app.sh

desktop-clean:
	rm -rf desktop-app/src-tauri/target "$${INTELSIGHT_DESKTOP_STAGE:-$${TMPDIR:-/tmp}/intelsight-desktop-run}/src-tauri/target"

clean: desktop-clean