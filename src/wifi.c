#include "wifi.h"
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/task.h"
#include "lwip/sockets.h"

#define CONNECTED BIT0
#define DISCONNECTED BIT1
#define STARTED BIT2
#define LOST_IP BIT3
#define NET_TRY(call) do { esp_err_t err = (call); if (err != ESP_OK) return err; } while (0)

static EventGroupHandle_t events;
static wifi_settings_t settings;
static bool running;
static httpd_handle_t server;
static esp_netif_t *ap_interface;
static char target_ssid_json[32 * 6 + 1], ap_ssid_json[32 * 6 + 1];
static portMUX_TYPE state_lock = portMUX_INITIALIZER_UNLOCKED;
static struct {
    bool station_connected;
    bool ap_active;
    char station_ip[16];
    char reading[WIFI_READING_CAPACITY];
    int64_t reading_us;
} state;

/* Self-contained: local clients need neither a CDN nor Internet access. */
static const char dashboard[] =
"<!doctype html>\n"
"<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>FlowLab Local</title>\n"
"<style>\n"
":root{color-scheme:dark;--bg:#10191d;--panel:#19272c;--line:#304348;--text:#edf5ed;--muted:#acc1bc;--green:#b5efb5;--amber:#ffcc86}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,sans-serif}main{max-width:1080px;padding:36px 24px;margin:auto}header{display:flex;justify-content:space-between;gap:20px;align-items:center;margin-bottom:28px}.eyebrow{color:var(--green);font-size:12px;letter-spacing:.12em;text-transform:uppercase}h1{font-size:clamp(28px,5vw,42px);letter-spacing:-.04em;margin:4px 0}h2{font-size:18px;margin:0 0 16px}p{margin:6px 0;color:var(--muted)}.badge{border:1px solid var(--line);border-radius:24px;padding:8px 14px;font-size:13px;white-space:nowrap;color:var(--amber)}.badge.live{color:var(--green)}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.card,.panel{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:22px}.label{font-size:13px;color:var(--muted)}.value{font-size:clamp(24px,3.8vw,36px);font-variant-numeric:tabular-nums;letter-spacing:-.04em;overflow-wrap:anywhere;margin:8px 0 4px}.unit{font-size:13px;color:var(--muted)}.note{font-size:12px;color:var(--muted);min-height:18px}.panels{display:grid;grid-template-columns:1.6fr 1fr;gap:14px;margin-top:14px}svg{display:block;width:100%;height:160px;border-bottom:1px solid var(--line)}polyline{stroke:var(--green);stroke-width:2;vector-effect:non-scaling-stroke;fill:none}.chart-note{font-size:12px;margin-top:12px}dl{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:0}dt{color:var(--muted);font-size:12px}dd{margin:2px 0 0;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}footer{margin-top:24px;font-size:13px;color:var(--muted)}a{color:var(--green)}#message{margin:0 0 20px;padding:12px 16px;border:1px solid var(--line);border-radius:12px;color:var(--muted)}@media(max-width:760px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.panels{grid-template-columns:1fr}header{align-items:flex-start;flex-direction:column;gap:12px}main{padding:24px 16px}.card,.panel{padding:18px}}@media(prefers-reduced-motion:no-preference){.badge{transition:color .2s}}\n"
"</style></head><body><main>\n"
"<header><div><div class=\"eyebrow\">ZJ-S201C / XIAO ESP32-S3</div><h1>FlowLab Local</h1><p>Live pulse readings, directly from your board.</p></div><div id=\"badge\" class=\"badge\" role=\"status\">Connecting</div></header>\n"
"<div id=\"message\" role=\"status\">Waiting for a reading from the board.</div>\n"
"<section class=\"grid\" aria-label=\"Latest measurements\">\n"
"<article class=\"card\"><div class=\"label\">Pulse frequency</div><div class=\"value\" id=\"frequency\">--</div><div class=\"unit\">Hz</div><div class=\"note\">Rolling measurement window</div></article>\n"
"<article class=\"card\"><div class=\"label\">Flow rate</div><div class=\"value\" id=\"flow\">--</div><div class=\"unit\">L / min</div><div class=\"note\" id=\"calibration\">Calibration needed</div></article>\n"
"<article class=\"card\"><div class=\"label\">Total pulses</div><div class=\"value\" id=\"count\">--</div><div class=\"unit\">pulses since boot</div><div class=\"note\">Hardware edge counter</div></article>\n"
"<article class=\"card\"><div class=\"label\">Total volume</div><div class=\"value\" id=\"volume\">--</div><div class=\"unit\">L since boot</div><div class=\"note\" id=\"volume-note\">Calibration needed</div></article>\n"
"</section>\n"
"<section class=\"panels\"><article class=\"panel\"><h2>Frequency history</h2><svg viewBox=\"0 0 600 160\" preserveAspectRatio=\"none\" role=\"img\" aria-label=\"Recent frequency readings\"><polyline id=\"trace\" points=\"\"></polyline></svg><p id=\"range\" class=\"chart-note\">Waiting for data</p><p class=\"chart-note\">Latest 60 browser samples. Polls once per second; pauses when this tab is hidden.</p></article>\n"
"<article class=\"panel\"><h2>Signal details</h2><dl><div><dt>Duty cycle</dt><dd id=\"duty\">--</dd></div><div><dt>Pulse frequency</dt><dd id=\"edge-hz\">--</dd></div><div><dt>High time</dt><dd id=\"high\">--</dd></div><div><dt>Low time</dt><dd id=\"low\">--</dd></div><div><dt>Report interval</dt><dd id=\"interval\">--</dd></div><div><dt>Averaging window</dt><dd id=\"window\">--</dd></div></dl><p class=\"chart-note\">Timing is unavailable until enough edges arrive, and clears when the signal becomes stale.</p></article></section>\n"
"<section class=\"panel\" style=\"margin-top:14px\"><h2>Connection</h2><dl><div><dt>Upstream Wi-Fi</dt><dd id=\"upstream\">--</dd></div><div><dt>Station address</dt><dd id=\"station-ip\">--</dd></div><div><dt>Local access point</dt><dd id=\"ap\">--</dd></div><div><dt>Data age</dt><dd id=\"age\">--</dd></div></dl><p class=\"chart-note\">A station IP confirms local network access. Internet access and cloud delivery are separate checks.</p></section>\n"
"<footer>Input: D10 / GPIO9. Unknown calibration stays blank. <a href=\"/api/status\">JSON data</a> &middot; <a href=\"/healthz\">Health</a><p>This local page requires no Internet. The board does not forward Internet access to connected devices.</p></footer>\n"
"</main><script>\n"
"const el=id=>document.getElementById(id), finite=x=>typeof x==='number'&&Number.isFinite(x);\n"
"const fmt=(x,n=2)=>finite(x)?x.toLocaleString(undefined,{maximumFractionDigits:n,minimumFractionDigits:n}):'--';\n"
"const unit=(x,u,n=1)=>finite(x)?fmt(x,n)+' '+u:'--';\n"
"let history=[],lastUptime=null,busy=false,lastResponse=0,timer;\n"
"function render(data){\n"
" const r=data.reading,n=data.network||{},age=data.reading_age_ms;\n"
" const live=!!r&&finite(age)&&age<3000;\n"
" el('badge').textContent=live?'Live from board':r?'Reading stale':'Waiting for data';el('badge').className='badge'+(live?' live':'');\n"
" el('message').textContent=!r?'Waiting for the first sensor report.':!live?'Last reading is stale. Check the board connection.':r.flow_lpm===null?'Receiving raw pulse data. Set the sensor calibration to display flow and volume.':'Receiving calibrated readings. Physical accuracy depends on your calibration.';\n"
" el('upstream').textContent=(n.ssid||'Wi-Fi')+(n.station_connected?' / IP obtained':' / waiting for IP');\n"
" el('station-ip').textContent=n.station_ip||'--';el('ap').textContent=n.ap_active?(n.ap_ssid+' / '+n.ap_clients+' client(s)'):'Inactive';el('age').textContent=unit(age,'ms',0);\n"
" if(!r)return;\n"
" el('frequency').textContent=fmt(r.frequency_hz);el('flow').textContent=fmt(r.flow_lpm,3);el('count').textContent=fmt(r.total_pulses,0);el('volume').textContent=fmt(r.total_l,3);\n"
" el('calibration').textContent=finite(r.flow_lpm)?'Calibration configured':'Calibration needed';el('volume-note').textContent=finite(r.total_l)?'Per-boot total':'Calibration needed';\n"
" const p=r.pulse||{};el('duty').textContent=unit(p.duty_pct,'%',1);el('edge-hz').textContent=unit(p.hz,'Hz',2);el('high').textContent=unit(p.high_us,'us');el('low').textContent=unit(p.low_us,'us');el('interval').textContent=unit(r.dt_us/1000,'ms');el('window').textContent=unit(r.window_us/1000,'ms');\n"
" if(live&&r.uptime_us!==lastUptime&&finite(r.frequency_hz)){\n"
"  if(lastUptime!==null&&r.uptime_us<lastUptime)history=[];\n"
"  history.push(r.frequency_hz);history=history.slice(-60);lastUptime=r.uptime_us;\n"
"  const top=Math.max(1,...history);el('trace').setAttribute('points',history.map((v,i)=>(i*600/59).toFixed(2)+','+(150-140*v/top).toFixed(2)).join(' '));\n"
"  el('range').textContent='Range 0 - '+fmt(top)+' Hz / '+history.length+' samples';\n"
" }\n"
"}\n"
"async function poll(){\n"
" if(busy||document.hidden)return;busy=true;\n"
" const abort=new AbortController(),timeout=setTimeout(()=>abort.abort(),4000);\n"
" try{const response=await fetch('/api/status',{cache:'no-store',signal:abort.signal});if(!response.ok)throw new Error('HTTP '+response.status);const data=await response.json();render(data);lastResponse=Date.now();}\n"
" catch(error){el('badge').textContent='Connection lost';el('badge').className='badge';el('message').textContent='Cannot reach the board. Reconnect to its local Wi-Fi, then keep this page open. Previous values remain visible.';el('age').textContent=lastResponse?'Response '+Math.round((Date.now()-lastResponse)/1000)+' s ago':'--';}\n"
" finally{clearTimeout(timeout);busy=false;}\n"
"}\n"
"function schedule(){clearInterval(timer);if(!document.hidden){poll();timer=setInterval(poll,1000);}}\n"
"document.addEventListener('visibilitychange',schedule);schedule();\n"
"</script></body></html>\n"
;

