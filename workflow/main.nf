#!/usr/bin/env nextflow
nextflow.enable.dsl = 2

params.claims_dir   = "${projectDir}/claims"
params.reports_dir  = "${projectDir}/reports"
params.offline      = false
params.skip_sentinel = false

process sentinel_check {
    output: path 'sentinel.ok'
    script:
    """
    ft-smoke > sentinel.log 2>&1
    touch sentinel.ok
    """
}

process validate_claim {
    tag "${claim.baseName}"
    input:  path claim
    output: tuple path(claim), path("${claim.baseName}.valid")
    script:
    """
    ft-validate ${claim} && touch ${claim.baseName}.valid
    """
}

process ft_audit {
    tag "${claim.baseName}"
    publishDir params.reports_dir, mode: 'copy', pattern: '*_audit.json'
    input:  tuple path(claim), path(valid_marker)
    output: path "${claim.baseName}_audit.json"
    script:
    def offline_flag = params.offline ? '--no-live' : ''
    """
    ft-audit ${claim} ${offline_flag} --json-out ${claim.baseName}_audit.json
    """
}

process aggregate_reports {
    publishDir params.reports_dir, mode: 'copy'
    input:  path reports
    output:
        path 'audit_summary.json'
        path 'audit_summary.html'
    script:
    """
    mkdir -p inputs
    cp ${reports} inputs/
    python3 ${projectDir}/scripts/batch_audit.py \\
        --aggregate-only --reports-dir inputs
    cp inputs/audit_summary.json .
    cp inputs/audit_summary.html .
    """
}

workflow {
    claims_ch = Channel.fromPath("${params.claims_dir}/*.{yaml,yml}", checkIfExists: true)
    sentinel_ch = params.skip_sentinel ? Channel.value('skipped') : sentinel_check()
    validated = validate_claim(claims_ch)
    audits = ft_audit(validated)
    aggregate_reports(audits.collect())
}
