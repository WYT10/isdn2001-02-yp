#include "wifi.h"
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "esp_netif_sntp.h"
#include "esp_mac.h"
#include "esp_random.h"
#include "cJSON.h"

#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_netif.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "esp_eap_client.h"
#include "nvs_flash.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include "freertos/queue.h"
#include "freertos/task.h"

#define CONNECTED BIT0
#define DISCONNECTED BIT1
#define STARTED BIT2
#define LOST_IP BIT3
#define NET_TRY(call) do { esp_err_t err = (call); if (err != ESP_OK) return err; } while (0)

static EventGroupHandle_t events;
static QueueHandle_t actions;
static wifi_settings_t settings;
static bool running;
static httpd_handle_t server;
static esp_netif_t *ap_interface;
static char target_ssid_json[32 * 6 + 1], ap_ssid_json[32 * 6 + 1];
static portMUX_TYPE state_lock = portMUX_INITIALIZER_UNLOCKED;
static struct {
    bool station_connected;
    bool ap_active;
    bool ready;
    bool ap_only;
    char station_ip[16];
    char reading[WIFI_READING_CAPACITY];
    int64_t reading_us;
} state;
static void escape_ssid(const unsigned char *input, char output[32 * 6 + 1]);

enum { CLOUD_QUEUE_SIZE = 24, CLOUD_BATCH_SIZE = 24, CLOUD_SAMPLE_SIZE = 896,
       CLOUD_BODY_SIZE = CLOUD_BATCH_SIZE * CLOUD_SAMPLE_SIZE + 256 };
static QueueHandle_t cloud_queue;
static wifi_cloud_settings_t cloud_settings;
static struct {
    uint64_t sequence, acknowledged, dropped;
    uint32_t failures, pending;
    int http_status;
    bool clock_synced, blocked;
    int64_t last_success_us;
    char device_id[40], boot_id[33];
} cloud;

static void cloud_status(char *output, size_t capacity)
{
    portENTER_CRITICAL(&state_lock);
    snprintf(output, capacity,
        "{\"enabled\":%s,\"device_id\":\"%s\",\"boot_id\":\"%s\","
        "\"acknowledged\":%" PRIu64 ",\"dropped\":%" PRIu64 ",\"pending\":%" PRIu32 ","
        "\"failures\":%" PRIu32 ",\"http_status\":%d,\"blocked\":%s,\"clock_synced\":%s,"
        "\"last_success_uptime_us\":%" PRId64 "}",
        cloud_queue ? "true" : "false", cloud.device_id, cloud.boot_id,
        cloud.acknowledged, cloud.dropped, cloud.pending, cloud.failures, cloud.http_status,
        cloud.blocked ? "true" : "false", cloud.clock_synced ? "true" : "false", cloud.last_success_us);
    portEXIT_CRITICAL(&state_lock);
}

static void clock_sync(struct timeval *tv)
{
    (void)tv;
    portENTER_CRITICAL(&state_lock);
    cloud.clock_synced = true;
    portEXIT_CRITICAL(&state_lock);
}

/* One producer (sensor task); never wait for the network or a queue slot. */
static void cloud_enqueue(const char *json, size_t length)
{
    if (!cloud_queue) return;
    char sample[CLOUD_SAMPLE_SIZE], timestamp[80] = "";
    portENTER_CRITICAL(&state_lock);
    uint64_t seq = cloud.sequence++, dropped = cloud.dropped;
    bool synced = cloud.clock_synced;
    portEXIT_CRITICAL(&state_lock);
    if (synced) {
        struct timeval tv;
        struct tm utc;
        gettimeofday(&tv, NULL);
        gmtime_r(&tv.tv_sec, &utc);
        char date[24];
        strftime(date, sizeof(date), "%Y-%m-%dT%H:%M:%S", &utc);
        snprintf(timestamp, sizeof(timestamp), ",\"observed_at\":\"%s.%06ldZ\"", date, (long)tv.tv_usec);
    }
    int n = snprintf(sample, sizeof(sample),
        "%.*s,\"seq\":%" PRIu64 ",\"upload_dropped\":%" PRIu64 ",\"queue_depth\":%u%s}",
        (int)length - 1, json, seq, dropped, (unsigned)uxQueueMessagesWaiting(cloud_queue), timestamp);
    if (n <= 0 || (size_t)n >= sizeof(sample) || xQueueSend(cloud_queue, sample, 0) != pdTRUE) {
        portENTER_CRITICAL(&state_lock);
        ++cloud.dropped;
        portEXIT_CRITICAL(&state_lock);
    }
}

