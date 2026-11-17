idf_component_register(
    SRCS "main.c" "wifi.c" "flow_sensor.c"
    INCLUDE_DIRS "." "../include"
    REQUIRES esp_driver_gpio esp_driver_pcnt esp_driver_mcpwm esp_driver_ledc esp_timer esp-dsp
             esp_wifi esp_event esp_netif nvs_flash esp_http_server lwip
)
target_compile_options(${COMPONENT_LIB} PRIVATE -O2)
