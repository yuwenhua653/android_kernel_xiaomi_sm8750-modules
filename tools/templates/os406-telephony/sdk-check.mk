# OS4.0.6 prebuilt QtiTelephony, IMS and six other apps require API 37.
# Passing this minimum check does not qualify framework or native ABI support.
ifeq ($(strip $(PLATFORM_SDK_VERSION)),)
$(error annibale OS4.0.6 profile requires a defined PLATFORM_SDK_VERSION >= 37)
endif
ifneq ($(call math_gt_or_eq,$(PLATFORM_SDK_VERSION),37),true)
$(error annibale OS4.0.6 APKs require PLATFORM_SDK_VERSION >= 37; use matching older blobs for an older framework)
endif