typedef struct { char data[384]; size_t used; } cloud_response_t;

static esp_err_t cloud_response(esp_http_client_event_t *event)
{
    cloud_response_t *response = event->user_data;
    if (event->event_id == HTTP_EVENT_ON_DATA && event->data_len > 0) {
        size_t available = sizeof(response->data) - response->used - 1;
        size_t copy = (size_t)event->data_len < available ? (size_t)event->data_len : available;
        memcpy(response->data + response->used, event->data, copy);
        response->used += copy;
        response->data[response->used] = 0;
    }
    return ESP_OK;
}

static void cloud_task(void *argument)
{
    (void)argument;
    /* Leave handshake headroom: allocate the HTTP body only after Wi-Fi has an IP. */
    char *body = NULL;
    char sample[CLOUD_SAMPLE_SIZE];
    unsigned count = 0, failures = 0;
    size_t used = 0;
    int64_t next_attempt = 0;
    bool sntp_started = false;
    cloud_response_t response;
    esp_http_client_handle_t client = NULL;
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(100));
        portENTER_CRITICAL(&state_lock);
        bool connected = state.station_connected, blocked = cloud.blocked;
        portEXIT_CRITICAL(&state_lock);
        if (!connected || blocked) {
            if (client) { esp_http_client_cleanup(client); client = NULL; }
            if (!count) { free(body); body = NULL; }
            continue;
        }
        if (!sntp_started) {
            esp_sntp_config_t config = ESP_NETIF_SNTP_DEFAULT_CONFIG("time.cloudflare.com");
            config.sync_cb = clock_sync;
            sntp_started = esp_netif_sntp_init(&config) == ESP_OK;
        }
        int64_t now = esp_timer_get_time();
        if (now < next_attempt) continue;
        if (!body) {
            body = malloc(CLOUD_BODY_SIZE);
            if (!body) {
                portENTER_CRITICAL(&state_lock);
                ++cloud.failures;
                portEXIT_CRITICAL(&state_lock);
                puts("{\"type\":\"cloud\",\"status\":\"allocation_failed\"}");
                next_attempt = now + 5000000;
                continue;
            }
        }
        if (!count) {
            used = snprintf(body, CLOUD_BODY_SIZE,
                "{\"device_id\":\"%s\",\"label\":\"%s\",\"boot_id\":\"%s\",\"samples\":[",
                cloud.device_id, cloud_settings.label, cloud.boot_id);
            while (count < CLOUD_BATCH_SIZE && xQueueReceive(cloud_queue, sample, 0) == pdTRUE) {
                used += snprintf(body + used, CLOUD_BODY_SIZE - used, "%s%s", count ? "," : "", sample);
                ++count;
            }
            if (!count) continue;
            used += snprintf(body + used, CLOUD_BODY_SIZE - used, "]}");
            portENTER_CRITICAL(&state_lock);
            cloud.pending = count;
            portEXIT_CRITICAL(&state_lock);
        }
        memset(&response, 0, sizeof(response));
        esp_http_client_config_t config = {
            .url = cloud_settings.url, .method = HTTP_METHOD_POST,
            .timeout_ms = cloud_settings.timeout_ms, .crt_bundle_attach = esp_crt_bundle_attach,
            .disable_auto_redirect = true, .event_handler = cloud_response, .user_data = &response,
            .keep_alive_enable = true,
            .buffer_size = 1024, .buffer_size_tx = 1024,
        };
        if (!client) client = esp_http_client_init(&config);
        esp_err_t result = ESP_ERR_NO_MEM;
        int status = 0;
        if (client) {
            char authorization[136];
            snprintf(authorization, sizeof(authorization), "Bearer %s", cloud_settings.device_token);
            esp_http_client_set_header(client, "Authorization", authorization);
            esp_http_client_set_header(client, "Content-Type", "application/json");
            esp_http_client_set_post_field(client, body, used);
            result = esp_http_client_perform(client);
            status = esp_http_client_get_status_code(client);
        }
        bool accepted = false;
        cJSON *reply = cJSON_Parse(response.data);
        cJSON *inserted = cJSON_GetObjectItemCaseSensitive(reply, "inserted");
        cJSON *duplicates = cJSON_GetObjectItemCaseSensitive(reply, "duplicates");
        if (result == ESP_OK && (status == 200 || status == 201) &&
            cJSON_IsNumber(inserted) && cJSON_IsNumber(duplicates) &&
            inserted->valuedouble >= 0 && duplicates->valuedouble >= 0 &&
            inserted->valuedouble + duplicates->valuedouble == count) accepted = true;
        cJSON_Delete(reply);
        if (!accepted && client) { esp_http_client_cleanup(client); client = NULL; }
        portENTER_CRITICAL(&state_lock);
        cloud.http_status = status;
        if (accepted) {
            cloud.acknowledged += count;
            cloud.pending = 0;
            cloud.last_success_us = esp_timer_get_time();
        } else {
            ++cloud.failures;
            if (status == 400 || status == 401 || status == 403 || status == 409 ||
                status == 404 || status == 413 || (status >= 300 && status < 400)) cloud.blocked = true;
        }
        portEXIT_CRITICAL(&state_lock);
        printf("{\"type\":\"cloud\",\"status\":\"%s\",\"http_status\":%d,\"samples\":%u,"
               "\"queued\":%u,\"code\":%d}\n", accepted ? "acknowledged" : "retry_pending",
               status, count, (unsigned)uxQueueMessagesWaiting(cloud_queue), result);
        if (accepted) { count = 0; failures = 0; }
        else if (failures < 4) ++failures;
        uint32_t delay = accepted ? cloud_settings.batch_interval_ms : (5000U << (failures - 1));
        if (delay > 60000) delay = 60000;
        next_attempt = (accepted ? now : esp_timer_get_time()) + (int64_t)delay * 1000;
    }
}

