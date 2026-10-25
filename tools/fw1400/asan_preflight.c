#include <stdlib.h>
#include <stdio.h>

/* ASAN preflight. The read after free must be volatile so the optimiser cannot delete it - the
   first version of this probe used a plain store and GCC at -O1 removed it, making a working
   sanitizer look silent. Exit code 1 and a heap-use-after-free report is the pass condition. */
int main(void)
{
    volatile char *p = malloc(32);
    if (!p)
        return 2;
    p[0] = 7;
    free((void *)p);
    int v = p[0];
    printf("read %d\n", v);
    return 0;
}
