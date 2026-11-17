# SPDX-License-Identifier: GPL-2.0-only
"""Reviewed Sun SCMI/PSCI thermal and power providers for the native plan."""
PROFILE = 'annibale-scmi-psci'
ROOTS = {
    'qcom_cpufreq_thermal', 'qcom_lpm', 'qti_ocp_notifier', 'qcom_tsens',
    'qti_cpufreq_cdev', 'thermal_pause', 'qti_thermal_vendor_hooks',
    'qcom_spmi_adc5_gen3', 'qcom_spmi_temp_alarm', 'qcom_stats',
    'ddr_cdev', 'qti_devfreq_cdev',
}
SUPPLIERS = {
    'qcom_cpufreq_thermal': {'qcom_cpucp', 'scmi_cpufreq'},
    'qcom_lpm': {'sched_walt'},
    'qti_ocp_notifier': {'nvmem_qcom_spmi_sdam', 'rpmh_regulator', 'spmi_pmic_arb'},
    'qcom_tsens': {'qti_thermal_vendor_hooks'},
    'qti_cpufreq_cdev': {'scmi_cpufreq', 'qti_thermal_vendor_hooks'},
    'thermal_pause': {'sched_walt', 'qti_thermal_vendor_hooks'},
    'qcom_spmi_adc5_gen3': {'spmi_pmic_arb', 'qcom_spmi_pmic'},
    'qcom_spmi_temp_alarm': {'qcom_spmi_adc5_gen3', 'spmi_pmic_arb', 'qti_thermal_vendor_hooks'},
    'qcom_stats': {'qcom_aoss'},
    'ddr_cdev': {'qnoc_sun', 'qti_thermal_vendor_hooks'},
    'qti_devfreq_cdev': {'msm_kgsl', 'qti_thermal_vendor_hooks'},
}
BUILTINS = {'scmi_cpufreq', 'scmi_core', 'scmi_perf_domain'}
CONFIGS = ('ARM_SCMI_CPUFREQ', 'ARM_SCMI_PROTOCOL', 'ARM_SCMI_PERF_DOMAIN',
           'ARM_PSCI_CPUIDLE', 'ARM_PSCI_CPUIDLE_DOMAIN', 'THERMAL', 'THERMAL_OF')


def check_plan(policy, selected, board, builtins):
    if 'power_profile' not in policy:
        return
    if policy['power_profile'] != PROFILE:
        raise ValueError('unknown Annibale power profile')
    if not ROOTS <= selected:
        raise ValueError('missing Annibale power driver: ' + ', '.join(sorted(ROOTS - selected)))
    if not BUILTINS <= builtins:
        raise ValueError('Annibale power requires built-in SCMI performance providers')
    for consumer, needed in SUPPLIERS.items():
        if not needed <= set(board.get(consumer, [])):
            raise ValueError('missing reviewed power suppliers: ' + consumer)


def check_config(policy, config):
    if 'power_profile' not in policy:
        return
    lines = set(config.splitlines())
    missing = [n for n in CONFIGS if 'CONFIG_' + n + '=y' not in lines]
    if missing:
        raise ValueError('missing built-in power configuration: ' + ', '.join(missing))
