#include "omega_native.h"
#include <assert.h>
#include <math.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sched.h>

struct thread_args { struct ox_queue *q; size_t count; };
static void *producer(void *ptr) {
    struct thread_args *a = ptr;
    for (size_t i=0; i<a->count; ++i) {
        while (!ox_queue_push(a->q, i + 1)) sched_yield();
    }
    return NULL;
}
static void *consumer(void *ptr) {
    struct thread_args *a = ptr;
    for (size_t i=0; i<a->count; ++i) {
        uint64_t value;
        while (!ox_queue_pop(a->q, &value)) sched_yield();
        assert(value == i + 1);
    }
    return NULL;
}
int main(void) {
    assert(ox_queue_create(0) == NULL);
    assert(ox_queue_create(3) == NULL);
    struct ox_queue *q = ox_queue_create(128);
    assert(q);
    assert(((uintptr_t)q & 63u) == 0u);
    struct thread_args args = {q, 200000};
    pthread_t a, b;
    assert(pthread_create(&a, NULL, producer, &args) == 0);
    assert(pthread_create(&b, NULL, consumer, &args) == 0);
    assert(pthread_join(a, NULL) == 0);
    assert(pthread_join(b, NULL) == 0);
    assert(ox_queue_size(q) == 0);
    ox_queue_destroy(q);
    const size_t n = 1031;
    float *x = calloc(n, sizeof(float)), *y = calloc(n, sizeof(float));
    float *scalar = calloc(n, sizeof(float)), *fast = calloc(n, sizeof(float));
    assert(x && y && scalar && fast);
    for (size_t i=0; i<n; ++i) { x[i] = (float)i / 7.0f; y[i] = (float)(i % 11); }
    assert(ox_saxpy(x,y,scalar,n,0.125f,1) == 1);
    assert(ox_saxpy(x,y,fast,n,0.125f,0) > 0);
    for (size_t i=0; i<n; ++i) assert(fabsf(scalar[i] - fast[i]) < 0.0001f);
    assert(ox_saxpy(NULL,NULL,NULL,1,0.0f,0) == -1);
    free(x); free(y); free(scalar); free(fast);
    int8_t mat_a[] = {-128,127,-1,100,0,-100};
    int8_t mat_b[] = {3,-2,-7,11,80,90};
    int64_t result[4] = {0};
    assert(ox_matmul_i8(mat_a,mat_b,result,2,3,2) == 0);
    assert(result[0] == -128*3 + 127*(-7) - 80);
    assert(result[1] == (-128)*(-2) + 127*11 - 90);
    assert(result[2] == 100*3 - 100*80);
    assert(result[3] == 100*(-2) - 100*90);
    assert(ox_matmul_i8(NULL,mat_b,result,2,3,2) == -1);
    int8_t many_a[256], many_b[256];
    int64_t many_result[1];
    for(size_t i=0;i<256;++i){many_a[i]=-128;many_b[i]=-128;}
    assert(ox_matmul_i8(many_a,many_b,many_result,1,256,1)==0);
    assert(many_result[0]==256LL*128*128);
    puts("NATIVE_SANITIZER_TEST_PASS: SPSC 200000 items; SIMD 1031 elements; INT8 GEMM; bounds");
    return 0;
}
