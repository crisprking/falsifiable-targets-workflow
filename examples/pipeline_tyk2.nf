#!/usr/bin/env nextflow
nextflow.enable.dsl = 2

process audit_tyk2 {
    output: path 'tyk2_audit.json'
    script:
    """
    ft-audit ${projectDir}/../claims/tyk2_psoriasis.yaml --no-live --json-out tyk2_audit.json
    """
}

workflow { audit_tyk2() }
