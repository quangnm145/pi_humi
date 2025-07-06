#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <termios.h>
#include <unistd.h>
#include <time.h>
#include <jansson.h>
#include <errno.h>
#include <sys/stat.h>

#define UART_PORT "/dev/ttyACM0"
#define BAUD_RATE B9600
#define BAUD_RATE_VALUE 9600
#define JSON_FILE "data_log.json"
#define MAX_LINE 256
#define SYNC_TIMEOUT 2

int setup_uart() {
    int fd = open(UART_PORT, O_RDWR | O_NOCTTY | O_NDELAY);
    if (fd == -1) {
        perror("Lỗi mở cổng UART");
        return -1;
    }

    struct termios options;
    tcgetattr(fd, &options);
    cfsetispeed(&options, BAUD_RATE);
    cfsetospeed(&options, BAUD_RATE);

    options.c_cflag = (options.c_cflag & ~CSIZE) | CS8;
    options.c_cflag &= ~PARENB;
    options.c_cflag &= ~CSTOPB;
    options.c_cflag |= CLOCAL | CREAD;
    options.c_lflag = 0;
    options.c_iflag = 0;
    options.c_oflag = 0;
    options.c_cc[VMIN] = 0;
    options.c_cc[VTIME] = 2;

    tcflush(fd, TCIOFLUSH);
    if (tcsetattr(fd, TCSANOW, &options) != 0) {
        perror("Lỗi cấu hình UART");
        close(fd);
        return -1;
    }

    printf("Kết nối thành công với %s\n", UART_PORT);
    return fd;
}

void get_timestamp(char *buffer, size_t size) {
    time_t now = time(NULL);
    struct tm *tm = localtime(&now);
    strftime(buffer, size, "%Y-%m-%dT%H:%M:%S", tm);
}

int parse_data(const char *line, double *humidity, char *relay_status, double *threshold) {
    *humidity = 0.0;
    strcpy(relay_status, "Unknown");
    *threshold = 0.0;

    char *moisture_str = strstr(line, "MOISTURE:");
    char *relay_str = strstr(line, "RELAY:");
    char *threshold_str = strstr(line, "THRESHOLD:");
    
    if (!moisture_str || !relay_str || !threshold_str) {
        fprintf(stderr, "Dữ liệu không hợp lệ: %s\n", line);
        return -1;
    }

    moisture_str += 9;
    char *comma = strchr(moisture_str, ',');
    if (!comma) {
        fprintf(stderr, "Lỗi phân tích MOISTURE: %s\n", line);
        return -1;
    }
    char hum_val[16];
    strncpy(hum_val, moisture_str, comma - moisture_str);
    hum_val[comma - moisture_str] = '\0';
    *humidity = atof(hum_val);

    relay_str += 6;
    comma = strchr(relay_str, ',');
    if (!comma) {
        fprintf(stderr, "Lỗi phân tích RELAY: %s\n", line);
        return -1;
    }
    char relay_val[2];
    strncpy(relay_val, relay_str, comma - relay_str);
    relay_val[comma - relay_str] = '\0';
    if (strcmp(relay_val, "0") == 0) {
        strcpy(relay_status, "OFF");
    } else if (strcmp(relay_val, "1") == 0) {
        strcpy(relay_status, "ON");
    } else {
        fprintf(stderr, "Giá trị RELAY không hợp lệ: %s\n", relay_val);
        return -1;
    }

    threshold_str += 10;
    char thresh_val[16];
    strncpy(thresh_val, threshold_str, sizeof(thresh_val) - 1);
    thresh_val[sizeof(thresh_val) - 1] = '\0';
    *threshold = atof(thresh_val);

    return 0;
}

