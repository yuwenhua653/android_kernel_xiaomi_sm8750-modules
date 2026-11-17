# SPDX-License-Identifier: GPL-2.0-only
"""Native Sun secure-processor load ordering; no firmware/provisioning actions."""
PROFILE = 'annibale-sun-spss'
ROOTS = {'qcom_spss', 'qcom_glink_spss', 'spss_utils', 'spcom'}
SUPPLIERS = {
    'qcom_spss': {'qcom_ipcc', 'clk_rpmh', 'rpmh_regulator', 'qnoc_sun', 'qcom_aoss'},
    'qcom_glink_spss': {'qcom_ipcc'},
    'spss_utils': {'qcom_spss'},
    'spcom': {'spss_utils', 'qcom_spss'},
}


def check_plan(policy, selected, board):
    if 'spu_profile' not in policy:
        return
    if policy['spu_profile'] != PROFILE:
        raise ValueError('unknown Annibale SPU profile')
    if not ROOTS <= selected:
        raise ValueError('missing Annibale SPU driver: ' + ', '.join(sorted(ROOTS - selected)))
    for consumer, needed in SUPPLIERS.items():
        if not needed <= set(board.get(consumer, [])):
            raise ValueError('missing reviewed SPU suppliers: ' + consumer)