static const char *network_auth_label(void)
{
    return settings.password[0] ? "wpa2_personal" : "open";
}

static void escape_ssid(const unsigned char *input, char output[32 * 6 + 1])
{
    size_t position = 0;
    for (size_t j = 0; j < 32 && input[j]; ++j) {
        unsigned char ch = input[j];
        if (ch < 32 || ch >= 127 || ch == '"' || ch == '\\')
            position += snprintf(output + position, 32 * 6 + 1 - position,
                                 "\\u%04x", (unsigned)ch);
        else output[position++] = (char)ch;
    }
    output[position] = '\0';
}

esp_err_t wifi_publish_reading(const char *json, size_t length)
{
    if (!json || !length || length >= sizeof(state.reading)) return ESP_ERR_INVALID_ARG;
    int64_t now = esp_timer_get_time();
    portENTER_CRITICAL(&state_lock);
    memcpy(state.reading, json, length);
    state.reading[length] = '\0';
    state.reading_us = now;
    portEXIT_CRITICAL(&state_lock);
    return ESP_OK;
}

static void response_headers(httpd_req_t *request, const char *type)
{
    httpd_resp_set_type(request, type);
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    httpd_resp_set_hdr(request, "X-Content-Type-Options", "nosniff");
    httpd_resp_set_hdr(request, "Content-Security-Policy",
        "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
        "connect-src 'self'; base-uri 'none'; frame-ancestors 'none'");
}

