idf_component_register(
    SRCS "modules/math/mulc/float/dsps_mulc_f32_ansi.c"
         "modules/math/mulc/float/dsps_mulc_f32_ae32.S"
    INCLUDE_DIRS "modules/common/include" "modules/math/mulc/include"
)
target_compile_definitions(${COMPONENT_LIB} PUBLIC CONFIG_DSP_OPTIMIZED=1)
target_compile_options(${COMPONENT_LIB} PRIVATE -O2)
