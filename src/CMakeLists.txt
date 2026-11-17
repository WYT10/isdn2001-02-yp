if(IDF_TARGET STREQUAL "esp32s3")
    set(serial_driver esp_driver_usb_serial_jtag)
else()
    set(serial_driver esp_driver_uart)
endif()

idf_component_register(
    SRCS "main.c" "wifi.c" "flow_sensor.c" "cli.c"
    INCLUDE_DIRS "." "../include"
    REQUIRES esp_driver_gpio esp_driver_pcnt esp_driver_mcpwm esp_driver_ledc esp_timer esp-dsp
             esp_wifi esp_event esp_netif nvs_flash esp_http_server lwip wpa_supplicant ${serial_driver}
)
set(private_wifi "${CMAKE_SOURCE_DIR}/.local/wifi.json")
set(private_header "${CMAKE_CURRENT_BINARY_DIR}/private/wifi_private.h")
execute_process(
    COMMAND "${PYTHON}" "${CMAKE_SOURCE_DIR}/tools/generate_wifi_config.py" "${private_wifi}" "${private_header}"
    RESULT_VARIABLE private_wifi_result
)
if(NOT private_wifi_result EQUAL 0)
    message(FATAL_ERROR "Private Wi-Fi configuration could not be generated")
endif()
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${CMAKE_SOURCE_DIR}/tools/generate_wifi_config.py")
if(EXISTS "${private_wifi}")
    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${private_wifi}")
endif()
target_include_directories(${COMPONENT_LIB} PRIVATE "${CMAKE_CURRENT_BINARY_DIR}/private")
target_compile_options(${COMPONENT_LIB} PRIVATE -O2)