static esp_err_t dashboard_get(httpd_req_t *request)
{
    response_headers(request, "text/html; charset=utf-8");
    return httpd_resp_send(request, dashboard, sizeof(dashboard) - 1);
}

static esp_err_t health_get(httpd_req_t *request)
{
    response_headers(request, "application/json");
    return httpd_resp_sendstr(request, "{\"status\":\"ok\",\"service\":\"flowlab-local\"}");
}

static esp_err_t favicon_get(httpd_req_t *request)
{
    httpd_resp_set_status(request, "204 No Content");
    return httpd_resp_send(request, NULL, 0);
}

static esp_err_t status_get(httpd_req_t *request)
{
    char reading[WIFI_READING_CAPACITY], station_ip[16];
    bool connected, ap_active;
    int64_t reading_us;
    portENTER_CRITICAL(&state_lock);
    memcpy(reading, state.reading, sizeof(reading));
    memcpy(station_ip, state.station_ip, sizeof(station_ip));
    connected = state.station_connected;
    ap_active = state.ap_active;
    reading_us = state.reading_us;
    portEXIT_CRITICAL(&state_lock);

    wifi_sta_list_t clients = {0};
    if (ap_active) esp_wifi_ap_get_sta_list(&clients);
    wifi_ap_record_t upstream;
    char rssi[16] = "null", address[20] = "null", ap_ip[20] = "null";
    if (connected) {
        snprintf(address, sizeof(address), "\"%s\"", station_ip);
        if (esp_wifi_sta_get_ap_info(&upstream) == ESP_OK)
            snprintf(rssi, sizeof(rssi), "%d", upstream.rssi);
    }
    esp_netif_ip_info_t info;
    if (ap_active && esp_netif_get_ip_info(ap_interface, &info) == ESP_OK)
        snprintf(ap_ip, sizeof(ap_ip), "\"" IPSTR "\"", IP2STR(&info.ip));
    char age[32] = "null";
    if (reading[0])
        snprintf(age, sizeof(age), "%" PRId64, (esp_timer_get_time() - reading_us) / 1000);
    char body[2048];
    int length = snprintf(body, sizeof(body),
        "{\"network\":{\"station_connected\":%s,\"ssid\":\"%s\",\"station_ip\":%s,"
        "\"rssi_dbm\":%s,\"ap_active\":%s,\"ap_ssid\":\"%s\",\"ap_ip\":%s,"
        "\"ap_clients\":%u},\"reading_age_ms\":%s,\"reading\":%s}",
        connected ? "true" : "false", target_ssid_json, address, rssi,
        ap_active ? "true" : "false", ap_ssid_json, ap_ip,
        (unsigned)clients.num, age, reading[0] ? reading : "null");
    if (length < 0 || (size_t)length >= sizeof(body))
        return httpd_resp_send_err(request, HTTPD_500_INTERNAL_SERVER_ERROR, "Status too large");
    response_headers(request, "application/json");
    return httpd_resp_send(request, body, length);
}