esp_err_t wifi_cloud_start(const wifi_cloud_settings_t *config)
{
    if (!config) return ESP_ERR_INVALID_ARG;
    if (!config->enabled) return ESP_OK;
    if (cloud_queue || !config->url || strncmp(config->url, "https://", 8) ||
        !config->device_token || strlen(config->device_token) < 16 || strlen(config->device_token) > 127 ||
        !config->label || strspn(config->label, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_ ") != strlen(config->label) ||
        !config->label[0] || strlen(config->label) > 80 || config->batch_interval_ms < 500 ||
        config->timeout_ms < 1000 || config->build_epoch < 1704067200) return ESP_ERR_INVALID_ARG;
    cloud_settings = *config;
    uint8_t mac[6], random[16];
    NET_TRY(esp_read_mac(mac, ESP_MAC_WIFI_STA));
    esp_fill_random(random, sizeof(random));
    snprintf(cloud.device_id, sizeof(cloud.device_id), "esp32-%02x%02x%02x%02x%02x%02x",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    for (unsigned i = 0; i < sizeof(random); ++i) snprintf(cloud.boot_id + i * 2, 3, "%02x", random[i]);
    time_t current_time = time(NULL);
    if (current_time < config->build_epoch) {
        struct timeval seed = {.tv_sec = config->build_epoch};
        settimeofday(&seed, NULL);
    }
    cloud_queue = xQueueCreate(CLOUD_QUEUE_SIZE, CLOUD_SAMPLE_SIZE);
    if (!cloud_queue) return ESP_ERR_NO_MEM;
    if (xTaskCreate(cloud_task, "cloud", 8192, NULL, 1, NULL) != pdPASS) {
        vQueueDelete(cloud_queue);
        cloud_queue = NULL;
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}

esp_err_t wifi_request(wifi_action_t action)
{
    if ((unsigned)action > WIFI_ACTION_STATUS) return ESP_ERR_INVALID_ARG;
    if (!actions) return ESP_ERR_INVALID_STATE;
    return xQueueSend(actions, &action, 0) == pdTRUE ? ESP_OK : ESP_ERR_TIMEOUT;
}

static void wifi_log_status(void)
{
    wifi_mode_t mode = WIFI_MODE_NULL;
    wifi_config_t config = {0};
    wifi_sta_list_t clients = {0};
    uint8_t channel = 0, mac[6] = {0};
    wifi_second_chan_t secondary;
    int8_t power = 0;
    bool ready, active, connected, ap_only;
    char ip[16];
    portENTER_CRITICAL(&state_lock);
    ready = state.ready;
    active = state.ap_active;
    connected = state.station_connected;
    ap_only = state.ap_only;
    memcpy(ip, state.station_ip, sizeof(ip));
    portEXIT_CRITICAL(&state_lock);
    char upload[448];
    cloud_status(upload, sizeof(upload));
    printf("{\"type\":\"cloud_status\",\"cloud\":%s,\"queued\":%u}\n", upload,
           cloud_queue ? (unsigned)uxQueueMessagesWaiting(cloud_queue) : 0);
    esp_err_t result = esp_wifi_get_mode(&mode);
    if (result == ESP_OK) {
        esp_wifi_get_channel(&channel, &secondary);
        esp_wifi_get_max_tx_power(&power);
    }
    if (mode == WIFI_MODE_AP || mode == WIFI_MODE_APSTA) {
        esp_wifi_get_config(WIFI_IF_AP, &config);
        esp_wifi_get_mac(WIFI_IF_AP, mac);
        esp_wifi_ap_get_sta_list(&clients);
    }
    char ssid[32 * 6 + 1];
    escape_ssid(config.ap.ssid, ssid);
    printf("{\"type\":\"wifi_status\",\"ready\":%s,\"mode\":\"%s\","
           "\"station_connected\":%s,\"station_ip\":\"%s\",\"ap_active\":%s,"
           "\"ap_only\":%s,\"ap_ssid\":\"%s\",\"ap_hidden\":%s,\"channel\":%u,"
           "\"ap_auth_mode\":%d,\"ap_clients\":%u,\"beacon_tu\":%u,\"max_tx_power_dbm\":%.2f,"
           "\"ap_mac\":\"%02x:%02x:%02x:%02x:%02x:%02x\",\"code\":%d}\n",
           ready ? "true" : "false", mode == WIFI_MODE_AP ? "ap" :
           mode == WIFI_MODE_APSTA ? "ap_sta" : mode == WIFI_MODE_STA ? "sta" : "off",
           connected ? "true" : "false", connected ? ip : "", active ? "true" : "false",
           ap_only ? "true" : "false", ssid, config.ap.ssid_hidden ? "true" : "false",
           channel, config.ap.authmode, (unsigned)clients.num, config.ap.beacon_interval,
           power * 0.25, mac[0], mac[1], mac[2], mac[3], mac[4], mac[5], result);
}

/* Self-contained: local clients need neither a CDN nor Internet access. */
static const char dashboard[] =
"<!doctype html>\n"
"<html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>SensorLab Local</title>\n"
"<style>\n"
":root{color-scheme:dark;--bg:#10191d;--panel:#19272c;--line:#304348;--text:#edf5ed;--muted:#acc1bc;--green:#b5efb5;--amber:#ffcc86}*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 system-ui,sans-serif}main{max-width:1080px;padding:36px 24px;margin:auto}header{display:flex;justify-content:space-between;gap:20px;align-items:center;margin-bottom:28px}.eyebrow{color:var(--green);font-size:12px;letter-spacing:.12em;text-transform:uppercase}h1{font-size:clamp(28px,5vw,42px);letter-spacing:-.04em;margin:4px 0}h2{font-size:18px;margin:0 0 16px}p{margin:6px 0;color:var(--muted)}.badge{border:1px solid var(--line);border-radius:24px;padding:8px 14px;font-size:13px;white-space:nowrap;color:var(--amber)}.badge.live{color:var(--green)}.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.card,.panel{background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:22px}.label{font-size:13px;color:var(--muted)}.value{font-size:clamp(24px,3.8vw,36px);font-variant-numeric:tabular-nums;letter-spacing:-.04em;overflow-wrap:anywhere;margin:8px 0 4px}.unit{font-size:13px;color:var(--muted)}.note{font-size:12px;color:var(--muted);min-height:18px}.panels{display:grid;grid-template-columns:1.6fr 1fr;gap:14px;margin-top:14px}svg{display:block;width:100%;height:160px;border-bottom:1px solid var(--line)}polyline{stroke:var(--green);stroke-width:2;vector-effect:non-scaling-stroke;fill:none}.chart-note{font-size:12px;margin-top:12px}dl{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:0}dt{color:var(--muted);font-size:12px}dd{margin:2px 0 0;font-variant-numeric:tabular-nums;overflow-wrap:anywhere}footer{margin-top:24px;font-size:13px;color:var(--muted)}a{color:var(--green)}#message{margin:0 0 20px;padding:12px 16px;border:1px solid var(--line);border-radius:12px;color:var(--muted)}@media(max-width:760px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}.panels{grid-template-columns:1fr}header{align-items:flex-start;flex-direction:column;gap:12px}main{padding:24px 16px}.card,.panel{padding:18px}}@media(prefers-reduced-motion:no-preference){.badge{transition:color .2s}}\n"
"</style></head><body><main>\n"
"<header><div><div class=\"eyebrow\" id=\"device\">ZJ-S201C / ESP32</div><h1>SensorLab Local</h1><p>Live pulse readings, directly from your board.</p></div><div id=\"badge\" class=\"badge\" role=\"status\">Connecting</div></header>\n"
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
"<footer>Input: <span id=\"sensor-pin\">--</span>. Unknown calibration stays blank. <a href=\"/api/status\">JSON data</a> &middot; <a href=\"/healthz\">Health</a><p>This local page requires no Internet. The board does not forward Internet access to connected devices.</p></footer>\n"
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
" el('device').textContent='ZJ-S201C / '+(r.board||'ESP32');el('sensor-pin').textContent=finite(r.gpio)?'GPIO'+r.gpio:'--';\n"
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
    if (settings.enterprise.enabled) return "wpa2_enterprise_peap";
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
    cloud_enqueue(json, length);
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
    return httpd_resp_sendstr(request, "{\"status\":\"ok\",\"service\":\"sensorlab-local\"}");
}

static esp_err_t favicon_get(httpd_req_t *request)
{
    httpd_resp_set_status(request, "204 No Content");
    return httpd_resp_send(request, NULL, 0);
}

static esp_err_t status_get(httpd_req_t *request)
{
    char reading[WIFI_READING_CAPACITY], station_ip[16];
    bool connected, ap_active, ap_only;
    int64_t reading_us;
    portENTER_CRITICAL(&state_lock);
    memcpy(reading, state.reading, sizeof(reading));
    memcpy(station_ip, state.station_ip, sizeof(station_ip));
    connected = state.station_connected;
    ap_active = state.ap_active;
    ap_only = state.ap_only;
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
    char upload[448];
    cloud_status(upload, sizeof(upload));
    char body[2560];
    int length = snprintf(body, sizeof(body),
        "{\"network\":{\"station_connected\":%s,\"ssid\":\"%s\",\"station_ip\":%s,"
        "\"rssi_dbm\":%s,\"ap_active\":%s,\"ap_ssid\":\"%s\",\"ap_ip\":%s,"
        "\"ap_clients\":%u,\"ap_only\":%s},\"reading_age_ms\":%s,\"reading\":%s,\"cloud\":%s}",
        connected ? "true" : "false", target_ssid_json, address, rssi,
        ap_active ? "true" : "false", ap_ssid_json, ap_ip,
        (unsigned)clients.num, ap_only ? "true" : "false", age, reading[0] ? reading : "null", upload);
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
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_STOP) {
        portENTER_CRITICAL(&state_lock);
        state.station_connected = false;
        portEXIT_CRITICAL(&state_lock);
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *event = data;
        char ip[16];
        snprintf(ip, sizeof(ip), IPSTR, IP2STR(&event->ip_info.ip));
        portENTER_CRITICAL(&state_lock);
        memcpy(state.station_ip, ip, sizeof(ip));
        state.station_connected = true;
        portEXIT_CRITICAL(&state_lock);
        printf("{\"type\":\"wifi\",\"status\":\"connected\",\"ssid\":\"%s\","
               "\"ip\":\"%s\",\"auth\":\"%s\",\"server_validation\":%s}\n",
               target_ssid_json, ip, network_auth_label(), settings.enterprise.enabled ? "true" : "false");
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
            .threshold.authmode = settings.enterprise.enabled ? WIFI_AUTH_WPA2_ENTERPRISE :
                                  settings.password[0] ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN,
            .scan_method = WIFI_ALL_CHANNEL_SCAN,
            .pmf_cfg = {.capable = true, .required = false},
        },
    };
    memcpy(config.sta.ssid, settings.ssid, strlen(settings.ssid));
    memcpy(config.sta.password, settings.password, strlen(settings.password));
    NET_TRY(esp_wifi_set_mode(settings.fallback.enabled ? WIFI_MODE_APSTA : WIFI_MODE_STA));
    NET_TRY(esp_wifi_set_config(WIFI_IF_STA, &config));
    if (settings.enterprise.enabled) {
        const wifi_enterprise_settings_t *enterprise = &settings.enterprise;
        struct timeval clock;
        gettimeofday(&clock, NULL);
        if (clock.tv_sec < enterprise->build_epoch) {
            clock.tv_sec = enterprise->build_epoch;
            clock.tv_usec = 0;
            if (settimeofday(&clock, NULL)) return ESP_FAIL;
        }
        NET_TRY(esp_eap_client_set_identity((const unsigned char *)enterprise->identity, strlen(enterprise->identity)));
        NET_TRY(esp_eap_client_set_username((const unsigned char *)enterprise->username, strlen(enterprise->username)));
        NET_TRY(esp_eap_client_set_password((const unsigned char *)enterprise->password, strlen(enterprise->password)));
        NET_TRY(esp_eap_client_set_eap_methods(ESP_EAP_TYPE_PEAP));
        NET_TRY(esp_eap_client_use_default_cert_bundle(true));
        NET_TRY(esp_eap_client_set_domain_name(enterprise->server_domain));
        NET_TRY(esp_eap_client_set_disable_time_check(false));
        NET_TRY(esp_wifi_sta_enterprise_enable());
    }
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

static esp_err_t activate_ap(bool only)
{
    if (!ap_interface) return ESP_ERR_INVALID_STATE;
    NET_TRY(esp_wifi_set_mode(only ? WIFI_MODE_AP : WIFI_MODE_APSTA));
    wifi_config_t config = {
        .ap = {
            .ssid_len = strlen(settings.fallback.ssid),
            .ssid_hidden = 0,
            .channel = settings.fallback.channel,
            .authmode = WIFI_AUTH_WPA2_PSK,
            .pairwise_cipher = WIFI_CIPHER_TYPE_CCMP,
            .max_connection = settings.fallback.max_clients,
            .beacon_interval = 100,
            .pmf_cfg = {.required = false},
        },
    };
    memcpy(config.ap.ssid, settings.fallback.ssid, strlen(settings.fallback.ssid));
    memcpy(config.ap.password, settings.fallback.password, strlen(settings.fallback.password));
    NET_TRY(esp_wifi_set_config(WIFI_IF_AP, &config));
    wifi_config_t actual;
    NET_TRY(esp_wifi_get_config(WIFI_IF_AP, &actual));
    if (actual.ap.ssid_len != config.ap.ssid_len || actual.ap.ssid_hidden ||
        memcmp(actual.ap.ssid, config.ap.ssid, config.ap.ssid_len)) return ESP_FAIL;
    return ESP_OK;
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
           "\"auth\":\"%s\",\"server_validation\":%s}\n", target_ssid_json, network_auth_label(),
           settings.enterprise.enabled ? "true" : "false");
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
    esp_wifi_set_ps(WIFI_PS_NONE);
    portENTER_CRITICAL(&state_lock);
    state.ready = true;
    portEXIT_CRITICAL(&state_lock);
    int64_t wait_started_us = esp_timer_get_time(), last_status_us = wait_started_us;
    err = scan_networks();
    if (err != ESP_OK)
        printf("{\"type\":\"wifi_scan\",\"status\":\"error\",\"code\":%d}\n", err);
    unsigned attempts = 0;
    int64_t next_connect_us = esp_timer_get_time(), next_fallback_us = 0;
    bool ap_started = false, ap_only = false;
    while (true) {
        EventBits_t bits = xEventGroupWaitBits(events, CONNECTED | DISCONNECTED | LOST_IP,
                                              pdTRUE, pdFALSE, pdMS_TO_TICKS(250));
        int64_t now = esp_timer_get_time();
        portENTER_CRITICAL(&state_lock);
        bool connected = state.station_connected;
        portEXIT_CRITICAL(&state_lock);
        wifi_action_t action;
        if (xQueueReceive(actions, &action, 0) == pdTRUE) {
            static const char *const names[] = {"scan", "reconnect", "ap_on", "ap_only", "auto", "status"};
            if (action == WIFI_ACTION_STATUS) {
                err = ESP_OK;
            } else if (action == WIFI_ACTION_AP_ON || action == WIFI_ACTION_AP_ONLY) {
                bool resuming_station = ap_only && action == WIFI_ACTION_AP_ON;
                err = activate_ap(action == WIFI_ACTION_AP_ONLY);
                if (err == ESP_OK) {
                    ap_started = true;
                    ap_only = action == WIFI_ACTION_AP_ONLY;
                    if (ap_only) { connected = false; next_connect_us = 0; }
                    else if (resuming_station && !connected) next_connect_us = now;
                }
            } else if (action == WIFI_ACTION_AUTO) {
                bool resuming_station = ap_only;
                err = esp_wifi_set_mode(ap_started ? WIFI_MODE_APSTA : WIFI_MODE_STA);
                if (err == ESP_OK) {
                    ap_only = false;
                    if (resuming_station && !connected) next_connect_us = now;
                }
            } else if (action == WIFI_ACTION_RECONNECT) {
                err = ap_only ? ESP_ERR_INVALID_STATE : esp_wifi_disconnect();
                if (!ap_only && (err == ESP_OK || err == ESP_ERR_WIFI_NOT_CONNECT)) {
                    err = ESP_OK;
                    connected = false;
                    next_connect_us = now + (int64_t)settings.retry_delay_ms * 1000;
                }
            } else {
                /* Pause a pending connection so the driver can run a full scan. */
                if (!connected && !ap_only) {
                    if (esp_wifi_disconnect() == ESP_OK)
                        xEventGroupWaitBits(events, DISCONNECTED, pdTRUE, pdFALSE, pdMS_TO_TICKS(1000));
                }
                err = scan_networks();
                if (!connected && !ap_only)
                    next_connect_us = esp_timer_get_time() + (int64_t)settings.retry_delay_ms * 1000;
            }
            portENTER_CRITICAL(&state_lock);
            state.ap_only = ap_only;
            if (ap_only) state.station_connected = false;
            portEXIT_CRITICAL(&state_lock);
            wifi_log_status();
            printf("{\"type\":\"wifi_command\",\"action\":\"%s\",\"status\":\"%s\",\"code\":%d}\n",
                   names[action], err == ESP_OK ? "ok" : "error", err);
        }
        if (connected) {
            wait_started_us = 0;
            attempts = 0;
            next_connect_us = 0;
        } else if (!ap_only) {
            if (!wait_started_us) wait_started_us = now;
            uint32_t delay_ms = ap_started ? settings.fallback.retry_delay_ms : settings.retry_delay_ms;
            if (bits & DISCONNECTED) next_connect_us = now + (int64_t)delay_ms * 1000;
            if (settings.fallback.enabled && !ap_started && now >= next_fallback_us &&
                now - wait_started_us >= (int64_t)settings.fallback.after_ms * 1000) {
                err = activate_ap(false);
                if (err == ESP_OK) {
                    ap_started = true;
                    esp_netif_ip_info_t info = {0};
                    esp_netif_get_ip_info(ap_interface, &info);
                    printf("{\"type\":\"wifi_fallback\",\"status\":\"started\",\"ssid\":\"%s\","
                           "\"ip\":\"" IPSTR "\",\"wait_ms\":%" PRId64 ",\"mode\":\"ap_sta\"}\n",
                           ap_ssid_json, IP2STR(&info.ip), (now - wait_started_us) / 1000);
                    wifi_log_status();
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
    if (config->enterprise.enabled &&
        (!config->enterprise.identity[0] || !memchr(config->enterprise.identity, 0, sizeof(config->enterprise.identity)) ||
         !config->enterprise.username[0] || !memchr(config->enterprise.username, 0, sizeof(config->enterprise.username)) ||
         !config->enterprise.password[0] || !memchr(config->enterprise.password, 0, sizeof(config->enterprise.password)) ||
         !config->enterprise.server_domain[0] || !memchr(config->enterprise.server_domain, 0, sizeof(config->enterprise.server_domain)) ||
         config->enterprise.build_epoch < 1704067200)) return ESP_ERR_INVALID_ARG;
    if (config->fallback.enabled &&
        (!valid_credentials(config->fallback.ssid, config->fallback.password, false) ||
         !config->fallback.after_ms || !pdMS_TO_TICKS(config->fallback.retry_delay_ms) ||
         config->fallback.channel < 1 || config->fallback.channel > 11 ||
         config->fallback.max_clients < 1 || config->fallback.max_clients > 4))
        return ESP_ERR_INVALID_ARG;
    if (running) return ESP_ERR_INVALID_STATE;
    settings = *config;
    actions = xQueueCreate(4, sizeof(wifi_action_t));
    if (!actions) return ESP_ERR_NO_MEM;
    running = true;
    if (xTaskCreate(network_task, "wifi", 8192, NULL, 3, NULL) != pdPASS) {
        running = false;
        vQueueDelete(actions);
        actions = NULL;
        printf("{\"type\":\"wifi\",\"status\":\"task_error\"}\n");
        return ESP_ERR_NO_MEM;
    }
    return ESP_OK;
}
