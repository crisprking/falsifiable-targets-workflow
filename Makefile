.PHONY: help batch nf-local nf-docker snakemake docker-build clean

help:
	@echo "make batch        — standalone Python batch (no workflow engine)"
	@echo "make nf-local     — Nextflow, local executor"
	@echo "make nf-docker    — Nextflow, Docker profile"
	@echo "make snakemake    — Snakemake, local"
	@echo "make docker-build — build the engine container"

batch:
	python3 scripts/batch_audit.py --claims-dir claims --reports-dir reports --offline

nf-local:
	cd workflow && nextflow run main.nf -profile standard --offline true

nf-docker:
	cd workflow && nextflow run main.nf -profile docker --offline true

snakemake:
	snakemake --snakefile workflow/Snakefile --cores 4 --config offline=True

docker-build:
	docker build -t falsifiable-targets:latest .

clean:
	rm -rf reports/ work/ .nextflow*