static esp_err_t start_server(void)
{
    if (server) return ESP_OK;
    httpd_config_t config = HTTPD_DEFAULT_CONFIG();
    config.stack_size = 8192;
    config.max_open_sockets = 4;
    config.lru_purge_enable = true;
    config.recv_wait_timeout = 2;
    config.send_wait_timeout = 2;
    NET_TRY(httpd_start(&server, &config));
    const httpd_uri_t routes[] = {
        {.uri = "/", .method = HTTP_GET, .handler = dashboard_get},
        {.uri = "/api/status", .method = HTTP_GET, .handler = status_get},
        {.uri = "/healthz", .method = HTTP_GET, .handler = health_get},
        {.uri = "/favicon.ico", .method = HTTP_GET, .handler = favicon_get},
    };
    for (size_t i = 0; i < sizeof(routes) / sizeof(routes[0]); ++i) {
        esp_err_t err = httpd_register_uri_handler(server, &routes[i]);
        if (err != ESP_OK) {
            httpd_stop(server);
            server = NULL;
            return err;
        }
    }
    return ESP_OK;
}

/* Once per server start: exercise the actual handlers without relying on RF. */
static bool check_route(const char *path, const char *expected)
{
    int sock = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (sock < 0) return false;
    struct timeval timeout = {.tv_sec = 2};
    setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
    struct sockaddr_in address = {.sin_family = AF_INET, .sin_port = htons(80)};
    address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    bool passed = false;
    if (connect(sock, (struct sockaddr *)&address, sizeof(address)) == 0) {
        char request[160];
        int length = snprintf(request, sizeof(request),
            "GET %s HTTP/1.0\r\nHost: localhost\r\nConnection: close\r\n\r\n", path);
        if (send(sock, request, length, 0) == length) {
            char response[3072] = {0}, block[512];
            size_t used = 0, total = 0;
            int received;
            while ((received = recv(sock, block, sizeof(block), 0)) > 0) {
                size_t copy = (size_t)received;
                if (copy > sizeof(response) - 1 - used) copy = sizeof(response) - 1 - used;
                memcpy(response + used, block, copy);
                used += copy;
                total += received;
                response[used] = '\0';
                passed = strstr(response, "200 OK") && strstr(response, expected);
                const char *body = strstr(response, "\r\n\r\n");
                const char *length_header = strstr(response, "Content-Length: ");
                /* Drain the whole response before close, including the large page. */
                if (body && length_header && total >= (size_t)(body + 4 - response) +
                    strtoul(length_header + strlen("Content-Length: "), NULL, 10)) break;
            }
        }
    }
    close(sock);
    return passed;
}

