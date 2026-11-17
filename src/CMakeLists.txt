if(IDF_TARGET STREQUAL "esp32s3")
    set(serial_driver esp_driver_usb_serial_jtag)
else()
    set(serial_driver esp_driver_uart)
endif()

idf_component_register(
    SRCS "main.c" "wifi.c" "flow_sensor.c" "cli.c"
    INCLUDE_DIRS "." "../include"
    REQUIRES esp_driver_gpio esp_driver_pcnt esp_driver_mcpwm esp_driver_ledc esp_timer esp-dsp
             esp_wifi esp_event esp_netif nvs_flash esp_http_server lwip ${serial_driver}
)
target_compile_options(${COMPONENT_LIB} PRIVATE -O2)
