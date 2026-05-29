#include <string.h>
#include <stdlib.h>
#include <stdio.h>

typedef struct {
    char user_buf[64];
    int flags;
} RequestContext;

void safe_process_buffer(char* external_data, int size) {
    RequestContext ctx;
    if (size <= 0 || size > (int)sizeof(ctx.user_buf)) {
        return;
    }
    memcpy(ctx.user_buf, external_data, size);
    ctx.user_buf[sizeof(ctx.user_buf) - 1] = '\0';
    printf("Received: %s\n", ctx.user_buf);
}