int save_to_json(double humidity, const char *relay_status, double threshold) {
    json_t *root;
    json_error_t error;

    FILE *file_check = fopen(JSON_FILE, "a+");
    if (!file_check) {
        perror("Lỗi mở file JSON");
        return -1;
    }
    fclose(file_check);

    root = json_load_file(JSON_FILE, JSON_DECODE_ANY, &error);
    if (!root) {
        root = json_object();
        if (!root) {
            fprintf(stderr, "Lỗi tạo JSON object\n");
            return -1;
        }
        json_t *config = json_object();
        json_object_set_new(config, "port", json_string(UART_PORT));
        json_object_set_new(config, "baud_rate", json_integer(BAUD_RATE_VALUE));
        json_object_set_new(root, "config", config);
        json_object_set_new(root, "data", json_array());
    } else if (json_is_array(root)) {
        json_t *new_root = json_object();
        json_t *config = json_object();
        json_object_set_new(config, "port", json_string(UART_PORT));
        json_object_set_new(config, "baud_rate", json_integer(BAUD_RATE_VALUE));
        json_object_set_new(new_root, "config", config);
        json_object_set_new(new_root, "data", root);
        root = new_root;
    } else {
        json_t *config = json_object_get(root, "config");
        if (json_is_object(config)) {
            json_t *baud_rate = json_object_get(config, "baud_rate");
            if (!json_is_integer(baud_rate) || json_integer_value(baud_rate) != BAUD_RATE_VALUE) {
                fprintf(stderr, "Sửa baud_rate trong config từ %lld thành %d\n",
                        json_is_integer(baud_rate) ? json_integer_value(baud_rate) : -1,
                        BAUD_RATE_VALUE);
                json_object_set_new(config, "baud_rate", json_integer(BAUD_RATE_VALUE));
            }
        } else {
            json_t *config = json_object();
            json_object_set_new(config, "port", json_string(UART_PORT));
            json_object_set_new(config, "baud_rate", json_integer(BAUD_RATE_VALUE));
            json_object_set_new(root, "config", config);
        }
    }

    json_t *data = json_object_get(root, "data");
    if (!json_is_array(data)) {
        data = json_array();
        json_object_set_new(root, "data", data);
    }

    json_t *record = json_object();
    char timestamp[32];
    get_timestamp(timestamp, sizeof(timestamp));

    json_object_set_new(record, "timestamp", json_string(timestamp));
    json_object_set_new(record, "humidity", json_real(humidity));
    json_object_set_new(record, "relay_status", json_string(relay_status));
    json_object_set_new(record, "threshold", json_real(threshold));

    json_array_append_new(data, record);

    if (json_array_size(data) > 100) {
        json_array_remove(data, 0);
    }

    if (json_dump_file(root, JSON_FILE, JSON_INDENT(2)) != 0) {
        fprintf(stderr, "Lỗi ghi file JSON: %s\n", strerror(errno));
        json_decref(root);
        return -1;
    }

    char *json_str = json_dumps(root, JSON_INDENT(2));
    printf("JSON đã lưu:\n%s\n", json_str);
    free(json_str);

    json_decref(root);
    return 0;
}

int main() {
    int uart_fd = setup_uart();
    if (uart_fd < 0) {
        return 1;
    }

    chmod(JSON_FILE, S_IRUSR | S_IWUSR | S_IRGRP | S_IROTH);

    char line[MAX_LINE];
    int pos = 0;
    time_t start_time = time(NULL);
    int synced = 0;

    while (1) {
        char c;
        if (read(uart_fd, &c, 1) > 0) {
            if (c == '\n' || c == '\r') {
                if (pos > 0) {
                    line[pos] = '\0';
                    printf("Dữ liệu nhận được: %s\n", line);

                    if (!synced && (time(NULL) - start_time) < SYNC_TIMEOUT) {
                        printf("Bỏ qua bản tin trong giai đoạn đồng bộ\n");
                        pos = 0;
                        continue;
                    }
                    synced = 1;

                    double humidity, threshold;
                    char relay_status[8];
                    if (parse_data(line, &humidity, relay_status, &threshold) == 0) {
                        if (save_to_json(humidity, relay_status, threshold) == 0) {
                            printf("Đã lưu: humidity=%.1f, relay=%s, threshold=%.1f\n",
                                   humidity, relay_status, threshold);
                        } else {
                            fprintf(stderr, "Lỗi lưu JSON\n");
                        }
                    } else {
                        printf("Dữ liệu không hợp lệ, bỏ qua\n");
                    }
                    pos = 0;
                }
            } else if (pos < MAX_LINE - 1) {
                line[pos++] = c;
            }
        } else {
            usleep(100000);
        }
    }

    close(uart_fd);
    printf("Đã đóng cổng UART\n");
    return 0;
}