static void on_network_event(void *context, esp_event_base_t base, int32_t id, void *data)
{
    (void)context;
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        xEventGroupSetBits(events, STARTED);
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        portENTER_CRITICAL(&state_lock);
        state.station_connected = false;
        portEXIT_CRITICAL(&state_lock);
        printf("{\"type\":\"wifi\",\"status\":\"disconnected\",\"reason\":%d}\n",
               ((wifi_event_sta_disconnected_t *)data)->reason);
        xEventGroupSetBits(events, DISCONNECTED);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = data;
        char ip[16];
        snprintf(ip, sizeof(ip), IPSTR, IP2STR(&event->ip_info.ip));
        portENTER_CRITICAL(&state_lock);
        memcpy(state.station_ip, ip, sizeof(ip));
        state.station_connected = true;
        portEXIT_CRITICAL(&state_lock);
        printf("{\"type\":\"wifi\",\"status\":\"connected\",\"ssid\":\"%s\","
               "\"ip\":\"%s\",\"auth\":\"%s\",\"server_validation\":false}\n",
               target_ssid_json, ip, network_auth_label());
        xEventGroupSetBits(events, CONNECTED);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_LOST_IP) {
        portENTER_CRITICAL(&state_lock);
        state.station_connected = false;
        portEXIT_CRITICAL(&state_lock);
        xEventGroupSetBits(events, LOST_IP);
    } else if (base == WIFI_EVENT && (id == WIFI_EVENT_AP_START || id == WIFI_EVENT_AP_STOP)) {
        portENTER_CRITICAL(&state_lock);
        state.ap_active = id == WIFI_EVENT_AP_START;
        portEXIT_CRITICAL(&state_lock);
    } else if (base == WIFI_EVENT &&
               (id == WIFI_EVENT_AP_STACONNECTED || id == WIFI_EVENT_AP_STADISCONNECTED)) {
        printf("{\"type\":\"wifi_ap_client\",\"connected\":%s}\n",
               id == WIFI_EVENT_AP_STACONNECTED ? "true" : "false");
    }
}

static esp_err_t scan_networks(void)
{
    wifi_scan_config_t config = {
        .show_hidden = true,
        .scan_type = WIFI_SCAN_TYPE_ACTIVE,
        .scan_time.active = {.min = 100, .max = 300},
    };
    printf("{\"type\":\"wifi_scan\",\"status\":\"starting\"}\n");
    NET_TRY(esp_wifi_scan_start(&config, true));
    uint16_t count = 0;
    esp_err_t err = esp_wifi_scan_get_ap_num(&count);
    if (err != ESP_OK || count == 0) {
        esp_wifi_clear_ap_list();
        if (err == ESP_OK)
            printf("{\"type\":\"wifi_scan\",\"status\":\"complete\",\"ap_count\":0,\"target_count\":0}\n");
        return err;
    }
    wifi_ap_record_t *records = calloc(count, sizeof(*records));
    if (!records) {
        esp_wifi_clear_ap_list();
        return ESP_ERR_NO_MEM;
    }
    err = esp_wifi_scan_get_ap_records(&count, records);
    if (err == ESP_OK) {
        unsigned target = 0;
        for (uint16_t i = 0; i < count; ++i) {
            const wifi_ap_record_t *ap = &records[i];
            char ssid[32 * 6 + 1];
            escape_ssid(ap->ssid, ssid);
            if (strcmp((const char *)ap->ssid, settings.ssid) == 0) ++target;
            printf("{\"type\":\"wifi_ap\",\"ssid\":\"%s\",\"rssi_dbm\":%d,"
                   "\"channel\":%u,\"auth_mode\":%d}\n",
                   ssid, ap->rssi, (unsigned)ap->primary, ap->authmode);
        }
        printf("{\"type\":\"wifi_scan\",\"status\":\"complete\",\"ap_count\":%u,"
               "\"target_count\":%u}\n", (unsigned)count, target);
    }
    free(records);
    esp_wifi_clear_ap_list();
    return err;
}

