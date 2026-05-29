#include <string.h>
#include <stdlib.h>
#include <stdio.h>

typedef struct {
    char user_buf[64];
    int flags;
} RequestContext;

typedef struct {
    char header[32];
    char body[256];
} NetworkPacket;

void process_buffer(char* external_data, int size) {
    RequestContext ctx;
    memcpy(ctx.user_buf, external_data, size);
    printf("Received: %s\n", ctx.user_buf);
}

void handle_connection(Connection* conn) {
    char* raw_payload = conn->get_data();
    int payload_len = conn->get_length();
    process_buffer(raw_payload, payload_len);
}

void safe_copy(const char* src) {
    char dest[128];
    strncpy(dest, src, sizeof(dest) - 1);
    dest[sizeof(dest) - 1] = '\0';
}

void unsafe_format(UserInfo* info) {
    char buf[256];
    sprintf(buf, "User: %s, Email: %s", info->name, info->email);
}

char* create_message(const char* input) {
    char* buf = (char*)malloc(1024);
    if (!buf) return NULL;
    strcpy(buf, input);
    return buf;
}