static esp_err_t initialise_network(void)
{
    /* Preserve NVS; an incompatible/full store is reported rather than erased. */
    NET_TRY(nvs_flash_init());
    NET_TRY(esp_netif_init());
    NET_TRY(esp_event_loop_create_default());
    if (!esp_netif_create_default_wifi_sta()) return ESP_ERR_NO_MEM;
    if (settings.fallback.enabled) {
        ap_interface = esp_netif_create_default_wifi_ap();
        if (!ap_interface) return ESP_ERR_NO_MEM;
    }
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    NET_TRY(esp_wifi_init(&init));
    NET_TRY(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, on_network_event, NULL));
    NET_TRY(esp_event_handler_register(IP_EVENT, ESP_EVENT_ANY_ID, on_network_event, NULL));
    NET_TRY(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    wifi_config_t config = {
        .sta = {
            .threshold.authmode = settings.password[0] ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN,
            .scan_method = WIFI_ALL_CHANNEL_SCAN,
            .pmf_cfg = {.capable = true, .required = false},
        },
    };
    memcpy(config.sta.ssid, settings.ssid, strlen(settings.ssid));
    memcpy(config.sta.password, settings.password, strlen(settings.password));
    NET_TRY(esp_wifi_set_mode(settings.fallback.enabled ? WIFI_MODE_APSTA : WIFI_MODE_STA));
    NET_TRY(esp_wifi_set_config(WIFI_IF_STA, &config));
    if (settings.fallback.enabled) {
        wifi_config_t ap = {
            .ap = {
                .ssid_len = strlen(settings.fallback.ssid),
                .channel = settings.fallback.channel,
                .authmode = WIFI_AUTH_WPA2_PSK,
                .max_connection = settings.fallback.max_clients,
                .pmf_cfg = {.required = false},
            },
        };
        memcpy(ap.ap.ssid, settings.fallback.ssid, strlen(settings.fallback.ssid));
        memcpy(ap.ap.password, settings.fallback.password, strlen(settings.fallback.password));
        NET_TRY(esp_wifi_set_config(WIFI_IF_AP, &ap));
        /* Configure the AP before start, but broadcast only after the deadline. */
        NET_TRY(esp_wifi_set_mode(WIFI_MODE_STA));
    }
    return esp_wifi_start();
}

static void network_task(void *context)
{
    (void)context;
    escape_ssid((const unsigned char *)settings.ssid, target_ssid_json);
    escape_ssid((const unsigned char *)settings.fallback.ssid, ap_ssid_json);
    events = xEventGroupCreate();
    if (!events) {
        printf("{\"type\":\"wifi\",\"status\":\"no_memory\"}\n");
        vTaskDelete(NULL);
        return;
    }
    printf("{\"type\":\"wifi\",\"status\":\"starting\",\"ssid\":\"%s\","
           "\"auth\":\"%s\",\"server_validation\":false}\n", target_ssid_json, network_auth_label());
    esp_err_t err = initialise_network();
    if (err != ESP_OK) {
        printf("{\"type\":\"wifi\",\"status\":\"setup_error\",\"code\":%d}\n", err);
        vTaskDelete(NULL);
        return;
    }
    EventBits_t started = xEventGroupWaitBits(events, STARTED, pdTRUE, pdFALSE, pdMS_TO_TICKS(10000));
    if (!(started & STARTED)) {
        printf("{\"type\":\"wifi\",\"status\":\"start_timeout\"}\n");
        vTaskDelete(NULL);
        return;
    }
    int64_t wait_started_us = esp_timer_get_time(), last_status_us = wait_started_us;
    err = scan_networks();
    if (err != ESP_OK)
        printf("{\"type\":\"wifi_scan\",\"status\":\"error\",\"code\":%d}\n", err);
    unsigned attempts = 0;
    int64_t next_connect_us = esp_timer_get_time(), next_fallback_us = 0;
    bool ap_started = false, checked_server = false;
    while (true) {
        EventBits_t bits = xEventGroupWaitBits(events, CONNECTED | DISCONNECTED | LOST_IP,
                                              pdTRUE, pdFALSE, pdMS_TO_TICKS(250));
        int64_t now = esp_timer_get_time();
        portENTER_CRITICAL(&state_lock);
        bool connected = state.station_connected;
        portEXIT_CRITICAL(&state_lock);
        if (connected) {
            wait_started_us = 0;
            attempts = 0;
            next_connect_us = 0;
        } else {
            if (!wait_started_us) wait_started_us = now;
            uint32_t delay_ms = ap_started ? settings.fallback.retry_delay_ms : settings.retry_delay_ms;
            if (bits & DISCONNECTED) next_connect_us = now + (int64_t)delay_ms * 1000;
            if (settings.fallback.enabled && !ap_started && now >= next_fallback_us &&
                now - wait_started_us >= (int64_t)settings.fallback.after_ms * 1000) {
                err = esp_wifi_set_mode(WIFI_MODE_APSTA);
                if (err == ESP_OK) {
                    ap_started = true;
                    esp_netif_ip_info_t info = {0};
                    esp_netif_get_ip_info(ap_interface, &info);
                    printf("{\"type\":\"wifi_fallback\",\"status\":\"started\",\"ssid\":\"%s\","
                           "\"ip\":\"" IPSTR "\",\"wait_ms\":%" PRId64 ",\"mode\":\"ap_sta\"}\n",
                           ap_ssid_json, IP2STR(&info.ip), (now - wait_started_us) / 1000);
                } else {
                    next_fallback_us = now + 5000000;
                    printf("{\"type\":\"wifi_fallback\",\"status\":\"error\",\"code\":%d}\n", err);
                }
            }
            if (next_connect_us && now >= next_connect_us) {
                printf("{\"type\":\"wifi\",\"status\":\"connecting\",\"attempt\":%u,"
                       "\"wait_ms\":%" PRId64 "}\n", ++attempts, (now - wait_started_us) / 1000);
                err = esp_wifi_connect();
                next_connect_us = err == ESP_OK ? 0 : now + (int64_t)delay_ms * 1000;
                if (err != ESP_OK)
                    printf("{\"type\":\"wifi\",\"status\":\"connect_error\",\"code\":%d}\n", err);
            }
            if (now - last_status_us >= (int64_t)settings.status_interval_ms * 1000) {
                printf("{\"type\":\"wifi\",\"status\":\"waiting\",\"wait_ms\":%" PRId64 "}\n",
                       (now - wait_started_us) / 1000);
                last_status_us = now;
            }
        }
        if (ap_started && !server && now >= next_fallback_us) {
            err = start_server();
            if (err != ESP_OK) {
                next_fallback_us = now + 5000000;
                printf("{\"type\":\"local_http\",\"status\":\"start_error\",\"code\":%d}\n", err);
            }
        }
        if (server && !checked_server) {
            bool health = check_route("/healthz", "\"status\":\"ok\"");
            bool status = check_route("/api/status", "\"reading\":{\"type\":\"flow\"");
            bool page = check_route("/", "FlowLab Local");
            printf("{\"type\":\"local_http_check\",\"scope\":\"board_loopback\","
                   "\"health\":%s,\"status\":%s,\"page\":%s,\"pass\":%s}\n",
                   health ? "true" : "false", status ? "true" : "false",
                   page ? "true" : "false", health && status && page ? "true" : "false");
            checked_server = true;
        }
    }
}

static bool valid_credentials(const char ssid[33], const char password[65], bool allow_open)
{
    size_t name = strnlen(ssid, 33), secret = strnlen(password, 65);
    return name > 0 && name <= 32 && secret <= 64 &&
           ((allow_open && secret == 0) || secret >= 8);
}

esp_err_t wifi_start(const wifi_settings_t *config)
{
    if (!config || !valid_credentials(config->ssid, config->password, true) ||
        !pdMS_TO_TICKS(config->retry_delay_ms) || !pdMS_TO_TICKS(config->status_interval_ms))
        return ESP_ERR_INVALID_ARG;
    if (config->fallback.enabled &&
        (!valid_credentials(config->fallback.ssid, config->fallback.password, false) ||
         !config->fallback.after_ms || !pdMS_TO_TICKS(config->fallback.retry_delay_ms) ||
         config->fallback.channel < 1 || config->fallback.channel > 11 ||
         config->fallback.max_clients < 1 || config->fallback.max_clients > 4))
        return ESP_ERR_INVALID_ARG;
    if (running) return ESP_ERR_INVALID_STATE;
    settings = *config;
    running = true;
    if (xTaskCreate(network_task, "wifi", 8192, NULL, 3, NULL) != pdPASS) {
        running = false;
        printf("{\"type\":\"wifi\",\"status\":\"task_error\"}\n");
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}
